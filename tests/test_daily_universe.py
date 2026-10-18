# numpy makes the random numbers used in the look-ahead test
import numpy as np
# pandas gives us tables (DataFrames) and reads/writes parquet files
import pandas as pd
# pytest is the test framework; we use its raises and tmp_path
import pytest

# BAR_MS says how long one bar lasts
from wh_research.data.hyperliquid.candles import BAR_MS
# The functions we are testing
from wh_research.data.hyperliquid.daily_universe import (
    daily_universe_filename,
    filter_daily_universe,
    update_daily_universe,
)


def make_df(rows):
    """rows: list of (symbol, bar, open, high, low, close, volume), one row per daily bar"""
    # Build a table from the list of rows and name its columns
    df = pd.DataFrame(rows, columns=["symbol", "bar", "open", "high", "low", "close", "volume"])
    # Turn "bar number" into a real time: bar 0 is 2024-01-01 00:00, and each bar is one day later
    df["open_time"] = pd.Timestamp("2024-01-01", tz="UTC") + pd.to_timedelta(df["bar"] * BAR_MS["1d"], unit="ms")
    # A daily bar closes 1 ms before the next one opens, like the real data
    df["close_time"] = df["open_time"] + pd.Timedelta(milliseconds=BAR_MS["1d"] - 1)
    # Hand back the finished table
    return df


def flat_bars(symbol, volumes, skip=()):
    # One flat bar (open = high = low = close = 1) per volume, so dollar volume equals volume.
    # Bars whose number is in skip are left out, which makes a gap in the series.
    return [(symbol, bar, 1.0, 1.0, 1.0, 1.0, volume) for bar, volume in enumerate(volumes) if bar not in skip]


def kept_bars(result):
    # The kept rows' bar numbers: days since 2024-01-01
    return list((result["open_time"] - pd.Timestamp("2024-01-01", tz="UTC")).dt.days)


def test_first_row_is_the_31st_bar_of_a_coin():
    # Arrange: 40 bars with a dollar volume of 10, well above the cutoff of 5
    df = make_df(flat_bars("A", [10.0] * 40))
    # Act: filter with a cutoff of 5
    result = filter_daily_universe(df, 5)
    # Assert: 30 bars of history are needed, so the first kept bar is bar 30 (the 31st) and it runs to the end
    assert kept_bars(result) == list(range(30, 40))


def test_a_spike_on_day_t_cannot_make_day_t_eligible():
    # Arrange: 30 quiet bars (volume 1), then 15 busy bars (volume 1000). The 30-day median first
    # reaches the cutoff at bar 44 (15 quiet + 15 busy bars in the window), and bars 30 to 43 are not enough.
    df = make_df(flat_bars("A", [1.0] * 30 + [1000.0] * 15))
    # Act: filter with a cutoff of 100
    result = filter_daily_universe(df, 100)
    # Assert: the median reaches the cutoff at the close of bar 44, so bar 44 itself is NOT kept; bar 45 would be
    assert kept_bars(result) == []
    # Arrange again with one more busy bar so bar 45 exists
    df = make_df(flat_bars("A", [1.0] * 30 + [1000.0] * 16))
    # Act again
    result = filter_daily_universe(df, 100)
    # Assert: only bar 45 is kept, the day after the median reached the cutoff
    assert kept_bars(result) == [45]


def test_the_median_ignores_one_huge_day():
    # Arrange: 40 quiet bars with a single enormous bar (a mean would be about 25 million)
    volumes = [1.0] * 40
    # Make bar 35 enormous
    volumes[35] = 1e9
    # Act: filter with a cutoff of 100
    result = filter_daily_universe(make_df(flat_bars("A", volumes)), 100)
    # Assert: the coin never qualifies
    assert result.empty


def test_cutoff_is_inclusive():
    # Arrange: 40 bars with a dollar volume of exactly 5
    df = make_df(flat_bars("A", [5.0] * 40))
    # Act and assert: a cutoff of exactly 5 keeps the bars after the history period
    assert kept_bars(filter_daily_universe(df, 5)) == list(range(30, 40))
    # Act and assert: a cutoff just above 5 keeps nothing
    assert filter_daily_universe(df, 5.01).empty


def test_a_missing_bar_blocks_eligibility_until_the_window_is_full_again():
    # Arrange: 100 liquid bars, but bar 40 is missing from the series
    df = make_df(flat_bars("A", [10.0] * 100, skip={40}))
    # Act: filter with a cutoff of 5
    result = filter_daily_universe(df, 5)
    # Assert: bars 30 to 39 are kept, bar 41 is blocked (the bar before it is two days back), bars 42 to 70 are
    # blocked (their window holds the gap), and from bar 71 the window is full again
    assert kept_bars(result) == list(range(30, 40)) + list(range(71, 100))


def test_symbols_do_not_mix():
    # Arrange: coin A is liquid (10) and coin B is not (1), both with 40 bars
    df = make_df(flat_bars("A", [10.0] * 40) + flat_bars("B", [1.0] * 40))
    # Act: filter with a cutoff of 5
    result = filter_daily_universe(df, 5)
    # Assert: only coin A is kept
    assert set(result["symbol"]) == {"A"}


def test_dollar_volume_uses_the_typical_price():
    # Arrange: 35 bars with high 3, low 1, close 2 and volume 6, so the typical price is 2 and dollar volume is 12
    df = make_df([("A", bar, 2.0, 3.0, 1.0, 2.0, 6.0) for bar in range(35)])
    # Act: filter with a cutoff of 1
    result = filter_daily_universe(df, 1)
    # Assert: every kept bar has dollar volume 12 and a previous median of 12
    assert (result["dollar_volume"] == 12.0).all()
    # Assert: the median known at the previous close is 12 too
    assert (result["mdv_30d_prev"] == 12.0).all()


def test_same_day_median_column_is_not_in_the_result():
    # Arrange and act: a small liquid coin
    result = filter_daily_universe(make_df(flat_bars("A", [10.0] * 40)), 5)
    # Assert: only the previous-close median is given, so day t cannot be picked with day t's own data
    assert "mdv_30d_prev" in result.columns
    # Assert: the same-day median is not there
    assert "mdv_30d" not in result.columns


def test_no_look_ahead_in_the_universe():
    # Arrange: two coins with 80 random bars each; A is liquid (about 10) and B hovers around the cutoff (about 2)
    rng = np.random.default_rng(0)
    # Random volumes for coin A
    volumes_a = rng.uniform(5, 15, 80)
    # Random volumes for coin B
    volumes_b = rng.uniform(0.5, 3.5, 80)
    # Put both coins in one table
    df = make_df(flat_bars("A", volumes_a) + flat_bars("B", volumes_b))
    # The first 60 days are "the past"; later days are "the future"
    cut = pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=60)
    # Act: build the universe on all the data
    full = filter_daily_universe(df, 2)
    # Act: build it again with only the past
    past_only = filter_daily_universe(df[df["open_time"] < cut], 2)
    # Assert: the test is meaningful (the past has kept rows)
    assert len(past_only) > 0
    # Assert: every row up to the cut is identical whether or not the future is known
    pd.testing.assert_frame_equal(full[full["open_time"] < cut].reset_index(drop=True), past_only)
    # Arrange: make every future volume 1000 times bigger
    changed = df.copy()
    # Scale only the bars from the cut on
    changed.loc[changed["open_time"] >= cut, "volume"] *= 1000
    # Act: build the universe on the changed data
    changed_result = filter_daily_universe(changed, 2)
    # Assert: the past rows still do not change
    pd.testing.assert_frame_equal(changed_result[changed_result["open_time"] < cut].reset_index(drop=True), past_only)


def test_filename_uses_m_for_millions_and_k_for_thousands():
    # Whole millions
    assert daily_universe_filename(2_000_000) == "universe_1d_min_mdv_2m.parquet"
    # Whole thousands
    assert daily_universe_filename(500_000) == "universe_1d_min_mdv_500k.parquet"
    # Whole thousands that are not whole millions
    assert daily_universe_filename(2_500_000) == "universe_1d_min_mdv_2500k.parquet"
    # Anything else keeps the number
    assert daily_universe_filename(1_500) == "universe_1d_min_mdv_1500.parquet"


def test_filename_rejects_bad_cutoffs():
    # Zero is not a useful cutoff
    with pytest.raises(ValueError):
        daily_universe_filename(0)
    # Neither is a negative number
    with pytest.raises(ValueError):
        daily_universe_filename(-5)
    # Or a fraction of a dollar
    with pytest.raises(ValueError):
        daily_universe_filename(1.5)


def test_each_cutoff_gets_its_own_file_and_a_rerun_leaves_others_alone(tmp_path):
    # Arrange: a cleaned daily file with a liquid coin A (10) and a thinner coin B (3)
    df = make_df(flat_bars("A", [10.0] * 40) + flat_bars("B", [3.0] * 40))
    # Save it where the update looks for it
    df.to_parquet(tmp_path / "candles_1d_cleaned.parquet", index=False)
    # Act: build two cutoffs
    update_daily_universe(tmp_path, 2)
    # The second cutoff only lets coin A in
    update_daily_universe(tmp_path, 5)
    # Where the two files should be
    low, high = tmp_path / "universe_1d_min_mdv_2.parquet", tmp_path / "universe_1d_min_mdv_5.parquet"
    # Assert: both files exist side by side and no temporary file is left over
    assert low.exists() and high.exists()
    # Assert: no leftover temporary files
    assert not list(tmp_path.glob("*.tmp"))
    # Assert: the lower cutoff has both coins, the higher only coin A
    assert set(pd.read_parquet(low)["symbol"]) == {"A", "B"}
    # The higher cutoff has only coin A
    assert set(pd.read_parquet(high)["symbol"]) == {"A"}
    # Remember the high file's exact bytes
    before = high.read_bytes()
    # Act: rerun the low cutoff
    update_daily_universe(tmp_path, 2)
    # Assert: the other cutoff's file is untouched
    assert high.read_bytes() == before


def test_update_prints_a_summary(tmp_path, capsys):
    # Arrange: a cleaned daily file with one liquid coin
    make_df(flat_bars("A", [10.0] * 40)).to_parquet(tmp_path / "candles_1d_cleaned.parquet", index=False)
    # Act: build the universe
    update_daily_universe(tmp_path, 5)
    # Assert: the summary names the file and counts rows and symbols
    assert "saved 10 rows to universe_1d_min_mdv_5.parquet, 1 symbols on the latest day, 1 symbols ever" in capsys.readouterr().out


def test_a_coin_that_is_in_stays_in_between_the_exit_and_entry_levels():
    # Arrange: 30 bars at 12 (above the entry level of 10), then 40 bars at 7 (between the exit level 5 and 10)
    df = make_df(flat_bars("A", [12.0] * 30 + [7.0] * 40))
    # Act: filter with entry 10 and exit 5
    result = filter_daily_universe(df, 10, 5)
    # Assert: the coin joins on its 31st bar and is never dropped, because 7 never falls below the exit level
    assert kept_bars(result) == list(range(30, 70))
    # Act again: with a single cutoff of 10, the same coin is dropped once its median falls to 7
    single = filter_daily_universe(df, 10)
    # Assert: the single cutoff keeps it from the start but loses it before the end
    assert 30 in kept_bars(single)
    # Assert: the last bar is missing from the single-cutoff result
    assert 69 not in kept_bars(single)


def test_a_coin_between_the_levels_does_not_enter():
    # Arrange: 40 bars at 7, which is above the exit level (5) but below the entry level (10)
    df = make_df(flat_bars("A", [7.0] * 40))
    # Act: filter with entry 10 and exit 5
    result = filter_daily_universe(df, 10, 5)
    # Assert: the coin never joined, so nothing is kept
    assert result.empty


def test_a_coin_leaves_below_the_exit_level_and_needs_the_entry_level_to_return():
    # Arrange: 30 bars at 12 (joins), 30 at 2 (below the exit level 5), 30 at 7 (between the levels), 30 at 12 (back above entry)
    df = make_df(flat_bars("A", [12.0] * 30 + [2.0] * 30 + [7.0] * 30 + [12.0] * 30))
    # Act: filter with entry 10 and exit 5
    result = filter_daily_universe(df, 10, 5)
    # Assert: in from bar 30 to 45, out from bar 46 (median 2 at the previous close), still out while the median is
    # only 7, and back in from bar 106, the day after the median reached 12
    assert kept_bars(result) == list(range(30, 46)) + list(range(106, 120))


def test_exit_level_equal_to_entry_level_gives_the_single_cutoff_result():
    # Arrange: two coins with 80 random bars each, like the look-ahead test
    rng = np.random.default_rng(1)
    # Put both coins in one table
    df = make_df(flat_bars("A", rng.uniform(5, 15, 80)) + flat_bars("B", rng.uniform(0.5, 3.5, 80)))
    # Act: filter with a single cutoff, and with the exit level given as the same number
    single = filter_daily_universe(df, 2)
    # The same cutoff given as both entry and exit
    same = filter_daily_universe(df, 2, 2)
    # Assert: the results are identical (and not empty)
    assert len(single) > 0
    # The two tables match exactly
    pd.testing.assert_frame_equal(single, same)


def test_a_missing_bar_resets_a_coin_even_with_an_exit_level():
    # Arrange: 100 liquid bars (10) with bar 40 missing
    df = make_df(flat_bars("A", [10.0] * 100, skip={40}))
    # Act: filter with entry 5 and a much lower exit level of 1
    result = filter_daily_universe(df, 5, 1)
    # Assert: the gap blocks the coin until its window is full again, exactly as with a single cutoff
    assert kept_bars(result) == list(range(30, 40)) + list(range(71, 100))


def test_exit_level_state_does_not_carry_from_one_symbol_to_the_next():
    # Arrange: coin A joins and stays in (12, then 7); coin B only ever sits at 7
    df = make_df(flat_bars("A", [12.0] * 30 + [7.0] * 40) + flat_bars("B", [7.0] * 70))
    # Act: filter with entry 10 and exit 5
    result = filter_daily_universe(df, 10, 5)
    # Assert: only coin A is kept
    assert set(result["symbol"]) == {"A"}


def test_bad_exit_levels_are_rejected():
    # A small valid table to filter
    df = make_df(flat_bars("A", [10.0] * 40))
    # An exit level above the entry level makes no sense
    with pytest.raises(ValueError):
        filter_daily_universe(df, 5, 6)
    # Neither does zero
    with pytest.raises(ValueError):
        filter_daily_universe(df, 5, 0)
    # Or a negative number
    with pytest.raises(ValueError):
        filter_daily_universe(df, 5, -1)


def test_no_look_ahead_with_an_exit_level():
    # Arrange: two coins with 80 random bars each; A is liquid (about 10) and B sits between the levels (about 2)
    rng = np.random.default_rng(2)
    # Random volumes for coin A
    volumes_a = rng.uniform(5, 15, 80)
    # Random volumes for coin B
    volumes_b = rng.uniform(0.5, 3.5, 80)
    # Put both coins in one table
    df = make_df(flat_bars("A", volumes_a) + flat_bars("B", volumes_b))
    # The first 60 days are "the past"; later days are "the future"
    cut = pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=60)
    # Act: build the universe on all the data, with entry 8 and exit 4
    full = filter_daily_universe(df, 8, 4)
    # Act: build it again with only the past
    past_only = filter_daily_universe(df[df["open_time"] < cut], 8, 4)
    # Assert: the test is meaningful (the past has kept rows)
    assert len(past_only) > 0
    # Assert: every row up to the cut is identical whether or not the future is known
    pd.testing.assert_frame_equal(full[full["open_time"] < cut].reset_index(drop=True), past_only)
    # Arrange: make every future volume 1000 times bigger
    changed = df.copy()
    # Scale only the bars from the cut on
    changed.loc[changed["open_time"] >= cut, "volume"] *= 1000
    # Act: build the universe on the changed data
    changed_result = filter_daily_universe(changed, 8, 4)
    # Assert: the past rows still do not change
    pd.testing.assert_frame_equal(changed_result[changed_result["open_time"] < cut].reset_index(drop=True), past_only)


def test_filename_gets_an_exit_part_only_when_the_exit_level_is_lower():
    # An exit level below the entry level is added to the name
    assert daily_universe_filename(2_000_000, 1_000_000) == "universe_1d_min_mdv_2m_exit_1m.parquet"
    # The thousands label works for the exit level too
    assert daily_universe_filename(2_000_000, 500_000) == "universe_1d_min_mdv_2m_exit_500k.parquet"
    # An exit level equal to the entry level changes nothing
    assert daily_universe_filename(2_000_000, 2_000_000) == "universe_1d_min_mdv_2m.parquet"
    # No exit level changes nothing either
    assert daily_universe_filename(2_000_000, None) == "universe_1d_min_mdv_2m.parquet"
    # A bad exit level is rejected like a bad entry level
    with pytest.raises(ValueError):
        daily_universe_filename(2_000_000, 0)


def test_entry_exit_file_sits_next_to_the_single_cutoff_file(tmp_path):
    # Arrange: a cleaned daily file with one coin that joins (12) and then sits between the levels (7)
    make_df(flat_bars("A", [12.0] * 30 + [7.0] * 40)).to_parquet(tmp_path / "candles_1d_cleaned.parquet", index=False)
    # Act: build a single cutoff of 10, and then the same entry level with an exit level of 5
    update_daily_universe(tmp_path, 10)
    # The entry/exit version
    update_daily_universe(tmp_path, 10, 5)
    # Where the two files should be
    single, both = tmp_path / "universe_1d_min_mdv_10.parquet", tmp_path / "universe_1d_min_mdv_10_exit_5.parquet"
    # Assert: both files exist
    assert single.exists() and both.exists()
    # Assert: the exit level keeps the coin longer, so its file has more rows
    assert len(pd.read_parquet(both)) > len(pd.read_parquet(single))
    # Remember the single file's exact bytes
    before = single.read_bytes()
    # Act: rerun the entry/exit version
    update_daily_universe(tmp_path, 10, 5)
    # Assert: the single-cutoff file is untouched
    assert single.read_bytes() == before

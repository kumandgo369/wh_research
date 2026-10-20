# numpy gives us log and NaN checks
import numpy as np
# pandas gives us tables (DataFrames)
import pandas as pd
# pytest is the test framework; we use its raises
import pytest

# BAR_MS says how long one bar lasts for each interval
from wh_research.data.hyperliquid.candles import BAR_MS
# The function we are testing
from wh_research.data.hyperliquid.features import add_past_returns


def make_candles(rows, interval="1d"):
    """rows: list of (symbol, bar, close), one row per bar. Only the columns the features need."""
    # Build a table from the list of rows and name its columns
    df = pd.DataFrame(rows, columns=["symbol", "bar", "close"])
    # Turn "bar number" into a real time: bar 0 starts at 2024-01-01 00:00, and each bar is one interval later
    df["open_time"] = pd.Timestamp("2024-01-01", tz="UTC") + pd.to_timedelta(df["bar"] * BAR_MS[interval], unit="ms")
    # A bar closes 1 ms before the next one opens, like the real data
    df["close_time"] = df["open_time"] + pd.Timedelta(milliseconds=BAR_MS[interval] - 1)
    # Hand back the finished table
    return df


def bars(symbol, closes, skip=()):
    # One row per close; bars whose number is in skip are left out, which makes a gap in the series
    return [(symbol, bar, close) for bar, close in enumerate(closes) if bar not in skip]


def test_past_log_return_is_the_log_of_this_close_over_the_close_n_bars_earlier():
    # Arrange: closes that double every bar
    df = make_candles(bars("A", [1.0, 2.0, 4.0, 8.0]))
    # Act: one bar back and two bars back
    out = add_past_returns(df, "1d", [1, 2])
    # Assert: one bar back is log 2 everywhere except the first bar, which has no past
    np.testing.assert_allclose(out["past_log_return_1"], [np.nan, np.log(2), np.log(2), np.log(2)])
    # Assert: two bars back is log 4, and the first two bars have no past
    np.testing.assert_allclose(out["past_log_return_2"], [np.nan, np.nan, np.log(4), np.log(4)])


def test_direction_columns_only_exist_when_asked_for():
    # Arrange: a small table
    df = make_candles(bars("A", [1.0, 2.0, 3.0]))
    # Act: ask without and with the direction
    without = add_past_returns(df, "1d", 1)
    with_direction = add_past_returns(df, "1d", 1, direction=True)
    # Assert: no direction column by default
    assert "past_direction_1" not in without.columns
    # Assert: the direction column is there when asked for
    assert "past_direction_1" in with_direction.columns


def test_direction_is_1_for_up_and_0_for_flat_or_down_and_nan_stays_nan():
    # Arrange: closes that go up, stay flat, go down
    df = make_candles(bars("A", [1.0, 2.0, 2.0, 1.0]))
    # Act: one bar back with direction
    out = add_past_returns(df, "1d", 1, direction=True)
    # Assert: the first bar (no past) is NaN, not 0; then up = 1, flat = 0, down = 0
    np.testing.assert_array_equal(out["past_direction_1"], [np.nan, 1.0, 0.0, 0.0])


def test_the_first_n_bars_of_each_coin_have_no_feature():
    # Arrange: two coins with 10 bars each
    df = make_candles(bars("A", range(1, 11)) + bars("B", range(11, 21)))
    # Act: 3 bars back with direction
    out = add_past_returns(df, "1d", 3, direction=True)
    # Assert: exactly 3 missing returns per coin (not 0)
    assert out.groupby("symbol")["past_log_return_3"].apply(lambda s: s.isna().sum()).to_dict() == {"A": 3, "B": 3}
    # Assert: the directions are missing in the same places
    assert out.groupby("symbol")["past_direction_3"].apply(lambda s: s.isna().sum()).to_dict() == {"A": 3, "B": 3}


def test_no_rows_are_dropped_and_the_input_is_not_changed():
    # Arrange: a table with an unusual index and an extra column that must pass through
    df = make_candles(bars("A", [1.0, 2.0, 3.0]) + bars("B", [4.0, 5.0, 6.0]))
    # An index that is not 0, 1, 2, ...
    df.index = [30, 10, 20, 50, 40, 60]
    # An extra column such as the universe flag
    df["in_universe"] = [True, False, True, False, True, False]
    # Remember the input to compare later
    before = df.copy()
    # Act: two horizons
    out = add_past_returns(df, "1d", [1, 2])
    # Assert: same rows, in the same order, with the same index
    assert list(out.index) == [30, 10, 20, 50, 40, 60]
    # Assert: the original columns come through unchanged
    pd.testing.assert_frame_equal(out[list(df.columns)], before)
    # Assert: the input table itself was not modified
    pd.testing.assert_frame_equal(df, before)


def test_coins_do_not_mix():
    # Arrange: coin A has 2 bars and coin B follows right after it in the table
    df = make_candles(bars("A", [1.0, 2.0]) + bars("B", [10.0, 20.0]))
    # Act: one bar back
    out = add_past_returns(df, "1d", 1)
    # Assert: coin B's first bar has no past (a plain row shift would have used coin A's last bar)
    assert np.isnan(out["past_log_return_1"].iloc[2])
    # Assert: coin B's second bar uses coin B's own first bar
    assert out["past_log_return_1"].iloc[3] == pytest.approx(np.log(2))


def test_a_missing_source_bar_gives_nan_and_a_missing_bar_in_between_does_not_matter():
    # Arrange: closes 1..5 for bars 0 to 4, with bar 2 missing from the table
    df = make_candles(bars("A", [1.0, 2.0, 3.0, 4.0, 5.0], skip={2}))
    # Act: one and two bars back
    out = add_past_returns(df, "1d", [1, 2]).set_index("bar")
    # Assert: bar 3 needs bar 2, which is missing, so its 1-bar feature is NaN (not bar 1's price)
    assert np.isnan(out.loc[3, "past_log_return_1"])
    # Assert: bar 1 needs bar 0, which exists
    assert out.loc[1, "past_log_return_1"] == pytest.approx(np.log(2.0 / 1.0))
    # Assert: bar 2 does not exist, so bar 4 needs it for its 2-bar feature and gets NaN
    assert np.isnan(out.loc[4, "past_log_return_2"])
    # Assert: bar 3's 2-bar feature uses bar 1 (the gap in between is irrelevant), not the previous row
    assert out.loc[3, "past_log_return_2"] == pytest.approx(np.log(4.0 / 2.0))


def test_the_row_order_of_the_input_does_not_matter():
    # Arrange: two coins in a shuffled row order
    df = make_candles(bars("A", [1.0, 2.0, 4.0, 8.0]) + bars("B", [3.0, 6.0, 12.0, 24.0]))
    # The same rows in a shuffled order
    shuffled = df.sample(frac=1, random_state=0)
    # Act: compute on both tables
    out_sorted = add_past_returns(df, "1d", 1)
    # Compute on the shuffled table
    out_shuffled = add_past_returns(shuffled, "1d", 1)
    # Assert: the shuffled table keeps its own order
    assert list(out_shuffled.index) == list(shuffled.index)
    # Assert: every row gets the same feature either way
    pd.testing.assert_series_equal(out_shuffled["past_log_return_1"].sort_index(), out_sorted["past_log_return_1"])


def test_hourly_bars_use_hours_as_the_unit():
    # Arrange: 30 hourly bars with closes 100, 101, 102, ...
    df = make_candles(bars("A", [100.0 + bar for bar in range(30)]), interval="1h")
    # Act: 24 bars (one day) back
    out = add_past_returns(df, "1h", 24)
    # Assert: bar 24 looks at bar 0, which is 24 hours earlier
    assert out["past_log_return_24"].iloc[24] == pytest.approx(np.log(124.0 / 100.0))
    # Assert: the first 24 bars have no feature
    assert out["past_log_return_24"].isna().sum() == 24


def test_several_horizons_and_a_single_number_both_work():
    # Arrange: 10 bars
    df = make_candles(bars("A", range(1, 11)))
    # Act: three horizons in one call
    many = add_past_returns(df, "1d", [1, 3, 7])
    # Assert: a column for each horizon
    for n in (1, 3, 7):
        # The return column exists
        assert f"past_log_return_{n}" in many.columns
    # Act: a single number
    single = add_past_returns(df, "1d", 3)
    # Assert: the same as asking for [3]
    pd.testing.assert_series_equal(single["past_log_return_3"], many["past_log_return_3"])


def test_a_feature_depends_only_on_its_own_close_and_the_close_n_bars_earlier():
    # Arrange: 12 bars with made-up closes
    closes = [5.0, 7.0, 6.0, 9.0, 8.0, 10.0, 4.0, 11.0, 12.0, 3.0, 13.0, 2.0]
    # The feature for bar 6 with n = 3 uses bar 6 and bar 3
    original = add_past_returns(make_candles(bars("A", closes)), "1d", 3)["past_log_return_3"].iloc[6]
    # Arrange: change the bars in between (4, 5) and every bar after bar 6, which is the future
    changed_closes = list(closes)
    # Bars in between
    changed_closes[4], changed_closes[5] = 100.0, 200.0
    # Bars after (the future: must not matter)
    changed_closes[7:] = [300.0] * 5
    # Act: compute again
    unchanged = add_past_returns(make_candles(bars("A", changed_closes)), "1d", 3)["past_log_return_3"].iloc[6]
    # Assert: bar 6's feature did not move
    assert unchanged == original
    # Arrange: now change bar 3 itself
    changed_closes[3] = 90.0
    # Act: compute again
    moved = add_past_returns(make_candles(bars("A", changed_closes)), "1d", 3)["past_log_return_3"].iloc[6]
    # Assert: the feature follows bar 3
    assert moved == pytest.approx(np.log(4.0 / 90.0))


def test_bad_prices_give_nan_not_infinity():
    # Arrange: a coin with a zero close in the middle
    df = make_candles(bars("A", [1.0, 0.0, 2.0]))
    # Act: one bar back
    out = add_past_returns(df, "1d", 1)
    # Assert: no infinite values
    assert not np.isinf(out["past_log_return_1"]).any()
    # Assert: every return is NaN (the first has no past, the others touch the zero price)
    assert out["past_log_return_1"].isna().all()


def test_bad_input_is_rejected():
    # A small valid table
    df = make_candles(bars("A", [1.0, 2.0, 3.0]))
    # An interval we do not support
    with pytest.raises(ValueError):
        add_past_returns(df, "5m", 1)
    # Zero bars back is not a past return
    with pytest.raises(ValueError):
        add_past_returns(df, "1d", 0)
    # Neither is a negative number
    with pytest.raises(ValueError):
        add_past_returns(df, "1d", [1, -2])
    # Or a fraction of a bar
    with pytest.raises(ValueError):
        add_past_returns(df, "1d", 1.5)
    # The same coin and bar twice cannot be looked up
    with pytest.raises(ValueError):
        add_past_returns(pd.concat([df, df]), "1d", 1)

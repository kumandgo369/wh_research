# pandas gives us tables (DataFrames) and reads/writes parquet files
import pandas as pd
# pytest is the test framework; we use its parametrize and tmp_path
import pytest

# BAR_MS says how long one bar lasts, and candles_filename gives the raw file's name
from wh_research.data.hyperliquid.candles import BAR_MS, candles_filename
# The two functions we are testing
from wh_research.data.hyperliquid.clean_candles import clean_candles, update_candles_cleaned

# Every candle size the code supports; tests marked with INTERVALS run once per size
INTERVALS = list(BAR_MS)


def make_df(rows, interval="1d"):
    """rows: list of (symbol, bar, open, high, low, close, volume)"""
    # Build a table from the list of rows and name its columns
    df = pd.DataFrame(rows, columns=["symbol", "bar", "open", "high", "low", "close", "volume"])
    # Turn "bar number" into a real time: bar 0 is 2024-01-01 00:00, and each bar is one interval later
    df["open_time"] = pd.Timestamp("2024-01-01", tz="UTC") + pd.to_timedelta(df["bar"] * BAR_MS[interval], unit="ms")
    # Hand back the finished table
    return df


def flat_bar(symbol, bar, price, volume=1.0):
    # A bar where open, high, low and close are all the same price (always valid)
    return (symbol, bar, price, price, price, price, volume)


def test_drops_pre_trading_bars_but_keeps_mid_series_zero_volume():
    # Arrange: build four daily bars for coin A
    df = make_df([
        # Bar 0 has no volume and comes before the first trade, so it should be dropped
        flat_bar("A", 0, 1.0, volume=0),
        # Bar 1 is the first bar with volume, so it is where the coin starts
        flat_bar("A", 1, 1.1),
        # Bar 2 has no volume but comes after the first trade, so it should be kept
        flat_bar("A", 2, 1.2, volume=0),
        # Bar 3 has normal volume
        flat_bar("A", 3, 1.3),
    ])
    # Act: run the cleaning
    out = clean_candles(df, "1d")
    # Assert: the days left are Jan 2, 3 and 4 (bars 1, 2 and 3), so only bar 0 was dropped
    assert list(out["open_time"].dt.day) == [2, 3, 4]


def test_each_validity_rule():
    # Arrange: one good row, then one row that breaks each rule
    # (columns are: symbol, bar, open, high, low, close, volume)
    df = make_df([
        # Good row: low 1 <= open and close 2 <= high 3
        ("A", 0, 2, 3, 1, 2, 1),
        # Bad: high (1) is smaller than low (3)
        ("A", 1, 2, 1, 3, 2, 1),
        # Bad: high (3) is smaller than open (5)
        ("A", 2, 5, 3, 1, 2, 1),
        # Bad: high (3) is smaller than close (4)
        ("A", 3, 2, 3, 1, 4, 1),
        # Bad: low (1) is bigger than open (0.5)
        ("A", 4, 0.5, 3, 1, 2, 1),
        # Bad: low (1) is bigger than close (0.5)
        ("A", 5, 2, 3, 1, 0.5, 1),
        # Bad: open price is 0, and prices must be above 0
        ("A", 6, 0, 3, 0, 2, 1),
        # Bad: volume is negative
        ("A", 7, 2, 3, 1, 2, -1),
    ])
    # Act: run the cleaning
    out = clean_candles(df, "1d")
    # Assert: only the first row is valid and the other seven are flagged
    assert list(out["is_valid"]) == [True] + [False] * 7
    # Assert: flagged rows were kept, so all 8 rows are still there
    assert len(out) == 8


def test_stale_needs_more_than_three_equal_closes():
    # Closes: a run of 3 equal (1), a run of 4 equal (2), then one different (3)
    prices = [1, 1, 1, 2, 2, 2, 2, 3]
    # Arrange: one flat bar per price, one per bar, all for coin A
    df = make_df([flat_bar("A", i, p) for i, p in enumerate(prices)])
    # Act: run the cleaning
    out = clean_candles(df, "1d")
    # Assert: the run of 3 is fine, the run of 4 is stale, and the last bar is fine
    assert list(out["is_stale"]) == [False] * 3 + [True] * 4 + [False]


def test_stale_run_does_not_cross_symbols():
    # Arrange: coin A has 2 bars at price 1.0, and coin B also has 2 bars at price 1.0
    df = make_df(
        [flat_bar("A", i, 1.0) for i in range(2)]
        # Same price as A, but a different coin, so the runs must not join into one run of 4
        + [flat_bar("B", i, 1.0) for i in range(2)]
    )
    # Act: run the cleaning
    out = clean_candles(df, "1d")
    # Assert: no bar is stale, because each coin only has a run of 2
    assert not out["is_stale"].any()


@pytest.mark.parametrize("interval", INTERVALS)
def test_after_gap_flags_first_bar_after_missing_bars(interval):
    # Arrange: coin A has bars 0, 1 and 3 (bar 2 is missing), and coin B has bars 0 and 1 (no gap)
    df = make_df(
        [flat_bar("A", bar, 1.0 + bar) for bar in [0, 1, 3]]
        + [flat_bar("B", bar, 1.0 + bar) for bar in [0, 1]],
        interval,
    )
    # Act: run the cleaning for this interval
    out = clean_candles(df, interval)
    # Assert: only coin A's bar 3 (the one right after the gap) is flagged
    assert list(out["after_gap"]) == [False, False, True, False, False]


def test_gap_check_uses_the_interval_length():
    # Arrange: bars one hour apart, which is a normal step for 1h candles
    df = make_df([flat_bar("A", bar, 1.0 + bar) for bar in range(3)], "1h")
    # Assert: one hour apart is no gap for 1h candles, and (being shorter than a day) none for 1d either
    assert not clean_candles(df, "1h")["after_gap"].any()
    assert not clean_candles(df, "1d")["after_gap"].any()
    # Arrange: bars two hours apart
    df = make_df([flat_bar("A", bar * 2, 1.0 + bar) for bar in range(3)], "1h")
    # Assert: two hours apart is a gap for 1h candles, but not for 1d candles
    assert list(clean_candles(df, "1h")["after_gap"]) == [False, True, True]
    assert not clean_candles(df, "1d")["after_gap"].any()


@pytest.mark.parametrize("interval", INTERVALS)
def test_update_candles_cleaned_writes_file(tmp_path, interval):
    # Arrange: save a tiny raw candles file (3 bars with different prices) in a temporary folder
    raw = make_df([flat_bar("A", i, 1.0 + i) for i in range(3)], interval)
    # Write it under the raw file name for this interval
    raw.to_parquet(tmp_path / candles_filename(interval))
    # Act: build the cleaned file from it
    update_candles_cleaned(tmp_path, interval)
    # Read the cleaned file back from disk (its name contains the interval)
    out = pd.read_parquet(tmp_path / f"candles_{interval}_cleaned.parquet")
    # Assert: all 3 rows were written
    assert len(out) == 3
    # Assert: the flag columns exist (<= on sets means "is a subset of")
    assert {"is_valid", "is_stale", "after_gap"} <= set(out.columns)

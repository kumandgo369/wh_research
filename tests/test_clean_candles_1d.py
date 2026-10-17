# pandas gives us tables (DataFrames) and reads/writes parquet files
import pandas as pd

# The two functions we are testing
from wh_research.data.hyperliquid.clean_candles_1d import clean_candles_1d, update_candles_1d_cleaned


def make_df(rows):
    """rows: list of (symbol, day, open, high, low, close, volume)"""
    # Build a table from the list of rows and name its columns
    df = pd.DataFrame(rows, columns=["symbol", "day", "open", "high", "low", "close", "volume"])
    # Turn "day number" into a real date: day 0 is 2024-01-01, day 1 is 2024-01-02, and so on
    df["open_time"] = pd.Timestamp("2024-01-01", tz="UTC") + pd.to_timedelta(df["day"], unit="D")
    # Hand back the finished table
    return df


def flat_bar(symbol, day, price, volume=1.0):
    # A bar where open, high, low and close are all the same price (always valid)
    return (symbol, day, price, price, price, price, volume)


def test_drops_pre_trading_bars_but_keeps_mid_series_zero_volume():
    # Arrange: build four daily bars for coin A
    df = make_df([
        # Day 0 has no volume and comes before the first trade, so it should be dropped
        flat_bar("A", 0, 1.0, volume=0),
        # Day 1 is the first bar with volume, so it is where the coin starts
        flat_bar("A", 1, 1.1),
        # Day 2 has no volume but comes after the first trade, so it should be kept
        flat_bar("A", 2, 1.2, volume=0),
        # Day 3 has normal volume
        flat_bar("A", 3, 1.3),
    ])
    # Act: run the cleaning
    out = clean_candles_1d(df)
    # Assert: the days left are Jan 2, 3 and 4 (days 1, 2 and 3), so only day 0 was dropped
    assert list(out["open_time"].dt.day) == [2, 3, 4]


def test_each_validity_rule():
    # Arrange: one good row, then one row that breaks each rule
    # (columns are: symbol, day, open, high, low, close, volume)
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
    out = clean_candles_1d(df)
    # Assert: only the first row is valid and the other seven are flagged
    assert list(out["is_valid"]) == [True] + [False] * 7
    # Assert: flagged rows were kept, so all 8 rows are still there
    assert len(out) == 8


def test_stale_needs_more_than_three_equal_closes():
    # Closes: a run of 3 equal (1), a run of 4 equal (2), then one different (3)
    prices = [1, 1, 1, 2, 2, 2, 2, 3]
    # Arrange: one flat bar per price, one per day, all for coin A
    df = make_df([flat_bar("A", i, p) for i, p in enumerate(prices)])
    # Act: run the cleaning
    out = clean_candles_1d(df)
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
    out = clean_candles_1d(df)
    # Assert: no bar is stale, because each coin only has a run of 2
    assert not out["is_stale"].any()


def test_after_gap_flags_first_bar_after_missing_days():
    # Arrange: coin A has days 0, 1 and 3 (day 2 is missing), and coin B has days 0 and 1 (no gap)
    df = make_df(
        [flat_bar("A", day, 1.0 + day) for day in [0, 1, 3]]
        + [flat_bar("B", day, 1.0 + day) for day in [0, 1]]
    )
    # Act: run the cleaning
    out = clean_candles_1d(df)
    # Assert: only coin A's day 3 bar (the one right after the gap) is flagged
    assert list(out["after_gap"]) == [False, False, True, False, False]


def test_update_candles_1d_cleaned_writes_file(tmp_path):
    # Arrange: save a tiny raw candles file (3 bars with different prices) in a temporary folder
    make_df([flat_bar("A", i, 1.0 + i) for i in range(3)]).to_parquet(tmp_path / "candles_1d.parquet")
    # Act: build the cleaned file from it
    update_candles_1d_cleaned(tmp_path)
    # Read the cleaned file back from disk
    out = pd.read_parquet(tmp_path / "candles_1d_cleaned.parquet")
    # Assert: all 3 rows were written
    assert len(out) == 3
    # Assert: the two flag columns exist (<= on sets means "is a subset of")
    assert {"is_valid", "is_stale"} <= set(out.columns)

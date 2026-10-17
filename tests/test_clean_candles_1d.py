import pandas as pd

from wh_research.data.hyperliquid.clean_candles_1d import clean_candles_1d, update_candles_1d_cleaned


def make_df(rows):
    """rows: list of (symbol, day, open, high, low, close, volume)"""
    df = pd.DataFrame(rows, columns=["symbol", "day", "open", "high", "low", "close", "volume"])
    df["open_time"] = pd.Timestamp("2024-01-01", tz="UTC") + pd.to_timedelta(df["day"], unit="D")
    return df


def flat_bar(symbol, day, price, volume=1.0):
    return (symbol, day, price, price, price, price, volume)


def test_drops_pre_trading_bars_but_keeps_mid_series_zero_volume():
    df = make_df([
        flat_bar("A", 0, 1.0, volume=0),  # before first trade: dropped
        flat_bar("A", 1, 1.1),            # first trade
        flat_bar("A", 2, 1.2, volume=0),  # zero volume later on: kept
        flat_bar("A", 3, 1.3),
    ])
    out = clean_candles_1d(df)
    assert list(out["open_time"].dt.day) == [2, 3, 4]


def test_each_validity_rule():
    df = make_df([
        ("A", 0, 2, 3, 1, 2, 1),    # good row
        ("A", 1, 2, 1, 3, 2, 1),    # high < low
        ("A", 2, 5, 3, 1, 2, 1),    # high < open
        ("A", 3, 2, 3, 1, 4, 1),    # high < close
        ("A", 4, 0.5, 3, 1, 2, 1),  # low > open
        ("A", 5, 2, 3, 1, 0.5, 1),  # low > close
        ("A", 6, 0, 3, 0, 2, 1),    # price is 0
        ("A", 7, 2, 3, 1, 2, -1),   # negative volume
    ])
    out = clean_candles_1d(df)
    assert list(out["is_valid"]) == [True] + [False] * 7
    assert len(out) == 8  # nothing dropped


def test_stale_needs_more_than_three_equal_closes():
    prices = [1, 1, 1, 2, 2, 2, 2, 3]  # run of 3, run of 4, then one change
    df = make_df([flat_bar("A", i, p) for i, p in enumerate(prices)])
    out = clean_candles_1d(df)
    assert list(out["is_stale"]) == [False] * 3 + [True] * 4 + [False]


def test_stale_run_does_not_cross_symbols():
    df = make_df(
        [flat_bar("A", i, 1.0) for i in range(2)]
        + [flat_bar("B", i, 1.0) for i in range(2)]  # same price, but a different coin
    )
    out = clean_candles_1d(df)
    assert not out["is_stale"].any()


def test_update_candles_1d_cleaned_writes_file(tmp_path):
    make_df([flat_bar("A", i, 1.0 + i) for i in range(3)]).to_parquet(tmp_path / "candles_1d.parquet")
    update_candles_1d_cleaned(tmp_path)
    out = pd.read_parquet(tmp_path / "candles_1d_cleaned.parquet")
    assert len(out) == 3
    assert {"is_valid", "is_stale"} <= set(out.columns)

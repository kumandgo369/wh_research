"""Cleaning for the Hyperliquid daily candles (candles_1d.parquet).

Only works with that file's columns:
symbol, open_time, close_time, open, high, low, close, volume, trades

Example:
    df = pd.read_parquet("data/hyperliquid/candles_1d.parquet")
    df = clean_candles_1d(df)
    good = df[df["is_valid"] & ~df["is_stale"]]
"""

from pathlib import Path

import pandas as pd

STALE_BARS = 3  # a close that stays the same for MORE than this many bars is stale


def clean_candles_1d(df):
    """Drop pre-trading bars, then add True/False check columns.

    After the first step no rows are removed, so the daily series has no gaps.
    """
    df = df.sort_values(["symbol", "open_time"]).copy()

    # Step 0: drop the bars before each coin's first real trade (volume > 0).
    # This only trims the start of each coin, so it cannot leave a gap.
    traded = df[df["volume"] > 0]
    first_traded = traded.groupby("symbol")["open_time"].min()
    df = df[df["open_time"] >= df["symbol"].map(first_traded)].copy()

    # Step 1: validity checks. True means the row passes.
    df["ok_high_low"] = df["high"] >= df["low"]
    df["ok_high"] = (df["high"] >= df["open"]) & (df["high"] >= df["close"])
    df["ok_low"] = (df["low"] <= df["open"]) & (df["low"] <= df["close"])
    df["ok_price"] = (df[["open", "high", "low", "close"]] > 0).all(axis=1)
    df["ok_volume"] = df["volume"] >= 0
    ok_columns = ["ok_high_low", "ok_high", "ok_low", "ok_price", "ok_volume"]
    df["is_valid"] = df[ok_columns].all(axis=1)

    # Step 2: stale price detector.
    # A new "run" starts whenever the close differs from the previous bar's close
    # of the same coin. (The first bar of each coin has no previous bar, so it
    # always starts a new run. Runs never cross from one coin into the next.)
    previous_close = df.groupby("symbol")["close"].shift()
    run_id = (df["close"] != previous_close).cumsum()
    run_length = df.groupby(run_id)["close"].transform("size")
    df["is_stale"] = run_length > STALE_BARS

    return df


def update_candles_1d_cleaned(data_dir):
    """Rebuild candles_1d_cleaned.parquet from candles_1d.parquet.

    Always a full rebuild: a new bar can make earlier bars stale.
    """
    data_dir = Path(data_dir)
    df = clean_candles_1d(pd.read_parquet(data_dir / "candles_1d.parquet"))
    path = data_dir / "candles_1d_cleaned.parquet"
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)  # swap in only after a complete write
    print(f"saved {len(df)} rows, {df['is_stale'].sum()} stale, {(~df['is_valid']).sum()} invalid")

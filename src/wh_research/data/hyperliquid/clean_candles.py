"""Cleaning for the Hyperliquid candles (candles_1d.parquet or candles_1h.parquet).

Only works with those files' columns:
symbol, open_time, close_time, open, high, low, close, volume, trades

Example:
    df = pd.read_parquet("data/hyperliquid/candles_1h.parquet")
    df = clean_candles(df, "1h")
    good = df[df["is_valid"] & ~df["is_stale"] & ~df["after_gap"]]
"""

# Path builds file paths in a way that works on any operating system
from pathlib import Path

# pandas gives us tables (DataFrames) and reads/writes parquet files
import pandas as pd

# BAR_MS says how long one bar lasts, and candles_filename gives the raw file's name
from wh_research.data.hyperliquid.candles import BAR_MS, candles_filename

# A close price that stays the same for MORE than this many bars in a row is "stale"
STALE_BARS = 3


def clean_candles(df, interval):
    """Drop pre-trading bars, then add True/False check columns.

    After the first step no rows are removed, so the series has no gaps.
    """
    # Order the rows by coin, then by time, and work on a copy so the caller's table is untouched
    df = df.sort_values(["symbol", "open_time"]).copy()

    # Step 0: drop the bars before each coin's first real trade (volume > 0).
    # This only trims the start of each coin, so it cannot leave a gap.
    # Keep only the bars where something was actually traded
    traded = df[df["volume"] > 0]
    # For each coin, find the time of its first traded bar (the earliest open_time)
    first_traded = traded.groupby("symbol")["open_time"].min()
    # Look up each row's coin first-traded time and keep rows at or after it
    df = df[df["open_time"] >= df["symbol"].map(first_traded)].copy()

    # Step 1: validity checks. True means the row passes.
    # The high must be at least as big as the low
    df["ok_high_low"] = df["high"] >= df["low"]
    # The high must be at least as big as both the open and the close
    df["ok_high"] = (df["high"] >= df["open"]) & (df["high"] >= df["close"])
    # The low must be no bigger than both the open and the close
    df["ok_low"] = (df["low"] <= df["open"]) & (df["low"] <= df["close"])
    # All four prices must be above zero (.all(axis=1) means "true across the whole row")
    df["ok_price"] = (df[["open", "high", "low", "close"]] > 0).all(axis=1)
    # Volume can be zero but never negative
    df["ok_volume"] = df["volume"] >= 0
    # List the names of the five check columns
    ok_columns = ["ok_high_low", "ok_high", "ok_low", "ok_price", "ok_volume"]
    # A row is valid only when all five checks pass
    df["is_valid"] = df[ok_columns].all(axis=1)

    # Step 2: stale price detector.
    # A new "run" starts whenever the close differs from the previous bar's close
    # of the same coin. (The first bar of each coin has no previous bar, so it
    # always starts a new run. Runs never cross from one coin into the next.)
    # Get the previous bar's close within the same coin (the first bar of a coin gets nothing)
    previous_close = df.groupby("symbol")["close"].shift()
    # Whenever the close changed, add 1 to a running count, so equal closes in a row share a number
    run_id = (df["close"] != previous_close).cumsum()
    # Count how many bars share each run number, i.e. how long each run is
    run_length = df.groupby(run_id)["close"].transform("size")
    # A bar is stale when it belongs to a run longer than STALE_BARS
    df["is_stale"] = run_length > STALE_BARS

    # Step 3: gap detector. Flags the first bar after one or more missing bars.
    # Get the time between each bar and the previous bar of the same coin (the first bar gets nothing)
    time_since_previous = df.groupby("symbol")["open_time"].diff()
    # More than one bar length since the previous bar means bars are missing (a missing value counts as False)
    df["after_gap"] = time_since_previous > pd.Timedelta(milliseconds=BAR_MS[interval])

    # Hand the table back, with the new check columns added
    return df


def update_candles_cleaned(data_dir, interval):
    """Rebuild candles_<interval>_cleaned.parquet from candles_<interval>.parquet.

    Always a full rebuild: a new bar can make earlier bars stale.
    """
    # Make sure data_dir is a Path, even if the caller passed plain text
    data_dir = Path(data_dir)
    # Read the raw candles file and clean it
    df = clean_candles(pd.read_parquet(data_dir / candles_filename(interval)), interval)
    # Where the cleaned file will be saved, such as candles_1h_cleaned.parquet
    path = data_dir / f"candles_{interval}_cleaned.parquet"
    # A temporary file name next to it (same name, ending in .tmp)
    tmp = path.with_suffix(".tmp")
    # Write the table to the temporary file first (index=False skips the row numbers)
    df.to_parquet(tmp, index=False)
    # Swap the temporary file in only after it was fully written, so a crash can't corrupt the real file
    tmp.replace(path)
    # Print a summary: total rows, stale bars, rows that failed a check (~ means "not"), and gaps
    print(f"saved {len(df)} rows, {df['is_stale'].sum()} stale, {(~df['is_valid']).sum()} invalid, "
          f"{df['after_gap'].sum()} gaps")

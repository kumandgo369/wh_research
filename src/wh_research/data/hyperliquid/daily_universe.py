"""Daily tradeable universe: the cleaned 1d candles, kept only on days a coin was liquid enough.

Works with candles_1d_cleaned.parquet only (daily data, no interval argument).

A coin's liquidity is the median of its last 30 daily dollar volumes. A row for day t is
kept when that median, measured at the CLOSE OF DAY t-1, is at least the cutoff. So
nothing from day t (or later) decides whether day t is in the file, and there is no look-ahead.

Example:
    DATA_DIR = Path("path/to/data/hyperliquid")    # change to where your data folder is
    df = pd.read_parquet(DATA_DIR / "universe_1d_min_mdv_2m.parquet")
    # every row is already tradeable on its own day, so its return can be used directly
"""

# Path builds file paths in a way that works on any operating system
from pathlib import Path

# pandas gives us tables (DataFrames) and reads/writes parquet files
import pandas as pd

# BAR_MS says how long one bar lasts (we need the length of a daily bar)
from wh_research.data.hyperliquid.candles import BAR_MS

# How many daily bars the liquidity median looks at (also the history a coin needs first)
MDV_WINDOW_DAYS = 30


def daily_universe_filename(min_mdv_usd):
    """The name of the universe file for a cutoff, such as universe_1d_min_mdv_2m.parquet."""
    # The cutoff must be a whole number of dollars above zero
    if min_mdv_usd != int(min_mdv_usd) or min_mdv_usd <= 0:
        # Stop with a clear message instead of making a strange file name
        raise ValueError(f"min_mdv_usd must be a positive whole number of dollars, got {min_mdv_usd}")
    # Work with a plain integer from here on
    dollars = int(min_mdv_usd)
    # Whole millions are written with "m", such as 2000000 -> 2m
    if dollars % 1_000_000 == 0:
        # Build the short label from the number of millions
        label = f"{dollars // 1_000_000}m"
    # Whole thousands are written with "k", such as 500000 -> 500k
    elif dollars % 1_000 == 0:
        # Build the short label from the number of thousands
        label = f"{dollars // 1_000}k"
    # Anything else keeps the plain number
    else:
        # Use the dollars as they are
        label = str(dollars)
    # Put the label into the file name
    return f"universe_1d_min_mdv_{label}.parquet"


def filter_daily_universe(df, min_mdv_usd):
    """Keep the daily bars of coins that were liquid enough at the previous day's close.

    df is the cleaned 1d table. Returns its rows that pass, with two extra columns:
    dollar_volume (this bar's volume in dollars) and mdv_30d_prev (the 30-day median
    dollar volume as known at the previous bar's close).
    """
    # Order the rows by coin, then by time, and number the rows again from 0 so row labels are unique
    df = df.sort_values(["symbol", "open_time"]).reset_index(drop=True)

    # Dollar volume of each bar: coins traded times a typical price for the bar
    df["dollar_volume"] = df["volume"] * (df["high"] + df["low"] + df["close"]) / 3

    # Rolling window over the last 30 days that ends at this bar's close_time and looks at nothing later
    window = df.groupby("symbol").rolling(f"{MDV_WINDOW_DAYS}D", on="close_time")["dollar_volume"]
    # Median dollar volume over that window. The results come back in df's own row order (df is sorted by
    # coin, as the groups are), so we line them up by position instead of by label.
    mdv_30d = window.median().to_numpy()
    # Number of bars inside each window, in the same row order
    bars_in_window = window.count().to_numpy()
    # Minimum history: with fewer than 30 bars in the window (new coin or a gap) there is no value
    df["mdv_30d"] = pd.Series(mdv_30d, index=df.index).where(bars_in_window == MDV_WINDOW_DAYS)

    # What the median was at the PREVIOUS bar's close, within the same coin (first bar of a coin gets nothing)
    df["mdv_30d_prev"] = df.groupby("symbol")["mdv_30d"].shift()
    # The open time of the previous bar of the same coin
    previous_open = df.groupby("symbol")["open_time"].shift()
    # The previous bar only counts if it is exactly one day earlier (no missing bar right before this one)
    follows_directly = (df["open_time"] - previous_open) == pd.Timedelta(milliseconds=BAR_MS["1d"])
    # After a missing bar the old value is not trusted, so blank it
    df["mdv_30d_prev"] = df["mdv_30d_prev"].where(follows_directly)

    # Keep only the bars where the previous close's median reached the cutoff (a missing value counts as False)
    kept = df[df["mdv_30d_prev"] >= min_mdv_usd]
    # Hand back the kept rows without the same-day median, so it can't be used by mistake to pick day t
    return kept.drop(columns=["mdv_30d"]).reset_index(drop=True)


def update_daily_universe(data_dir, min_mdv_usd):
    """Rebuild the universe file for one cutoff from candles_1d_cleaned.parquet.

    Always a full rebuild of that cutoff's file. Files of other cutoffs are left alone.
    """
    # Make sure data_dir is a Path, even if the caller passed plain text
    data_dir = Path(data_dir)
    # Read the cleaned daily candles
    df = pd.read_parquet(data_dir / "candles_1d_cleaned.parquet")
    # Keep only the liquid-enough bars
    universe = filter_daily_universe(df, min_mdv_usd)
    # Where this cutoff's file will be saved, such as universe_1d_min_mdv_2m.parquet
    path = data_dir / daily_universe_filename(min_mdv_usd)
    # A temporary file name next to it (same name, ending in .tmp)
    tmp = path.with_suffix(".tmp")
    # Write the table to the temporary file first (index=False skips the row numbers)
    universe.to_parquet(tmp, index=False)
    # Swap the temporary file in only after it was fully written, so a crash can't corrupt the real file
    tmp.replace(path)
    # The newest day in the file (empty tables have none)
    latest = universe["open_time"].max()
    # How many coins were in the universe on that newest day
    latest_count = (universe["open_time"] == latest).sum()
    # Print a summary: rows, coins on the latest day, and coins that were ever included
    print(f"saved {len(universe)} rows to {path.name}, {latest_count} symbols on the latest day, "
          f"{universe['symbol'].nunique()} symbols ever included")

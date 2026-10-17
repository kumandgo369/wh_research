"""Hyperliquid perpetual futures daily candles.

Downloads and incrementally updates daily OHLCV bars for every perp in
info.meta()["universe"], delisted coins included, into one parquet file.

Scope:
- Perps only. Spot and builder-deployed (HIP-3) markets are not covered.
- Closed bars only. The current day's bar is excluded.
- Raw data. Leading zero-volume bars are kept; see clean_candles_1d.py.

Limits:
- The API serves at most 5000 candles per symbol and interval.
- Rate limited per IP (HTTP 429). download_with_retry backs off and retries.

Update behavior:
- The whole parquet file is rewritten on each run (atomic swap via .tmp).
- Symbols that fail are not written, so rerunning fetches only the missing ones.
- Delisted symbols already on disk are skipped.
"""

# time lets us read the clock and pause (sleep) between requests
import time
# datetime and timezone let us build the fixed start date below
from datetime import datetime, timezone
# Path builds file paths in a way that works on any operating system
from pathlib import Path

# pandas gives us tables (DataFrames) and reads/writes parquet files
import pandas as pd
# Info is Hyperliquid's class for asking the API for market data
from hyperliquid.info import Info
# constants holds the official API addresses, such as the main (real money) network
from hyperliquid.utils import constants

# The candle size we download: one bar per day
INTERVAL = "1d"
# The name of the file where the raw candles are saved
FILENAME = "candles_1d.parquet"

# The first moment we ask for, 2022-01-01 UTC, converted to milliseconds since 1970 (what the API wants)
START_TIME_MS = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
# The number of milliseconds in one day (24 * 60 * 60 * 1000)
ONE_DAY_MS = 86_400_000

# How many times we try a request before giving up
MAX_ATTEMPTS = 8
# Seconds to pause after each symbol, which keeps us under the API's rate limit
PAUSE_BETWEEN_SYMBOLS = 0.5

# The API uses one-letter keys. We rename them to readable column names.
API_COLUMN_NAMES = {
    # t = bar start time, T = bar end time, s = symbol (coin name)
    "t": "open_time", "T": "close_time", "s": "symbol",
    # o, h, l, c = open, high, low, close prices
    "o": "open", "h": "high", "l": "low", "c": "close",
    # v = volume traded, n = number of trades
    "v": "volume", "n": "trades",
}
# The columns that hold decimal numbers (the API sends them as text)
NUMBER_COLUMNS = ["open", "high", "low", "close", "volume"]
# All the columns of our table, in the order we save them
COLUMNS = ["symbol", "open_time", "close_time"] + NUMBER_COLUMNS + ["trades"]


def download_with_retry(info, symbol, start_ms, end_ms):
    """Ask the API for candles. If it says 429 (too many requests), wait and retry."""
    # Wait 5 seconds before the first retry
    wait_seconds = 5
    # Try the request up to MAX_ATTEMPTS times, counting attempts from 1
    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Run the request inside try so we can react if it fails
        try:
            # Ask the API for this symbol's candles and hand back the answer straight away if it works
            return info.candles_snapshot(symbol, INTERVAL, start_ms, end_ms)
        # If the request failed, catch the error so we can look at it
        except Exception as error:
            # The API's rate-limit errors carry the number 429 as their first argument
            is_rate_limit = error.args[:1] == (429,)
            # Give up (re-raise the error) if it is not a rate limit, or if this was the last attempt
            if not is_rate_limit or attempt == MAX_ATTEMPTS:
                raise
            # Tell the user we are about to wait
            print(f"{symbol}: 429, retry in {wait_seconds}s")
            # Pause so the rate limit can reset
            time.sleep(wait_seconds)
            # Wait twice as long next time, but never more than 60 seconds
            wait_seconds = min(wait_seconds * 2, 60)


def to_dataframe(raw_candles, end_ms):
    """Turn the API's list of dicts into a table with our columns.

    Bars that have not closed yet (close_time >= end_ms) are dropped.
    """
    # If the API returned nothing, return an empty table that still has our columns
    if not raw_candles:
        return pd.DataFrame(columns=COLUMNS)

    # Build a table from the list of dicts and rename the one-letter columns to readable names
    candles = pd.DataFrame(raw_candles).rename(columns=API_COLUMN_NAMES)
    # Keep only bars that finished before end_ms (a bar still forming would change later)
    candles = candles[candles["close_time"] < end_ms].copy()

    # The API sends numbers as text like "1.5", so convert them to real decimal numbers
    candles[NUMBER_COLUMNS] = candles[NUMBER_COLUMNS].astype(float)
    # Convert the start time from milliseconds to a proper UTC date and time
    candles["open_time"] = pd.to_datetime(candles["open_time"], unit="ms", utc=True)
    # Convert the end time the same way
    candles["close_time"] = pd.to_datetime(candles["close_time"], unit="ms", utc=True)
    # Return only our columns, in our order (this drops the API's extra "i" interval column)
    return candles[COLUMNS]


def fetch_candles_1d(info, symbol, start_ms, end_ms):
    """Download closed daily bars for one symbol as a table."""
    # Download the raw answer from the API, retrying when we are rate limited
    raw_candles = download_with_retry(info, symbol, start_ms, end_ms)
    # Turn the raw answer into our table and return it
    return to_dataframe(raw_candles, end_ms)


def load_saved_candles(path):
    """Read the saved file, or return an empty table on the very first run."""
    # If the file exists, read it into a table and return it
    if path.exists():
        return pd.read_parquet(path)
    # Otherwise this is the first run, so start from an empty table with our columns
    return pd.DataFrame(columns=COLUMNS)


def first_missing_bar_ms(symbol, last_saved):
    """Start time (ms) of the first bar we do not have yet for this symbol.

    last_saved maps symbol -> open_time of its newest saved bar.
    """
    # A symbol we have never saved needs everything, starting from the global start date
    if symbol not in last_saved.index:
        return START_TIME_MS
    # Otherwise convert its newest saved time to milliseconds and move forward one day
    return int(last_saved[symbol].timestamp() * 1000) + ONE_DAY_MS


def save_candles(tables, path):
    """Combine tables, remove duplicates, sort, and write the file safely.

    We write to a .tmp file first and then swap it in, so a crash while
    writing can never leave a half-written candles file.
    """
    # Build the final table by chaining these steps, from the first line to the last
    candles = (pd.concat(tables, ignore_index=True)  # stack all the tables into one
                 # if the same (symbol, open_time) appears twice, keep the later (newer) copy
                 .drop_duplicates(["symbol", "open_time"], keep="last")
                 # order the rows by coin, then by time
                 .sort_values(["symbol", "open_time"])
                 # renumber the rows 0, 1, 2, ... and throw away the old numbers
                 .reset_index(drop=True))

    # Create the data folder if it does not exist yet
    path.parent.mkdir(parents=True, exist_ok=True)
    # A temporary file name next to the real one (same name, ending in .tmp)
    tmp_path = path.with_suffix(".tmp")
    # Write the table to the temporary file first (index=False skips the row numbers)
    candles.to_parquet(tmp_path, index=False)
    # Swap the temporary file in only after it was fully written
    tmp_path.replace(path)
    # Print a summary: number of rows and number of different coins
    print(f"saved {len(candles)} rows, {candles['symbol'].nunique()} symbols")


def update_candles_1d(data_dir: Path) -> None:
    """Download any missing daily bars for every perp and save them."""
    # The full path of the candles file inside the data folder
    path = Path(data_dir) / FILENAME
    # Connect to Hyperliquid's main network; skip_ws=True means we don't need the live-feed connection
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    # "Now" in milliseconds; bars that close after this moment are not finished yet
    end_ms = int(time.time() * 1000)

    # Ask the API for the list of all perpetual futures (called the universe)
    universe = info.meta()["universe"]
    # Collect the names of coins marked as delisted (.get falls back to False when the flag is missing)
    delisted = {coin["name"] for coin in universe if coin.get("isDelisted", False)}

    # Load what we saved on earlier runs (empty on the first run)
    saved = load_saved_candles(path)
    # For each coin, find the time of its newest saved bar
    last_saved = saved.groupby("symbol")["open_time"].max()
    # Start a list of tables to combine at the end, beginning with the saved data
    tables = [saved]

    # try/finally makes sure the save at the bottom runs even if something goes wrong
    try:
        # Go through every coin in the universe
        for coin in universe:
            # The coin's name, such as "BTC"
            symbol = coin["name"]

            # A delisted coin's history never changes, so skip it once saved.
            if symbol in last_saved.index and symbol in delisted:
                continue

            # Work out where this coin's missing bars start
            start_ms = first_missing_bar_ms(symbol, last_saved)
            # Run the download inside try so one bad coin cannot stop the others
            try:
                # Download the missing closed bars for this coin
                new_bars = fetch_candles_1d(info, symbol, start_ms, end_ms)
            # If the download failed even after retries, handle the error here
            except Exception as error:
                # Say which coin failed and why
                print(f"{symbol}: failed ({error.args[:1]})")
                # Pause as usual so we do not hammer the API
                time.sleep(PAUSE_BETWEEN_SYMBOLS)
                # Move on to the next coin; this one is simply not saved, so a rerun will retry it
                continue

            # Only record coins that actually returned new bars
            if not new_bars.empty:
                # Add the new bars to the list of tables to save
                tables.append(new_bars)
                # Tell the user how many bars were added for this coin
                print(f"{symbol}: +{len(new_bars)}")
            # Pause briefly before the next coin to stay under the rate limit
            time.sleep(PAUSE_BETWEEN_SYMBOLS)
    # finally runs no matter what, even when the user presses Ctrl+C
    finally:
        # Save everything collected so far, so progress is never lost
        save_candles(tables, path)

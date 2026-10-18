"""Hyperliquid perpetual futures candles (1d or 1h).

Downloads and incrementally updates OHLCV bars for every perp in
info.meta()["universe"], delisted coins included, into one parquet file per interval.

Scope:
- Perps only. Spot and builder-deployed (HIP-3) markets are not covered.
- Closed bars only. The current bar is excluded.
- Raw data. Leading zero-volume bars are kept; see clean_candles.py.

Limits:
- The API serves at most the 5000 most recent candles per symbol and interval.
  That is about 13 years of 1d bars but only about 208 days of 1h bars, so 1h
  history older than that exists only if the update keeps being run.
- A symbol we have never saved is requested from 5000 bars before now, which is
  everything the API holds for an active coin. Delisted coins whose last bar is
  older than that return nothing and are not saved.
- Rate limited per IP (HTTP 429). download_with_retry backs off and retries.

Update behavior:
- The whole parquet file is rewritten on each run (atomic swap via .tmp).
- Symbols that fail are not written, so rerunning fetches only the missing ones.
- Delisted symbols are requested like any other, so a coin delisted between two
  runs still gets its last bars. The API returns nothing after delisting.
"""

# time lets us read the clock and pause (sleep) between requests
import time
# Path builds file paths in a way that works on any operating system
from pathlib import Path

# pandas gives us tables (DataFrames) and reads/writes parquet files
import pandas as pd
# Info is Hyperliquid's class for asking the API for market data
from hyperliquid.info import Info
# constants holds the official API addresses, such as the main (real money) network
from hyperliquid.utils import constants

# MAX_ATTEMPTS is re-exported here for the tests; the helpers retry requests and save tables safely
from wh_research.data.hyperliquid.api_helpers import MAX_ATTEMPTS, call_with_retry, save_table

# How long one bar lasts, in milliseconds, for each candle size we support
BAR_MS = {"1d": 86_400_000, "1h": 3_600_000}

# The most candles the API ever returns per symbol and interval
MAX_BARS = 5000

# Seconds to pause after each symbol, which keeps us under the API's rate limit
PAUSE_BETWEEN_SYMBOLS = 0.5
# Print a progress line after this many symbols, so a quiet run does not look frozen
PROGRESS_EVERY = 25

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


def candles_filename(interval):
    """The name of the raw candles file for an interval, such as candles_1h.parquet."""
    # Put the interval into the file name
    return f"candles_{interval}.parquet"


def download_with_retry(info, symbol, interval, start_ms, end_ms):
    """Ask the API for candles. If it says 429 (too many requests), wait and retry."""
    # Make the request with retries; the symbol name is used in the "429" message
    return call_with_retry(lambda: info.candles_snapshot(symbol, interval, start_ms, end_ms), symbol)


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


def fetch_candles(info, symbol, interval, start_ms, end_ms):
    """Download closed bars for one symbol as a table."""
    # Download the raw answer from the API, retrying when we are rate limited
    raw_candles = download_with_retry(info, symbol, interval, start_ms, end_ms)
    # Turn the raw answer into our table and return it
    return to_dataframe(raw_candles, end_ms)


def load_saved_candles(path):
    """Read the saved file, or return an empty table on the very first run."""
    # If the file exists, read it into a table and return it
    if path.exists():
        return pd.read_parquet(path)
    # Otherwise this is the first run, so start from an empty table with our columns
    return pd.DataFrame(columns=COLUMNS)


def first_missing_bar_ms(symbol, last_saved, interval, end_ms):
    """Start time (ms) of the first bar we do not have yet for this symbol.

    last_saved maps symbol -> open_time of its newest saved bar.
    """
    # A symbol we have never saved needs everything the API holds: the last MAX_BARS bars before end_ms
    if symbol not in last_saved.index:
        return end_ms - MAX_BARS * BAR_MS[interval]
    # Otherwise convert its newest saved time to milliseconds and move forward one bar
    return int(last_saved[symbol].timestamp() * 1000) + BAR_MS[interval]


def save_candles(tables, path):
    """Combine tables, remove duplicates, sort, and write the file safely."""
    # A candle is identified by its coin and its start time
    save_table(tables, path, ["symbol", "open_time"])


def update_candles(data_dir: Path, interval: str) -> None:
    """Download any missing bars (1d or 1h) for every perp and save them."""
    # Stop early with a clear message if the interval is not one we support
    if interval not in BAR_MS:
        raise ValueError(f"interval must be one of {list(BAR_MS)}, got {interval!r}")

    # The full path of the candles file inside the data folder
    path = Path(data_dir) / candles_filename(interval)
    # Connect to Hyperliquid's main network; skip_ws=True means we don't need the live-feed connection
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    # "Now" in milliseconds; bars that close after this moment are not finished yet
    end_ms = int(time.time() * 1000)

    # Ask the API for the list of all perpetual futures (called the universe)
    universe = info.meta()["universe"]

    # Load what we saved on earlier runs (empty on the first run)
    saved = load_saved_candles(path)
    # For each coin, find the time of its newest saved bar
    last_saved = saved.groupby("symbol")["open_time"].max()
    # Start a list of tables to combine at the end, beginning with the saved data
    tables = [saved]

    # Tell the user how much there is to check
    print(f"checking {len(universe)} symbols")
    # try/finally makes sure the save at the bottom runs even if something goes wrong
    try:
        # Go through every coin in the universe, counting from 1
        for number, coin in enumerate(universe, start=1):
            # Every PROGRESS_EVERY coins, say how far we are
            if number % PROGRESS_EVERY == 0:
                print(f"{number}/{len(universe)} symbols checked")
            # The coin's name, such as "BTC"
            symbol = coin["name"]

            # Work out where this coin's missing bars start
            start_ms = first_missing_bar_ms(symbol, last_saved, interval, end_ms)
            # If the next bar has not closed yet, there is nothing to download for this coin
            if start_ms + BAR_MS[interval] > end_ms:
                continue
            # Run the download inside try so one bad coin cannot stop the others
            try:
                # Download the missing closed bars for this coin
                new_bars = fetch_candles(info, symbol, interval, start_ms, end_ms)
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

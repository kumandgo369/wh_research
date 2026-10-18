"""Hyperliquid perpetual futures funding rate history.

Downloads and incrementally updates the funding rate history of every perp in
info.meta()["universe"], delisted coins included, into one parquet file.

Columns: symbol, time, funding_rate, premium

Limits:
- One API call returns at most 500 rows (about 20 days of hourly funding), oldest
  first, so a long history is downloaded page by page.
- Unlike candles there is no cap on how far back it goes, so the file can always
  be downloaded again from scratch.
- Rate limited per IP (HTTP 429). call_with_retry backs off and retries.

Update behavior:
- The whole parquet file is rewritten on each run (atomic swap via .tmp).
- A symbol is only added once all of its pages arrived. Symbols that fail are
  not written, so rerunning fetches only the missing ones.
- Delisted symbols are requested like any other, so a coin delisted between two
  runs still gets its last rows. After delisting the API keeps sending hourly
  rows with a funding rate of 0; they are saved as they come.
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

# The helpers retry requests that were rate limited and save tables safely
from wh_research.data.hyperliquid.api_helpers import call_with_retry, save_table

# The name of the file where the funding rates are saved
FILENAME = "funding.parquet"

# The most rows the API returns in one call; a shorter answer means it was the last page
PAGE_SIZE = 500

# Where a symbol's history starts: 2023-01-01 UTC in milliseconds, before Hyperliquid had funding data
START_TIME_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

# Seconds to pause after each request, which keeps us under the API's rate limit
PAUSE_BETWEEN_REQUESTS = 0.5
# Print a progress line after this many symbols, so a quiet run does not look frozen
PROGRESS_EVERY = 25

# The API's names for the columns, renamed to ours (time and premium already have good names)
API_COLUMN_NAMES = {"coin": "symbol", "fundingRate": "funding_rate"}
# All the columns of our table, in the order we save them
COLUMNS = ["symbol", "time", "funding_rate", "premium"]


def to_dataframe(raw_rows):
    """Turn the API's list of dicts into a table with our columns."""
    # If the API returned nothing, return an empty table that still has our columns
    if not raw_rows:
        return pd.DataFrame(columns=COLUMNS)

    # Build a table from the list of dicts and rename the columns that need it
    funding = pd.DataFrame(raw_rows).rename(columns=API_COLUMN_NAMES)
    # The API sends the rates as text like "0.0000125", so convert them to real decimal numbers
    funding[["funding_rate", "premium"]] = funding[["funding_rate", "premium"]].astype(float)
    # Convert the time from milliseconds to a proper UTC date and time
    funding["time"] = pd.to_datetime(funding["time"], unit="ms", utc=True)
    # Store it with microsecond precision, exactly like the candles' open_time and close_time
    funding["time"] = funding["time"].astype("datetime64[us, UTC]")
    # Return only our columns, in our order
    return funding[COLUMNS]


def download_funding(info, symbol, start_ms, end_ms):
    """Download all funding rows of one symbol from start_ms to end_ms as a table."""
    # One table per page of up to PAGE_SIZE rows
    pages = []
    # Keep asking for the next page until the API has nothing more
    while True:
        # Ask for one page, retrying when we are rate limited
        raw_rows = call_with_retry(lambda: info.funding_history(symbol, start_ms, end_ms), symbol)
        # Pause briefly before the next request to stay under the rate limit
        time.sleep(PAUSE_BETWEEN_REQUESTS)
        # No rows at all means there is nothing more to download
        if not raw_rows:
            break
        # Keep this page
        pages.append(to_dataframe(raw_rows))
        # A page shorter than PAGE_SIZE was the last one
        if len(raw_rows) < PAGE_SIZE:
            break
        # Otherwise the next page starts 1 ms after the last row we got (so no row comes twice)
        start_ms = raw_rows[-1]["time"] + 1

    # No pages means an empty table; otherwise stack the pages into one table
    if not pages:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(pages, ignore_index=True)


def load_saved_funding(path):
    """Read the saved file, or return an empty table on the very first run."""
    # If the file exists, read it into a table and return it
    if path.exists():
        return pd.read_parquet(path)
    # Otherwise this is the first run, so start from an empty table with our columns
    return pd.DataFrame(columns=COLUMNS)


def first_missing_time_ms(symbol, last_saved):
    """Start time (ms) of the first funding row we do not have yet for this symbol.

    last_saved maps symbol -> time of its newest saved row.
    """
    # A symbol we have never saved needs everything, starting from the global start date
    if symbol not in last_saved.index:
        return START_TIME_MS
    # Otherwise convert its newest saved time to milliseconds and move forward 1 ms
    return int(last_saved[symbol].timestamp() * 1000) + 1


def update_funding(data_dir: Path) -> None:
    """Download any missing funding rows for every perp and save them."""
    # The full path of the funding file inside the data folder
    path = Path(data_dir) / FILENAME
    # Connect to Hyperliquid's main network; skip_ws=True means we don't need the live-feed connection
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    # "Now" in milliseconds; we ask for funding rows up to this moment
    end_ms = int(time.time() * 1000)

    # Ask the API for the list of all perpetual futures (called the universe)
    universe = info.meta()["universe"]

    # Load what we saved on earlier runs (empty on the first run)
    saved = load_saved_funding(path)
    # For each coin, find the time of its newest saved row
    last_saved = saved.groupby("symbol")["time"].max()
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

            # Work out where this coin's missing rows start
            start_ms = first_missing_time_ms(symbol, last_saved)
            # Run the download inside try so one bad coin cannot stop the others
            try:
                # Download all the missing rows for this coin (every page)
                new_rows = download_funding(info, symbol, start_ms, end_ms)
            # If the download failed even after retries, handle the error here
            except Exception as error:
                # Say which coin failed and why
                print(f"{symbol}: failed ({error.args[:1]})")
                # Pause as usual so we do not hammer the API
                time.sleep(PAUSE_BETWEEN_REQUESTS)
                # Move on to the next coin; this one is simply not saved, so a rerun will retry it
                continue

            # Only record coins that actually returned new rows
            if not new_rows.empty:
                # Add the new rows to the list of tables to save
                tables.append(new_rows)
                # Tell the user how many rows were added for this coin
                print(f"{symbol}: +{len(new_rows)}")
    # finally runs no matter what, even when the user presses Ctrl+C
    finally:
        # Save everything collected so far, so progress is never lost
        save_table(tables, path, ["symbol", "time"])

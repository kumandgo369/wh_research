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

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from hyperliquid.info import Info
from hyperliquid.utils import constants

INTERVAL = "1d"
FILENAME = "candles_1d.parquet"

START_TIME_MS = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
ONE_DAY_MS = 86_400_000

MAX_ATTEMPTS = 8
PAUSE_BETWEEN_SYMBOLS = 0.5  # seconds, keeps us under the rate limit

# The API uses one-letter keys. We rename them to readable column names.
API_COLUMN_NAMES = {
    "t": "open_time", "T": "close_time", "s": "symbol",
    "o": "open", "h": "high", "l": "low", "c": "close",
    "v": "volume", "n": "trades",
}
NUMBER_COLUMNS = ["open", "high", "low", "close", "volume"]
COLUMNS = ["symbol", "open_time", "close_time"] + NUMBER_COLUMNS + ["trades"]


def download_with_retry(info, symbol, start_ms, end_ms):
    """Ask the API for candles. If it says 429 (too many requests), wait and retry."""
    wait_seconds = 5
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return info.candles_snapshot(symbol, INTERVAL, start_ms, end_ms)
        except Exception as error:
            is_rate_limit = error.args[:1] == (429,)
            if not is_rate_limit or attempt == MAX_ATTEMPTS:
                raise
            print(f"{symbol}: 429, retry in {wait_seconds}s")
            time.sleep(wait_seconds)
            wait_seconds = min(wait_seconds * 2, 60)


def to_dataframe(raw_candles, end_ms):
    """Turn the API's list of dicts into a table with our columns.

    Bars that have not closed yet (close_time >= end_ms) are dropped.
    """
    if not raw_candles:
        return pd.DataFrame(columns=COLUMNS)

    candles = pd.DataFrame(raw_candles).rename(columns=API_COLUMN_NAMES)
    candles = candles[candles["close_time"] < end_ms].copy()

    candles[NUMBER_COLUMNS] = candles[NUMBER_COLUMNS].astype(float)  # API sends text
    candles["open_time"] = pd.to_datetime(candles["open_time"], unit="ms", utc=True)
    candles["close_time"] = pd.to_datetime(candles["close_time"], unit="ms", utc=True)
    return candles[COLUMNS]


def fetch_candles_1d(info, symbol, start_ms, end_ms):
    """Download closed daily bars for one symbol as a table."""
    raw_candles = download_with_retry(info, symbol, start_ms, end_ms)
    return to_dataframe(raw_candles, end_ms)


def load_saved_candles(path):
    """Read the saved file, or return an empty table on the very first run."""
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(columns=COLUMNS)


def first_missing_bar_ms(symbol, last_saved):
    """Start time (ms) of the first bar we do not have yet for this symbol.

    last_saved maps symbol -> open_time of its newest saved bar.
    """
    if symbol not in last_saved.index:
        return START_TIME_MS
    return int(last_saved[symbol].timestamp() * 1000) + ONE_DAY_MS


def save_candles(tables, path):
    """Combine tables, remove duplicates, sort, and write the file safely.

    We write to a .tmp file first and then swap it in, so a crash while
    writing can never leave a half-written candles file.
    """
    candles = (pd.concat(tables, ignore_index=True)
                 .drop_duplicates(["symbol", "open_time"], keep="last")
                 .sort_values(["symbol", "open_time"])
                 .reset_index(drop=True))

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    candles.to_parquet(tmp_path, index=False)
    tmp_path.replace(path)
    print(f"saved {len(candles)} rows, {candles['symbol'].nunique()} symbols")


def update_candles_1d(data_dir: Path) -> None:
    """Download any missing daily bars for every perp and save them."""
    path = Path(data_dir) / FILENAME
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    end_ms = int(time.time() * 1000)

    universe = info.meta()["universe"]
    delisted = {coin["name"] for coin in universe if coin.get("isDelisted", False)}

    saved = load_saved_candles(path)
    last_saved = saved.groupby("symbol")["open_time"].max()
    tables = [saved]

    try:
        for coin in universe:
            symbol = coin["name"]

            # A delisted coin's history never changes, so skip it once saved.
            if symbol in last_saved.index and symbol in delisted:
                continue

            start_ms = first_missing_bar_ms(symbol, last_saved)
            try:
                new_bars = fetch_candles_1d(info, symbol, start_ms, end_ms)
            except Exception as error:
                print(f"{symbol}: failed ({error.args[:1]})")
                time.sleep(PAUSE_BETWEEN_SYMBOLS)
                continue

            if not new_bars.empty:
                tables.append(new_bars)
                print(f"{symbol}: +{len(new_bars)}")
            time.sleep(PAUSE_BETWEEN_SYMBOLS)
    finally:  # saves progress even on Ctrl+C
        save_candles(tables, path)

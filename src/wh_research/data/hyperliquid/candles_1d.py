"""Hyperliquid perpetual futures daily candles.

Downloads and incrementally updates daily OHLCV bars for every perp in
info.meta()["universe"], delisted coins included, into one parquet file.

Scope:
- Perps only. Spot and builder-deployed (HIP-3) markets are not covered.
- Closed bars only. The current day's bar is excluded.
- Raw data. Leading zero-volume bars are kept; filter at load time.

Limits:
- The API serves at most 5000 candles per symbol and interval.
- Rate limited per IP (HTTP 429). fetch_candles_1d backs off and retries.

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
START_MS = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
DAY_MS = 86_400_000
NUM = ["open", "high", "low", "close", "volume"]
COLS = ["symbol", "open_time", "close_time"] + NUM + ["trades"]


def fetch_candles_1d(info, symbol, start_ms, end_ms):
    """Fetch closed daily bars, retrying with backoff on 429."""
    delay = 5
    for attempt in range(8):
        try:
            raw = info.candles_snapshot(symbol, INTERVAL, start_ms, end_ms)
            break
        except Exception as e:
            if e.args[:1] != (429,) or attempt == 7:
                raise
            print(f"{symbol}: 429, retry in {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 60)

    if not raw:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame(raw).rename(columns={
        "t": "open_time", "T": "close_time", "s": "symbol",
        "o": "open", "h": "high", "l": "low", "c": "close",
        "v": "volume", "n": "trades",
    })
    df = df[df["close_time"] < end_ms].copy()
    df[NUM] = df[NUM].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df[COLS]


def update_candles_1d(data_dir: Path) -> None:
    path = Path(data_dir) / FILENAME
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    end_ms = int(time.time() * 1000)
    universe = info.meta()["universe"]
    delisted = {u["name"] for u in universe if u.get("isDelisted", False)}

    old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=COLS)
    last = old.groupby("symbol")["open_time"].max()
    frames = [old]

    try:
        for u in universe:
            sym = u["name"]
            on_disk = sym in last.index
            if on_disk and sym in delisted:
                continue  # history is static
            start_ms = int(last[sym].timestamp() * 1000) + DAY_MS if on_disk else START_MS
            try:
                new = fetch_candles_1d(info, sym, start_ms, end_ms)
            except Exception as e:
                print(f"{sym}: failed ({e.args[:1]})")
                time.sleep(0.5)
                continue
            if not new.empty:
                frames.append(new)
                print(f"{sym}: +{len(new)}")
            time.sleep(0.5)
    finally:  # saves progress even on Ctrl+C
        out = (pd.concat(frames, ignore_index=True)
                 .drop_duplicates(["symbol", "open_time"], keep="last")
                 .sort_values(["symbol", "open_time"])
                 .reset_index(drop=True))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        out.to_parquet(tmp, index=False)
        tmp.replace(path)
        print(f"saved {len(out)} rows, {out['symbol'].nunique()} symbols")
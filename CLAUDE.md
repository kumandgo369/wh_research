# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Quantitative crypto research repo. Currently it contains two data pipelines for all Hyperliquid perps, stored as parquet files and used from notebooks: 1d and 1h OHLCV candles (one file per interval) and funding rate history (one file). On top of the 1d cleaned candles it builds daily-only tradeable-universe files (every row plus an `in_universe` flag, one file per liquidity cutoff), and it has functions that add forward-return labels and past-return features to candle tables. The package is `wh_research` (src layout, built with `uv_build`, Python 3.14, managed with `uv`).

## Commands

The interval (`1d` or `1h`) is the argument after the script name.

    uv sync                                                             # install deps (incl. dev group: jupyter, pytest)
    uv run python scripts/update_hyperliquid_candles.py 1h              # first download AND every later update (raw file)
    uv run python scripts/clean_hyperliquid_candles.py 1h               # rebuild candles_1h_cleaned.parquet from raw
    uv run python scripts/update_and_clean_hyperliquid_candles.py 1h    # update, then clean
    uv run python scripts/update_hyperliquid_funding.py                 # funding rates: first download AND every later update
    uv run python scripts/build_hyperliquid_daily_universe.py 2000000   # daily universe for a $2M cutoff (new cutoff = new file; same cutoff = rebuild)
    uv run python scripts/build_hyperliquid_daily_universe.py 2000000 1000000   # same with a lower $1M exit level (hysteresis), its own file
    uv run pytest                                                       # all tests
    uv run pytest tests/test_clean_candles.py::test_name                # single test

No linter or formatter is configured.

Code style:

- Prioritise simplicity above everything else. Write the simplest code that works: plain, readable steps over clever tricks, and no handling for cases that can't happen. Small functions that each do one clear job are good (they are easy to test and change). Avoid layers nobody needs yet: classes, extra options or generic helpers added "just in case". When two approaches work, pick the one a beginner can follow.
- Every code line has a plain-English comment on its own line directly above it, written for a beginner. Keep this when adding or editing code.

## Layout

- `src/wh_research/data/hyperliquid/candles.py` — all downloader logic; `clean_candles.py` — cleaning (`clean_candles`) and the cleaned-file rebuild (`update_candles_cleaned`). Both take an `interval`; `BAR_MS` in `candles.py` is the table of supported intervals and bar lengths. `funding.py` downloads funding rates (paged, 500 rows per call). `api_helpers.py` holds the retry-on-429 and safe-save helpers shared by both downloaders. `daily_universe.py` builds the daily-only tradeable-universe files from `candles_1d_cleaned.parquet` (`flag_daily_universe`, `update_daily_universe`). `labels.py` has `add_forward_returns(df, interval, horizons)` for forward log-return, direction and end-time columns on the candle schema. `features.py` has `add_past_returns(df, interval, horizons, direction=False)` for trailing log-return (and optional direction) columns on the same schema. The `scripts/` files are thin runners that point them at `data/hyperliquid/`.
- `data/` is gitignored. `candles_<interval>.parquet` is the raw dataset and `candles_<interval>_cleaned.parquet` is derived, `universe_1d_min_mdv_<cutoff>[_exit_<exit>].parquet` is derived (all cleaned rows plus `in_universe`, one file per cutoff or entry/exit pair), and `funding.parquet` is raw. The 1d files can be re-downloaded in full, but the 1h raw file cannot (see below), so it needs a backup.
- `notebooks/` — analysis notebooks. `wip/` — scratch notebooks and scripts, gitignored.
- `docs/1-daily_data_downloading.md`, `2-daily_data_updating.md`, `3-daily_data_cleaning.md`, `4-hourly_data.md`, `5-funding_data.md`, `6-daily_universe.md`, `7-forward_returns.md`, `8-past_returns.md` — the datasets' schema, quirks, update workflow, cleaning flags, 1h specifics, funding specifics, the daily universe files and the forward-return labels. Read them before touching the data or writing analysis on it. `docs/tests.md` lists every test and how the downloader tests fake the API.

## Data pipeline: things that span multiple places

- **Incremental update, full rewrite.** `update_candles` reads the existing parquet, fetches only new bars per symbol (from last `open_time` + one bar), concatenates, dedupes on `(symbol, open_time)`, sorts, and swaps the file in via `.tmp`. The write is in a `finally`, so Ctrl+C or a crash still saves progress.
- **Failed symbols are simply absent** (the script does not record them). Rerunning fetches whatever is missing. HTTP 429 is retried with backoff, and the SDK raises exceptions whose `args[0]` is the status code, which is what the retry check inspects.
- **Delisted symbols** (`isDelisted` in `info.meta()["universe"]`) are kept on disk. Do not drop them (survivorship bias). They are asked again on every update, so a coin delisted since the last run still gets its final bars: candles come back empty, but funding keeps returning hourly zero-rate placeholder rows after delisting (see `5-funding_data.md`).
- **Closed bars only**: bars with `close_time >= now` are dropped at fetch time.
- **Start of a new symbol**: requested from `MAX_BARS` (5000) bars before now, not from a fixed date. This avoids a survivorship-biased 1h slice (delisted coins reach further back than active ones), but delisted coins older than the window are never saved.
- **The API keeps only the 5000 most recent bars per symbol and interval** (about 208 days at 1h). 1h history older than that exists only because earlier updates saved it, so run the 1h update at least every ~200 days and never delete `candles_1h.parquet` without a backup. The 1h data starts at 2026-03-23.
- **Raw file is not cleaned.** Leading zero-volume bars exist for many symbols (e.g. BTC has about 420 daily bars), and some have invalid OHLC. `clean_candles` trims bars before each symbol's first `volume > 0` bar and adds `ok_*`, `is_valid`, `is_stale` and `after_gap` flags without dropping anything else, so the series has no gaps. `is_stale` is backward-looking (a bar is stale from the 4th equal close in a row), so it never uses later bars. The cleaned file is always a full rebuild from raw, so run clean after update, never alongside.
- **Look-ahead**: in as-of joins use `close_time`, not `open_time`, as the left key. Funding rows are not on the exact hour (a few ms offset): join them to candles with `merge_asof` (`direction="backward"`, `by="symbol"`), see `5-funding_data.md`. The API's funding key `coin` is renamed to `symbol`.
- **Daily universe files are daily-only, hold every cleaned row, and are look-ahead-free by construction.** The `in_universe` flag for day *t* is True only if the 30-day median dollar volume at the close of day *t−1* reached the cutoff (a coin is first flagged on its 31st cleaned bar), so use the flag on the same row with no extra shift. Rows are never dropped, so each coin's series stays gap-free: compute labels and features on the whole file, then filter with `df[df["in_universe"]]`. An optional lower exit level (`_exit_<exit>` in the name) makes a coin that joined at the cutoff stay flagged in until its median falls below the exit level, so it does not flip in and out; it uses only the same previous-close median, so it is look-ahead-free too. A new level makes a new file; rerunning the same levels rebuilds it. Run order: update → clean → universe, because it is built from the cleaned file. See `6-daily_universe.md`.
- **Forward-return labels look into the future by definition.** `add_forward_returns` looks the future close up by `(symbol, open_time + n bars)` (never a row shift, which breaks at gaps), keeps all rows and NaNs (the caller drops them), and keeps a missing direction as NaN, not 0. Never use `fwd_*` columns as features; purge CV folds with `fwd_end_time_{n}` (a training row's label must end before the evaluation period starts); split the universe files by time, not by row position (they are sorted by symbol first). See `7-forward_returns.md`.
- **Past-return features look only backwards.** `add_past_returns` looks the earlier close up by `(symbol, open_time - n bars)` (never a row shift), keeps all rows and NaNs, and keeps a missing direction as NaN. The value on a row uses data up to that bar's `close_time` only, so it is safe as a feature on the same row. Compute on the whole file, then filter with `in_universe`. See `8-past_returns.md`.
- **Funding history has no 5000-row cap** (it starts 2023-05-12), so unlike 1h candles `funding.parquet` can be downloaded again from scratch (about 2.5 hours, ~9,300 calls).
- Supporting a new interval means adding it to `BAR_MS`. Intervals shorter than 1h will not keep history without a continuously running collector (see the docs).

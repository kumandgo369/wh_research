# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Quantitative crypto research repo. Currently it contains one data pipeline: 1d and 1h OHLCV candles for all Hyperliquid perps, stored in one parquet file per interval and used from notebooks. The package is `wh_research` (src layout, built with `uv_build`, Python 3.14, managed with `uv`).

## Commands

The interval (`1d` or `1h`) is the argument after the script name.

    uv sync                                                             # install deps (incl. dev group: jupyter, pytest)
    uv run python scripts/update_hyperliquid_candles.py 1h              # first download AND every later update (raw file)
    uv run python scripts/clean_hyperliquid_candles.py 1h               # rebuild candles_1h_cleaned.parquet from raw
    uv run python scripts/update_and_clean_hyperliquid_candles.py 1h    # update, then clean
    uv run pytest                                                       # all tests
    uv run pytest tests/test_clean_candles.py::test_name                # single test

No linter or formatter is configured.

Code style: every code line has a plain-English comment on its own line directly above it, written for a beginner. Keep this when adding or editing code.

## Layout

- `src/wh_research/data/hyperliquid/candles.py` — all downloader logic; `clean_candles.py` — cleaning (`clean_candles`) and the cleaned-file rebuild (`update_candles_cleaned`). Both take an `interval`; `BAR_MS` in `candles.py` is the table of supported intervals and bar lengths. The `scripts/` files are thin runners that point them at `data/hyperliquid/`.
- `data/` is gitignored. `candles_<interval>.parquet` is the raw dataset and `candles_<interval>_cleaned.parquet` is derived. The 1d files can be re-downloaded in full, but the 1h raw file cannot (see below), so it needs a backup.
- `notebooks/` — analysis notebooks. `wip/` — scratch notebooks and scripts, gitignored.
- `docs/1-daily_data_downloading.md`, `2-daily_data_updating.md`, `3-daily_data_cleaning.md`, `4-hourly_data.md` — the dataset's schema, quirks, update workflow, cleaning flags and 1h specifics. Read them before touching the data or writing analysis on it. `docs/tests.md` lists every test and how the downloader tests fake the API. `docs/research_process.md` is currently empty.

## Data pipeline: things that span multiple places

- **Incremental update, full rewrite.** `update_candles` reads the existing parquet, fetches only new bars per symbol (from last `open_time` + one bar), concatenates, dedupes on `(symbol, open_time)`, sorts, and swaps the file in via `.tmp`. The write is in a `finally`, so Ctrl+C or a crash still saves progress.
- **Failed symbols are simply absent** (the script does not record them). Rerunning fetches whatever is missing. HTTP 429 is retried with backoff, and the SDK raises exceptions whose `args[0]` is the status code, which is what the retry check inspects.
- **Delisted symbols** (`isDelisted` in `info.meta()["universe"]`) are kept on disk and never refetched. Do not drop them (survivorship bias).
- **Closed bars only**: bars with `close_time >= now` are dropped at fetch time.
- **Start of a new symbol**: requested from `MAX_BARS` (5000) bars before now, not from a fixed date. This avoids a survivorship-biased 1h slice (delisted coins reach further back than active ones), but delisted coins older than the window are never saved.
- **The API keeps only the 5000 most recent bars per symbol and interval** (about 208 days at 1h). 1h history older than that exists only because earlier updates saved it, so run the 1h update at least every ~200 days and never delete `candles_1h.parquet` without a backup. The 1h data starts at 2026-03-23.
- **Raw file is not cleaned.** Leading zero-volume bars exist for many symbols (e.g. BTC has about 420 daily bars), and some have invalid OHLC. `clean_candles` trims bars before each symbol's first `volume > 0` bar and adds `ok_*`, `is_valid`, `is_stale` and `after_gap` flags without dropping anything else, so the series has no gaps. The cleaned file is always a full rebuild from raw (a new bar can make earlier bars stale), so run clean after update, never alongside.
- **Look-ahead**: in as-of joins use `close_time`, not `open_time`, as the left key. Funding data (planned) calls the key `coin`; rename it to `symbol`.
- Supporting a new interval means adding it to `BAR_MS`. Intervals shorter than 1h will not keep history without a continuously running collector (see the docs).

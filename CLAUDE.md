# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Quantitative crypto research repo. Currently it contains one data pipeline: daily OHLCV candles for all Hyperliquid perps, stored in a single parquet file and used from notebooks. The package is `wh_research` (src layout, built with `uv_build`, Python 3.14, managed with `uv`).

## Commands

    uv sync                                                  # install deps (incl. dev group: jupyter, pytest)
    uv run python scripts/update_hyperliquid_candles_1d.py             # first download AND every later update (raw file)
    uv run python scripts/clean_hyperliquid_candles_1d.py              # rebuild candles_1d_cleaned.parquet from raw
    uv run python scripts/update_and_clean_hyperliquid_candles_1d.py   # update, then clean
    uv run pytest                                                      # all tests
    uv run pytest tests/test_clean_candles_1d.py::test_name            # single test

No linter or formatter is configured.

## Layout

- `src/wh_research/data/hyperliquid/candles_1d.py` — all downloader logic; `clean_candles_1d.py` — cleaning (`clean_candles_1d`) and the cleaned-file rebuild (`update_candles_1d_cleaned`). The `scripts/` files are thin runners that point them at `data/hyperliquid/`.
- `data/hyperliquid/candles_1d.parquet` — the raw dataset, committed to git, so each update shows up as a modified binary. `candles_1d_cleaned.parquet` is derived and gitignored.
- `notebooks/` — analysis notebooks. `wip/` — scratch notebooks and scripts, gitignored.
- `docs/1-daily_data_downloading.md`, `2-daily_data_updating.md`, `3-daily_data_cleaning.md` — the dataset's schema, quirks, update workflow and cleaning flags. Read them before touching the data or writing analysis on it. `docs/tests.md` lists every test and how the downloader tests fake the API. `docs/research_process.md` is currently empty.

## Data pipeline: things that span multiple places

- **Incremental update, full rewrite.** `update_candles_1d` reads the existing parquet, fetches only new bars per symbol (from last `open_time` + 1 day), concatenates, dedupes on `(symbol, open_time)`, sorts, and swaps the file in via `.tmp`. The write is in a `finally`, so Ctrl+C or a crash still saves progress.
- **Failed symbols are simply absent** (the script does not record them). Rerunning fetches whatever is missing. HTTP 429 is retried with backoff, and the SDK raises exceptions whose `args[0]` is the status code, which is what the retry check inspects.
- **Delisted symbols** (`isDelisted` in `info.meta()["universe"]`) are kept on disk and never refetched. Do not drop them (survivorship bias).
- **Closed bars only**: bars with `close_time >= now` are dropped at fetch time.
- **Raw file is not cleaned.** Leading zero-volume bars exist for many symbols (e.g. BTC has about 420), and some have invalid OHLC. `clean_candles_1d` trims bars before each symbol's first `volume > 0` bar and adds `ok_*`, `is_valid` and `is_stale` flags without dropping anything else, so the series has no gaps. The cleaned file is always a full rebuild from raw (a new bar can make earlier bars stale), so run clean after update, never alongside.
- **Look-ahead**: in as-of joins use `close_time`, not `open_time`, as the left key. Funding data (planned) calls the key `coin`; rename it to `symbol`.
- The interval is deliberately hardcoded to 1d in file, function and constant names. Intraday data should go in a separate module and file layout (see the docs), not into this file.

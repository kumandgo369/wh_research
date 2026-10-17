# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Quantitative crypto research repo. Currently it contains one data pipeline: daily OHLCV candles for all Hyperliquid perps, stored in a single parquet file and used from notebooks. The package is `wh_research` (src layout, built with `uv_build`, Python 3.14, managed with `uv`).

## Commands

    uv sync                                                  # install deps (incl. dev group: jupyter, pytest)
    uv run python scripts/update_hyperliquid_candles_1d.py   # first download AND every later update
    uv run pytest                                            # tests/ is currently empty
    uv run pytest tests/test_x.py::test_name                 # single test

No linter or formatter is configured.

## Layout

- `src/wh_research/data/hyperliquid/candles_1d.py` — all downloader logic; `scripts/update_hyperliquid_candles_1d.py` is a thin runner that points it at `data/hyperliquid/`.
- `data/hyperliquid/candles_1d.parquet` — the dataset. It is committed to git (the "remove data/ from gitignore" commit), although `docs/1-hyperliquid_data.md` still says gitignored. Each update therefore shows up as a modified binary in `git status`.
- `notebooks/` — analysis notebooks. `wip/` — scratch notebooks and scripts, gitignored.
- `docs/1-hyperliquid_data.md` — authoritative description of the dataset: schema, design decisions, quirks, TODOs. Read it before touching the data or writing analysis on it. `docs/research_process.md` is currently empty.

## Data pipeline: things that span multiple places

- **Incremental update, full rewrite.** `update_candles_1d` reads the existing parquet, fetches only new bars per symbol (from last `open_time` + 1 day), concatenates, dedupes on `(symbol, open_time)`, sorts, and swaps the file in via `.tmp`. The write is in a `finally`, so Ctrl+C or a crash still saves progress.
- **Failed symbols are simply absent** (the script does not record them). Rerunning fetches whatever is missing. HTTP 429 is retried with backoff, and the SDK raises exceptions whose `args[0]` is the status code, which is what the retry check inspects.
- **Delisted symbols** (`isDelisted` in `info.meta()["universe"]`) are kept on disk and never refetched. Do not drop them (survivorship bias).
- **Closed bars only**: bars with `close_time >= now` are dropped at fetch time.
- **Raw file is not cleaned.** Leading zero-volume bars exist for many symbols (e.g. BTC has about 420), and some have invalid OHLC. Research code must filter at load time using `first_traded` = first bar with `volume > 0`. The planned `load_candles()` helper that owns this does not exist yet.
- **Look-ahead**: in as-of joins use `close_time`, not `open_time`, as the left key. Funding data (planned) calls the key `coin`; rename it to `symbol`.
- The interval is deliberately hardcoded to 1d in file, function and constant names. Intraday data should go in a separate module and file layout (see the docs), not into this file.

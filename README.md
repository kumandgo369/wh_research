# wh_research

WIP research library for WH

## Requirements

[uv](https://docs.astral.sh/uv/getting-started/installation/) is the only thing to install yourself. It also downloads Python 3.14 for you.

    # macOS / Linux
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Windows (PowerShell)
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

You also need [git](https://git-scm.com/downloads).

## Install

    git clone https://github.com/kumandgo369/wh_research.git
    cd wh_research
    uv sync

`uv sync` creates a `.venv` folder and installs everything, including pytest and Jupyter.

## Download the data

The data is not in git, so download it after cloning. The `data/hyperliquid/` folder is created for you.

    uv run python scripts/update_and_clean_hyperliquid_candles.py 1d
    uv run python scripts/update_and_clean_hyperliquid_candles.py 1h
    uv run python scripts/update_hyperliquid_funding.py

The candle commands download the candles and then build the cleaned file, which takes a few minutes. The funding command downloads the full funding rate history, which takes about 2 to 3 hours the first time (later updates take minutes). Messages like `429, retry in 5s` are normal (the API is rate limiting). If any symbol fails, run the same command again and only the missing ones are fetched.

You get `candles_1d.parquet` and `candles_1h.parquet` (raw) plus `candles_1d_cleaned.parquet` and `candles_1h_cleaned.parquet`, and `funding.parquet`, in `data/hyperliquid/`.

## Build the daily universe

The daily universe keeps only the days a coin was liquid enough (30-day median dollar volume at the previous close is at least the cutoff). Give the cutoff in dollars; each cutoff gets its own file.

    uv run python scripts/build_hyperliquid_daily_universe.py 2000000    # → universe_1d_min_mdv_2m.parquet
    uv run python scripts/build_hyperliquid_daily_universe.py 500000     # → universe_1d_min_mdv_500k.parquet

Run it after the 1d candles are updated and cleaned. It takes a few seconds.

## Check that it works

    uv run pytest

All tests run offline in about a second.

## Notebooks

    uv run jupyter lab

## Using another device

- **Code and docs:** `git pull`, then `uv sync` if the dependencies changed.
- **1d data:** run the 1d command above again. The API holds all of it.
- **Funding data:** run the funding command again (or copy `funding.parquet` to skip the 2 to 3 hour download). The API holds all of it.
- **1h data:** copy `data/hyperliquid/candles_1h.parquet` over from the other device instead of downloading. The API only holds the last ~208 days of hourly bars, so older history exists only in files that were updated over time. See `docs/4-hourly_data.md`.

## Learn more

- [Downloading](docs/1-daily_data_downloading.md): schema, design choices, data quirks
- [Updating](docs/2-daily_data_updating.md): commands and how an update works
- [Cleaning](docs/3-daily_data_cleaning.md): the validity, stale and gap flags
- [Hourly data](docs/4-hourly_data.md): the 5000-bar cap, where 1h data starts, backups
- [Funding data](docs/5-funding_data.md): schema, paging, timestamps, joining to candles
- [Daily universe](docs/6-daily_universe.md): the liquidity filter, the no-look-ahead rule, one file per cutoff
- [Tests](docs/tests.md)

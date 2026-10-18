# wh_research

Research on Hyperliquid perpetual futures: daily (1d) and hourly (1h) candles for every perp, downloaded from the Hyperliquid API, cleaned, and used from notebooks.

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
- [Tests](docs/tests.md)

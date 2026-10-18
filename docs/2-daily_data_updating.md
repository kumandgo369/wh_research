# Candle data: updating

Give the interval (`1d` or `1h`) after the script name.

    uv sync
    uv run python scripts/update_hyperliquid_candles.py 1d               # update raw file only
    uv run python scripts/clean_hyperliquid_candles.py 1d                # rebuild cleaned file only
    uv run python scripts/update_and_clean_hyperliquid_candles.py 1d     # update, then clean

The first download and every later update use the same command.

## What an update does

- Fetches only new bars per symbol (from the last `open_time` + one bar), plus any symbol missing from the file.
- Asks again for delisted symbols too (the API returns nothing after delisting), so a coin delisted since the last run still gets its last bars. This costs about 56 quick requests per run.
- **Skips coins that cannot have a new closed bar yet.** If everything is current (for example a second `1d` run on the same day), no request is made and the run finishes in seconds.
- Prints `checking N symbols`, a `25/234 symbols checked` line every 25 symbols, and `SYMBOL: +N` for each coin that got new bars, so a run does not look frozen. When new bars have closed, a `1d` run makes about one request per active coin and takes 2 to 3 minutes.
- Rewrites the whole file (about 200k rows for 1d, under a second) via `.tmp` and an atomic swap. Progress is saved even on Ctrl+C.
- A symbol that fails (for example a 429 after all retries) is simply not written. **Rerun the command** and only the missing symbols are fetched.

## Notes

- All of `data/` is gitignored. The 1d files can be re-downloaded in full (5000 daily bars is over 13 years). The 1h raw file cannot be fully re-downloaded, so back it up. See `4-hourly_data.md`.
- `candles_<interval>_cleaned.parquet` is rebuilt from the raw file and can be deleted and regenerated at any time. See `3-daily_data_cleaning.md`.
- Run clean after update, never at the same time: clean reads the file that update writes.
- An unsupported interval (anything not in `BAR_MS`) stops with an error before any request is made.

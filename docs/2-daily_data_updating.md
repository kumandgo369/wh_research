# Daily data: updating

    uv sync
    uv run python scripts/update_hyperliquid_candles_1d.py               # update raw file only
    uv run python scripts/clean_hyperliquid_candles_1d.py                # rebuild cleaned file only
    uv run python scripts/update_and_clean_hyperliquid_candles_1d.py     # update, then clean

The first download and every later update use the same command.

## What an update does

- Fetches only new bars per symbol (from the last `open_time` + 1 day), plus any symbol missing from the file.
- Skips delisted symbols already on disk.
- Rewrites the whole file (about 200k rows, under a second) via `.tmp` and an atomic swap. Progress is saved even on Ctrl+C.
- A symbol that fails (for example a 429 after all retries) is simply not written. **Rerun the command** and only the missing symbols are fetched.

## Notes

- `data/hyperliquid/candles_1d.parquet` is tracked in git, so every update shows as a modified binary.
- `candles_1d_cleaned.parquet` is gitignored. It is rebuilt from the raw file and can be deleted and regenerated at any time. See `3-daily_data_cleaning.md`.
- Run clean after update, never at the same time: clean reads the file that update writes.

## TODO

- [ ] Intraday collector

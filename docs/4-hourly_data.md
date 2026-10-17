# Hourly (1h) candle data

Same code, schema and flags as 1d (see docs 1 to 3). Pass `1h` as the interval:

    uv run python scripts/update_hyperliquid_candles.py 1h
    uv run python scripts/clean_hyperliquid_candles.py 1h
    uv run python scripts/update_and_clean_hyperliquid_candles.py 1h     # update, then clean

Files: `data/hyperliquid/candles_1h.parquet` (raw) and `candles_1h_cleaned.parquet`.

## The history cap: back up the raw file

The API returns only the 5000 most recent hourly bars per symbol, about 208 days. Anything older exists only because an earlier update saved it.

- **Run the update at least every ~200 days.** Bars that fall off the API's window before you save them are lost for good.
- **`candles_1h.parquet` is irreplaceable.** `data/` is gitignored, so back it up yourself (for example a cloud drive). The cleaned file can always be rebuilt from it.
- Delisted coins keep the last 5000 bars they had, which is why some symbols start years earlier than others.

## First download (2026-10-17)

- 1,148,775 raw rows, 234 symbols, about 42 MB (the cleaned file is similar). Expect it to grow by about 1.5M rows (60 MB) a year.
- The 178 active coins start around 2026-03-23, the other 56 are delisted. No duplicates, and no symbol failed (27 rate-limit retries).
- Takes several minutes. Later updates fetch only the newest bars.

## Cleaning at 1h

- `after_gap` uses one hour: a step between bars longer than 1 hour. Result: 0 gaps.
- `is_stale` is still "more than 3 equal closes in a row", which at 1h means 4 flat hours. That is common for thin coins: 19,500 of 1,148,102 bars (34 symbols) are flagged. Decide per analysis whether to exclude them.
- 1,148,102 rows kept (673 pre-trading bars trimmed), all valid.

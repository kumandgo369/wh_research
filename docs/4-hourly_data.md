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

## Where the data starts, and why

A symbol we have never saved is requested from 5000 bars before now (`MAX_BARS` in `candles.py`), which is everything the API holds for an active coin. Updates then add only the newest bars.

- The 1h data starts at **2026-03-23** (the first download was 2026-10-17) and grows by one hour per hour while the update keeps running. It cannot be backfilled through this API.
- Use the daily data for anything earlier.
- **Delisted coins** whose last bar is older than the window return nothing and are not saved. Each update still requests them once and gets an empty answer (about 20 seconds in total).

### Why not start at 2022?

The first 1h download did start at 2022-01-01. For an active coin that returns the same last 5000 bars, but a delisted coin returns the 5000 bars before its delisting, which can be years earlier. That left 245,304 rows (21%) before 2026-03-23 that came **only from coins that were later delisted**: a survivorship-biased slice with BTC and every surviving coin missing. Symbol counts per month looked like 2 to 22 coins until early 2026, then jumped to about 190, which does not reflect listings or delistings.

Those rows were removed once (2026-10-17, by trimming the file to `open_time >= 2026-03-23`). A copy of the untrimmed file may still exist as `data/hyperliquid/candles_1h.backup.parquet`; it can be deleted.

## Size

About 903k rows for 234 symbols, 32 MB raw and 33 MB cleaned. Expect roughly 1.5M rows (60 MB) of growth a year.

## Cleaning at 1h

- `after_gap` uses one hour: a step between bars longer than 1 hour. Result: 0 gaps.
- `is_stale` is still "more than 3 equal closes in a row", which at 1h means 4 flat hours. That is common for thin coins, so decide per analysis whether to exclude those bars. After the trim only 1,485 of 903,471 bars are flagged.

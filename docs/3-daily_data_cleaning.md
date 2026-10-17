# Daily data: cleaning

- **Code:** `src/wh_research/data/hyperliquid/clean_candles_1d.py` (`clean_candles_1d`, `update_candles_1d_cleaned`)
- **Output:** `data/hyperliquid/candles_1d_cleaned.parquet` (gitignored, rebuilt from raw on every run)

## What it does

1. **Trims the start of each symbol.** Drops bars before the first bar with `volume > 0`. This cannot leave a gap in the middle of a series.
2. **Adds True/False flag columns. No other rows are dropped.**

| Column | True when |
| ------ | --------- |
| `ok_high_low` | `high >= low` |
| `ok_high` | `high >= open` and `high >= close` |
| `ok_low` | `low <= open` and `low <= close` |
| `ok_price` | open, high, low and close are all `> 0` |
| `ok_volume` | `volume >= 0` |
| `is_valid` | all five `ok_*` columns are True |
| `is_stale` | the close is unchanged for more than 3 bars in a row (`STALE_BARS`) |
| `after_gap` | this is the first bar after one or more missing days for that coin |

Rows are flagged, not dropped, so the daily series has no gaps. A flat price can be a real quiet day, so you decide what to do with it.

## Using it

    df = pd.read_parquet("data/hyperliquid/candles_1d_cleaned.parquet")
    good = df[df["is_valid"] & ~df["is_stale"]]

Current data: 176,925 of 217,560 rows kept, 0 invalid, 27 stale bars (HPOS, NFTI, PANDORA), 0 gaps. 74 mid-series zero-volume bars are kept.

## Research rules

- **Look-ahead.** A bar is only known at its close. In as-of joins use `close_time` as the left key, never `open_time`.
- **Join key.** Use `symbol`. Funding data calls it `coin`, so rename on ingest.
- **Units.** Convert datetimes to the same dtype and unit before `merge_asof`.

## TODO

- [ ] Funding rate downloader and as-of join helper

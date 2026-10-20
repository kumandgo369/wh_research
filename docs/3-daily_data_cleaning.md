# Candle data: cleaning

- **Code:** `src/wh_research/data/hyperliquid/clean_candles.py` (`clean_candles(df, interval)`, `update_candles_cleaned(data_dir, interval)`)
- **Output:** `data/hyperliquid/candles_<interval>_cleaned.parquet` (gitignored, rebuilt from raw on every run)

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
| `is_stale` | the bar is the 4th or later bar in a row with the same close (`STALE_BARS` = 3). Only the bar itself and earlier bars decide it, so it is known at the bar's close and is safe to filter on |
| `after_gap` | this is the first bar after one or more missing bars for that coin (a step longer than one bar of the interval) |

Rows are flagged, not dropped, so the series keeps no gaps. A flat price can be a real quiet period, so you decide what to do with it.

## Using it

    DATA_DIR = Path("path/to/data/hyperliquid")    # change to where your data folder is
    df = pd.read_parquet(DATA_DIR / "candles_1d_cleaned.parquet")
    good = df[df["is_valid"] & ~df["is_stale"]]

Current 1d data: 176,925 of 217,560 rows kept, 0 invalid, 9 stale bars (HPOS, NFTI, PANDORA), 0 gaps. 74 mid-series zero-volume bars are kept.

## Research rules

- **Look-ahead.** A bar is only known at its close. In as-of joins use `close_time` as the left key, never `open_time`.
- **Join key.** Use `symbol`. Funding data calls it `coin` in the API; it is renamed to `symbol` when downloaded (see `5-funding_data.md`).
- **Units.** Convert datetimes to the same dtype and unit before `merge_asof`.

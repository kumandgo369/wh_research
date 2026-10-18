# Daily universe files

- **Code:** `src/wh_research/data/hyperliquid/daily_universe.py` (`filter_daily_universe(df, min_adv_usd)`, `update_daily_universe(data_dir, min_adv_usd)`, `daily_universe_filename(min_adv_usd)`)
- **Runner:** `uv run python scripts/build_hyperliquid_daily_universe.py <min_adv_usd>`, for example `2000000`
- **Input:** `data/hyperliquid/candles_1d_cleaned.parquet`
- **Output:** one file per cutoff, `data/hyperliquid/universe_1d_min_adv_<cutoff>.parquet` (gitignored, derived)

**Daily data only.** These files are made from daily bars for daily panels. There is no hourly version (see "Using it with hourly data" below).

## What a file contains

The cleaned daily candles, **kept only on the days a coin was liquid enough to be in the universe**. A coin that is not liquid on a day has no row for that day, and a coin can leave and rejoin.

All the columns of `candles_1d_cleaned.parquet` are kept (including the `ok_*`, `is_valid`, `is_stale` and `after_gap` flags), plus:

| Column | Meaning |
| ------ | ------- |
| `dollar_volume` | This bar's volume in dollars: `volume * (high + low + close) / 3` (volume is in coin units) |
| `adv_30d_prev` | The **median** `dollar_volume` of the 30 bars ending at the **previous** bar's close |

A row for day *t* is present when `adv_30d_prev >= cutoff`. To use a higher cutoff than the file's, filter in a notebook: `df[df["adv_30d_prev"] >= higher_cutoff]`.

## No look-ahead

- Whether day *t* is in the file is decided only from bars that had **closed by the end of day *t−1***. Nothing from day *t* or later is used, and nothing is ranked or scaled against the full history.
- So **a row's own return can be used directly**: you knew at the start of day *t* that the coin was in the universe. Do not shift the membership again.
- The same-day median is deliberately not stored, so it can't be used by mistake to pick day *t*.
- The window is a trailing 30 days on `close_time` (this bar included, nothing later). Adding newer bars never changes older rows, so a rerun gives identical earlier rows.
- `tests/test_daily_universe.py::test_no_look_ahead_in_the_universe` checks this by cutting the data and by multiplying future volumes by 1000.

## Rules

- **Median, not mean.** A single spike day (a listing, a pump) does not push a coin into the universe.
- **Minimum history.** The median needs 30 bars in its window, so a coin first appears on its **31st** cleaned bar (after the leading zero-volume bars are trimmed).
- **Gaps.** A window with a missing bar has no median, and a bar that does not directly follow the previous one (one day earlier) is not kept. The current 1d data has no gaps.
- **Stale and invalid bars** are not excluded from the median; they count with their actual volume. Filter them on the rows if you want to (`~is_stale & is_valid`).
- **Delisted coins** are kept while they qualify, so there is no survivorship bias. A delisted coin simply stops having rows, so a backtest has to handle the exit at its last bar.

## Many cutoffs, many files

- The cutoff in dollars is the script argument and is part of the file name: `2000000` gives `universe_1d_min_adv_2m.parquet`, `500000` gives `universe_1d_min_adv_500k.parquet`, `2500000` gives `universe_1d_min_adv_2500k.parquet`.
- A new cutoff creates a new file next to the others. Existing files for other cutoffs are never changed.
- Running the same cutoff again **rebuilds that file from the cleaned candles** (it does not append). Run it after `clean_hyperliquid_candles.py 1d`, so the order is update → clean → universe, for each cutoff you keep.

## Using it

    df = pd.read_parquet("data/hyperliquid/universe_1d_min_adv_2m.parquet")
    df["ret"] = df["close"] / df["open"] - 1       # the day's return; every row is tradeable that day

Current 1d data (as of 2026-10-17):

| Cutoff | Rows | Symbols on the latest day | Symbols ever included |
| ------ | ---- | ------------------------- | --------------------- |
| $2M | 47,699 | 63 | 173 |
| $500k | 92,044 | 97 | 223 |

The universe grows with market activity: at $2M it had 4 coins in mid-2023, about 27 in early 2024, and 63 in October 2026. If you need a stable size across time, filter on `adv_30d_prev` and take the top *N* per day in the notebook.

## Using it with hourly data

These files are for daily panels and there is no hourly universe file yet. Day *t*'s membership is known at the start of day *t* (the previous close), so it would be valid for the hourly bars that open during day *t*; build that join deliberately (match on the UTC date of the hourly `open_time`) rather than reusing these files directly.

# Daily universe files

- **Code:** `src/wh_research/data/hyperliquid/daily_universe.py` (`flag_daily_universe(df, min_mdv_usd, exit_mdv_usd=None)`, `update_daily_universe(data_dir, min_mdv_usd, exit_mdv_usd=None)`, `daily_universe_filename(min_mdv_usd, exit_mdv_usd=None)`)
- **Runner:** `uv run python scripts/build_hyperliquid_daily_universe.py <min_mdv_usd> [<exit_mdv_usd>]`, for example `2000000` or `2000000 1000000`
- **Input:** `data/hyperliquid/candles_1d_cleaned.parquet`
- **Output:** one file per entry (and exit) level, `data/hyperliquid/universe_1d_min_mdv_<entry>[_exit_<exit>].parquet` (gitignored, derived)

**Daily data only.** These files are made from daily bars for daily panels. There is no hourly version (see "Using it with hourly data" below).

## What a file contains

**Every row of the cleaned daily candles, with a True/False `in_universe` flag.** Nothing is dropped, so every coin keeps its full, gap-free series. That matters because forward returns (see `7-forward_returns.md`) and any feature that looks back (momentum, volatility) need contiguous history. In a file with the liquid-enough rows only, a coin that left and rejoined has holes, and a shift by *n* rows would land on the wrong day.

All the columns of `candles_1d_cleaned.parquet` are kept (including the `ok_*`, `is_valid`, `is_stale` and `after_gap` flags), plus:

| Column | Meaning |
| ------ | ------- |
| `dollar_volume` | This bar's volume in dollars: `volume * (high + low + close) / 3` (volume is in coin units) |
| `mdv_30d_prev` | MDV: the **median** daily dollar volume (not the mean, which is what "ADV" would mean) of the 30 bars ending at the **previous** bar's close |
| `in_universe` | `True` when the coin was liquid enough on this day (rule below); never missing |

With a single cutoff, `in_universe` is `mdv_30d_prev >= cutoff`, and a higher cutoff in a notebook is `df["mdv_30d_prev"] >= higher_cutoff`. With an entry and exit level (next section) the flag also covers the days in between, so that comparison does not give a single-cutoff universe.

**Compute labels and features on the whole file first, and filter on `in_universe` afterwards** (`df[df["in_universe"]]`).

## Entry and exit levels

A single cutoff makes a coin whose MDV hovers around it join and leave again and again. Give a second, lower **exit** level to stop that: a coin joins when `mdv_30d_prev` reaches the **entry** level and stays in until `mdv_30d_prev` falls below the **exit** level.

For each coin, in time order:

- `mdv_30d_prev >= entry`: in.
- `mdv_30d_prev < exit`: out.
- Between exit and entry: keeps its last state (a coin that is in stays in, a coin that is out stays out, so it cannot enter below the entry level).
- No `mdv_30d_prev` (under 30 bars of history, or right after a missing bar): out, and the state starts again from out.

The exit level must be above 0 and at most the entry level. An exit level equal to the entry level (or none) is the single-cutoff rule, and gives the same file name and flags as a single cutoff. Like everything else it only uses `mdv_30d_prev`, so it has no look-ahead: `tests/test_daily_universe.py::test_no_look_ahead_with_an_exit_level` checks this.

On the current data, entry $2M with exit $1M has 563 joins and leaves instead of 1,048 for a single $2M cutoff. It flags 11,946 more rows, all with `mdv_30d_prev` between $1.0M and $2.0M, and every row flagged by the single $2M cutoff is flagged too.

## No look-ahead

- The flag for day *t* is decided only from bars that had **closed by the end of day *t−1***. Nothing from day *t* or later is used, and nothing is ranked or scaled against the full history.
- So **use the flag on the same row**: you knew at the start of day *t* that the coin was in the universe. Do not shift it again.
- The same-day median is deliberately not stored, so it can't be used by mistake to pick day *t*.
- The window is a trailing 30 days on `close_time` (this bar included, nothing later). Adding newer bars never changes older rows, so a rerun gives identical earlier rows.
- `tests/test_daily_universe.py::test_no_look_ahead_in_the_universe` checks this by cutting the data and by multiplying future volumes by 1000.

## Rules

- **Median, not mean.** A single spike day (a listing, a pump) does not push a coin into the universe.
- **Minimum history.** The median needs 30 bars in its window, so a coin is first flagged in on its **31st** cleaned bar (after the leading zero-volume bars are trimmed).
- **Gaps.** A window with a missing bar has no median, and a bar that does not directly follow the previous one (one day earlier) is flagged out. The current 1d data has no gaps.
- **Stale and invalid bars** are not excluded from the median; they count with their actual volume. Filter them on the rows if you want to (`~is_stale & is_valid`).
- **Delisted coins** are flagged in while they qualify, so there is no survivorship bias. A delisted coin simply stops having rows, so a backtest has to handle the exit at its last bar.

## Many cutoffs, many files

- The cutoff in dollars is the first script argument and is part of the file name: `2000000` gives `universe_1d_min_mdv_2m.parquet`, `500000` gives `universe_1d_min_mdv_500k.parquet`, `2500000` gives `universe_1d_min_mdv_2500k.parquet`.
- An optional second argument is the exit level and adds `_exit_<level>` to the name: `2000000 1000000` gives `universe_1d_min_mdv_2m_exit_1m.parquet`.
- A new level creates a new file next to the others. Existing files for other levels are never changed.
- Running the same levels again **rebuilds that file from the cleaned candles** (it does not append). Run it after `clean_hyperliquid_candles.py 1d`, so the order is update → clean → universe, for each file you keep.

## Using it

    DATA_DIR = Path("path/to/data/hyperliquid")    # change to where your data folder is
    df = pd.read_parquet(DATA_DIR / "universe_1d_min_mdv_2m.parquet")
    universe = df[df["in_universe"]]               # only the days a coin was tradeable

Current 1d data (as of 2026-10-17). Every file has all 177,103 cleaned rows; this counts the ones flagged `in_universe`:

| Entry / exit | Rows flagged in | Symbols in on the latest day | Symbols ever in |
| ------------ | --------------- | ---------------------------- | --------------- |
| $2M | 47,699 | 63 | 173 |
| $2M / $1M | 59,645 | 65 | 173 |
| $500k | 92,044 | 97 | 223 |

The universe grows with market activity: at $2M it had 4 coins in mid-2023, about 27 in early 2024, and 63 in October 2026. If you need a stable size across time, filter on `mdv_30d_prev` and take the top *N* per day in the notebook.

## Using it with hourly data

These files are for daily panels and there is no hourly universe file yet. Day *t*'s flag is known at the start of day *t* (the previous close), so it would be valid for the hourly bars that open during day *t*; build that join deliberately (match on the UTC date of the hourly `open_time`) rather than reusing these files directly.

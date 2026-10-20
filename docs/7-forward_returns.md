# Forward-return labels

How this fits into the research steps and the leakage rules: `9-research_workflow.md`. `split_holdout` and `block_rows` in `src/wh_research/evaluation/splits.py` implement the purge below.

- **Code:** `src/wh_research/data/hyperliquid/labels.py` (`add_forward_returns(df, interval, horizons)`)
- **Works on:** the candle schema (`symbol`, `open_time`, `close_time`, `close`): raw or cleaned `candles_1d` / `candles_1h`, or a universe file. Other columns pass through.

    from wh_research.data.hyperliquid.labels import add_forward_returns

    DATA_DIR = Path("path/to/data/hyperliquid")    # change to where your data folder is
    df = pd.read_parquet(DATA_DIR / "universe_1d_min_mdv_2m_exit_1m.parquet")
    df = add_forward_returns(df, "1d", [1, 3, 7])
    train = df[df["in_universe"]].dropna(subset=["fwd_log_return_7"])

## What it adds

`horizons` are numbers of bars of the interval (`[24]` on `"1h"` means one day). For each horizon *n* the function returns a copy of the table, with the same rows, order and index, plus:

| Column | Meaning |
| ------ | ------- |
| `fwd_log_return_{n}` | `log(close of the bar n bars later / this bar's close)`. The position is opened at this bar's `close_time` and closed at the close of the bar *n* bars later. NaN when that bar does not exist. |
| `fwd_direction_{n}` | `1.0` if the return is above 0, `0.0` if it is 0 or below, **NaN where the return is NaN** |
| `fwd_end_time_{n}` | `close_time + n bars`: the moment the label becomes known (used for purging, below) |

## Design decisions

- **Looked up by time, not by row.** The future close is found by `(symbol, open_time + n bars)`. A missing bar gives NaN, never a different day, coins never mix, and the row order of the input does not matter. A row shift (`shift(-n)`) would silently use the wrong day wherever a coin has a gap. (In the old filtered universe file, 84 symbols had holes.) Duplicate `(symbol, open_time)` rows raise an error.
- **NaNs are kept, never dropped or filled.** Dropping inside the function would break the row alignment with your features, hide which rows have no label, and remove the newest rows, which you still need for live prediction. Filling would invent a return. Drop them yourself with `dropna(subset=[...])`.
- **The direction keeps NaN as NaN.** `(ret > 0).astype(int)` turns "no label" into "down" and quietly adds wrong rows to the down class. Flat returns (exactly 0) are 0.14% of daily bars and count as "not up".
- **Bad prices.** A close of 0 or below gives NaN instead of ±inf (the data has none now).
- **`is_valid` / `is_stale` are not used**, because raw files don't have them. Filter first if you want to.
- **Close-to-close.** The label assumes you can trade at the close price. The next bar's open differs from the previous close by a median of 0.05% (99th percentile 1.45%) on the daily data, so real fills differ somewhat.

## Avoiding future leaks

A label looks into the future by definition. What the function guarantees is that a label depends **only on the close at this bar's `close_time` and the close *n* bars later** (`test_a_label_depends_only_on_its_own_close_and_the_close_n_bars_later`). The leaks come from how you use it:

1. **Never use `fwd_*` columns as features.** Features may only use data up to each bar's `close_time`.
2. **Compute labels (and features) on the whole file, then filter.** Use a universe file with its `in_universe` flag and only filter on it after labelling. Labelling an already filtered table would drop the rows whose future day fell outside the universe, which biases the sample.
3. **Purge cross-validation folds.** A row's label is only known at `fwd_end_time_{n}`. A training row whose label ends after the evaluation period starts overlaps it and leaks the future into training. With the evaluation period starting at `cut`:

       cut = pd.Timestamp("2025-03-01", tz="UTC")
       train = df[df["fwd_end_time_7"] < cut]        # label fully known before the eval period
       evaluation = df[df["close_time"] >= cut]

   With several folds, apply the same rule at every boundary. A fold's evaluation rows start at `open_time >= eval_start` and also need their label to end before the next boundary (the next fold's `eval_start`, or the holdout start), otherwise they overlap it:

       train = members[members["fwd_end_time_3"] < eval_start]
       evaluation = members[(members["open_time"] >= eval_start) & (members["fwd_end_time_3"] < next_boundary)]

   Use the longest horizon you label with. On the 2m/1m universe the holdout split at *n* = 7 removes 466 rows from the pre-holdout set (`notebooks/case_study_1/3_computing_labels_and_features.ipynb`). The feature lookback needs no purge, only the label horizon does. No embargo is needed in a walk-forward split, because training never uses data after the evaluation period.

   Split by **time** like this (or by sorting by `open_time` first). The universe files are sorted by symbol and then time, so slicing them by row position, such as `df[:int(len(df) * 0.7)]`, cuts by coin and not by date.
4. **The last *n* bars of every coin have no label**, and for a delisted coin those are its final days before the delisting. Dropping the NaNs removes them, which hides the worst outcomes. It is small (42 of 59,645 rows at *n* = 7 in the 2m/1m universe) but real: handle delisting explicitly in a backtest.

## Using it with hourly data

    h = pd.read_parquet(DATA_DIR / "candles_1h_cleaned.parquet")
    h = add_forward_returns(h, "1h", [1, 24])         # 1 hour and 24 hours ahead

About 900k rows take under a second.

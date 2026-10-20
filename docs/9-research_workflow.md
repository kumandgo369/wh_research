# Research workflow

> **Work in progress.** This document covers the workflow only up to **feature evaluation** (case study 1, notebooks 1 to 4). Model training, turning predictions into positions, the backtest and the final holdout evaluation have not been built yet, so they are only listed under "Not yet covered" at the end. The document grows as the case study does.

The aim of every rule below is the same: **a number measured in research must be a number that could have been measured at the time**, with no information from the future and no choices made while looking at the final exam.

## The steps

| # | Step | Where | Function / script | Output |
| - | ---- | ----- | ----------------- | ------ |
| 1 | Download candles | `docs/1`, `docs/2` | `scripts/update_hyperliquid_candles.py 1d` | `candles_1d.parquet` (raw) |
| 2 | Clean | `docs/3` | `scripts/clean_hyperliquid_candles.py 1d` | `candles_1d_cleaned.parquet` |
| 3 | Build and choose a universe | `docs/6`, notebook 1 | `scripts/build_hyperliquid_daily_universe.py 2000000 1000000`, `universe_size` | `universe_1d_min_mdv_2m_exit_1m.parquet`, then a **frozen copy** in `case_study_data/` |
| 4 | Decide the time splits | notebook 2 | `find_holdout_start`, `find_fold_starts` (`evaluation/splits.py`) | decisions (70/30 holdout, fold boundaries at 40% and 70% of the train days) |
| 5 | Add labels and features to the **whole** file | `docs/7`, `docs/8`, notebook 3 | `add_forward_returns`, `add_past_returns` | `fwd_*` and `past_log_return_*` columns |
| 6 | Cut off the holdout (purged) | notebook 3 | `split_holdout` | `pre_holdout.parquet`, `holdout.parquet` |
| 7 | Evaluate the features on pre-holdout | notebook 4 | `ic_summary`, `ic_by_block`, `quantile_table`, `quantile_table_by_block`, plots (`evaluation/ic.py`, `plots.py`) | tables and charts |
| 8 | Check the saved data | any time | `scripts/check_case_study_data.py` | PASS / FAIL per check |

Run order for data: update, then clean, then universe (each is built from the previous file). Re-run step 8 after any data update.

## What is known when

For a row of day *t* (the bar opens at the start of day *t* and closes at `close_time`):

| Moment | What is known | Used for |
| ------ | ------------- | -------- |
| start of day *t* | `in_universe` (decided from the 30-day median volume at the close of day *t-1*) | is the coin tradeable today |
| `close_time` of day *t* | `past_log_return_n` = log(close *t* / close *t-n*) | **features** |
| `close_time` of day *t+n* | `fwd_log_return_n` = log(close *t+n* / close *t*) | **labels** (`fwd_end_time_n` is this moment) |

So features may only use data up to `close_time`; labels use data after it; and the universe flag and the features are known at the same moment the label starts, so they are used **on the same row with no shift**.

## Leakage rules (the checklist)

1. **Compute labels and features on the whole series of every coin, then filter** to `in_universe`. Filtering first leaves holes, and a shift by *n* rows would land on the wrong day. Lookups are by time (`symbol`, `open_time ± n bars`), never by row shift.
2. **`fwd_*` columns are never features.**
3. **Cut by date, never by row position.** The files are sorted by symbol first, so row slices cut by coin.
4. **Purge by the label horizon.** A row's label is only known at `fwd_end_time_n`. Keep a row only if that moment is before the period that must not see it (`split_holdout` for the holdout, `block_rows` for a time block, and later for each fold's evaluation period). The feature lookback needs no purge: a walk-forward training set never uses data after the evaluation period, so only the label horizon matters.
5. **The holdout is cut first and then left alone.** Every description, plot and test during research uses `pre_holdout` only. It is opened once, at the end. Anything fitted later (scalers, thresholds, model settings) uses training rows only.
6. **Do not select rows or days with information from the future.** The "at least 10 coins per day" rule counts coins that have the *feature*, not the label (a label depends on the future: a delisting removes it). The quintile cut includes every coin that has the feature.
7. **Choose the universe, features and labels without looking at holdout results**, and write down anything you did see (see the disclosure in `docs/10-case_study_1_audit.md`).
8. **Count your tests.** Every feature, label, block or setting you look at is a test. Raw p-values from many tests overstate the evidence (see the limitations in notebook 4).
9. **Re-run `scripts/check_case_study_data.py`** after any data change.

## The statistics

- **Cross-sectional IC** (`daily_ic`): each day, the Spearman rank correlation between the feature and the label across the coins of that day. Rank based, so outliers matter little, and per day, so market-wide moves cancel.
- **Mean IC with a HAC test** (`hac_test`): the mean of the daily ICs, tested against 0 with a Newey-West standard error with as many lags as the label has days, because an *n*-day label overlaps the next *n-1* days and makes consecutive daily ICs correlated. The 95% confidence interval is mean ± t critical value × that standard error, so it agrees with the p-value.
- **Thin days:** days with fewer than `min_symbols` (10) coins are skipped, because a rank correlation over a handful of coins is noise.
- **Quantile means** (`daily_quantile_stats`, `quantile_table`): each day the coins are cut into buckets by the feature (1 = lowest), the mean (or median) label per bucket is taken, and the daily values are averaged. The median shows whether a few extreme coins drive the mean.
- **Time blocks** (`ic_by_block`, `quantile_table_by_block`): the same tables inside separate periods, to see whether a result is stable over time. The blocks do not overlap and each block is purged at its end.

## Adding a new feature or label

- **Feature:** write a function like `add_past_returns` that looks the earlier bar up **by time** and keeps all rows and NaNs. Add it to notebook 3 and to `features` in notebook 4. Add tests in the style of `tests/test_features.py` (including "depends only on past data"), and a recomputation to `evaluation/checks.py` if it is saved.
- **Label:** add the horizon to `add_forward_returns` in notebook 3 and to the `labels` dict in notebook 4. If it is longer than the current longest, raise the `horizon` passed to `split_holdout`, because the holdout purge uses the longest label.

## Bias checklist

| Risk | How it is handled | Where |
| ---- | ----------------- | ----- |
| Look-ahead in the universe | flag from the previous close, verified by recomputation | `docs/6`, `check_universe_median` |
| Look-ahead in features and labels | time lookups, tests, recomputation | `docs/7`, `docs/8`, `check_saved_columns` |
| Overlapping labels across splits | purge by `fwd_end_time_n` | `split_holdout`, `block_rows` |
| Overlapping labels inside the IC test | HAC standard error | `hac_test` |
| Peeking at the holdout | cut first, check pre-holdout only; earlier peek disclosed | notebook 3, audit doc |
| Survivorship | delisted coins are kept; **their last labels are missing and drop out, and a delisting return is not observed** | audit doc, final evaluation must handle it |
| Selection by future availability | day and bucket rules use the feature only | `keep_days_with_enough_coins` |
| Selecting on past returns through the universe | measured: in-universe rows have no unusual past return | audit doc |
| Outliers | median next to mean; rank-based IC | notebook 4 |
| Many tests / data snooping | stated, adjusted p-values in the audit | notebook 4, audit doc |
| One regime | results by time block | notebook 4 |
| Costs, slippage, funding, capacity, same-close execution | **not modelled yet** | audit doc, backtest step |

## Not yet covered

- **Model training and tuning on walk-forward folds.** Build the folds from `pre_holdout` after the features and the label are chosen (fold 1 trains before `fold1_eval_start` and is evaluated until `fold2_eval_start`, and so on), with the label-horizon purge from `block_rows` and everything fitted on training rows only. The audit risks that apply: purging, multiple testing across model settings, regime concentration.
- **Predictions to positions and portfolio construction.** Risks: capacity in the least liquid coins, turnover, equal weighting.
- **Backtest with costs.** Risks: same-close execution, spread and slippage, funding payments (the daily funding is small next to returns but correlated with the momentum features), delistings.
- **Final holdout evaluation.** Done once. Risks: delistings (15 coins that were in the universe stop trading after the holdout starts, and their last labels are missing), nothing may be tuned on it.

# Case study 1: audit for look-ahead and other biases

Audit of the whole path from the downloaded candles to the feature evaluation (notebook 4): the code, the saved data files and the notebooks. Done on 2026-10-20 on the data up to 2026-10-17. The checks that can be repeated are in `scripts/check_case_study_data.py` (`src/wh_research/evaluation/checks.py`).

**Result:** no look-ahead was found in the data pipeline, the universe, the labels, the features or the splits as they are now. Three issues were found and fixed along the way (two in an earlier pass), and a list of smaller issues and residual risks is documented below. The residual risks matter for the next stages.

## Method

1. Read every module on the path and the four notebooks.
2. Recompute the key quantities a second, independent way and compare with what is saved (the checks below).
3. Measure suspected biases on the real data (missing labels, outliers, selection, multiple testing, funding) instead of reasoning about them.
4. Fix what is cheap to fix, document the rest.

## Checked and clean

| Area | How it was checked | Result |
| ---- | ------------------ | ------ |
| Download | read the code | only closed bars (`close_time < now`), incremental append never rewrites old bars |
| Universe flag `in_universe` | recomputed the median of the 30 dollar volumes strictly before each bar by position (`check_universe_median`), for all 177,103 rows | 0 mismatches. Never flagged on a coin's first 30 bars (`check_universe_needs_history`) |
| Cleaning flags | read the code, rebuilt after the fix below | `is_valid`, `after_gap` use the bar and earlier bars only |
| Features | recomputed `past_log_return_7/14/30` from the frozen universe by time lookup (`check_saved_columns`), 37,725 + 21,454 rows | 0 differences. Unit tests prove a value depends only on its own close and the close *n* bars earlier |
| Labels | same for `fwd_log_return_1/3/7` | 0 differences. `past_log_return_n` on day *t* equals `fwd_log_return_n` on day *t-n* exactly |
| Holdout split | `check_split` | 0 overlapping rows, universe rows only, the latest pre-holdout label ends at 2025-09-21 23:59:59.999, before the holdout starts on 2025-09-22 |
| Time blocks in notebook 4 | overlap and purge check | no row in two blocks, every kept label ends before its block ends |
| Universe vs past returns | compared the mean past 7-day return of in-universe and other rows | -0.0105 vs -0.0082: the liquidity filter does not select on recent performance |
| HAC lags | t-stats with *n*, *2n* and 10 lags | stable (block 3, 30-day feature against the 7-day label: t = 3.14, 2.94, 3.00) |

## Findings

| # | Severity | Finding | Status |
| - | -------- | ------- | ------ |
| A | High (earlier pass) | CV folds and the holdout split were not purged: a training row near an evaluation start had a label that ended inside the evaluation period | **Fixed**: `split_holdout`, `block_rows`, rule in `docs/7-forward_returns.md` |
| B | Medium (earlier pass) | `is_stale` flagged the first bars of a long flat run because of later bars (look-ahead). No effect on the case study (0 stale rows in the universe) | **Fixed**: it is now backward-looking, and the derived files were rebuilt (only `is_stale` changed: 27 to 9 rows in the 1d files, 1,489 to 517 in the 1h file) |
| 1 | Medium | **The holdout was partly seen.** An earlier version of notebook 3 printed label base rates and feature statistics over all universe rows, including the holdout, and notebook 1 chose the universe cutoffs from universe-size statistics over the whole period | **Notebook 3 fixed**: the split comes first and every check runs on pre-holdout only. **The earlier peek cannot be undone.** It revealed only the base rate of the labels in the holdout (up-day share 0.454 / 0.439 / 0.417 for the 1 / 3 / 7-day label, against 0.479 / 0.473 / 0.453 pre-holdout), nothing about a feature-label relation. Notebook 1's choice used trading volume only. Both are disclosed here and in notebook 1 |
| 2 | Medium (interpretation) | **Many tests and one strong block.** 9 whole-period and 27 per-block tests with unadjusted p-values. After Holm / Bonferroni on the whole period only the 7-day feature against the 1-day label (adjusted p = 0.018) and the 30-day feature against the 7-day label (0.029 to 0.033) survive; the 30-day feature against the 3-day label (raw p = 0.034) does not. Per block (27 tests) only block 3 (2024-12 to 2025-09) is significant for the 14 and 30-day features, and only the 30-day feature against the 7-day label is at the 5% edge after Holm (adjusted p = 0.050); with Benjamini-Hochberg block 3's 14d-7d, 30d-3d and 30d-7d survive (q = 0.020). Blocks 1 and 2 are not significant | **Documented** (notebook 4 limitations). Treat the momentum result as one regime until it is confirmed |
| 3 | Low | The "at least 10 coins a day" rule counted coins that have a **label**, which depends on the future (a delisting removes a coin from the count) | **Fixed**: the rule counts the feature. 0 of 744 days changed |
| 4 | Low | The quintile cut used only coins that have a label | **Fixed**: the cut uses every coin with the feature, then drops coins without a label. Quintile means moved by at most 0.03 percentage points |
| 5 | Low | **Delisting returns are not observed.** The last *n* labels of a coin that stops trading while in the universe are missing and drop out of every IC. In pre-holdout this is 3 coins and 21 rows (RNDR, FTM, MKR, which migrated to new tickers); 56 of 234 symbols stop before the end of the data, 24 of them were ever in the universe, and **15 of those stop after the holdout starts**, so the final evaluation is more exposed. The earlier docs said "no survivorship bias", which was too strong | **Documented**; softened in `docs/6`. Must be handled explicitly in the final evaluation (assume an exit at the last bar) |
| 6 | Low | Outliers can move means: 7 one-day moves beyond ±100% (SHIA, OM, JELLY, VINE, TNSR, ZEREBRO, HYPER) and 10 rows with a 7-day return beyond ±150%. The IC is rank based and robust | **Fixed**: notebook 4 shows the median next to the mean |
| 7 | Low | The derived data files still carried the old `is_stale` flag | **Fixed** (see B) |
| 8 | Info | **Not look-ahead, but a backtest would be rosier than reality:** signal and trade at the same close, no costs or slippage, funding ignored (mean +0.040% a day, standard deviation 0.14%, against a 6.3% standard deviation of the 1-day return; the features correlate with funding rank by 0.10 to 0.13, so momentum longs pay more), equal weight down to $2M of daily volume (capacity), and Hyperliquid chooses what to list | **Documented**; to be handled in the backtest step |

## Residual risks that cannot be removed offline

- **Completeness of delisted coins.** The downloader keeps every coin that `info.meta()` returns, delisted ones included. Whether the API still returns every perp that was ever delisted cannot be verified without it. If old delistings are missing, the early years are survivorship-biased.
- **The partial holdout peek** (finding 1).
- **Regime dependence** (finding 2): one block drives the whole-period result.
- **Ticker migrations** (RNDR to RENDER, FTM to S, MKR to SKY) are treated as separate coins: history is lost, but no return is invented.
- **Fixed split choices.** The 70/30 holdout and the 40% / 70% fold boundaries were fixed by rule once; no alternative was tried.

## Repeating the audit

    uv run python scripts/check_case_study_data.py     # data invariants, prints PASS / FAIL
    uv run pytest                                      # unit tests, including tests/test_evaluation_checks.py

Run both after any data update or code change on this path. The measurements for findings 2, 5, 6 and 8 were one-off analyses on the data of 2026-10-17; repeat them if the data changes a lot.

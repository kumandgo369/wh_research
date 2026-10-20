"""Information coefficient (IC) and quantile tests for features against forward-return labels.

Works on a universe table (symbol, open_time, in_universe, the feature columns and the label
columns). Pass it only the rows you are allowed to look at, for example pre_holdout, or one block
from block_rows in splits.py.

- daily_ic: on each day, the Spearman rank correlation between a feature and a label across coins
- hac_test: test whether the mean daily IC differs from 0, robust to overlapping labels
- ic_summary / ic_by_block: the full table for every feature-label pair (whole period / per block)
- daily_quantile_stats / quantile_table / quantile_table_by_block: the mean (or median) label per
  feature quantile, with the quantiles cut separately on each day

Labels look n days ahead, so labels is always a dict {label_column: n_days}, for example
{"fwd_log_return_1": 1, "fwd_log_return_3": 3}. See docs/9-research_workflow.md.
"""

# numpy gives us a column of ones for the regression
import numpy as np
# pandas gives us tables (DataFrames)
import pandas as pd
# statsmodels does the regression with HAC (Newey-West) standard errors
import statsmodels.api as sm

# block_rows cuts one time block and removes the rows whose label looks past its end
from wh_research.evaluation.splits import block_rows


def keep_days_with_enough_coins(df, feature, min_symbols):
    """Keep the rows that have the feature, on days with at least min_symbols such coins.

    The count uses the feature only. Whether a coin has a label depends on the future (a delisting
    removes it), so it must not decide which days are used.
    """
    # Keep only the rows that have the feature
    d = df.dropna(subset=[feature])
    # Count the coins we have on each day
    coins_per_day = d.groupby("open_time")["symbol"].size()
    # The days that have enough coins
    good_days = coins_per_day[coins_per_day >= min_symbols].index
    # Keep only those days
    return d[d["open_time"].isin(good_days)]


def daily_ic(df, feature, label, min_symbols=10):
    """The IC of every day: the Spearman rank correlation between the feature and the label across coins.

    Returns a Series with one value per day. Days with fewer than min_symbols coins are skipped.
    """
    # The days we can use, then only the rows that also have the label
    d = keep_days_with_enough_coins(df, feature, min_symbols).dropna(subset=[label])
    # On each day, rank the coins by the feature and by the label and correlate the ranks
    return d.groupby("open_time").apply(lambda day: day[feature].corr(day[label], method="spearman"))


def hac_test(ic, n):
    """Test the mean of the daily ICs against 0 with a HAC (Newey-West) standard error.

    n is the label horizon in days. An n-day label overlaps the next n-1 days, so consecutive daily
    ICs are correlated, and a plain t-test would overstate the significance. We allow n lags.
    Returns: mean IC, standard error, t-stat, two-sided p-value, 95% CI low, 95% CI high.
    """
    # Regress the daily ICs on a constant: the constant is the mean IC
    result = sm.OLS(ic.to_numpy(), np.ones(len(ic))).fit(cov_type="HAC", cov_kwds={"maxlags": n}, use_t=True)
    # The 95% confidence interval of the mean IC, built from the HAC standard error
    ci_low, ci_high = result.conf_int(alpha=0.05)[0]
    # Hand back the numbers
    return result.params[0], result.bse[0], result.tvalues[0], result.pvalues[0], ci_low, ci_high


def summary_row(ic, n):
    """One row of the summary table for one series of daily ICs and its label horizon n."""
    # The daily ICs of this pair (days that could not be computed are empty)
    ic = ic.dropna()
    # Test the mean IC against 0
    mean_ic, se, t_stat, p_value, ci_low, ci_high = hac_test(ic, n)
    # The row of numbers
    return {
        "days": len(ic),
        "mean_ic": mean_ic,
        "std_ic": ic.std(),
        "se_hac": se,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "t_stat_hac": t_stat,
        "p_value": p_value,
    }


def ic_summary(df, features, labels, min_symbols=10):
    """The IC summary of every feature-label pair over all the rows of df.

    Returns (summary, ic_daily): summary has one row per (feature, label) with days, mean_ic, std_ic,
    se_hac, ci_low, ci_high, t_stat_hac and p_value. ic_daily has one column per pair with the daily ICs.
    """
    # The daily ICs of every pair, one column per (feature, label)
    ic_daily = pd.DataFrame({
        (feature, label): daily_ic(df, feature, label, min_symbols)
        for feature in features
        for label in labels
    })
    # One summary row per pair, using as many lags as the label has days
    rows = {(feature, label): summary_row(ic, labels[label]) for (feature, label), ic in ic_daily.items()}
    # Make the table and name the row levels
    summary = pd.DataFrame.from_dict(rows, orient="index")
    summary.index = pd.MultiIndex.from_tuples(summary.index, names=["feature", "label"])
    # Hand back both
    return summary, ic_daily


def ic_by_block(df, blocks, features, labels, min_symbols=10):
    """The same summary, run separately inside each time block.

    blocks is a dict {name: (start, end)}. Inside a block only the rows whose label ends before the
    block ends are used (block_rows), with the horizon of the label being tested.
    Returns one row per (feature, label, block).
    """
    # One summary row for every block, feature and label
    rows = {}
    for block, (start, end) in blocks.items():
        for feature in features:
            for label, n in labels.items():
                # The rows of this block, purged for this label's horizon
                rows_in_block = block_rows(df, start, end, n)
                # The daily ICs of this pair inside the block, and their summary row
                rows[(feature, label, block)] = summary_row(daily_ic(rows_in_block, feature, label, min_symbols), n)
    # Make the table and name the row levels
    summary = pd.DataFrame.from_dict(rows, orient="index")
    summary.index = pd.MultiIndex.from_tuples(summary.index, names=["feature", "label", "block"])
    # Hand it back
    return summary


def daily_quantile_stats(df, feature, label, statistic="mean", n_quantiles=5, min_symbols=10):
    """The mean (or median) label of every feature quantile on every day.

    On each day the coins are ranked by the feature and cut into n_quantiles equal buckets,
    1 = lowest feature, n_quantiles = highest. The buckets use every coin that has the feature, so
    a coin's missing label (the future) cannot move the cut. Returns one row per day, one column
    per bucket.
    """
    # The usable days, and a copy so we can add a column
    d = keep_days_with_enough_coins(df, feature, min_symbols).copy()
    # On each day, rank the coins by the feature (ties broken by order, so every bucket gets filled)
    rank = d.groupby("open_time")[feature].rank(method="first")
    # On each day, cut the ranks into equal buckets numbered 1 to n_quantiles
    d["quantile"] = rank.groupby(d["open_time"]).transform(lambda r: pd.qcut(r, n_quantiles, labels=False)) + 1
    # Only now drop the coins without a label
    d = d.dropna(subset=[label])
    # The statistic of the label in every bucket on every day: one row per day, one column per bucket
    return d.groupby(["open_time", "quantile"])[label].agg(statistic).unstack()


def quantile_table(df, features, labels, statistic="mean", n_quantiles=5, min_symbols=10):
    """The label per feature quantile, averaged over days, in percent, for every feature-label pair.

    Returns one row per (feature, label) and one column per quantile.
    """
    # Average the daily statistic of every bucket over all days, as a percentage
    rows = {
        (feature, label): daily_quantile_stats(df, feature, label, statistic, n_quantiles, min_symbols).mean() * 100
        for feature in features
        for label in labels
    }
    # Make the table and name the row levels
    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index = pd.MultiIndex.from_tuples(table.index, names=["feature", "label"])
    # Hand it back
    return table


def quantile_table_by_block(df, blocks, features, labels, statistic="mean", n_quantiles=5, min_symbols=10):
    """The same quantile table inside each time block (rows purged for each label's horizon).

    Returns one row per (block, feature, label).
    """
    # One table per block, with the block name as an extra row level
    tables = {}
    for block, (start, end) in blocks.items():
        # The table of this block: each label uses its own purged rows
        rows = {}
        for feature in features:
            for label, n in labels.items():
                # The rows of this block, purged for this label's horizon
                rows_in_block = block_rows(df, start, end, n)
                # The average of the daily statistic of every bucket, as a percentage
                rows[(feature, label)] = (
                    daily_quantile_stats(rows_in_block, feature, label, statistic, n_quantiles, min_symbols).mean() * 100
                )
        # Make the table of this block
        tables[block] = pd.DataFrame.from_dict(rows, orient="index")
    # Stack the blocks and name the row levels
    table = pd.concat(tables)
    table.index.names = ["block", "feature", "label"]
    # Hand it back
    return table

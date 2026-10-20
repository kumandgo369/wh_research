# numpy makes the random numbers
import numpy as np
# pandas gives us tables (DataFrames)
import pandas as pd
# pytest is the test framework; we use its approx
import pytest
# scipy gives us reference answers to compare with
from scipy import stats

# The functions we are testing
from wh_research.evaluation.ic import (
    daily_ic,
    daily_quantile_stats,
    hac_test,
    ic_by_block,
    ic_summary,
    quantile_table,
    quantile_table_by_block,
)

# Day 0 of the made-up data
START = pd.Timestamp("2024-01-01", tz="UTC")


def make_panel(n_days=40, n_coins=12, seed=0):
    """A made-up universe table: the label is partly driven by the feature, plus noise."""
    # A reproducible random number generator
    rng = np.random.default_rng(seed)
    # One row per coin per day
    rows = [(f"C{coin}", day) for day in range(n_days) for coin in range(n_coins)]
    df = pd.DataFrame(rows, columns=["symbol", "day"])
    # The start and end of each daily bar
    df["open_time"] = START + pd.to_timedelta(df["day"], unit="D")
    df["close_time"] = df["open_time"] + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    # A random feature, and a label that follows it a little
    df["feat"] = rng.normal(size=len(df))
    df["lab"] = 0.3 * df["feat"] + rng.normal(size=len(df))
    # The moment the 1-day label becomes known
    df["fwd_end_time_1"] = df["close_time"] + pd.Timedelta(days=1)
    # Hand back the table
    return df


def test_the_daily_ic_is_the_spearman_correlation_across_the_coins_of_that_day():
    # Arrange: a made-up panel
    df = make_panel()
    # Act: the IC of every day
    ic = daily_ic(df, "feat", "lab")
    # Assert: day 7 equals scipy's Spearman correlation on that day's rows
    day = df[df["day"] == 7]
    assert ic[START + pd.Timedelta(days=7)] == pytest.approx(stats.spearmanr(day["feat"], day["lab"]).statistic)
    # Assert: one value per day
    assert len(ic) == 40


def test_days_with_too_few_coins_are_skipped():
    # Arrange: days 0 to 4 only have 5 coins, the others have 12
    df = make_panel()
    df = df[(df["day"] >= 5) | (df["symbol"].isin([f"C{i}" for i in range(5)]))]
    # Act: the IC with at least 10 coins per day
    ic = daily_ic(df, "feat", "lab", min_symbols=10)
    # Assert: the 5 thin days are gone
    assert len(ic) == 35
    assert ic.index.min() == START + pd.Timedelta(days=5)


def test_the_coin_count_ignores_missing_labels_because_those_depend_on_the_future():
    # Arrange: on day 3 exactly 10 coins have a feature, but one of them has no label (it was delisted later)
    df = make_panel(n_coins=10)
    df.loc[(df["day"] == 3) & (df["symbol"] == "C0"), "lab"] = np.nan
    # Act: the IC with at least 10 coins per day
    ic = daily_ic(df, "feat", "lab", min_symbols=10)
    # Assert: day 3 is still used (10 coins had the feature), with the 9 coins that have a label
    assert START + pd.Timedelta(days=3) in ic.index
    day = df[(df["day"] == 3)].dropna(subset=["lab"])
    assert ic[START + pd.Timedelta(days=3)] == pytest.approx(stats.spearmanr(day["feat"], day["lab"]).statistic)


def test_the_hac_test_gives_the_mean_a_standard_error_and_a_matching_confidence_interval():
    # Arrange: 200 made-up daily ICs
    ic = pd.Series(np.random.default_rng(1).normal(0.05, 0.2, 200))
    # Act: test with no lags
    mean_ic, se, t_stat, p_value, ci_low, ci_high = hac_test(ic, 0)
    # Assert: the mean is the mean of the ICs
    assert mean_ic == pytest.approx(ic.mean())
    # Assert: with no lags it is very close to the plain t-test
    assert t_stat == pytest.approx(stats.ttest_1samp(ic, 0).statistic, rel=0.02)
    # Assert: the t-stat is the mean over its standard error
    assert t_stat == pytest.approx(mean_ic / se)
    # Assert: the interval is the mean plus or minus the t critical value times the standard error
    critical = stats.t.ppf(0.975, len(ic) - 1)
    assert ci_low == pytest.approx(mean_ic - critical * se)
    assert ci_high == pytest.approx(mean_ic + critical * se)
    # Assert: the interval excludes 0 exactly when the p-value is below 0.05
    assert (ci_low > 0 or ci_high < 0) == (p_value < 0.05)


def test_the_hac_standard_error_is_larger_when_daily_ics_are_correlated():
    # Arrange: daily ICs that are strongly correlated from one day to the next (overlapping labels do this)
    noise = np.random.default_rng(2).normal(size=400)
    # A 5-day moving average of the noise makes neighbouring days share most of their data
    ic = pd.Series(np.convolve(noise, np.ones(5) / 5, mode="valid"))
    # Act: the standard error with no lags and with 5 lags
    se_plain = hac_test(ic, 0)[1]
    se_hac = hac_test(ic, 5)[1]
    # Assert: allowing for the correlation widens the standard error
    assert se_hac > 1.3 * se_plain


def test_ic_summary_has_one_row_per_pair_with_all_the_columns():
    # Arrange: a panel with two features and two labels (the second label is the first plus noise)
    df = make_panel()
    df["feat2"] = -df["feat"]
    df["lab2"] = df["lab"] + np.random.default_rng(3).normal(size=len(df))
    df["fwd_end_time_2"] = df["close_time"] + pd.Timedelta(days=2)
    # Act: the summary and the daily ICs
    summary, ic_daily = ic_summary(df, ["feat", "feat2"], {"lab": 1, "lab2": 2})
    # Assert: 4 pairs, with the expected columns
    assert len(summary) == 4
    assert list(summary.columns) == ["days", "mean_ic", "std_ic", "se_hac", "ci_low", "ci_high", "t_stat_hac", "p_value"]
    # Assert: the daily IC table has one column per pair
    assert ic_daily.shape == (40, 4)
    # Assert: a feature and its negative have opposite mean ICs
    assert summary.loc[("feat", "lab"), "mean_ic"] == pytest.approx(-summary.loc[("feat2", "lab"), "mean_ic"])
    # Assert: the feature that drives the label has a clearly positive IC
    assert summary.loc[("feat", "lab"), "mean_ic"] > 0.1


def test_ic_by_block_uses_only_the_rows_inside_each_block_and_purges_their_end():
    # Arrange: 40 days cut into two blocks at day 20
    df = make_panel()
    blocks = {"first": (START, START + pd.Timedelta(days=20)), "second": (START + pd.Timedelta(days=20), START + pd.Timedelta(days=40))}
    # Act: the summary by block for a 1-day label
    summary = ic_by_block(df, blocks, ["feat"], {"lab": 1})
    # Assert: one row per block
    assert len(summary) == 2
    # Assert: each block loses its last day, because that label ends after the block ends
    assert summary.loc[("feat", "lab", "first"), "days"] == 19
    assert summary.loc[("feat", "lab", "second"), "days"] == 19


def test_quantile_buckets_are_cut_per_day_with_the_highest_feature_in_the_last_bucket():
    # Arrange: one day with 10 coins, the label equal to the feature (1 to 10)
    df = pd.DataFrame({"symbol": [f"C{i}" for i in range(10)], "feat": np.arange(1.0, 11.0), "lab": np.arange(1.0, 11.0)})
    df["open_time"] = START
    # Act: 5 buckets
    means = daily_quantile_stats(df, "feat", "lab", n_quantiles=5, min_symbols=10)
    # Assert: two coins per bucket, bucket 1 = coins 1 and 2, bucket 5 = coins 9 and 10
    assert list(means.iloc[0]) == [1.5, 3.5, 5.5, 7.5, 9.5]
    # Assert: the buckets are numbered 1 to 5
    assert list(means.columns) == [1, 2, 3, 4, 5]


def test_bucket_sizes_differ_by_at_most_one_coin():
    # Arrange: one day with 13 coins
    df = pd.DataFrame({"symbol": [f"C{i}" for i in range(13)], "feat": np.random.default_rng(4).normal(size=13)})
    df["open_time"] = START
    # Any label will do, because we only count the coins in each bucket
    df["lab"] = 1.0
    # Act: the number of coins in every bucket (the statistic "size" counts them)
    sizes = daily_quantile_stats(df, "feat", "lab", statistic="size", min_symbols=10).iloc[0]
    # Assert: all 13 coins are in a bucket and the sizes are 3, 3, 3, 2, 2 in some order
    assert sizes.sum() == 13
    assert sizes.max() - sizes.min() <= 1


def test_a_market_wide_move_on_one_day_does_not_change_the_difference_between_quantiles():
    # Arrange: a panel and the same panel with +0.5 added to every label on day 10
    df = make_panel()
    moved = df.copy()
    moved.loc[moved["day"] == 10, "lab"] += 0.5
    # Act: the average quantile table of both
    before = quantile_table(df, ["feat"], ["lab"])
    after = quantile_table(moved, ["feat"], ["lab"])
    # Assert: the levels shift by the same amount in every bucket, so the top-minus-bottom spread is unchanged
    assert (after.iloc[0, 4] - after.iloc[0, 0]) == pytest.approx(before.iloc[0, 4] - before.iloc[0, 0])
    assert (after.iloc[0] - before.iloc[0]).std() == pytest.approx(0, abs=1e-9)


def test_the_bucket_cut_does_not_depend_on_which_labels_are_missing():
    # Arrange: a panel and the same panel with one label missing on day 5
    df = make_panel(n_coins=10)
    missing = df.copy()
    missing.loc[(missing["day"] == 5) & (missing["symbol"] == "C0"), "lab"] = np.nan
    # Act: the daily bucket means of both
    full = daily_quantile_stats(df, "feat", "lab", min_symbols=10)
    partial = daily_quantile_stats(missing, "feat", "lab", min_symbols=10)
    # Assert: every other day is identical
    pd.testing.assert_frame_equal(full.drop(index=START + pd.Timedelta(days=5)), partial.drop(index=START + pd.Timedelta(days=5)))
    # Assert: on day 5 only the bucket of the coin without a label changes (the other buckets keep their coins)
    changed = (full.loc[START + pd.Timedelta(days=5)] != partial.loc[START + pd.Timedelta(days=5)]).sum()
    assert changed == 1


def test_the_median_ignores_one_extreme_coin_but_the_mean_does_not():
    # Arrange: one day with 15 coins (3 per bucket), the label equal to the feature, and one extreme label
    df = pd.DataFrame({"symbol": [f"C{i}" for i in range(15)], "feat": np.arange(1.0, 16.0), "lab": np.arange(1.0, 16.0)})
    df["open_time"] = START
    df.loc[df["symbol"] == "C14", "lab"] = 1000.0
    # Act: the mean and the median of bucket 5, which holds the coins with labels 13, 14 and 1000
    mean_5 = daily_quantile_stats(df, "feat", "lab", statistic="mean", min_symbols=10)[5].iloc[0]
    median_5 = daily_quantile_stats(df, "feat", "lab", statistic="median", min_symbols=10)[5].iloc[0]
    # Assert: the median is the middle coin, the mean is dragged far above it by the extreme coin
    assert median_5 == 14.0
    assert mean_5 == pytest.approx((13 + 14 + 1000) / 3)


def test_quantile_tables_are_in_percent_with_one_column_per_quantile():
    # Arrange: a panel with labels of size about 1
    df = make_panel()
    # Act: the table over days, and by block
    table = quantile_table(df, ["feat"], ["lab"])
    blocks = {"first": (START, START + pd.Timedelta(days=20)), "second": (START + pd.Timedelta(days=20), START + pd.Timedelta(days=40))}
    by_block = quantile_table_by_block(df, blocks, ["feat"], {"lab": 1})
    # Assert: five quantiles as columns
    assert list(table.columns) == [1, 2, 3, 4, 5]
    # Assert: in percent, so the value is 100 times the plain average of the daily bucket means
    assert table.iloc[0, 0] == pytest.approx(daily_quantile_stats(df, "feat", "lab").mean().iloc[0] * 100)
    # Assert: the lowest bucket has a lower label than the highest, because the label follows the feature
    assert table.iloc[0, 4] > table.iloc[0, 0]
    # Assert: the by-block table has one row per block with the right row levels
    assert list(by_block.index.names) == ["block", "feature", "label"]
    assert len(by_block) == 2


def test_the_row_order_of_the_input_does_not_matter():
    # Arrange: a panel and the same rows shuffled
    df = make_panel()
    shuffled = df.sample(frac=1, random_state=0)
    # Act: the IC summary and the quantile table of both
    summary, _ = ic_summary(df, ["feat"], {"lab": 1})
    summary_shuffled, _ = ic_summary(shuffled, ["feat"], {"lab": 1})
    # Assert: the same numbers
    pd.testing.assert_frame_equal(summary, summary_shuffled)
    pd.testing.assert_frame_equal(quantile_table(df, ["feat"], ["lab"]), quantile_table(shuffled, ["feat"], ["lab"]))

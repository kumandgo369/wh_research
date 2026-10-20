"""Data checks for the case-study files: look-ahead and split invariants measured in the audit.

Every check returns (passed, detail). Each one recomputes the thing in a second, independent way
and compares it with what is saved, so a bug in either side shows up. Run them all with
scripts/check_case_study_data.py. See docs/10-case_study_1_audit.md.
"""

# numpy does the maths on whole columns at once
import numpy as np
# pandas gives us tables (DataFrames)
import pandas as pd

# The window of days the liquidity median looks at
from wh_research.data.hyperliquid.daily_universe import MDV_WINDOW_DAYS


def check_universe_median(universe):
    """mdv_30d_prev must be the median of the 30 dollar volumes strictly before the bar.

    Recomputed by position (shift by one bar, then a 30-bar rolling median), which is independent of
    the 30-day time window used to build the file. Needs gap-free series, which the daily data has.
    """
    # Sort so every coin's bars are in time order
    u = universe.sort_values(["symbol", "open_time"])
    # The median of the 30 bars before each bar, by position within each coin
    expected = u.groupby("symbol")["dollar_volume"].transform(lambda s: s.shift(1).rolling(MDV_WINDOW_DAYS).median())
    # Rows that have a value in both versions must agree
    both = expected.notna() & u["mdv_30d_prev"].notna()
    mismatches = int((~np.isclose(expected[both], u.loc[both, "mdv_30d_prev"])).sum())
    # The two versions must also be missing in the same places
    different_gaps = int((expected.isna() != u["mdv_30d_prev"].isna()).sum())
    # Pass only if everything agrees
    return mismatches == 0 and different_gaps == 0, f"{int(both.sum())} rows compared, {mismatches} mismatches, {different_gaps} rows missing in only one version"


def check_universe_needs_history(universe):
    """A coin must never be flagged in_universe during its first 30 bars."""
    # The position of each bar within its coin, from 0
    position = universe.sort_values(["symbol", "open_time"]).groupby("symbol").cumcount()
    # Count the flagged bars among the first 30
    early = int((universe.sort_values(["symbol", "open_time"])["in_universe"] & (position < MDV_WINDOW_DAYS)).sum())
    # Pass if there are none
    return early == 0, f"{early} rows flagged in_universe on a coin's first {MDV_WINDOW_DAYS} bars"


def check_saved_columns(saved, universe, shift_days, column):
    """A saved past-return or forward-return column must match a recomputation from the full series.

    shift_days is negative for a past return (look back) and positive for a forward return.
    """
    # Every close of the full series, labelled by coin and bar start
    closes = universe.set_index(["symbol", "open_time"])["close"]
    # The bar to compare with: shift_days later (forward) or earlier (past) for the same coin
    other = pd.MultiIndex.from_arrays([saved["symbol"], saved["open_time"] + pd.Timedelta(days=shift_days)])
    other_close = closes.reindex(other).to_numpy()
    # A past return is log(this / earlier), a forward return is log(later / this)
    this_close = saved["close"].to_numpy()
    expected = np.log(this_close / other_close) if shift_days < 0 else np.log(other_close / this_close)
    # Compare, treating missing as equal to missing
    expected = pd.Series(expected, index=saved.index)
    same = np.isclose(expected, saved[column]) | (expected.isna() & saved[column].isna())
    # Pass if every row agrees
    return bool(same.all()), f"{column}: {len(saved)} rows compared, {int((~same).sum())} differ"


def check_split(pre_holdout, holdout, horizon):
    """The holdout split must have no overlap, only universe rows, and no label reaching into the holdout."""
    # The first day of the holdout
    holdout_start = holdout["open_time"].min()
    # Rows that appear in both sets
    overlap = pre_holdout.merge(holdout[["symbol", "open_time"]], on=["symbol", "open_time"]).shape[0]
    # Pre-holdout rows whose label ends at or after the holdout start
    reaching = int((pre_holdout[f"fwd_end_time_{horizon}"] >= holdout_start).sum())
    # Rows outside the universe in either set
    outside = int((~pre_holdout["in_universe"]).sum() + (~holdout["in_universe"]).sum())
    # Pass if all three are zero
    return overlap == 0 and reaching == 0 and outside == 0, f"{overlap} overlapping rows, {reaching} labels reaching into the holdout, {outside} rows outside the universe"

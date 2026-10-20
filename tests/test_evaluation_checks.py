# numpy makes the random prices and volumes
import numpy as np
# pandas gives us tables (DataFrames)
import pandas as pd

# The candle columns and the universe flag builder, to make a realistic table
from wh_research.data.hyperliquid.daily_universe import flag_daily_universe
# The labels and features the checks verify
from wh_research.data.hyperliquid.features import add_past_returns
from wh_research.data.hyperliquid.labels import add_forward_returns
# The functions we are testing
from wh_research.evaluation.checks import (
    check_saved_columns,
    check_split,
    check_universe_median,
    check_universe_needs_history,
)
# The split that builds the two sets
from wh_research.evaluation.splits import split_holdout

# Day 0 of the made-up data
START = pd.Timestamp("2024-01-01", tz="UTC")


def make_candles(n_days=80, coins=("A", "B", "C")):
    """Made-up daily candles with random prices and volumes, in the cleaned candle schema."""
    # A reproducible random number generator
    rng = np.random.default_rng(0)
    # One row per coin per day
    rows = [(coin, day) for coin in coins for day in range(n_days)]
    df = pd.DataFrame(rows, columns=["symbol", "day"])
    # The start and end of each daily bar
    df["open_time"] = START + pd.to_timedelta(df["day"], unit="D")
    df["close_time"] = df["open_time"] + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    # A random walk close, and a high and low around it
    df["close"] = 100 * np.exp(rng.normal(0, 0.02, len(df)).cumsum())
    df["high"] = df["close"] * 1.01
    df["low"] = df["close"] * 0.99
    # Random volumes
    df["volume"] = rng.uniform(1000, 5000, len(df))
    # Hand back the table
    return df.drop(columns="day")


def make_universe():
    # The universe flags with a low cutoff so most bars are in
    return flag_daily_universe(make_candles(), min_mdv_usd=1000)


def test_the_median_check_passes_on_a_correct_universe_and_fails_when_the_median_is_wrong():
    # Arrange: a correct universe
    universe = make_universe()
    # Assert: the check passes
    assert check_universe_median(universe)[0]
    # Arrange: break one median
    broken = universe.copy()
    broken.loc[broken["mdv_30d_prev"].notna().idxmax(), "mdv_30d_prev"] *= 2
    # Assert: the check fails
    assert not check_universe_median(broken)[0]


def test_the_history_check_fails_when_a_coin_is_flagged_in_its_first_bars():
    # Arrange: a correct universe, then flag the first bar of coin A
    universe = make_universe()
    assert check_universe_needs_history(universe)[0]
    broken = universe.copy()
    broken.loc[(broken["symbol"] == "A") & (broken["open_time"] == START), "in_universe"] = True
    # Assert: the check fails
    assert not check_universe_needs_history(broken)[0]


def test_the_saved_column_check_passes_on_real_columns_and_fails_on_a_shifted_one():
    # Arrange: labels and features added by the real functions
    universe = add_past_returns(add_forward_returns(make_universe(), "1d", [3]), "1d", [7])
    # Assert: both pass
    assert check_saved_columns(universe, universe, -7, "past_log_return_7")[0]
    assert check_saved_columns(universe, universe, 3, "fwd_log_return_3")[0]
    # Arrange: a look-ahead bug, the past return computed with the wrong sign of shift
    broken = universe.copy()
    broken["past_log_return_7"] = broken.groupby("symbol")["close"].transform(lambda s: np.log(s.shift(-7) / s))
    # Assert: the check catches it
    assert not check_saved_columns(broken, universe, -7, "past_log_return_7")[0]


def test_the_split_check_fails_on_overlap_and_on_labels_reaching_into_the_holdout():
    # Arrange: a correct split
    universe = add_forward_returns(make_universe(), "1d", [3])
    holdout_start = START + pd.Timedelta(days=60)
    pre, holdout = split_holdout(universe, holdout_start, horizon=3)
    # Assert: the check passes
    assert check_split(pre, holdout, 3)[0]
    # Arrange: a bad split that forgot the purge, using plain open_time
    unpurged = universe[(universe["in_universe"]) & (universe["open_time"] < holdout_start)]
    # Assert: the check catches the labels that reach into the holdout
    assert not check_split(unpurged, holdout, 3)[0]
    # Assert: and the check catches a row that is in both sets
    assert not check_split(pd.concat([pre, holdout.head(1)]), holdout, 3)[0]

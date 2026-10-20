# pandas gives us tables (DataFrames)
import pandas as pd

# The functions we are testing
from wh_research.evaluation.splits import block_rows, find_fold_starts, find_holdout_start, split_holdout

# Day 0 of the made-up data
START = pd.Timestamp("2024-01-01", tz="UTC")


def make_panel(n_days, coins=("A", "B"), in_universe=True):
    """One row per coin per day, with the columns the splits need and a 3-day label end time."""
    # One row per coin and day
    rows = [(coin, day) for coin in coins for day in range(n_days)]
    # Build the table
    df = pd.DataFrame(rows, columns=["symbol", "day"])
    # The start of each daily bar
    df["open_time"] = START + pd.to_timedelta(df["day"], unit="D")
    # A bar closes 1 ms before the next one opens, like the real data
    df["close_time"] = df["open_time"] + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    # The universe flag
    df["in_universe"] = in_universe
    # A 3-day label becomes known 3 bars after the close_time
    df["fwd_end_time_3"] = df["close_time"] + pd.Timedelta(days=3)
    # Hand back the table
    return df


def test_the_holdout_starts_at_the_train_fraction_of_the_universe_days():
    # Arrange: 10 days, all in the universe
    df = make_panel(10)
    # Act: find the holdout start with the default 70% train
    holdout_start = find_holdout_start(df)
    # Assert: 70% of 10 days is 7, so the holdout starts on day 7
    assert holdout_start == START + pd.Timedelta(days=7)


def test_days_with_no_coin_in_the_universe_do_not_count_for_the_holdout_start():
    # Arrange: 10 days in the universe, plus 10 earlier-looking days that are all outside it
    inside = make_panel(10)
    # Move the outside days 100 days earlier so they come first in time
    outside = make_panel(10, in_universe=False)
    outside["open_time"] = outside["open_time"] - pd.Timedelta(days=100)
    # Act: find the holdout start on the combined table
    holdout_start = find_holdout_start(pd.concat([inside, outside]))
    # Assert: the same answer as with the inside days alone
    assert holdout_start == START + pd.Timedelta(days=7)


def test_split_holdout_has_no_overlap_and_purges_labels_that_reach_into_the_holdout():
    # Arrange: 20 days, holdout starts on day 14
    df = make_panel(20)
    holdout_start = START + pd.Timedelta(days=14)
    # Act: split with a 3-day label
    pre, holdout = split_holdout(df, holdout_start, horizon=3)
    # Assert: every pre-holdout label ends before the holdout starts
    assert (pre["fwd_end_time_3"] < holdout_start).all()
    # Assert: the pre-holdout set ends 3 days before the holdout (days 0 to 10)
    assert pre["day"].max() == 10
    # Assert: the holdout starts exactly at the holdout start and runs to the end
    assert holdout["day"].min() == 14 and holdout["day"].max() == 19
    # Assert: the 3 purged days (11, 12, 13) are in neither set
    assert set(pre["day"]) & set(holdout["day"]) == set()
    assert not {11, 12, 13} & (set(pre["day"]) | set(holdout["day"]))


def test_split_holdout_keeps_only_universe_rows():
    # Arrange: coin A is in the universe, coin B never is
    df = make_panel(20)
    df.loc[df["symbol"] == "B", "in_universe"] = False
    # Act: split
    pre, holdout = split_holdout(df, START + pd.Timedelta(days=14), horizon=3)
    # Assert: only coin A is left in both sets
    assert set(pre["symbol"]) == {"A"} and set(holdout["symbol"]) == {"A"}


def test_split_holdout_keeps_rows_with_a_missing_label():
    # Arrange: a feature column and a label column with one missing label before the purge zone
    df = make_panel(20)
    df["fwd_log_return_3"] = 0.1
    df.loc[(df["symbol"] == "A") & (df["day"] == 5), "fwd_log_return_3"] = float("nan")
    # Act: split
    pre, _ = split_holdout(df, START + pd.Timedelta(days=14), horizon=3)
    # Assert: the row with the missing label is still there (the caller decides what to do with it)
    assert pre[(pre["symbol"] == "A") & (pre["day"] == 5)].shape[0] == 1


def test_block_rows_cut_by_date_and_purge_the_end_of_the_block():
    # Arrange: 20 days
    df = make_panel(20)
    # Act: the block from day 5 (included) to day 15 (not included), with a 3-day label
    block = block_rows(df, START + pd.Timedelta(days=5), START + pd.Timedelta(days=15), horizon=3)
    # Assert: it starts on day 5
    assert block["day"].min() == 5
    # Assert: it ends 3 days before the block end, so no label looks into the next block
    assert block["day"].max() == 11
    # Assert: every kept label ends before the block ends
    assert (block["fwd_end_time_3"] < START + pd.Timedelta(days=15)).all()


def test_neighbouring_blocks_do_not_overlap():
    # Arrange: 30 days cut into two blocks at day 15
    df = make_panel(30)
    cut = START + pd.Timedelta(days=15)
    # Act: the two blocks
    first = block_rows(df, START, cut, horizon=3)
    second = block_rows(df, cut, START + pd.Timedelta(days=30), horizon=3)
    # Assert: no row is in both blocks
    assert set(first["day"]) & set(second["day"]) == set()
    # Assert: the second block's last 3 days are purged too, because their labels end after the block end
    assert second["day"].max() == 26


def test_fold_starts_are_at_the_fractions_of_the_train_days():
    # Arrange: 20 days, the holdout starts on day 14 so there are 14 train days
    df = make_panel(20)
    holdout_start = START + pd.Timedelta(days=14)
    # Act: the fold starts with the default 40% and 70%
    first, second = find_fold_starts(df, holdout_start)
    # Assert: 40% of 14 days is day 5 (int of 5.6) and 70% is day 9 (int of 9.8)
    assert first == START + pd.Timedelta(days=5)
    assert second == START + pd.Timedelta(days=9)
    # Act: other fractions
    (half,) = find_fold_starts(df, holdout_start, fractions=(0.5,))
    # Assert: 50% of 14 days is day 7
    assert half == START + pd.Timedelta(days=7)

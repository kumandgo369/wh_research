"""Time splits for the research workflow: the holdout split and purged time blocks.

Works on a universe table that already has the forward-return labels (see labels.py and
docs/7-forward_returns.md): the columns symbol, open_time, in_universe and fwd_end_time_{n}.

Two rules keep the splits free of look-ahead:
- Splits are cut by DATE, never by row position (the files are sorted by symbol first).
- A row is only kept if its label is fully known before the period that must not see it
  starts or ends (fwd_end_time_{n}), so no label looks into the next period.

Example:
    df = add_forward_returns(df, "1d", [1, 3, 7])
    holdout_start = find_holdout_start(df)
    pre_holdout, holdout = split_holdout(df, holdout_start, horizon=7)
    fold1_eval_start, fold2_eval_start = find_fold_starts(df, holdout_start)
"""


def find_holdout_start(df, train_fraction=0.70):
    """The first day of the holdout: the day after the first train_fraction of the universe days.

    Only days with at least one coin in the universe count, as in 2_determining_cv_folds.
    """
    # Every day with at least one coin in the universe, oldest first
    days = df.loc[df["in_universe"], "open_time"].drop_duplicates().sort_values().reset_index(drop=True)
    # The day at the train_fraction mark is the first day of the holdout
    return days.iloc[int(len(days) * train_fraction)]


def find_fold_starts(df, holdout_start, fractions=(0.4, 0.7)):
    """The first day of each walk-forward evaluation period inside the train days.

    The train days are the universe days before holdout_start. With the default fractions, fold 1
    is evaluated from the day 40% into the train days and fold 2 from the day 70% into them, as
    decided in 2_determining_cv_folds. Returns a list with one start day per fraction.
    """
    # Every day with at least one coin in the universe, oldest first
    days = df.loc[df["in_universe"], "open_time"].drop_duplicates().sort_values().reset_index(drop=True)
    # The days before the holdout
    train_days = days[days < holdout_start]
    # The day at each fraction of the train days is where that evaluation period starts
    return [train_days.iloc[int(len(train_days) * fraction)] for fraction in fractions]


def split_holdout(df, holdout_start, horizon):
    """Split the universe rows into (pre_holdout, holdout).

    horizon is the longest label horizon in bars. A pre-holdout row is kept only if its label ends
    before the holdout starts. The last horizon days before the holdout are therefore in neither
    set. Rows that are not in the universe are dropped, and rows with a missing label are kept.
    """
    # Only the days a coin was tradeable
    members = df[df["in_universe"]]
    # The moment each row's longest label becomes known
    label_end = members[f"fwd_end_time_{horizon}"]
    # Pre-holdout: the label ends before the holdout starts
    pre_holdout = members[label_end < holdout_start]
    # Holdout: everything from the holdout start
    holdout = members[members["open_time"] >= holdout_start]
    # Hand back both sets
    return pre_holdout, holdout


def block_rows(df, start, end, horizon):
    """The rows of one time block: open_time from start (included) to end (not included).

    A row is kept only if its label (horizon bars ahead) ends before the block ends, so no label
    looks into the next block and the blocks stay independent.
    """
    # The rows that start inside the block
    in_block = (df["open_time"] >= start) & (df["open_time"] < end)
    # The rows whose label is fully known before the block ends
    label_known = df[f"fwd_end_time_{horizon}"] < end
    # Keep the rows that pass both
    return df[in_block & label_known]

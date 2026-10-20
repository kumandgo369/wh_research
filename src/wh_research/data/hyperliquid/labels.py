"""Forward log-return labels for the Hyperliquid candles (1d or 1h, raw or cleaned).

Works with the candle columns: symbol, open_time, close_time, close. Any other columns
(such as in_universe from the daily universe files) are passed through untouched.

For every bar the label looks n bars ahead of its close_time: the log-return from this bar's
close to the close of the bar n bars later. Looking ahead is what a label is, so these columns
must NEVER be used as features. See docs/7-forward_returns.md for how to use them without leaks.

Example:
    df = pd.read_parquet(DATA_DIR / "universe_1d_min_mdv_2m_exit_1m.parquet")
    df = add_forward_returns(df, "1d", [1, 3, 7])
    train = df[df["in_universe"]].dropna(subset=["fwd_log_return_7"])
"""

# numpy does the maths on whole columns at once
import numpy as np
# pandas gives us tables (DataFrames)
import pandas as pd

# BAR_MS says how long one bar lasts for each interval we support
from wh_research.data.hyperliquid.candles import BAR_MS


def add_forward_returns(df, interval, horizons):
    """Add forward log-return, direction and end-time columns for each horizon n (in bars).

    Returns a copy of df with the same rows, order and index, plus for each n:
        fwd_log_return_{n}  log(close n bars later / this close), NaN if that bar is missing
        fwd_direction_{n}   1.0 if the return is above 0, 0.0 if it is 0 or below, NaN if it is NaN
        fwd_end_time_{n}    close_time + n bars: the moment the label becomes known

    No rows are dropped and nothing is filled in, so the caller decides what to do with the NaNs
    (the last n bars of every coin never have a label).
    """
    # Stop early with a clear message if the interval is not one we support
    if interval not in BAR_MS:
        raise ValueError(f"interval must be one of {list(BAR_MS)}, got {interval!r}")
    # A single number is the same as a list with one number in it
    if np.ndim(horizons) == 0:
        horizons = [horizons]
    # Every horizon must be a whole number of bars above zero
    for n in horizons:
        if n != int(n) or n <= 0:
            raise ValueError(f"horizons must be whole numbers above 0, got {n}")
    # Looking bars up by (symbol, open_time) only works if each pair appears once
    if df.duplicated(["symbol", "open_time"]).any():
        raise ValueError("df has the same (symbol, open_time) more than once")

    # One bar's length as a time step
    bar = pd.Timedelta(milliseconds=BAR_MS[interval])
    # Every close, labelled by its coin and bar start time, so we can look a bar up by name
    closes = df.set_index(["symbol", "open_time"])["close"]
    # This bar's own close as plain numbers
    close = df["close"].to_numpy()
    # Work on a copy so the caller's table is untouched
    out = df.copy()

    # Do the same steps for each horizon
    for n in horizons:
        # The name of the bar that starts n bars after each bar, for the same coin
        later = pd.MultiIndex.from_arrays([df["symbol"], df["open_time"] + n * bar])
        # The close of that bar (NaN when the coin has no such bar, so we never use a different day)
        future_close = closes.reindex(later).to_numpy()
        # A return can only be worked out when both prices are above zero (this also leaves out NaN)
        valid = (close > 0) & (future_close > 0)
        # The price ratio, with NaN wherever the prices are not usable
        ratio = np.divide(future_close, close, out=np.full(len(df), np.nan), where=valid)
        # The log-return is the log of the ratio
        log_return = np.log(ratio)

        # The log-return n bars ahead
        out[f"fwd_log_return_{n}"] = log_return
        # Direction: 1 when up, 0 when flat or down, and NaN stays NaN (it must not become "down")
        out[f"fwd_direction_{n}"] = np.where(np.isnan(log_return), np.nan, (log_return > 0).astype(float))
        # The label uses prices up to the close of the bar n bars later, so it is known from that moment
        out[f"fwd_end_time_{n}"] = df["close_time"] + n * bar

    # Hand back the table with the new columns added
    return out

"""Past log-return features for the Hyperliquid candles (1d or 1h, raw or cleaned).

Works with the candle columns: symbol, open_time, close_time, close. Any other columns
(such as in_universe from the daily universe files) are passed through untouched.

For every bar the feature looks n bars back from its close_time: the log-return from the close
of the bar n bars earlier to this bar's close. It only uses data up to this bar's close_time, so it
is known at the same moment as the in_universe flag and can be used on the same row with no shift.
See docs/8-past_returns.md.

Example:
    df = pd.read_parquet(DATA_DIR / "universe_1d_min_mdv_2m_exit_1m.parquet")
    df = add_past_returns(df, "1d", [7], direction=True)
    train = df[df["in_universe"]].dropna(subset=["past_log_return_7"])
"""

# numpy does the maths on whole columns at once
import numpy as np
# pandas gives us tables (DataFrames)
import pandas as pd

# BAR_MS says how long one bar lasts for each interval we support
from wh_research.data.hyperliquid.candles import BAR_MS


def add_past_returns(df, interval, horizons, direction=False):
    """Add the past log-return (and optionally its direction) for each horizon n (in bars).

    Returns a copy of df with the same rows, order and index, plus for each n:
        past_log_return_{n}  log(this close / close n bars earlier), NaN if that bar is missing
        past_direction_{n}   only if direction=True: 1.0 if the return is above 0, 0.0 if it is 0 or
                             below, NaN if it is NaN

    No rows are dropped and nothing is filled in, so the caller decides what to do with the NaNs
    (the first n bars of every coin never have a feature).
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
        # The name of the bar that starts n bars before each bar, for the same coin
        earlier = pd.MultiIndex.from_arrays([df["symbol"], df["open_time"] - n * bar])
        # The close of that bar (NaN when the coin has no such bar, so we never use a different day)
        past_close = closes.reindex(earlier).to_numpy()
        # A return can only be worked out when both prices are above zero (this also leaves out NaN)
        valid = (close > 0) & (past_close > 0)
        # The price ratio, with NaN wherever the prices are not usable
        ratio = np.divide(close, past_close, out=np.full(len(df), np.nan), where=valid)
        # The log-return is the log of the ratio
        log_return = np.log(ratio)

        # The log-return over the last n bars
        out[f"past_log_return_{n}"] = log_return
        # Only add the direction if it was asked for
        if direction:
            # Direction: 1 when up, 0 when flat or down, and NaN stays NaN (it must not become "down")
            out[f"past_direction_{n}"] = np.where(np.isnan(log_return), np.nan, (log_return > 0).astype(float))

    # Hand back the table with the new columns added
    return out

# Past-return features

- **Code:** `src/wh_research/data/hyperliquid/features.py` (`add_past_returns(df, interval, horizons, direction=False)`)
- **Works on:** the candle schema (`symbol`, `open_time`, `close_time`, `close`): raw or cleaned `candles_1d` / `candles_1h`, or a universe file. Other columns pass through.

It is the backward-looking twin of `add_forward_returns` (see `7-forward_returns.md`).

    from wh_research.data.hyperliquid.features import add_past_returns

    DATA_DIR = Path("path/to/data/hyperliquid")    # change to where your data folder is
    df = pd.read_parquet(DATA_DIR / "universe_1d_min_mdv_2m_exit_1m.parquet")
    df = add_past_returns(df, "1d", [7], direction=True)
    train = df[df["in_universe"]].dropna(subset=["past_log_return_7"])

## What it adds

`horizons` are numbers of bars of the interval (`[24]` on `"1h"` means one day). For each horizon *n* the function returns a copy of the table, with the same rows, order and index, plus:

| Column | Meaning |
| ------ | ------- |
| `past_log_return_{n}` | `log(this bar's close / close of the bar n bars earlier)`. NaN when that earlier bar does not exist (the first *n* bars of every coin). |
| `past_direction_{n}` | Only with `direction=True`. `1.0` if the return is above 0, `0.0` if it is 0 or below, **NaN where the return is NaN** |

## Design decisions

- **Looked up by time, not by row.** The earlier close is found by `(symbol, open_time - n bars)`. A missing bar gives NaN, never a different day, coins never mix, and the row order of the input does not matter. A row shift (`shift(n)`) would silently use the wrong day wherever a coin has a gap. Duplicate `(symbol, open_time)` rows raise an error.
- **NaNs are kept, never dropped or filled.** Dropping inside the function would break the row alignment with the labels. Drop them yourself with `dropna(subset=[...])`.
- **The direction keeps NaN as NaN**, for the same reason as in the labels. It is off by default because a log-return already holds the sign; turn it on when you want a 0/1 feature.
- **Bad prices.** A close of 0 or below gives NaN instead of ±inf.

## Why it is safe as a feature

The value on a row uses only the close at that bar's `close_time` and the close *n* bars before it, so it is known at the same moment as the `in_universe` flag. Use it on the same row with no extra shift (`test_a_feature_depends_only_on_its_own_close_and_the_close_n_bars_earlier`). It matches the forward label from *n* bars earlier: `past_log_return_n` on day *t* equals `fwd_log_return_n` on day *t − n*, This is not a leak: the label of day *t − n* is fully known at day *t*'s close. (Purging is still needed for the labels at a train/evaluation boundary, see `7-forward_returns.md`.)

Compute features on the whole file first, then filter with `df[df["in_universe"]]`. Filtering first would leave holes in each coin's series and give NaN or a longer-than-intended window.

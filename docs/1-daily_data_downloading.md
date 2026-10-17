# Candle data: downloading

Hyperliquid `candles_snapshot`, intervals `1d` and `1h`, perps only. Hourly specifics are in `4-hourly_data.md`.

- **Code:** `src/wh_research/data/hyperliquid/candles.py`
- **Output:** `data/hyperliquid/candles_<interval>.parquet` (raw, gitignored)

## Schema

Key: `(symbol, open_time)`, sorted by symbol then time, no index. Same columns for every interval.

| Column                 | Type           | Notes                                                       |
| ---------------------- | -------------- | ----------------------------------------------------------- |
| symbol                 | str            | Perp name. A `k` prefix (kPEPE, kSHIB) means price per 1000 units |
| open_time              | datetime64 UTC | Bar start                                                   |
| close_time             | datetime64 UTC | `open_time + one bar - 1ms`                                 |
| open, high, low, close | float          |                                                             |
| volume                 | float          | Base asset units                                            |
| trades                 | int            | Trade count                                                 |

## Design choices

- **Closed bars only.** The forming bar is dropped.
- **Raw file kept faithful.** No filtering at download time. See `3-daily_data_cleaning.md`.
- **Delisted coins included**, to avoid survivorship bias. Their rows are never dropped.
- **Starts 2022-01-01**, earlier than any real trading.
- **History cap.** The API returns at most the 5000 most recent candles per symbol and interval. 1d covers over 13 years, 1h about 208 days, 1m about 3.5 days.
- **One file per interval.** The interval is a parameter (`"1d"` or `"1h"`), and `BAR_MS` in `candles.py` holds the bar lengths.

## Data quirks

- **Leading zero-volume bars.** Many symbols (BTC about 420, ALGO/XLM/ZEC about 1000 daily bars) have bars before real trading began, probably backfilled reference prices.
- **Invalid OHLC** on two of those daily bars: HPOS 2023-05-21 and UNIBOT 2023-06-23.
- **Rate limits.** The first full download triggers many 429s. The script backs off and retries.

## Not covered

Spot markets and HIP-3 perps. Intervals shorter than 1h (1m history lasts only about 3.5 days, so it needs a collector that runs continuously and probably a partitioned directory).

# Daily data: downloading

Hyperliquid `candles_snapshot`, interval `1d`, perps only.

- **Code:** `src/wh_research/data/hyperliquid/candles_1d.py`
- **Output:** `data/hyperliquid/candles_1d.parquet` (raw, tracked in git)

## Schema

Key: `(symbol, open_time)`, sorted by symbol then time, no index.

| Column                 | Type           | Notes                                                       |
| ---------------------- | -------------- | ----------------------------------------------------------- |
| symbol                 | str            | Perp name. A `k` prefix (kPEPE, kSHIB) means price per 1000 units |
| open_time              | datetime64 UTC | Bar start                                                   |
| close_time             | datetime64 UTC | `open_time + 1d - 1ms`                                      |
| open, high, low, close | float          |                                                             |
| volume                 | float          | Base asset units                                            |
| trades                 | int            | Trade count                                                 |

## Design choices

- **Closed bars only.** The forming bar is dropped.
- **Raw file kept faithful.** No filtering at download time. See `3-daily_data_cleaning.md`.
- **Delisted coins included**, to avoid survivorship bias. Their rows are never dropped.
- **Starts 2022-01-01**, earlier than any real trading.
- **History cap.** The API returns at most the 5000 most recent candles per symbol and interval. 1d covers over 13 years, 1h about 7 months, 1m about 3.5 days.

## Data quirks

- **Leading zero-volume bars.** Many symbols (BTC about 420, ALGO/XLM/ZEC about 1000) have bars before real trading began, probably backfilled reference prices.
- **Invalid OHLC** on two of those bars: HPOS 2023-05-21 and UNIBOT 2023-06-23.
- **Rate limits.** The first full download triggers many 429s. The script backs off and retries.

## Not covered

Spot markets and HIP-3 perps. Intraday history cannot be backfilled past the cap, so it needs a collector that runs continuously, as a separate module and a partitioned directory rather than this file.

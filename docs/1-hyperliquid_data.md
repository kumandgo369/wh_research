# Hyperliquid daily candle data

## Summary

- **Source:** Hyperliquid `candles_snapshot`, interval `1d`, perps only.
- **Code:** `src/wh_research/data/hyperliquid/candles_1d.py`
- **Runner:** `scripts/update_hyperliquid_candles_1d.py`
- **Output:** `data/hyperliquid/candles_1d.parquet`

## Usage

    uv sync
    uv run python scripts/update_hyperliquid_candles_1d.py

The same command performs the first download and every later update. If any
symbols fail with 429 after all retries, rerun it. Only missing symbols and
new bars are fetched.

## Schema

| Column                 | Type           | Notes                                                                         |
| ---------------------- | -------------- | ----------------------------------------------------------------------------- |
| symbol                 | str            | Hyperliquid perp name. `k` prefix (kPEPE, kSHIB) means price per 1000 units |
| open_time              | datetime64 UTC | Bar start                                                                     |
| close_time             | datetime64 UTC | `open_time + 1d - 1ms`                                                      |
| open, high, low, close | float          |                                                                               |
| volume                 | float          | Base asset units                                                              |
| trades                 | int            | Trade count                                                                   |

Key: `(symbol, open_time)`, sorted by symbol then time. The file stores no index.

## Design decisions

- **Closed bars only.** The forming bar is dropped so updates never patch a partial row.
- **Raw file kept faithful.** No filtering at download time, so the file always matches what the API returned.
- **Delisted coins included.** The API serves their history, which avoids survivorship bias. Rows for coins delisted later are never dropped from disk.
- **Start date 2022-01-01.** Earlier than any real trading, so nothing is truncated. See the zero-volume note below.
- **Single file, full rewrite.** About 190k rows, so a rewrite takes under a second. Writes go to `.tmp` and are swapped in atomically.
- **Interval hardcoded.** File name, function names and `INTERVAL` all say 1d, so intraday data cannot be written into this file by mistake.

## Data quirks

- **Leading zero-volume bars.** Many symbols, including BTC and ETH, have bars before real trading began (roughly 420 for BTC). Coins like ALGO, XLM and ZEC have around 1000 such bars. These look like backfilled reference prices, source unconfirmed.
- **Universe leakage risk.** Building a universe from "a row exists" includes coins long before they were tradable. Use first traded date instead.
- **Invalid OHLC on zero-volume bars.** HPOS (2023-05-21) and UNIBOT (2023-06-23) violate high/low consistency. Both vanish under `volume > 0`.
- **Rate limits.** The full first download triggers many 429s. Daily updates fetch one or two bars per symbol and rarely do.

## Using the data in research

- **Filter at load time.** Define `first_traded` per symbol as the first bar with `volume > 0` and drop earlier bars when loading. A `load_candles()` function in the same package should own this. Not yet implemented.
- **Look-ahead.** A bar is only known at its close. In ASOF joins use `close_time` as the left key, never `open_time`.
- **Join key.** Keep `symbol` as the key across datasets. Funding data calls it `coin`, so rename on ingest.
- **Units.** Convert all datetimes to the same dtype and unit before `merge_asof`.

## Limits and extension

- **History cap.** The API returns at most the 5000 most recent candles per symbol and interval. 1d covers over 13 years. 1h covers about 7 months. 1m covers about 3.5 days.
- **Intraday.** History cannot be backfilled past the cap, so it needs a collector that runs continuously. Treat it as a separate module (for example `candles_1m.py`) reusing the column schema. At that size, switch from one file to a partitioned directory (for example symbol and month) so an update writes only the newest partition.
- **Not covered.** Spot markets (`spot_meta`, names like `PURR/USDC` and `@107`) and HIP-3 perps. If added, name files `perp_` and `spot_` to keep them apart.
- **Polars.** Pandas is used in four places (`DataFrame`, `to_datetime`, `concat`, `read_parquet`), so a migration is a small edit.

## TODO

- [ ] `load_candles()` with the `first_traded` filter
- [ ] Funding rate downloader and ASOF join helper
- [ ] Intraday collector

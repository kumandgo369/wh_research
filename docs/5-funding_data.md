# Funding rate data

Hyperliquid `funding_history` for every perp (delisted coins included).

- **Code:** `src/wh_research/data/hyperliquid/funding.py`
- **Output:** `data/hyperliquid/funding.parquet` (raw, gitignored)
- **Command:** `uv run python scripts/update_hyperliquid_funding.py` (first download and every later update)

## Schema

Key: `(symbol, time)`, sorted by symbol then time, no index.

| Column       | Type           | Notes                                              |
| ------------ | -------------- | -------------------------------------------------- |
| symbol       | str            | The API calls it `coin`; renamed to match the candles |
| time         | datetime64 UTC | Microsecond precision, the same type as the candles' `open_time` |
| funding_rate | float          | Funding rate of that row                           |
| premium      | float          | Premium used for that row                          |

## How it is downloaded

- **Paged.** One call returns at most 500 rows, oldest first. The code asks again from `last time + 1 ms` until a page has fewer than 500 rows.
- **Full history.** History starts on 2023-05-12 (BTC) and there is no 5000-row cap like the candles have. The file can always be downloaded again from scratch, so it needs no backup.
- **Cost.** The first download (2026-10-17) was 4,820,977 rows for 234 symbols (61 MB) and took about 2.5 hours (238 rate-limit retries, no failed symbol). Later updates take about one call per active coin, a few minutes. Growth is about 1.6M rows a year.
- **Same rules as the candles.** Incremental update with a full rewrite via `.tmp`. A symbol is saved only after all its pages arrived, so a failed or interrupted symbol is absent and a rerun fetches it. Delisted coins are asked again on every run, so one delisted since the last update still gets its final rows (see "After delisting" below for what comes back).
- **Progress.** It prints `checking N symbols`, a progress line every 25 symbols, and `SYMBOL: +N` per coin. Funding has no skip like the candles do, so even a second run makes about one request per active coin (a few minutes).
- **Raw.** There is no cleaning step for funding yet.

## Data quirks

- **Empty premiums.** 4,427 rows (9 symbols: STRAX 2,602, FRIEND 1,443, and a few dozen each for NFTI, OX, PANDORA, SHIA, UNIBOT and others) have `premium` = NaN. The API itself returns the text `NaN` there, together with a `funding_rate` of exactly `0.0`; they fall between 2024-03 and 2024-07. The raw file keeps them as they are. `funding_rate` has no empty values.
- **After delisting.** The API keeps returning hourly rows after a coin's last candle, almost all with `funding_rate` exactly 0. At the audit (2026-10-18) that was 608,495 rows (12.6% of the file) for the 56 delisted coins, only 126 of them non-zero. They do no harm in the candle join (there are no candles after delisting), but drop them for funding-only analysis:

      last = candles_1d.groupby("symbol")["close_time"].max()
      funding = funding[funding["time"] <= funding["symbol"].map(last)]

  Because delisted coins are asked again on every run, these placeholder rows keep growing by about 24 rows a day per delisted coin (about 0.5M rows a year).
- **Exchange-wide gaps.** On 2023-05-23 all 21 coins that existed then jump 8h23m between two rows. A few dates are missing single hours (141 rows on 2024-08-15, 44 on 2023-08-23, 28 on 2023-07-02). These are in the API's data, not a download problem.

## Timestamps

Funding times are not on the exact hour: they carry a few milliseconds of offset, for example `00:00:00.048` or `10:00:00.201`. A candle's `open_time` is exactly on the hour, so the two never match on equality. Early rows are 8 hours apart (`00:00`, `08:00`, `16:00`) and later ones are hourly.

Hyperliquid's funding docs say funding is paid every hour and the premium is averaged over the hour, but they do not say whether a timestamp means the hour ending or the hour starting at that time. No rounded `hour` column is stored, because it would hide that guess.

## Joining to candles

Take, for each candle, the latest funding row at or before its close. This never uses a funding row from after the candle closed, whichever way the timestamp is meant:

    joined = pd.merge_asof(
        candles.sort_values("close_time"),
        funding.sort_values("time"),
        left_on="close_time", right_on="time",
        by="symbol", direction="backward",
    )

Both time columns must have the same dtype (they do: `datetime64[us, UTC]`).

## TODO

- [ ] Cleaning flags for funding (for example gaps between rows)

# Tests

    uv run pytest                                              # everything
    uv run pytest tests/test_candles.py                        # one file
    uv run pytest tests/test_candles.py::test_second_run_fetches_only_new_bars_and_skips_delisted   # one test

All tests run offline and in about a second. Nothing touches the network or your real data files (file tests use pytest's `tmp_path`).

Tests marked "both intervals" use `@pytest.mark.parametrize("interval", INTERVALS)`, where `INTERVALS = list(BAR_MS)`, so they run once for `1d` and once for `1h`. A newly supported interval is picked up automatically.

## `tests/test_candles.py` — the downloader

| Test | Checks |
| ---- | ------ |
| `test_candles_filename_contains_the_interval` | `candles_1d.parquet` and `candles_1h.parquet` |
| `test_to_dataframe_renames_columns_and_converts_types` (both intervals) | API keys become our column names, prices become floats, times become UTC |
| `test_to_dataframe_drops_bar_that_has_not_closed` (both intervals) | A bar still forming is dropped |
| `test_to_dataframe_with_no_data_returns_empty_table` | No API data gives an empty table with the right columns |
| `test_retry_succeeds_after_two_429s_and_waits_longer_each_time` | Retries after "too many requests", waiting 5s then 10s |
| `test_retry_does_not_retry_other_errors` | Any other error is raised straight away |
| `test_retry_gives_up_after_max_attempts` | Gives up after `MAX_ATTEMPTS` rate-limit errors |
| `test_first_missing_bar_for_new_symbol_is_the_global_start` | A new symbol starts from `START_TIME_MS` |
| `test_first_missing_bar_for_saved_symbol_is_the_next_bar` (both intervals) | A saved symbol continues from its last bar + one bar |
| `test_first_run_saves_every_symbol_sorted` (both intervals) | First run saves all symbols into the interval's file, sorted by symbol then time |
| `test_second_run_fetches_only_new_bars_and_skips_delisted` (both intervals) | Update asks only for new bars, never re-fetches a saved delisted coin, and creates no duplicates |
| `test_failed_symbol_is_left_out_and_fetched_on_the_next_run` | A failing symbol is not saved, and a rerun fills it in |
| `test_unsupported_interval_is_rejected` | An interval like `5m` raises a clear error before any request |

## `tests/test_clean_candles.py` — the cleaning

| Test | Checks |
| ---- | ------ |
| `test_drops_pre_trading_bars_but_keeps_mid_series_zero_volume` | Only bars before the first trade are removed |
| `test_each_validity_rule` | Each OHLCV rule flags its bad row, and no row is dropped |
| `test_stale_needs_more_than_three_equal_closes` | 3 equal closes are fine, 4 are stale |
| `test_stale_run_does_not_cross_symbols` | A flat price at the end of one coin does not carry into the next |
| `test_after_gap_flags_first_bar_after_missing_bars` (both intervals) | Only the bar right after a missing bar is flagged, and the first bar of a coin never is |
| `test_gap_check_uses_the_interval_length` | Bars 2 hours apart are a gap for `1h` but not for `1d` |
| `test_update_candles_cleaned_writes_file` (both intervals) | The cleaned parquet is written with the flag columns, named after the interval |

## How the downloader tests avoid the network

- `FakeInfo` replaces the Hyperliquid `Info` class. It has coin A (active) and coin B (delisted), each with `bars_available` bars from 2024-01-01 (the bar length follows the interval the code asks for), and it records every request in `calls`. Set `broken_symbols` to make a coin fail.
- `RateLimitedInfo(failures=n)` raises a 429 error `n` times, then answers.
- The `fake_info` fixture swaps `candles.Info` for `FakeInfo`.
- The `sleeps` fixture (applied to every test) replaces `time.sleep`, so retries are instant, and records the waits so tests can check them.
- The 2024 test dates are in the past, so every fake bar counts as closed.

## Adding a test

- Reuse `api_bar(symbol, bar_number, interval)` to build fake API candles.
- To test a new download behaviour, change `FakeInfo` (more bars, a broken symbol), run `update_candles(tmp_path, interval)`, then read the file with `read_saved(tmp_path, interval)`.
- If the behaviour depends on the bar length, add the `INTERVALS` parametrize line.
- Name the test after the behaviour it proves, one behaviour per test.

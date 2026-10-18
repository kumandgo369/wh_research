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
| `test_first_missing_bar_for_new_symbol_is_5000_bars_before_now` (both intervals) | A new symbol starts `MAX_BARS` bars before "now" |
| `test_first_missing_bar_for_saved_symbol_is_the_next_bar` (both intervals) | A saved symbol continues from its last bar + one bar |
| `test_first_run_saves_every_symbol_sorted` (both intervals) | First run saves all symbols into the interval's file, sorted by symbol then time, starting `MAX_BARS` bars before "now" |
| `test_second_run_fetches_only_new_bars_and_skips_delisted` (both intervals) | Update asks only for new bars, never re-fetches a saved delisted coin, and creates no duplicates |
| `test_failed_symbol_is_left_out_and_fetched_on_the_next_run` | A failing symbol is not saved, and a rerun fills it in |
| `test_update_makes_no_requests_when_everything_is_up_to_date` (both intervals) | A second run right after the newest bar closed asks for nothing and changes nothing |
| `test_update_prints_progress` | The update prints how many symbols it checks and how far it got |
| `test_unsupported_interval_is_rejected` | An interval like `5m` raises a clear error before any request |

## `tests/test_funding.py` — the funding downloader

| Test | Checks |
| ---- | ------ |
| `test_to_dataframe_renames_columns_and_converts_types` | `coin` becomes `symbol`, rates become floats, `time` is `datetime64[us, UTC]` like the candles, the ms offset is kept |
| `test_to_dataframe_with_no_data_returns_empty_table` | No API data gives an empty table with the right columns |
| `test_funding_can_be_joined_to_candles_with_merge_asof` | A candle gets the latest funding row at or before its close, with no dtype error |
| `test_download_funding_collects_every_page` | 7 rows over pages of 3 all arrive once, in order, and page 2 starts 1 ms after page 1's last row |
| `test_download_funding_needs_one_extra_request_when_the_last_page_is_full` | 6 rows over pages of 3 need a third, empty request |
| `test_download_funding_with_no_rows_returns_empty_table` | Nothing to download gives an empty table |
| `test_first_missing_time_for_new_symbol_is_the_global_start` | A new symbol starts from `START_TIME_MS` |
| `test_first_missing_time_for_saved_symbol_is_one_millisecond_later` | A saved symbol continues 1 ms after its last row |
| `test_first_run_saves_every_symbol_sorted` | First run saves all symbols, sorted by symbol then time |
| `test_second_run_fetches_only_new_rows_and_skips_delisted` | Update asks only for new rows, never re-fetches a saved delisted coin, and creates no duplicates |
| `test_failed_symbol_is_left_out_and_fetched_on_the_next_run` | A failing symbol is not saved, and a rerun fills it in |
| `test_update_prints_progress` | The update prints how many symbols it checks and how far it got |

## `tests/test_api_helpers.py` — shared retry and save helpers

| Test | Checks |
| ---- | ------ |
| `test_call_with_retry_returns_the_answer_when_nothing_fails` | The answer comes back after one call |
| `test_call_with_retry_waits_longer_after_each_429` | Waits 5s, then 10s, then succeeds |
| `test_call_with_retry_caps_the_wait_at_60_seconds` | Waits double (5, 10, 20, 40) and then stay at 60 |
| `test_call_with_retry_raises_other_errors_at_once` | A non-429 error is raised with no retry and no waiting |
| `test_call_with_retry_gives_up_after_max_attempts` | Gives up after `MAX_ATTEMPTS` rate-limit errors |
| `test_save_table_sorts_removes_duplicates_and_leaves_no_tmp_file` | Sorted by key, newer duplicate kept, folder created, no `.tmp` left |

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

## `tests/test_daily_universe.py` — the daily universe files

Daily only. The tests build flat bars (open = high = low = close = 1) so dollar volume equals volume.

| Test | Checks |
| ---- | ------ |
| `test_first_row_is_the_31st_bar_of_a_coin` | 30 bars of history are needed, so a coin first appears on its 31st bar |
| `test_a_spike_on_day_t_cannot_make_day_t_eligible` | The day the median reaches the cutoff is not kept; the next day is |
| `test_the_median_ignores_one_huge_day` | One enormous day does not lift a coin into the universe |
| `test_cutoff_is_inclusive` | A median exactly at the cutoff is kept, just below it is not |
| `test_a_missing_bar_blocks_eligibility_until_the_window_is_full_again` | A gap blocks the bar after it and every bar whose 30-day window contains it |
| `test_symbols_do_not_mix` | A liquid coin does not lift an illiquid one |
| `test_dollar_volume_uses_the_typical_price` | Dollar volume is volume times (high + low + close) / 3 |
| `test_same_day_median_column_is_not_in_the_result` | Only `adv_30d_prev` is returned, not the same-day median |
| `test_no_look_ahead_in_the_universe` | Rows up to a cut date are identical with or without the later data, even if later volumes are multiplied by 1000 |
| `test_filename_uses_m_for_millions_and_k_for_thousands` | `2m`, `500k`, `2500k` and the plain number |
| `test_filename_rejects_bad_cutoffs` | Zero, negative and fractional cutoffs raise an error |
| `test_each_cutoff_gets_its_own_file_and_a_rerun_leaves_others_alone` | Two cutoffs write two files, no `.tmp` is left, and rerunning one does not touch the other |
| `test_update_prints_a_summary` | The printed summary has the rows, latest-day symbols and symbols ever included |

## How the downloader tests avoid the network

(`test_funding.py` works the same way: its `FakeInfo` has `funding_history`, hourly rows from 2024-01-01 with a 48 ms offset, and `PAGE_SIZE` is patched to 3 so paging is tested with tiny data.)

- `FakeInfo` replaces the Hyperliquid `Info` class. It has coin A (active) and coin B (delisted), each with `bars_available` bars from 2024-01-01 (the bar length follows the interval the code asks for), and it records every request in `calls`. Set `broken_symbols` to make a coin fail.
- `RateLimitedInfo(failures=n)` raises a 429 error `n` times, then answers.
- The `fake_info` fixture swaps `candles.Info` for `FakeInfo`.
- The `sleeps` fixture (applied to every test) replaces `time.sleep`, so retries are instant, and records the waits so tests can check them.
- The `fake_info` fixture also freezes `time.time` at `NOW_MS`, 30 days after the fake data starts, so every fake bar counts as closed and "5000 bars before now" is predictable.

## Adding a test

- Reuse `api_bar(symbol, bar_number, interval)` to build fake API candles.
- To test a new download behaviour, change `FakeInfo` (more bars, a broken symbol), run `update_candles(tmp_path, interval)`, then read the file with `read_saved(tmp_path, interval)`.
- If the behaviour depends on the bar length, add the `INTERVALS` parametrize line.
- Name the test after the behaviour it proves, one behaviour per test.

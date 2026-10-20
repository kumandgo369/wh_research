# Tests

    uv run pytest                                              # everything
    uv run pytest tests/test_candles.py                        # one file
    uv run pytest tests/test_candles.py::test_second_run_fetches_new_bars_for_every_coin_including_delisted   # one test

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
| `test_second_run_fetches_new_bars_for_every_coin_including_delisted` (both intervals) | Update asks only for new bars, but for every coin including delisted ones (one may have been delisted since the last run), and creates no duplicates |
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
| `test_second_run_fetches_new_rows_for_every_coin_including_delisted` | Update asks only for new rows, but for every coin including delisted ones, and creates no duplicates |
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
| `test_stale_needs_more_than_three_equal_closes` | 3 equal closes are fine; from the 4th equal close on a bar is stale |
| `test_a_bar_is_never_stale_because_of_later_bars` | A bar gets the same flag whether or not later bars exist (no look-ahead) |
| `test_stale_run_does_not_cross_symbols` | A flat price at the end of one coin does not carry into the next |
| `test_after_gap_flags_first_bar_after_missing_bars` (both intervals) | Only the bar right after a missing bar is flagged, and the first bar of a coin never is |
| `test_gap_check_uses_the_interval_length` | Bars 2 hours apart are a gap for `1h` but not for `1d` |
| `test_update_candles_cleaned_writes_file` (both intervals) | The cleaned parquet is written with the flag columns, named after the interval |

## `tests/test_daily_universe.py` — the daily universe files

Daily only. The tests build flat bars (open = high = low = close = 1) so dollar volume equals volume. Most tests look at the rows flagged `in_universe` (the helper `in_universe_rows`); "kept" below means flagged in.

| Test | Checks |
| ---- | ------ |
| `test_first_row_is_the_31st_bar_of_a_coin` | 30 bars of history are needed, so a coin first appears on its 31st bar |
| `test_a_spike_on_day_t_cannot_make_day_t_eligible` | The day the median reaches the cutoff is not kept; the next day is |
| `test_the_median_ignores_one_huge_day` | One enormous day does not lift a coin into the universe |
| `test_cutoff_is_inclusive` | A median exactly at the cutoff is kept, just below it is not |
| `test_a_missing_bar_blocks_eligibility_until_the_window_is_full_again` | A gap blocks the bar after it and every bar whose 30-day window contains it |
| `test_symbols_do_not_mix` | A liquid coin does not lift an illiquid one |
| `test_dollar_volume_uses_the_typical_price` | Dollar volume is volume times (high + low + close) / 3 |
| `test_same_day_median_column_is_not_in_the_result` | Only `mdv_30d_prev` is returned, not the same-day median |
| `test_every_input_row_is_kept_and_the_series_stay_gap_free` | No row is dropped and each coin keeps one row per day |
| `test_in_universe_is_a_true_false_column_and_false_for_the_first_30_bars` | The flag is a bool column, False for a coin's first 30 bars |
| `test_universe_size_counts_the_coins_in_the_universe_on_each_day` | Counts the distinct coins flagged `in_universe` on each day |
| `test_no_look_ahead_in_the_universe` | The panel (flags and medians) up to a cut date is identical with or without the later data, even if later volumes are multiplied by 1000 |
| `test_filename_uses_m_for_millions_and_k_for_thousands` | `2m`, `500k`, `2500k` and the plain number |
| `test_filename_rejects_bad_cutoffs` | Zero, negative and fractional cutoffs raise an error |
| `test_each_cutoff_gets_its_own_file_and_a_rerun_leaves_others_alone` | Two cutoffs write two files with all rows and different flags, no `.tmp` is left, and rerunning one does not touch the other |
| `test_update_prints_a_summary` | The printed summary has the rows saved, symbols in the universe on the latest day and symbols ever in it |
| `test_a_coin_that_is_in_stays_in_between_the_exit_and_entry_levels` | With an exit level a joined coin is kept while its median is between the levels; a single cutoff drops it |
| `test_a_coin_between_the_levels_does_not_enter` | A coin that never reached the entry level is not kept, even above the exit level |
| `test_a_coin_leaves_below_the_exit_level_and_needs_the_entry_level_to_return` | Leaves when the median falls below the exit level, stays out in between, returns only at the entry level |
| `test_exit_level_equal_to_entry_level_gives_the_single_cutoff_result` | Exit equal to entry gives exactly the single-cutoff rows |
| `test_a_missing_bar_resets_a_coin_even_with_an_exit_level` | A gap still blocks the coin until its window is full again |
| `test_exit_level_state_does_not_carry_from_one_symbol_to_the_next` | A coin that is in does not make the next coin in |
| `test_bad_exit_levels_are_rejected` | Exit above entry, zero or negative raises an error |
| `test_no_look_ahead_with_an_exit_level` | The same check with an exit level |
| `test_filename_gets_an_exit_part_only_when_the_exit_level_is_lower` | `..._2m_exit_1m`, and no suffix for an equal or missing exit level |
| `test_entry_exit_file_sits_next_to_the_single_cutoff_file` | Both files exist side by side, and rerunning one leaves the other untouched |

## `tests/test_labels.py` — the forward-return labels

The tests build tiny candle tables (only `symbol`, `bar`, `close` plus the times) with known prices, so every label can be worked out by hand.

| Test | Checks |
| ---- | ------ |
| `test_forward_log_return_is_the_log_of_the_close_n_bars_later_over_this_close` | Closes that double give `log 2` one bar ahead and `log 4` two bars ahead, NaN at the end |
| `test_direction_is_1_for_up_and_0_for_flat_or_down_and_nan_stays_nan` | Up = 1, flat = 0, down = 0, and a missing label is NaN, not 0 |
| `test_the_last_n_bars_of_each_coin_have_no_label` | Exactly *n* missing returns and directions per coin |
| `test_no_rows_are_dropped_and_the_input_is_not_changed` | Same rows, order, index and extra columns (like `in_universe`); the input table is untouched |
| `test_coins_do_not_mix` | A coin's last bar does not borrow the next coin's first bar |
| `test_a_missing_target_bar_gives_nan_and_a_missing_bar_in_between_does_not_matter` | A gap gives NaN where the target is missing, but a correct label when only a bar in between is missing (a row shift would get this wrong) |
| `test_the_row_order_of_the_input_does_not_matter` | A shuffled table gets the same labels and keeps its own order |
| `test_end_time_is_the_close_time_of_the_bar_the_label_uses` | `fwd_end_time_{n}` is the target bar's `close_time`, and `close_time + n bars` even without a label |
| `test_hourly_bars_use_hours_as_the_unit` | On `"1h"`, *n* = 24 looks 24 hours ahead |
| `test_several_horizons_and_a_single_number_both_work` | Three columns per horizon, and `3` gives the same as `[3]` |
| `test_a_label_depends_only_on_its_own_close_and_the_close_n_bars_later` | Changing the bars in between or after leaves the label unchanged; changing the target bar moves it |
| `test_bad_prices_give_nan_not_infinity` | A zero close gives NaN, never infinity |
| `test_bad_input_is_rejected` | Unsupported interval, zero, negative or fractional horizons, and duplicate bars raise an error |

## `tests/test_features.py` — the past-return features

Same tiny candle tables as the label tests, so every feature can be worked out by hand.

| Test | Checks |
| ---- | ------ |
| `test_past_log_return_is_the_log_of_this_close_over_the_close_n_bars_earlier` | Closes that double give `log 2` one bar back and `log 4` two bars back, NaN at the start |
| `test_direction_columns_only_exist_when_asked_for` | No `past_direction_{n}` unless `direction=True` |
| `test_direction_is_1_for_up_and_0_for_flat_or_down_and_nan_stays_nan` | Up = 1, flat = 0, down = 0, and a missing feature is NaN, not 0 |
| `test_the_first_n_bars_of_each_coin_have_no_feature` | Exactly *n* missing returns and directions per coin |
| `test_no_rows_are_dropped_and_the_input_is_not_changed` | Same rows, order, index and extra columns (like `in_universe`); the input table is untouched |
| `test_coins_do_not_mix` | A coin's first bar does not borrow the previous coin's last bar |
| `test_a_missing_source_bar_gives_nan_and_a_missing_bar_in_between_does_not_matter` | A gap gives NaN where the earlier bar is missing, but a correct value when only a bar in between is missing (a row shift would get this wrong) |
| `test_the_row_order_of_the_input_does_not_matter` | A shuffled table gets the same features and keeps its own order |
| `test_hourly_bars_use_hours_as_the_unit` | On `"1h"`, *n* = 24 looks 24 hours back |
| `test_several_horizons_and_a_single_number_both_work` | A column per horizon, and `3` gives the same as `[3]` |
| `test_a_feature_depends_only_on_its_own_close_and_the_close_n_bars_earlier` | Changing the bars in between or after (the future) leaves the feature unchanged; changing the earlier bar moves it |
| `test_bad_prices_give_nan_not_infinity` | A zero close gives NaN, never infinity |
| `test_bad_input_is_rejected` | Unsupported interval, zero, negative or fractional horizons, and duplicate bars raise an error |

## `tests/test_evaluation_splits.py` — holdout split and time blocks

Tiny panels of coins and days with a 3-day label end time (`fwd_end_time_3`), so every kept and purged row can be counted by hand.

| Test | Checks |
| ---- | ------ |
| `test_the_holdout_starts_at_the_train_fraction_of_the_universe_days` | 10 days, 70% train: the holdout starts on day 7 |
| `test_days_with_no_coin_in_the_universe_do_not_count_for_the_holdout_start` | Days with nothing in the universe are ignored |
| `test_split_holdout_has_no_overlap_and_purges_labels_that_reach_into_the_holdout` | Every pre-holdout label ends before the holdout starts; the 3 days in between are in neither set |
| `test_split_holdout_keeps_only_universe_rows` | Rows outside the universe are dropped |
| `test_split_holdout_keeps_rows_with_a_missing_label` | A missing label is kept (the caller decides) |
| `test_block_rows_cut_by_date_and_purge_the_end_of_the_block` | A block starts at its start and loses the last 3 days, whose labels end after it |
| `test_neighbouring_blocks_do_not_overlap` | No row is in two blocks |
| `test_fold_starts_are_at_the_fractions_of_the_train_days` | 40% and 70% of 14 train days give days 5 and 9; other fractions work |

## `tests/test_evaluation_ic.py` — IC, HAC test and quantiles

A made-up panel (40 days, 12 coins) where the label follows the feature a little, plus hand-made single days.

| Test | Checks |
| ---- | ------ |
| `test_the_daily_ic_is_the_spearman_correlation_across_the_coins_of_that_day` | A day's IC equals `scipy.stats.spearmanr` on that day's rows |
| `test_days_with_too_few_coins_are_skipped` | Days under `min_symbols` coins give no IC |
| `test_the_coin_count_ignores_missing_labels_because_those_depend_on_the_future` | A day with 10 coins that have the feature stays, even if one coin has no label |
| `test_the_hac_test_gives_the_mean_a_standard_error_and_a_matching_confidence_interval` | Mean, t = mean / se, CI = mean ± t critical × se, the CI excludes 0 exactly when p < 0.05, and 0 lags is close to a plain t-test |
| `test_the_hac_standard_error_is_larger_when_daily_ics_are_correlated` | With overlapping (autocorrelated) ICs the HAC standard error is wider than the plain one |
| `test_ic_summary_has_one_row_per_pair_with_all_the_columns` | One row per feature-label pair with the 8 columns, daily IC table shape, a negated feature has the opposite IC |
| `test_ic_by_block_uses_only_the_rows_inside_each_block_and_purges_their_end` | Each block loses its last day for a 1-day label |
| `test_quantile_buckets_are_cut_per_day_with_the_highest_feature_in_the_last_bucket` | 10 coins in 5 buckets: two per bucket, bucket 5 holds the highest features |
| `test_bucket_sizes_differ_by_at_most_one_coin` | 13 coins split 3, 3, 3, 2, 2 |
| `test_a_market_wide_move_on_one_day_does_not_change_the_difference_between_quantiles` | Adding a constant to all labels of a day shifts every bucket equally |
| `test_the_bucket_cut_does_not_depend_on_which_labels_are_missing` | A missing label changes only its own bucket, never the cut |
| `test_the_median_ignores_one_extreme_coin_but_the_mean_does_not` | The bucket median stays at 14 while the mean is dragged up |
| `test_quantile_tables_are_in_percent_with_one_column_per_quantile` | Percent units, 5 columns, row levels of the block table |
| `test_the_row_order_of_the_input_does_not_matter` | A shuffled table gives identical tables |

## `tests/test_evaluation_checks.py` — the data checks

Made-up candles with random prices; each check must pass on correct data and **fail** on deliberately broken data.

| Test | Checks |
| ---- | ------ |
| `test_the_median_check_passes_on_a_correct_universe_and_fails_when_the_median_is_wrong` | A doubled median is caught |
| `test_the_history_check_fails_when_a_coin_is_flagged_in_its_first_bars` | A flag on a coin's first bar is caught |
| `test_the_saved_column_check_passes_on_real_columns_and_fails_on_a_shifted_one` | A past return computed with the wrong shift sign is caught |
| `test_the_split_check_fails_on_overlap_and_on_labels_reaching_into_the_holdout` | A split without the purge, and a row in both sets, are caught |

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

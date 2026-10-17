"""Tests for the candle downloader (1d and 1h). They never touch the network."""

# datetime and timezone let us build a fixed start date
from datetime import datetime, timezone

# pandas gives us tables (DataFrames) and timestamps
import pandas as pd
# pytest is the test framework; we use its fixtures, parametrize and pytest.raises
import pytest

# The module itself, so we can swap its Info class for a fake one
from wh_research.data.hyperliquid import candles
# The names we test or use as building blocks
from wh_research.data.hyperliquid.candles import (
    BAR_MS,
    COLUMNS,
    MAX_ATTEMPTS,
    MAX_BARS,
    candles_filename,
    download_with_retry,
    first_missing_bar_ms,
    to_dataframe,
    update_candles,
)

# Every candle size the code supports; tests marked with INTERVALS run once per size
INTERVALS = list(BAR_MS)
# 2024-01-01 UTC in milliseconds: "bar 0" for all fake data. It is in the past, so bars count as closed
BAR0_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
# The fake "now": 30 days after the fake data starts, so every fake bar has closed
NOW_MS = BAR0_MS + 30 * BAR_MS["1d"]


def api_bar(symbol, bar_number, interval="1d"):
    """One candle shaped like the real API answer. Numbers are text, as in the API."""
    # Start time of this bar: bar 0 plus `bar_number` whole bars
    open_ms = BAR0_MS + bar_number * BAR_MS[interval]
    # Return a dict with the same one-letter keys the real API uses
    return {
        # t = start time, T = end time (1 ms before the next bar starts), s = symbol, i = interval
        "t": open_ms, "T": open_ms + BAR_MS[interval] - 1, "s": symbol, "i": interval,
        # open, high, low, close and volume as text; n = number of trades
        "o": "1.0", "h": "2.0", "l": "0.5", "c": "1.5", "v": "10.0", "n": 5,
    }


class FakeInfo:
    """Stands in for the Hyperliquid Info class.

    Coin A is active and coin B is delisted. Every coin has `bars_available`
    bars starting at BAR0_MS. Add a bar by raising `bars_available`.
    """

    def __init__(self):
        # How many bars exist for every coin
        self.bars_available = 3
        # Coins in this set raise a server error when asked for candles
        self.broken_symbols = set()
        # A log of every request made: (symbol, start_ms)
        self.calls = []

    def meta(self):
        # The list of coins, like the real API: A is active, B is marked delisted
        return {"universe": [{"name": "A"}, {"name": "B", "isDelisted": True}]}

    def candles_snapshot(self, symbol, interval, start_ms, end_ms):
        # Remember this request so tests can check what was asked for
        self.calls.append((symbol, start_ms))
        # Pretend the server fails for broken coins (500 is not a rate-limit error)
        if symbol in self.broken_symbols:
            raise Exception(500, "server error")
        # Bar numbers 0, 1, 2, ... for the bars that exist
        bar_numbers = range(self.bars_available)
        # Return only the bars that start at or after start_ms, like the real API does
        return [api_bar(symbol, number, interval) for number in bar_numbers
                if BAR0_MS + number * BAR_MS[interval] >= start_ms]


class RateLimitedInfo:
    """Raises a 429 error `failures` times, then answers normally."""

    def __init__(self, failures):
        # How many requests should fail before one works
        self.failures = failures
        # How many requests have been made so far
        self.calls = 0

    def candles_snapshot(self, symbol, interval, start_ms, end_ms):
        # Count this request
        self.calls += 1
        # While we are still within the failure budget, raise a rate-limit (429) error
        if self.calls <= self.failures:
            raise Exception(429, "too many requests")
        # After that, answer with a single bar
        return [api_bar(symbol, 0, interval)]


# autouse=True applies this fixture to every test in this file without naming it
@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Skip real waiting, and record how long the code asked to wait."""
    # A list that collects every wait time
    waited = []
    # Replace time.sleep with list.append, so "sleeping 5 seconds" just records 5
    monkeypatch.setattr("time.sleep", waited.append)
    # Give the list to tests that ask for it
    return waited


@pytest.fixture
def fake_info(monkeypatch):
    # Create one fake API object
    fake = FakeInfo()
    # Make candles.Info return our fake instead of connecting to Hyperliquid
    monkeypatch.setattr(candles, "Info", lambda *args, **kwargs: fake)
    # Freeze the clock at NOW_MS (time.time gives seconds, so divide by 1000)
    monkeypatch.setattr("time.time", lambda: NOW_MS / 1000)
    # Give the fake to the test so it can change it and inspect its calls
    return fake


# --- candles_filename -----------------------------------------------------

def test_candles_filename_contains_the_interval():
    # Assert: each interval gets its own file name
    assert candles_filename("1d") == "candles_1d.parquet"
    assert candles_filename("1h") == "candles_1h.parquet"


# --- to_dataframe ---------------------------------------------------------

@pytest.mark.parametrize("interval", INTERVALS)
def test_to_dataframe_renames_columns_and_converts_types(interval):
    # Act: convert one fake API bar, using an end time far after the bar closed
    result = to_dataframe([api_bar("A", 0, interval)], end_ms=BAR0_MS + 10 * BAR_MS["1d"])

    # Assert: the columns are exactly ours, in our order
    assert list(result.columns) == COLUMNS
    # Assert: prices were converted from text to decimal numbers
    assert result["open"].dtype == float
    # Assert: times are timezone-aware and in UTC
    assert str(result["open_time"].dt.tz) == "UTC"
    # Assert: bar 0 became the date 2024-01-01
    assert result["open_time"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")


@pytest.mark.parametrize("interval", INTERVALS)
def test_to_dataframe_drops_bar_that_has_not_closed(interval):
    # end_ms is during bar 1, so bar 0 is closed but bar 1 is still forming
    end_ms = BAR0_MS + BAR_MS[interval] + 1000
    # Act: convert two bars (bar 0 and bar 1)
    result = to_dataframe([api_bar("A", 0, interval), api_bar("A", 1, interval)], end_ms)

    # Assert: only the closed bar (bar 0) is left
    assert len(result) == 1


def test_to_dataframe_with_no_data_returns_empty_table():
    # Act: convert an empty answer from the API
    result = to_dataframe([], end_ms=BAR0_MS)

    # Assert: the table has no rows
    assert result.empty
    # Assert: it still has all our columns
    assert list(result.columns) == COLUMNS


# --- download_with_retry --------------------------------------------------

def test_retry_succeeds_after_two_429s_and_waits_longer_each_time(sleeps):
    # Arrange: an API that fails with 429 twice and then works
    info = RateLimitedInfo(failures=2)

    # Act: download with retries
    raw_candles = download_with_retry(info, "A", "1d", BAR0_MS, BAR0_MS + BAR_MS["1d"])

    # Assert: we got the bar from the successful third request
    assert len(raw_candles) == 1
    # Assert: 3 requests were made (2 failures and 1 success)
    assert info.calls == 3
    # Assert: we waited 5 seconds, then 10 seconds (the wait doubles)
    assert sleeps == [5, 10]


def test_retry_does_not_retry_other_errors(fake_info):
    # Arrange: make coin A fail with a server error (not a rate limit)
    fake_info.broken_symbols = {"A"}

    # Act and assert: the error is raised instead of being retried
    with pytest.raises(Exception, match="server error"):
        download_with_retry(fake_info, "A", "1d", BAR0_MS, BAR0_MS)

    # Assert: only one request was made, so there was no retry
    assert len(fake_info.calls) == 1


def test_retry_gives_up_after_max_attempts():
    # Arrange: an API that always says 429
    info = RateLimitedInfo(failures=1000)

    # Act and assert: after the last attempt the 429 error is raised
    with pytest.raises(Exception, match="too many requests"):
        download_with_retry(info, "A", "1d", BAR0_MS, BAR0_MS)

    # Assert: it tried exactly MAX_ATTEMPTS times
    assert info.calls == MAX_ATTEMPTS


# --- first_missing_bar_ms -------------------------------------------------

@pytest.mark.parametrize("interval", INTERVALS)
def test_first_missing_bar_for_new_symbol_is_5000_bars_before_now(interval):
    # Arrange: coin A was saved up to 2024-01-03, and "NEW" has never been saved
    last_saved = pd.Series({"A": pd.Timestamp("2024-01-03", tz="UTC")})

    # Assert: a coin we have never saved starts MAX_BARS bars before "now"
    assert first_missing_bar_ms("NEW", last_saved, interval, NOW_MS) == NOW_MS - MAX_BARS * BAR_MS[interval]


@pytest.mark.parametrize("interval", INTERVALS)
def test_first_missing_bar_for_saved_symbol_is_the_next_bar(interval):
    # Arrange: coin A was saved up to 2024-01-03
    last_saved = pd.Series({"A": pd.Timestamp("2024-01-03", tz="UTC")})
    # Where 2024-01-03 is in milliseconds (2 days after bar 0)
    last_saved_ms = BAR0_MS + 2 * BAR_MS["1d"]

    # Assert: the next missing bar starts exactly one bar length later
    assert first_missing_bar_ms("A", last_saved, interval, NOW_MS) == last_saved_ms + BAR_MS[interval]


# --- update_candles (whole run, using the fake API) -----------------------

def read_saved(tmp_path, interval):
    # Read the candles file the update wrote into the temporary folder
    return pd.read_parquet(tmp_path / candles_filename(interval))


@pytest.mark.parametrize("interval", INTERVALS)
def test_first_run_saves_every_symbol_sorted(fake_info, tmp_path, interval):
    # Act: run a full update into an empty temporary folder
    update_candles(tmp_path, interval)

    # Read back what was saved (from the file named after the interval)
    saved = read_saved(tmp_path, interval)
    # Sort a copy by coin and then time, which is the order the file should already be in
    sorted_copy = saved.sort_values(["symbol", "open_time"]).reset_index(drop=True)
    # Assert: the saved file was already in that order
    assert saved.equals(sorted_copy)
    # Assert: each coin has its 3 bars
    assert saved.groupby("symbol").size().to_dict() == {"A": 3, "B": 3}
    # Assert: the first request started MAX_BARS bars before "now"
    assert fake_info.calls[0][1] == NOW_MS - MAX_BARS * BAR_MS[interval]


@pytest.mark.parametrize("interval", INTERVALS)
def test_second_run_fetches_only_new_bars_and_skips_delisted(fake_info, tmp_path, interval):
    # Arrange: do the first run, which saves 3 bars for A and B
    update_candles(tmp_path, interval)
    # A new bar appears on the fake exchange
    fake_info.bars_available = 4
    # Forget the requests from the first run so we only see the second run's requests
    fake_info.calls.clear()

    # Act: run the update again
    update_candles(tmp_path, interval)

    # Assert: only A was requested, starting after its last saved bar; delisted B was never requested
    assert fake_info.calls == [("A", BAR0_MS + 3 * BAR_MS[interval])]
    # Read back what is now saved
    saved = read_saved(tmp_path, interval)
    # Assert: A gained the new bar (4 bars) and B is unchanged (3 bars)
    assert saved.groupby("symbol").size().to_dict() == {"A": 4, "B": 3}
    # Assert: no (symbol, open_time) pair appears twice
    assert not saved.duplicated(["symbol", "open_time"]).any()


def test_failed_symbol_is_left_out_and_fetched_on_the_next_run(fake_info, tmp_path):
    # Arrange: coin B will fail on the first run
    fake_info.broken_symbols = {"B"}
    # Act: run the update
    update_candles(tmp_path, "1d")
    # Assert: only A was saved
    assert set(read_saved(tmp_path, "1d")["symbol"]) == {"A"}

    # Arrange: B is fixed now
    fake_info.broken_symbols = set()
    # Act: run the update again
    update_candles(tmp_path, "1d")
    # Assert: B was filled in this time, so both coins are saved
    assert set(read_saved(tmp_path, "1d")["symbol"]) == {"A", "B"}


def test_unsupported_interval_is_rejected(fake_info, tmp_path):
    # Act and assert: asking for 5-minute candles fails with a clear message
    with pytest.raises(ValueError, match="interval must be one of"):
        update_candles(tmp_path, "5m")

    # Assert: nothing was requested from the API
    assert fake_info.calls == []

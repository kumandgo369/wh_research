"""Tests for the funding rate downloader. They never touch the network."""

# datetime and timezone let us build a fixed start date
from datetime import datetime, timezone

# pandas gives us tables (DataFrames) and timestamps
import pandas as pd
# pytest is the test framework; we use its fixtures
import pytest

# The module itself, so we can swap its Info class and PAGE_SIZE
from wh_research.data.hyperliquid import funding
# The names we test
from wh_research.data.hyperliquid.funding import (
    COLUMNS,
    START_TIME_MS,
    download_funding,
    first_missing_time_ms,
    to_dataframe,
    update_funding,
)

# One hour in milliseconds
HOUR_MS = 3_600_000
# 2024-01-01 UTC in milliseconds: when the fake funding history starts
BASE_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
# The fake "now": 30 days after the fake data starts
NOW_MS = BASE_MS + 30 * 24 * HOUR_MS


def funding_time_ms(row_number):
    """Time of fake row number n: n hours after BASE_MS, plus 48 ms like the real API."""
    # The real API's times are a few milliseconds off the hour
    return BASE_MS + row_number * HOUR_MS + 48


def api_row(symbol, row_number):
    """One funding row shaped like the real API answer. The rates are text, as in the API."""
    # Make the rate different for each row so tests can tell rows apart
    rate = f"0.0001{row_number}"
    # Same keys as the real API
    return {"coin": symbol, "fundingRate": rate, "premium": "0.0002", "time": funding_time_ms(row_number)}


class FakeInfo:
    """Stands in for the Hyperliquid Info class.

    Coin A is active and coin B is delisted. Every coin has `rows_available`
    hourly funding rows. Add rows by raising `rows_available`.
    """

    def __init__(self):
        # How many funding rows exist for every coin
        self.rows_available = 4
        # Coins in this set raise a server error when asked for funding
        self.broken_symbols = set()
        # A log of every request made: (symbol, start_ms)
        self.calls = []

    def meta(self):
        # The list of coins, like the real API: A is active, B is marked delisted
        return {"universe": [{"name": "A"}, {"name": "B", "isDelisted": True}]}

    def funding_history(self, name, startTime, endTime=None):
        # Remember this request so tests can check what was asked for
        self.calls.append((name, startTime))
        # Pretend the server fails for broken coins (500 is not a rate-limit error)
        if name in self.broken_symbols:
            raise Exception(500, "server error")
        # All the rows that exist and start at or after startTime, oldest first
        rows = [api_row(name, number) for number in range(self.rows_available)
                if funding_time_ms(number) >= startTime]
        # Like the real API, answer with at most one page
        return rows[:funding.PAGE_SIZE]


@pytest.fixture(autouse=True)
def fast_and_small(monkeypatch):
    """Skip real waiting, and use pages of 3 rows so paging happens with tiny data."""
    # Replace time.sleep with a function that does nothing
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    # Pages of 3 rows instead of 500
    monkeypatch.setattr(funding, "PAGE_SIZE", 3)


@pytest.fixture
def fake_info(monkeypatch):
    # Create one fake API object
    fake = FakeInfo()
    # Make funding.Info return our fake instead of connecting to Hyperliquid
    monkeypatch.setattr(funding, "Info", lambda *args, **kwargs: fake)
    # Freeze the clock at NOW_MS (time.time gives seconds, so divide by 1000)
    monkeypatch.setattr("time.time", lambda: NOW_MS / 1000)
    # Give the fake to the test so it can change it and inspect its calls
    return fake


# --- to_dataframe ---------------------------------------------------------

def test_to_dataframe_renames_columns_and_converts_types():
    # Act: convert two fake API rows
    result = to_dataframe([api_row("A", 0), api_row("A", 1)])

    # Assert: the columns are exactly ours, in our order
    assert list(result.columns) == COLUMNS
    # Assert: the rates were converted from text to decimal numbers
    assert result["funding_rate"].dtype == float
    assert result["premium"].dtype == float
    # Assert: time is UTC with microsecond precision, the same type as the candles' times
    assert str(result["time"].dtype) == "datetime64[us, UTC]"
    # Assert: the millisecond offset from the API is kept
    assert result["time"].iloc[0] == pd.Timestamp("2024-01-01 00:00:00.048", tz="UTC")


def test_to_dataframe_with_no_data_returns_empty_table():
    # Act: convert an empty answer from the API
    result = to_dataframe([])

    # Assert: the table has no rows but still has all our columns
    assert result.empty
    assert list(result.columns) == COLUMNS


def test_funding_can_be_joined_to_candles_with_merge_asof():
    # Arrange: funding rows for hours 0 to 3, and one candle that opened at 01:00 and closed at 01:59:59.999
    funding_rows = to_dataframe([api_row("A", number) for number in range(4)])
    close_time = pd.to_datetime(["2024-01-01 01:59:59.999"], utc=True).astype("datetime64[us, UTC]")
    candles = pd.DataFrame({"symbol": ["A"], "close_time": close_time})

    # Act: for each candle take the latest funding row at or before its close (never a later one)
    joined = pd.merge_asof(candles, funding_rows, left_on="close_time", right_on="time",
                           by="symbol", direction="backward")

    # Assert: it picked the row from 01:00:00.048 (row 1), not the one from 02:00 that comes after the close
    assert joined["funding_rate"].iloc[0] == pytest.approx(float("0.00011"))


# --- download_funding -----------------------------------------------------

def test_download_funding_collects_every_page(fake_info):
    # Arrange: 7 rows with a page size of 3 means pages of 3, 3 and 1
    fake_info.rows_available = 7

    # Act: download everything
    result = download_funding(fake_info, "A", START_TIME_MS, NOW_MS)

    # Assert: all 7 rows arrived, each once, in order
    assert len(result) == 7
    assert result["time"].is_unique and result["time"].is_monotonic_increasing
    # Assert: it took 3 requests
    assert len(fake_info.calls) == 3
    # Assert: the second page started 1 ms after the last row of the first page
    assert fake_info.calls[1][1] == funding_time_ms(2) + 1


def test_download_funding_needs_one_extra_request_when_the_last_page_is_full(fake_info):
    # Arrange: 6 rows with a page size of 3 means two full pages, so we cannot know it was the end
    fake_info.rows_available = 6

    # Act: download everything
    result = download_funding(fake_info, "A", START_TIME_MS, NOW_MS)

    # Assert: all 6 rows arrived and a third request found nothing more
    assert len(result) == 6
    assert len(fake_info.calls) == 3


def test_download_funding_with_no_rows_returns_empty_table(fake_info):
    # Arrange: the exchange has no funding rows
    fake_info.rows_available = 0

    # Act: download everything
    result = download_funding(fake_info, "A", START_TIME_MS, NOW_MS)

    # Assert: an empty table with our columns
    assert result.empty
    assert list(result.columns) == COLUMNS


# --- first_missing_time_ms ------------------------------------------------

def test_first_missing_time_for_new_symbol_is_the_global_start():
    # Arrange: coin A was saved up to 2024-01-03, and "NEW" has never been saved
    last_saved = pd.Series({"A": pd.Timestamp("2024-01-03", tz="UTC")})

    # Assert: a coin we have never saved starts from the global start time
    assert first_missing_time_ms("NEW", last_saved) == START_TIME_MS


def test_first_missing_time_for_saved_symbol_is_one_millisecond_later():
    # Arrange: coin A was saved up to 2024-01-03
    last_saved = pd.Series({"A": pd.Timestamp("2024-01-03", tz="UTC")})
    # Where 2024-01-03 is in milliseconds (2 days after BASE_MS)
    last_saved_ms = BASE_MS + 2 * 24 * HOUR_MS

    # Assert: the next missing row starts 1 ms after the last saved one
    assert first_missing_time_ms("A", last_saved) == last_saved_ms + 1


# --- update_funding (whole run, using the fake API) -----------------------

def read_saved(tmp_path):
    # Read the funding file the update wrote into the temporary folder
    return pd.read_parquet(tmp_path / "funding.parquet")


def test_first_run_saves_every_symbol_sorted(fake_info, tmp_path):
    # Act: run a full update into an empty temporary folder
    update_funding(tmp_path)

    # Read back what was saved
    saved = read_saved(tmp_path)
    # Sort a copy by coin and then time, which is the order the file should already be in
    sorted_copy = saved.sort_values(["symbol", "time"]).reset_index(drop=True)
    # Assert: the saved file was already in that order
    assert saved.equals(sorted_copy)
    # Assert: each coin has its 4 rows
    assert saved.groupby("symbol").size().to_dict() == {"A": 4, "B": 4}


def test_second_run_fetches_new_rows_for_every_coin_including_delisted(fake_info, tmp_path):
    # Arrange: do the first run, which saves 4 rows for A and B
    update_funding(tmp_path)
    # Two new rows appear on the fake exchange
    fake_info.rows_available = 6
    # Forget the requests from the first run so we only see the second run's requests
    fake_info.calls.clear()

    # Act: run the update again
    update_funding(tmp_path)

    # Assert: both coins were requested once, starting 1 ms after their last saved row (B is marked delisted
    # but may have been delisted only after the last run, so it is asked again)
    assert fake_info.calls == [("A", funding_time_ms(3) + 1), ("B", funding_time_ms(3) + 1)]
    # Read back what is now saved
    saved = read_saved(tmp_path)
    # Assert: both coins gained the 2 new rows
    assert saved.groupby("symbol").size().to_dict() == {"A": 6, "B": 6}
    # Assert: no (symbol, time) pair appears twice
    assert not saved.duplicated(["symbol", "time"]).any()


def test_failed_symbol_is_left_out_and_fetched_on_the_next_run(fake_info, tmp_path):
    # Arrange: coin B will fail on the first run
    fake_info.broken_symbols = {"B"}
    # Act: run the update
    update_funding(tmp_path)
    # Assert: only A was saved
    assert set(read_saved(tmp_path)["symbol"]) == {"A"}

    # Arrange: B is fixed now
    fake_info.broken_symbols = set()
    # Act: run the update again
    update_funding(tmp_path)
    # Assert: B was filled in this time, so both coins are saved
    assert set(read_saved(tmp_path)["symbol"]) == {"A", "B"}


def test_update_prints_progress(fake_info, tmp_path, monkeypatch, capsys):
    # Arrange: print a progress line after every symbol instead of every 25
    monkeypatch.setattr(funding, "PROGRESS_EVERY", 1)

    # Act: run the update (the fake exchange has 2 coins)
    update_funding(tmp_path)

    # Read everything the update printed
    output = capsys.readouterr().out
    # Assert: it said how many symbols it will check, and how far it got
    assert "checking 2 symbols" in output
    assert "1/2 symbols checked" in output
    assert "2/2 symbols checked" in output

"""Tests for the daily candle downloader. They never touch the network."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from wh_research.data.hyperliquid import candles_1d
from wh_research.data.hyperliquid.candles_1d import (
    COLUMNS,
    MAX_ATTEMPTS,
    ONE_DAY_MS,
    START_TIME_MS,
    download_with_retry,
    first_missing_bar_ms,
    to_dataframe,
    update_candles_1d,
)

DAY0_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def api_bar(symbol, day):
    """One candle shaped like the real API answer. Numbers are text, as in the API."""
    open_ms = DAY0_MS + day * ONE_DAY_MS
    return {
        "t": open_ms, "T": open_ms + ONE_DAY_MS - 1, "s": symbol, "i": "1d",
        "o": "1.0", "h": "2.0", "l": "0.5", "c": "1.5", "v": "10.0", "n": 5,
    }


class FakeInfo:
    """Stands in for the Hyperliquid Info class.

    Coin A is active and coin B is delisted. Every coin has `days_available`
    daily bars starting on 2024-01-01. Add a day by raising `days_available`.
    """

    def __init__(self):
        self.days_available = 3
        self.broken_symbols = set()  # these raise a server error
        self.calls = []              # (symbol, start_ms) for every request

    def meta(self):
        return {"universe": [{"name": "A"}, {"name": "B", "isDelisted": True}]}

    def candles_snapshot(self, symbol, interval, start_ms, end_ms):
        self.calls.append((symbol, start_ms))
        if symbol in self.broken_symbols:
            raise Exception(500, "server error")
        days = range(self.days_available)
        return [api_bar(symbol, day) for day in days if DAY0_MS + day * ONE_DAY_MS >= start_ms]


class RateLimitedInfo:
    """Raises a 429 error `failures` times, then answers normally."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def candles_snapshot(self, symbol, interval, start_ms, end_ms):
        self.calls += 1
        if self.calls <= self.failures:
            raise Exception(429, "too many requests")
        return [api_bar(symbol, 0)]


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Skip real waiting, and record how long the code asked to wait."""
    waited = []
    monkeypatch.setattr("time.sleep", waited.append)
    return waited


@pytest.fixture
def fake_info(monkeypatch):
    fake = FakeInfo()
    monkeypatch.setattr(candles_1d, "Info", lambda *args, **kwargs: fake)
    return fake


# --- to_dataframe ---------------------------------------------------------

def test_to_dataframe_renames_columns_and_converts_types():
    candles = to_dataframe([api_bar("A", 0)], end_ms=DAY0_MS + 10 * ONE_DAY_MS)

    assert list(candles.columns) == COLUMNS
    assert candles["open"].dtype == float
    assert str(candles["open_time"].dt.tz) == "UTC"
    assert candles["open_time"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")


def test_to_dataframe_drops_bar_that_has_not_closed():
    # end_ms is during day 1, so day 0 is closed but day 1 is still forming
    end_ms = DAY0_MS + ONE_DAY_MS + 1000
    candles = to_dataframe([api_bar("A", 0), api_bar("A", 1)], end_ms)

    assert len(candles) == 1


def test_to_dataframe_with_no_data_returns_empty_table():
    candles = to_dataframe([], end_ms=DAY0_MS)

    assert candles.empty
    assert list(candles.columns) == COLUMNS


# --- download_with_retry --------------------------------------------------

def test_retry_succeeds_after_two_429s_and_waits_longer_each_time(sleeps):
    info = RateLimitedInfo(failures=2)

    raw_candles = download_with_retry(info, "A", DAY0_MS, DAY0_MS + ONE_DAY_MS)

    assert len(raw_candles) == 1
    assert info.calls == 3
    assert sleeps == [5, 10]


def test_retry_does_not_retry_other_errors(fake_info):
    fake_info.broken_symbols = {"A"}

    with pytest.raises(Exception, match="server error"):
        download_with_retry(fake_info, "A", DAY0_MS, DAY0_MS)

    assert len(fake_info.calls) == 1


def test_retry_gives_up_after_max_attempts():
    info = RateLimitedInfo(failures=1000)

    with pytest.raises(Exception, match="too many requests"):
        download_with_retry(info, "A", DAY0_MS, DAY0_MS)

    assert info.calls == MAX_ATTEMPTS


# --- first_missing_bar_ms -------------------------------------------------

def test_first_missing_bar_for_new_symbol_is_the_global_start():
    last_saved = pd.Series({"A": pd.Timestamp("2024-01-03", tz="UTC")})

    assert first_missing_bar_ms("NEW", last_saved) == START_TIME_MS


def test_first_missing_bar_for_saved_symbol_is_the_next_day():
    last_saved = pd.Series({"A": pd.Timestamp("2024-01-03", tz="UTC")})

    assert first_missing_bar_ms("A", last_saved) == DAY0_MS + 3 * ONE_DAY_MS


# --- update_candles_1d (whole run, using the fake API) --------------------

def read_saved(tmp_path):
    return pd.read_parquet(tmp_path / "candles_1d.parquet")


def test_first_run_saves_every_symbol_sorted(fake_info, tmp_path):
    update_candles_1d(tmp_path)

    saved = read_saved(tmp_path)
    sorted_copy = saved.sort_values(["symbol", "open_time"]).reset_index(drop=True)
    assert saved.equals(sorted_copy)
    assert saved.groupby("symbol").size().to_dict() == {"A": 3, "B": 3}


def test_second_run_fetches_only_new_bars_and_skips_delisted(fake_info, tmp_path):
    update_candles_1d(tmp_path)
    fake_info.days_available = 4  # a new day appears
    fake_info.calls.clear()

    update_candles_1d(tmp_path)

    assert fake_info.calls == [("A", DAY0_MS + 3 * ONE_DAY_MS)]  # B never requested
    saved = read_saved(tmp_path)
    assert saved.groupby("symbol").size().to_dict() == {"A": 4, "B": 3}
    assert not saved.duplicated(["symbol", "open_time"]).any()


def test_failed_symbol_is_left_out_and_fetched_on_the_next_run(fake_info, tmp_path):
    fake_info.broken_symbols = {"B"}
    update_candles_1d(tmp_path)
    assert set(read_saved(tmp_path)["symbol"]) == {"A"}

    fake_info.broken_symbols = set()
    update_candles_1d(tmp_path)
    assert set(read_saved(tmp_path)["symbol"]) == {"A", "B"}

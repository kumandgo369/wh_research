"""Tests for the helpers shared by the candle and funding downloaders."""

# pandas gives us tables (DataFrames)
import pandas as pd
# pytest is the test framework; we use its fixtures and pytest.raises
import pytest

# The two helpers we are testing
from wh_research.data.hyperliquid.api_helpers import MAX_ATTEMPTS, call_with_retry, save_table


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


def failing_request(failures, error_code):
    """A request that raises Exception(error_code) `failures` times, then returns "ok"."""
    # Count how many times the request has been called (a list so the inner function can change it)
    calls = []

    def request():
        # Count this call
        calls.append(1)
        # While we are still within the failure budget, raise the error
        if len(calls) <= failures:
            raise Exception(error_code, "error")
        # After that, answer normally
        return "ok"

    # Hand back the request and its call counter
    return request, calls


def test_call_with_retry_returns_the_answer_when_nothing_fails():
    # Arrange: a request that never fails
    request, calls = failing_request(failures=0, error_code=429)

    # Act and assert: the answer comes straight back after one call
    assert call_with_retry(request, "A") == "ok"
    assert len(calls) == 1


def test_call_with_retry_waits_longer_after_each_429(sleeps):
    # Arrange: a request that fails with 429 twice and then works
    request, calls = failing_request(failures=2, error_code=429)

    # Act: run it with retries
    result = call_with_retry(request, "A")

    # Assert: the third call worked
    assert result == "ok"
    assert len(calls) == 3
    # Assert: we waited 5 seconds, then 10 seconds (the wait doubles)
    assert sleeps == [5, 10]


def test_call_with_retry_caps_the_wait_at_60_seconds(sleeps):
    # Arrange: a request that fails with 429 on all but the last attempt
    request, calls = failing_request(failures=MAX_ATTEMPTS - 1, error_code=429)

    # Act: run it with retries
    call_with_retry(request, "A")

    # Assert: the waits double (5, 10, 20, 40) and then stay at 60
    assert sleeps == [5, 10, 20, 40, 60, 60, 60]


def test_call_with_retry_raises_other_errors_at_once(sleeps):
    # Arrange: a request that fails with a server error (500), not a rate limit
    request, calls = failing_request(failures=5, error_code=500)

    # Act and assert: the error is raised instead of being retried
    with pytest.raises(Exception, match="error"):
        call_with_retry(request, "A")

    # Assert: only one call was made and we never waited
    assert len(calls) == 1
    assert sleeps == []


def test_call_with_retry_gives_up_after_max_attempts():
    # Arrange: a request that always says 429
    request, calls = failing_request(failures=1000, error_code=429)

    # Act and assert: after the last attempt the 429 error is raised
    with pytest.raises(Exception, match="error"):
        call_with_retry(request, "A")

    # Assert: it tried exactly MAX_ATTEMPTS times
    assert len(calls) == MAX_ATTEMPTS


def test_save_table_sorts_removes_duplicates_and_leaves_no_tmp_file(tmp_path):
    # Arrange: two tables that overlap on (symbol, n = 2), with the newer copy having value "new"
    older = pd.DataFrame({"symbol": ["B", "A"], "n": [1, 2], "value": ["x", "old"]})
    newer = pd.DataFrame({"symbol": ["A", "A"], "n": [2, 1], "value": ["new", "y"]})
    # Where the file will be saved; the folder does not exist yet
    path = tmp_path / "data" / "table.parquet"

    # Act: save them, identifying a row by (symbol, n)
    save_table([older, newer], path, ["symbol", "n"])

    # Read back what was saved
    saved = pd.read_parquet(path)
    # Assert: sorted by symbol then n, and the duplicate (A, 2) kept the newer copy
    assert saved[["symbol", "n", "value"]].values.tolist() == [["A", 1, "y"], ["A", 2, "new"], ["B", 1, "x"]]
    # Assert: the temporary file was swapped in, so it no longer exists
    assert not path.with_suffix(".tmp").exists()

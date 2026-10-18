"""Small helpers shared by the candle and funding downloaders."""

# time lets us pause (sleep) between retries
import time

# pandas gives us tables (DataFrames) and reads/writes parquet files
import pandas as pd

# How many times we try a request before giving up
MAX_ATTEMPTS = 8


def call_with_retry(request, label):
    """Run request(). If the API says 429 (too many requests), wait and retry.

    request is a function that takes no arguments and makes one API call.
    label is only used in the message we print, such as a coin name.
    """
    # Wait 5 seconds before the first retry
    wait_seconds = 5
    # Try the request up to MAX_ATTEMPTS times, counting attempts from 1
    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Run the request inside try so we can react if it fails
        try:
            # Make the API call and hand back the answer straight away if it works
            return request()
        # If the request failed, catch the error so we can look at it
        except Exception as error:
            # The API's rate-limit errors carry the number 429 as their first argument
            is_rate_limit = error.args[:1] == (429,)
            # Give up (re-raise the error) if it is not a rate limit, or if this was the last attempt
            if not is_rate_limit or attempt == MAX_ATTEMPTS:
                raise
            # Tell the user we are about to wait
            print(f"{label}: 429, retry in {wait_seconds}s")
            # Pause so the rate limit can reset
            time.sleep(wait_seconds)
            # Wait twice as long next time, but never more than 60 seconds
            wait_seconds = min(wait_seconds * 2, 60)


def save_table(tables, path, key_columns):
    """Combine tables, remove duplicates, sort, and write the file safely.

    key_columns identify one row, such as ["symbol", "open_time"]. We write to a
    .tmp file first and then swap it in, so a crash while writing can never
    leave a half-written file.
    """
    # Build the final table by chaining these steps, from the first line to the last
    table = (pd.concat(tables, ignore_index=True)  # stack all the tables into one
               # if the same key appears twice, keep the later (newer) copy
               .drop_duplicates(key_columns, keep="last")
               # order the rows by the key columns (for us: by coin, then by time)
               .sort_values(key_columns)
               # renumber the rows 0, 1, 2, ... and throw away the old numbers
               .reset_index(drop=True))

    # Create the data folder if it does not exist yet
    path.parent.mkdir(parents=True, exist_ok=True)
    # A temporary file name next to the real one (same name, ending in .tmp)
    tmp_path = path.with_suffix(".tmp")
    # Write the table to the temporary file first (index=False skips the row numbers)
    table.to_parquet(tmp_path, index=False)
    # Swap the temporary file in only after it was fully written
    tmp_path.replace(path)
    # Print a summary: number of rows and number of different coins
    print(f"saved {len(table)} rows, {table['symbol'].nunique()} symbols")

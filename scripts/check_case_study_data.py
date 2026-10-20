# sys lets us stop with an error code and read the words typed after the script name
import sys
# Path lets us build file and folder paths in a way that works on any operating system
from pathlib import Path

# pandas reads parquet files
import pandas as pd

# The checks, each returns (passed, detail)
from wh_research.evaluation.checks import (
    check_saved_columns,
    check_split,
    check_universe_median,
    check_universe_needs_history,
)

# The case-study folder: <project>/data/hyperliquid/case_study_data
# (__file__ is this script, the first .parent is the scripts folder, the second is the project folder)
data_dir = Path(__file__).resolve().parent.parent / "data" / "hyperliquid" / "case_study_data"
# The frozen universe file is the first word after the script name, or the one used in case study 1
universe_name = sys.argv[1] if len(sys.argv) > 1 else "universe_1d_min_mdv_2m_exit_1m_280323_171026.parquet"

# Read the frozen universe and the two saved sets
universe = pd.read_parquet(data_dir / universe_name)
pre_holdout = pd.read_parquet(data_dir / "pre_holdout.parquet")
holdout = pd.read_parquet(data_dir / "holdout.parquet")

# Every check as (name, result)
results = [
    ("universe median uses only the 30 days before each bar", check_universe_median(universe)),
    ("no coin is in the universe in its first 30 bars", check_universe_needs_history(universe)),
    ("holdout split: no overlap, universe rows only, purged", check_split(pre_holdout, holdout, 7)),
]
# Features look back and labels look ahead, for every column both saved sets must match a recomputation
for name, part in (("pre_holdout", pre_holdout), ("holdout", holdout)):
    for n in (7, 14, 30):
        if f"past_log_return_{n}" in part.columns:
            results.append((f"{name}: past_log_return_{n} looks back {n} days", check_saved_columns(part, universe, -n, f"past_log_return_{n}")))
    for n in (1, 3, 7):
        if f"fwd_log_return_{n}" in part.columns:
            results.append((f"{name}: fwd_log_return_{n} looks ahead {n} days", check_saved_columns(part, universe, n, f"fwd_log_return_{n}")))

# Print one line per check, and remember whether all passed
all_passed = True
for name, (passed, detail) in results:
    print(f"{'PASS' if passed else 'FAIL'}  {name}  ({detail})")
    all_passed = all_passed and passed
# A non-zero exit code tells the shell that something failed
sys.exit(0 if all_passed else 1)

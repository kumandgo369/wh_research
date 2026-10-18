# sys.argv holds the words typed after the script name on the command line
import sys
# Path lets us build file and folder paths in a way that works on any operating system
from pathlib import Path

# Import the function that rebuilds one cutoff's daily universe file from the cleaned candles
from wh_research.data.hyperliquid.daily_universe import update_daily_universe

# The entry level (minimum 30-day median dollar volume) is the first word after the script name, such as 2000000
min_mdv_usd = int(sys.argv[1])
# The exit level is an optional second word, such as 1000000; without it the exit level is the entry level
exit_mdv_usd = int(sys.argv[2]) if len(sys.argv) > 2 else None
# Build the universe in <project>/data/hyperliquid:
# __file__ is this script, .resolve() makes its path absolute, and the first .parent is
# the scripts folder, the second .parent is the project folder
update_daily_universe(Path(__file__).resolve().parent.parent / "data" / "hyperliquid", min_mdv_usd, exit_mdv_usd)

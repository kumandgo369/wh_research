# sys.argv holds the words typed after the script name on the command line
import sys
# Path lets us build file and folder paths in a way that works on any operating system
from pathlib import Path

# Import the function that downloads and saves the raw candles
from wh_research.data.hyperliquid.candles import update_candles
# Import the function that rebuilds the cleaned candles file from the raw one
from wh_research.data.hyperliquid.clean_candles import update_candles_cleaned

# The candle size is the first word after the script name, such as 1d or 1h
interval = sys.argv[1]
# Find the folder <project>/data/hyperliquid:
# __file__ is this script, .resolve() makes its path absolute, and the first .parent is
# the scripts folder, the second .parent is the project folder
data_dir = Path(__file__).resolve().parent.parent / "data" / "hyperliquid"
# First download any new candles into the raw file
update_candles(data_dir, interval)
# Then rebuild the cleaned file. This must come second because it reads the raw file
update_candles_cleaned(data_dir, interval)

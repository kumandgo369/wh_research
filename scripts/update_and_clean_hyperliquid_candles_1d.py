# Path lets us build file and folder paths in a way that works on any operating system
from pathlib import Path

# Import the function that downloads and saves the raw daily candles
from wh_research.data.hyperliquid.candles_1d import update_candles_1d
# Import the function that rebuilds the cleaned candles file from the raw one
from wh_research.data.hyperliquid.clean_candles_1d import update_candles_1d_cleaned

# Find the folder <project>/data/hyperliquid:
# __file__ is this script, .resolve() makes its path absolute, and the first .parent is
# the scripts folder, the second .parent is the project folder
data_dir = Path(__file__).resolve().parent.parent / "data" / "hyperliquid"
# First download any new candles into the raw file
update_candles_1d(data_dir)
# Then rebuild the cleaned file. This must come second because it reads the raw file
update_candles_1d_cleaned(data_dir)

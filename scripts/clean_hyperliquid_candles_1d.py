# Path lets us build file and folder paths in a way that works on any operating system
from pathlib import Path

# Import the function that rebuilds the cleaned candles file from the raw one
from wh_research.data.hyperliquid.clean_candles_1d import update_candles_1d_cleaned

# Clean the data in <project>/data/hyperliquid:
# __file__ is this script, .resolve() makes its path absolute, and the first .parent is
# the scripts folder, the second .parent is the project folder
update_candles_1d_cleaned(Path(__file__).resolve().parent.parent / "data" / "hyperliquid")

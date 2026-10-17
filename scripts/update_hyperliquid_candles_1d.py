# Path lets us build file and folder paths in a way that works on any operating system
from pathlib import Path

# Import the function that downloads and saves the daily candles
from wh_research.data.hyperliquid.candles_1d import update_candles_1d

# Run the update on the folder <project>/data/hyperliquid:
# __file__ is this script, .resolve() makes its path absolute, and the first .parent is
# the scripts folder, the second .parent is the project folder
update_candles_1d(Path(__file__).resolve().parent.parent / "data" / "hyperliquid")

# Path lets us build file and folder paths in a way that works on any operating system
from pathlib import Path

# Import the function that downloads and saves the funding rates
from wh_research.data.hyperliquid.funding import update_funding

# Run the update on the folder <project>/data/hyperliquid:
# __file__ is this script, .resolve() makes its path absolute, and the first .parent is
# the scripts folder, the second .parent is the project folder
update_funding(Path(__file__).resolve().parent.parent / "data" / "hyperliquid")

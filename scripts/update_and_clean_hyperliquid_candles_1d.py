from pathlib import Path

from wh_research.data.hyperliquid.candles_1d import update_candles_1d
from wh_research.data.hyperliquid.clean_candles_1d import update_candles_1d_cleaned

data_dir = Path(__file__).resolve().parent.parent / "data" / "hyperliquid"
update_candles_1d(data_dir)
update_candles_1d_cleaned(data_dir)

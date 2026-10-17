from pathlib import Path

from wh_research.data.hyperliquid.clean_candles_1d import update_candles_1d_cleaned

update_candles_1d_cleaned(Path(__file__).resolve().parent.parent / "data" / "hyperliquid")

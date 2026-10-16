from pathlib import Path

from wh_research.data.hyperliquid.candles_1d import update_candles_1d

update_candles_1d(Path(__file__).resolve().parent.parent / "data" / "hyperliquid")
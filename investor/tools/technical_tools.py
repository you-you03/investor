"""
Technical indicator calculations using pandas-ta.
These run locally on OHLCV bar data fetched from Polygon.
"""

from __future__ import annotations

from typing import Any

from investor.utils.logger import get_logger

logger = get_logger(__name__)


def compute_atr(bars: list[dict], window: int = 14) -> float | None:
    """
    Compute Average True Range (ATR) from OHLCV bar data.
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR = rolling simple average of True Range over `window` periods.
    Returns the most recent ATR value, or None if insufficient data.
    """
    try:
        if len(bars) < window + 1:
            return None
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i].get("high") or bars[i].get("h", 0)
            low = bars[i].get("low") or bars[i].get("l", 0)
            prev_close = bars[i - 1].get("close") or bars[i - 1].get("c", 0)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        recent = true_ranges[-window:]
        return sum(recent) / len(recent)
    except Exception as e:
        logger.warning(f"ATR computation failed: {e}")
        return None


def compute_bollinger_bands(bars: list[dict], window: int = 20, std: float = 2.0) -> dict[str, Any]:
    """
    Compute Bollinger Bands from OHLCV bar data using the `ta` library.
    Returns {upper, middle, lower} for the most recent bar.
    """
    try:
        import pandas as pd
        import ta.volatility as vol

        df = pd.DataFrame(bars)
        if "close" not in df.columns or len(df) < window:
            return {}

        close = df["close"]
        bb = vol.BollingerBands(close, window=window, window_dev=std)
        return {
            "upper": float(bb.bollinger_hband().iloc[-1]),
            "middle": float(bb.bollinger_mavg().iloc[-1]),
            "lower": float(bb.bollinger_lband().iloc[-1]),
        }
    except Exception as e:
        logger.warning(f"Bollinger Bands computation failed: {e}")
        return {}

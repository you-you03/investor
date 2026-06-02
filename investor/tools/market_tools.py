"""
Market data tool functions and their Claude JSON Schema definitions.
These are the functions Claude calls autonomously during the tool-use loop.
"""

from __future__ import annotations


import json
from typing import Any

from investor.data.yfinance_client import YFinanceClient
from investor.tools.technical_tools import compute_atr, compute_bollinger_bands
from investor.utils.logger import get_logger

logger = get_logger(__name__)
_yf = YFinanceClient()


# --------------------------------------------------------------------------- #
#  Tool functions (called by the agent's _execute_tools dispatcher)
# --------------------------------------------------------------------------- #

def get_market_movers(direction: str = "gainers", limit: int = 20) -> str:
    results = _yf.get_market_movers(direction=direction, limit=limit)
    return json.dumps(results)


def get_stock_snapshot(ticker: str) -> str:
    result = _yf.get_stock_snapshot(ticker)
    if result is None:
        return json.dumps({"error": f"No snapshot data for {ticker}"})
    return json.dumps(result)


def get_financials(ticker: str) -> str:
    results = _yf.get_financials(ticker)
    if not results:
        return json.dumps({"error": f"No financial data for {ticker}"})
    return json.dumps(results)


def get_technical_indicators(ticker: str) -> str:
    """Compute RSI, MACD, EMA, Bollinger Bands from OHLCV via yfinance + ta library."""
    bars = _yf.get_ohlcv_bars(ticker, days=60)
    if not bars:
        return json.dumps({"error": f"No OHLCV data for {ticker}"})

    rsi = _compute_rsi(bars)
    macd = _compute_macd(bars)
    ema_20 = _compute_ema(bars, 20)
    ema_50 = _compute_ema(bars, 50)
    bb = compute_bollinger_bands(bars)

    result = {
        "ticker": ticker.upper(),
        "rsi_14": rsi,
        "macd": macd,
        "ema_20": ema_20,
        "ema_50": ema_50,
        "bollinger_bands": bb,
    }
    return json.dumps(result)


def get_atr_targets(ticker: str, entry_price: float, atr_window: int = 14) -> str:
    """
    Calculate ATR-based price targets from OHLCV history.
    target_price = entry_price + 2.0 * ATR
    stop_loss    = entry_price - 1.0 * ATR
    """
    bars = _yf.get_ohlcv_bars(ticker, days=60)
    if not bars:
        return json.dumps({"error": f"No OHLCV data for {ticker}"})
    atr = compute_atr(bars, window=atr_window)
    if atr is None:
        return json.dumps({"error": f"Insufficient bars to compute ATR for {ticker}"})
    result = {
        "ticker": ticker.upper(),
        "entry_price": entry_price,
        "atr_14": round(atr, 4),
        "target_price": round(entry_price + 2.0 * atr, 2),
        "stop_loss": round(entry_price - 1.0 * atr, 2),
        "atr_pct": round(atr / entry_price * 100, 2),
    }
    return json.dumps(result)


def get_ticker_details(ticker: str) -> str:
    result = _yf.get_ticker_details(ticker)
    if result is None:
        return json.dumps({"error": f"No details for {ticker}"})
    return json.dumps(result)


def get_market_context() -> str:
    """
    Fetch macro market context: SPY, QQQ, VIX, TLT + regime classification.
    Call this FIRST before selecting any stocks.
    """
    result = _yf.get_market_context()
    return json.dumps(result)


def get_relative_strength(ticker: str, benchmark: str = "SPY") -> str:
    """
    Compute ticker's price return vs SPY over 1M and 3M.
    Returns rs_1m, rs_3m (positive = outperforming market), and rs_signal.
    """
    result = _yf.get_relative_strength(ticker, benchmark)
    return json.dumps(result)


def get_earnings_calendar(ticker: str) -> str:
    """
    Fetch next earnings date, days until earnings, and EPS/revenue estimates.
    Use this to detect pre-earnings catalyst setups.
    """
    result = _yf.get_earnings_calendar(ticker)
    return json.dumps(result)


def get_options_flow(ticker: str) -> str:
    """
    Compute put/call ratio from near-term options volume and open interest.
    Returns pc_vol_ratio, pc_oi_ratio, call/put totals, and a signal
    (BULLISH / NEUTRAL_BULLISH / NEUTRAL_BEARISH / BEARISH).
    """
    result = _yf.get_options_flow(ticker)
    return json.dumps(result)


def get_insider_activity(ticker: str) -> str:
    """
    Summarize insider buying/selling from SEC Form 4 filings (last 90 days).
    Returns buy/sell counts, total values, and a signal
    (NET_BUYER / MIXED_BUYER / NEUTRAL / NET_SELLER).
    """
    result = _yf.get_insider_activity(ticker)
    return json.dumps(result)


def get_sector_rs() -> str:
    """
    Compute relative strength of major sector ETFs vs SPY.
    Returns ranked sectors with rs_1m, rs_3m, and signal (LEADING/NEUTRAL/LAGGING).
    """
    result = _yf.get_sector_rs()
    return json.dumps(result)


def get_52w_breakouts(
    min_proximity_pct: float = 5.0,
    min_volume_ratio: float = 1.3,
) -> str:
    """
    Screen GROWTH_UNIVERSE for stocks at or near 52-week highs with elevated volume.
    Returns a JSON array sorted by proximity to 52w high.
    """
    result = _yf.get_52w_breakouts(
        min_proximity_pct=min_proximity_pct,
        min_volume_ratio=min_volume_ratio,
    )
    return json.dumps(result)


def get_earnings_surprises(min_surprise_pct: float = 5.0) -> str:
    """
    Screen GROWTH_UNIVERSE for stocks whose most recent quarter beat EPS estimates.
    Returns a JSON array sorted by surprise % (largest beat first).
    """
    result = _yf.get_earnings_surprises(min_surprise_pct=min_surprise_pct)
    return json.dumps(result)


def get_contrarian_screener(
    rsi_threshold: float = 32.0,
    ma200_discount: float = 0.92,
    max_results: int = 20,
) -> str:
    """
    Screen GROWTH_UNIVERSE for oversold contrarian candidates.

    Criteria (all must pass):
      1. RSI(14) ≤ rsi_threshold (default 32 — deep oversold)
      2. price ≤ 200-day MA × ma200_discount (default 0.92 = at least -8% below 200MA)
      3. ≥3 consecutive down-days (close < open)
      4. Market cap ≥ $500M

    Each result includes contrarian_tag=true and oversold_severity (EXTREME/MODERATE).
    Use when momentum screener returns 0 candidates, or when seeking sector-diversified
    entries during a downturn. Tags allow Claude to distinguish these from momentum picks.
    """
    result = _yf.get_contrarian_candidates(
        rsi_threshold=rsi_threshold,
        ma200_discount=ma200_discount,
        max_results=max_results,
    )
    return json.dumps(result)


def get_timeframe_alignment(ticker: str) -> str:
    """
    Check whether the daily trend is confirmed by weekly and monthly timeframes.

    Returns:
      daily_trend:   "up"/"down" (price vs EMA50 daily)
      weekly_trend:  "up"/"down"/"neutral" (price vs EMA13 weekly)
      monthly_trend: "up"/"down"/"neutral" (price vs EMA6 monthly)
      alignment:     ALIGNED_UP / ALIGNED_DOWN / PARTIAL_UP / PARTIAL_DOWN / MIXED
      tf_warning:    true if daily=up but weekly OR monthly is down

    When tf_warning=true, apply to scoring:
      - Technical score: −1pt
      - Conviction cap: MEDIUM (regardless of debate consensus)
    """
    result = _yf.get_timeframe_alignment(ticker)
    return json.dumps(result)


# --------------------------------------------------------------------------- #
#  Local technical computations (pure Python, no external API)
# --------------------------------------------------------------------------- #

def _compute_rsi(bars: list[dict], window: int = 14) -> float | None:
    try:
        import pandas as pd
        import ta.momentum as mom

        df = pd.DataFrame(bars)
        if "close" not in df.columns or len(df) < window + 1:
            return None
        rsi = mom.RSIIndicator(df["close"], window=window)
        val = rsi.rsi().iloc[-1]
        return round(float(val), 2) if not pd.isna(val) else None
    except Exception as e:
        logger.warning(f"RSI computation failed: {e}")
        return None


def _compute_macd(bars: list[dict]) -> dict[str, Any] | None:
    try:
        import pandas as pd
        import ta.trend as trend

        df = pd.DataFrame(bars)
        if "close" not in df.columns or len(df) < 26:
            return None
        macd_ind = trend.MACD(df["close"])
        return {
            "macd": round(float(macd_ind.macd().iloc[-1]), 4),
            "signal": round(float(macd_ind.macd_signal().iloc[-1]), 4),
            "histogram": round(float(macd_ind.macd_diff().iloc[-1]), 4),
        }
    except Exception as e:
        logger.warning(f"MACD computation failed: {e}")
        return None


def _compute_ema(bars: list[dict], window: int) -> float | None:
    try:
        import pandas as pd
        import ta.trend as trend

        df = pd.DataFrame(bars)
        if "close" not in df.columns or len(df) < window:
            return None
        ema = trend.EMAIndicator(df["close"], window=window)
        val = ema.ema_indicator().iloc[-1]
        return round(float(val), 2) if not pd.isna(val) else None
    except Exception as e:
        logger.warning(f"EMA({window}) computation failed: {e}")
        return None


# --------------------------------------------------------------------------- #
#  Claude tool definitions (JSON Schema)
# --------------------------------------------------------------------------- #

MARKET_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_market_context",
        "description": (
            "Fetch macro market context: SPY, QQQ, VIX fear index, TLT bond ETF. "
            "Returns current prices, daily change, SPY vs EMA50 trend signal, and a "
            "regime classification (e.g. ELEVATED_RISK_DOWNTREND). "
            "ALWAYS call this FIRST before selecting or scoring any stocks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_options_flow",
        "description": (
            "Compute put/call ratio from near-term options volume and open interest for a ticker. "
            "Aggregates call/put activity across the next 1-3 expirations (within 45 days). "
            "Returns pc_vol_ratio, pc_oi_ratio, and signal: "
            "BULLISH (pc_vol < 0.7, calls dominating = market expects upside), "
            "NEUTRAL_BULLISH (0.7–1.0), NEUTRAL_BEARISH (1.0–1.3), "
            "BEARISH (pc_vol > 1.3, elevated put buying = downside protection). "
            "Use this for top candidates to confirm or contradict price momentum."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_insider_activity",
        "description": (
            "Summarize insider buying and selling from SEC Form 4 filings over the last 90 days. "
            "Returns buy_count, sell_count, buy_value_usd, sell_value_usd, and signal: "
            "NET_BUYER (insiders buying aggressively — strong bullish signal), "
            "MIXED_BUYER (buying with some selling — mild bullish), "
            "NEUTRAL (no recent transactions or balanced), "
            "NET_SELLER (insiders selling — potential red flag). "
            "Also returns recent_purchases list with insider name, position, and value. "
            "NET_BUYER signal from a C-suite executive = +1pt bonus to sentiment score."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_sector_rs",
        "description": (
            "Compute relative strength of 12 major sector ETFs (SMH, XLK, IGV, XLC, XLY, XLF, "
            "IBB, XLE, XLI, XLU, ITA, ARKK) vs SPY over 1M and 3M periods. "
            "Returns ranked sectors with rs_1m, rs_3m, and signal: LEADING (outperforming SPY), "
            "NEUTRAL, or LAGGING. Use this to identify sector rotation opportunities and prioritize "
            "candidates from leading sectors. top_sectors lists LEADING sectors, bottom_sectors lists LAGGING ones. "
            "Call this early in the research process alongside get_market_context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_market_movers",
        "description": (
            "Get today's top gaining, losing, or most active US stocks. "
            "Use this first to discover which tickers are worth investigating."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["gainers", "losers", "actives"],
                    "description": "Which list to fetch",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of stocks to return (default 20)",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_stock_snapshot",
        "description": (
            "Get the current price, volume, and daily change for a single ticker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol, e.g. 'NVDA'"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_financials",
        "description": (
            "Get the last 4 quarters of financial data for a ticker: "
            "revenue, net income, EPS, and free cash flow."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_technical_indicators",
        "description": (
            "Get technical indicators for a ticker: RSI(14), MACD, EMA(20), EMA(50), "
            "and Bollinger Bands. Use this to assess momentum and overbought/oversold conditions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_atr_targets",
        "description": (
            "Calculate ATR-based price targets for a ticker given an entry price. "
            "Returns target_price (entry + 2×ATR) and stop_loss (entry − 1×ATR) "
            "derived from 14-day Average True Range. Use this instead of guessing price targets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "entry_price": {
                    "type": "number",
                    "description": "The intended entry price in USD",
                },
            },
            "required": ["ticker", "entry_price"],
        },
    },
    {
        "name": "get_ticker_details",
        "description": (
            "Get company metadata AND forward-looking estimates: full name, sector, market cap, "
            "forward EPS, forward P/E, PEG ratio, revenue/earnings growth YoY, gross margins, "
            "debt-to-equity, analyst target price, and analyst recommendation. "
            "Use this to assess valuation (forward_pe, peg_ratio) and growth trajectory "
            "(revenue_growth_yoy, earnings_growth_yoy) before scoring a candidate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_relative_strength",
        "description": (
            "Compute a stock's price return vs SPY benchmark over 1-month and 3-month periods. "
            "Returns rs_1m and rs_3m (positive = outperforming SPY) and rs_signal "
            "(STRONG_OUTPERFORM / OUTPERFORM / NEUTRAL / STRONG_UNDERPERFORM). "
            "Use this to confirm momentum quality — prefer stocks outperforming the market. "
            "A stock with STRONG_UNDERPERFORM rs_signal in a DOWNTREND regime is a red flag."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "benchmark": {
                    "type": "string",
                    "description": "Benchmark ticker (default: SPY)",
                    "default": "SPY",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_earnings_calendar",
        "description": (
            "Fetch next earnings date, days until earnings, and analyst EPS/revenue estimates. "
            "Use this to identify pre-earnings catalyst setups. "
            "If days_until_earnings < 7: high short-term catalyst, but also gap-risk — "
            "note this explicitly in key_catalysts and risk_factors. "
            "If days_until_earnings is None or far away (>60): no near-term earnings catalyst."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_52w_breakouts",
        "description": (
            "Screen the GROWTH_UNIVERSE for stocks at or near 52-week highs with elevated volume. "
            "This broadens the candidate pool beyond today's market movers — use it to find "
            "breakout setups that may not have appeared in gainers/actives lists. "
            "Results are sorted by proximity to 52w high (100% = at all-time high). "
            "volume_confirmed=true means volume ratio >= min_volume_ratio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_proximity_pct": {
                    "type": "number",
                    "description": "Max % below 52w high to include (default 5.0 = within 5%)",
                    "default": 5.0,
                },
                "min_volume_ratio": {
                    "type": "number",
                    "description": "Minimum volume vs 3-month average for confirmation (default 1.3)",
                    "default": 1.3,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_earnings_surprises",
        "description": (
            "Screen the GROWTH_UNIVERSE for stocks whose most recent quarter beat EPS estimates "
            "by at least min_surprise_pct%. Post-earnings-beat stocks often have continued momentum. "
            "Use this alongside market movers to find stocks that recently delivered strong earnings "
            "but may not be today's top movers. Sorted by surprise % (largest beat first)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_surprise_pct": {
                    "type": "number",
                    "description": "Minimum EPS surprise % to include (default 5.0)",
                    "default": 5.0,
                },
            },
            "required": [],
        },
    },
]

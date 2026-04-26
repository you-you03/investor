"""
Polygon.io REST API client.

Free tier limits:
  - 5 requests / minute
  - 15-minute data delay
  - No WebSocket streaming

Rate limiting strategy: sleep 12 seconds between calls to stay under 5 req/min.
"""

import json
import threading
import time
from datetime import date, timedelta
from typing import Any, Optional

import httpx

from investor.config import settings
from investor.utils.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.polygon.io"
_last_call_time: float = 0.0
_MIN_INTERVAL = 12.0  # seconds between calls (5 req/min = 12s apart)
_rate_lock = threading.Lock()  # ensures thread-safe rate limiting


def _rate_limited_get(url: str, params: dict[str, Any]) -> dict:
    global _last_call_time
    with _rate_lock:
        elapsed = time.time() - _last_call_time
        if elapsed < _MIN_INTERVAL:
            sleep_for = _MIN_INTERVAL - elapsed
            logger.debug(f"Rate limit: sleeping {sleep_for:.1f}s")
            time.sleep(sleep_for)

        params["apiKey"] = settings.polygon_api_key
        logger.debug(f"GET {url}")
        response = httpx.get(url, params=params, timeout=15.0)
        _last_call_time = time.time()

    if response.status_code == 429:
        logger.warning("Polygon rate limit hit, sleeping 60s")
        time.sleep(60)
        return _rate_limited_get(url, params)

    response.raise_for_status()
    return response.json()


class PolygonClient:
    def get_market_movers(
        self, direction: str = "gainers", limit: int = 20
    ) -> list[dict]:
        """
        Get today's top gainers, losers, or most active stocks.
        direction: 'gainers' | 'losers' | 'actives'
        Returns list of {ticker, price, change_pct, volume}
        """
        url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/{direction}"
        data = _rate_limited_get(url, {})
        tickers = data.get("tickers", [])[:limit]
        results = []
        for t in tickers:
            day = t.get("day", {})
            prev_day = t.get("prevDay", {})
            last_trade = t.get("lastTrade", {})
            price = last_trade.get("p") or day.get("c") or 0
            prev_close = prev_day.get("c") or 1
            change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
            results.append(
                {
                    "ticker": t.get("ticker"),
                    "price": price,
                    "change_pct": round(change_pct, 2),
                    "volume": day.get("v", 0),
                }
            )
        return results

    def get_stock_snapshot(self, ticker: str) -> Optional[dict]:
        """
        Get current snapshot for a single ticker.
        Returns {ticker, price, prev_close, open, high, low, volume, vwap, change_pct}
        Note: 15-minute delayed data on free tier.
        """
        url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker.upper()}"
        try:
            data = _rate_limited_get(url, {})
        except httpx.HTTPStatusError as e:
            logger.warning(f"Snapshot failed for {ticker}: {e}")
            return None

        t = data.get("ticker", {})
        if not t:
            return None

        day = t.get("day", {})
        prev_day = t.get("prevDay", {})
        last_trade = t.get("lastTrade", {})
        price = last_trade.get("p") or day.get("c") or 0
        prev_close = prev_day.get("c") or 1
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0

        return {
            "ticker": ticker.upper(),
            "price": price,
            "prev_close": prev_close,
            "open": day.get("o"),
            "high": day.get("h"),
            "low": day.get("l"),
            "volume": day.get("v"),
            "vwap": day.get("vw"),
            "change_pct": round(change_pct, 2),
        }

    def get_ohlcv_bars(
        self, ticker: str, days: int = 60
    ) -> list[dict]:
        """
        Get daily OHLCV bars for the past `days` calendar days.
        Used as input for technical indicator calculation.
        """
        to_date = date.today().isoformat()
        from_date = (date.today() - timedelta(days=days)).isoformat()
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker.upper()}/range/1/day/{from_date}/{to_date}"
        try:
            data = _rate_limited_get(
                url,
                {"adjusted": "true", "sort": "asc", "limit": 120},
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"OHLCV failed for {ticker}: {e}")
            return []

        results = []
        for bar in data.get("results", []):
            results.append(
                {
                    "date": bar.get("t"),  # unix ms timestamp
                    "open": bar.get("o"),
                    "high": bar.get("h"),
                    "low": bar.get("l"),
                    "close": bar.get("c"),
                    "volume": bar.get("v"),
                    "vwap": bar.get("vw"),
                }
            )
        return results

    def get_rsi(self, ticker: str, window: int = 14) -> Optional[float]:
        """Return most recent RSI value."""
        url = f"{BASE_URL}/v1/indicators/rsi/{ticker.upper()}"
        try:
            data = _rate_limited_get(
                url,
                {
                    "timespan": "day",
                    "adjusted": "true",
                    "window": window,
                    "series_type": "close",
                    "limit": 1,
                },
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"RSI failed for {ticker}: {e}")
            return None

        values = data.get("results", {}).get("values", [])
        return values[0].get("value") if values else None

    def get_macd(self, ticker: str) -> Optional[dict]:
        """Return most recent MACD values: {macd, signal, histogram}."""
        url = f"{BASE_URL}/v1/indicators/macd/{ticker.upper()}"
        try:
            data = _rate_limited_get(
                url,
                {
                    "timespan": "day",
                    "adjusted": "true",
                    "short_window": 12,
                    "long_window": 26,
                    "signal_window": 9,
                    "series_type": "close",
                    "limit": 1,
                },
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"MACD failed for {ticker}: {e}")
            return None

        values = data.get("results", {}).get("values", [])
        if not values:
            return None
        v = values[0]
        return {
            "macd": v.get("value"),
            "signal": v.get("signal"),
            "histogram": v.get("histogram"),
        }

    def get_ema(self, ticker: str, window: int = 20) -> Optional[float]:
        """Return most recent EMA value for given window."""
        url = f"{BASE_URL}/v1/indicators/ema/{ticker.upper()}"
        try:
            data = _rate_limited_get(
                url,
                {
                    "timespan": "day",
                    "adjusted": "true",
                    "window": window,
                    "series_type": "close",
                    "limit": 1,
                },
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"EMA({window}) failed for {ticker}: {e}")
            return None

        values = data.get("results", {}).get("values", [])
        return values[0].get("value") if values else None

    def get_financials(self, ticker: str) -> list[dict]:
        """
        Get last 4 quarters of financial data.
        Returns list of {period, revenue, net_income, eps, free_cash_flow}
        """
        url = f"{BASE_URL}/vX/reference/financials"
        try:
            data = _rate_limited_get(
                url,
                {
                    "ticker": ticker.upper(),
                    "timeframe": "quarterly",
                    "limit": 4,
                    "sort": "period_of_report_date",
                    "order": "desc",
                },
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"Financials failed for {ticker}: {e}")
            return []

        results = []
        for item in data.get("results", []):
            financials = item.get("financials", {})
            income = financials.get("income_statement", {})
            cash = financials.get("cash_flow_statement", {})
            results.append(
                {
                    "period": item.get("period_of_report_date"),
                    "revenue": income.get("revenues", {}).get("value"),
                    "net_income": income.get("net_income_loss", {}).get("value"),
                    "eps": income.get("basic_earnings_per_share", {}).get("value"),
                    "free_cash_flow": cash.get("net_cash_flow_from_operating_activities", {}).get("value"),
                }
            )
        return results

    def get_ticker_details(self, ticker: str) -> Optional[dict]:
        """Get basic company info: name, sector, description, market_cap."""
        url = f"{BASE_URL}/v3/reference/tickers/{ticker.upper()}"
        try:
            data = _rate_limited_get(url, {})
        except httpx.HTTPStatusError as e:
            logger.warning(f"Ticker details failed for {ticker}: {e}")
            return None

        result = data.get("results", {})
        return {
            "name": result.get("name"),
            "sector": result.get("sic_description"),
            "description": result.get("description"),
            "market_cap": result.get("market_cap"),
            "employees": result.get("total_employees"),
            "homepage": result.get("homepage_url"),
        }

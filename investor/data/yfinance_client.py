"""
yfinance-based market data client.
Replaces polygon_client.py — no API key required.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd
import yfinance as yf

from investor.utils import cache as cache_store
from investor.utils.logger import get_logger

# Sector ETFs for rotation analysis
SECTOR_ETFS: dict[str, str] = {
    "Semiconductors": "SMH",
    "Technology": "XLK",
    "Cloud/Software": "IGV",
    "Communication": "XLC",
    "Consumer Discretionary": "XLY",
    "Financials": "XLF",
    "Healthcare/Biotech": "IBB",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Defense/Aerospace": "ITA",
    "Disruptive Innovation": "ARKK",
}

# Full universe for Phase 1 screening (snapshot + technicals only)
SCREEN_UNIVERSE: list[str] = [
    # AI / Semiconductor
    "NVDA", "AMD", "ALAB", "CRDO", "MRVL", "AVGO", "ARM", "QCOM",
    "AAOI", "COHR", "MPWR", "KLAC", "LRCX", "ENTG", "SMCI", "AMAT",
    "MU", "TSM", "ASML", "INTC", "ON", "TXN", "ADI",
    # Cloud / Enterprise Software
    "MSFT", "AMZN", "GOOGL", "META", "CRM", "NOW", "SNOW", "DDOG",
    "MDB", "NET", "ZS", "CRWD", "PANW", "HUBS", "SHOP", "TTD",
    "GTLB", "VEEV", "WDAY", "ADSK", "ORCL", "INTU", "TEAM",
    # Space / Defense / Gov-Tech
    "RKLB", "ASTS", "PLTR", "AXON", "LUNR", "LMT", "RTX", "NOC",
    "GD", "LDOS", "SAIC", "BAH",
    # Fintech / Consumer Finance
    "SQ", "HOOD", "SOFI", "AFRM", "COIN", "NU", "V", "MA", "PYPL",
    "FIS", "FISV", "GPN", "WEX", "TOST",
    # Healthcare / Biotech
    "MRNA", "RXRX", "CERE", "BEAM", "LLY", "NVO", "ABBV", "BMY",
    "REGN", "VRTX", "GILD", "AMGN", "ISRG", "DXCM", "GEHC",
    # Energy / Power Infrastructure
    "VST", "CEG", "GEV", "NEE", "FSLR", "ENPH", "XOM", "CVX",
    "COP", "SLB", "HAL", "OXY",
    # Industrials / Manufacturing
    "CAT", "DE", "EMR", "ETN", "HON", "GE", "ITW", "PH", "ROK", "AME",
    # Consumer Discretionary / Retail
    "TSLA", "UBER", "ABNB", "DASH", "RBLX", "NKE", "LULU", "DECK", "BKNG",
    # Financial Services / Banking
    "JPM", "GS", "MS", "BAC", "WFC", "BX", "KKR", "APO", "SCHW", "CME",
    # Consumer Staples
    "COST", "WMT", "PG", "KO", "PEP",
    # Real Estate / REITs
    "AMT", "PLD", "EQIX", "DLR", "SBAC",
]

# Backward-compat alias used by 52w-breakout and earnings-surprise screeners
GROWTH_UNIVERSE = SCREEN_UNIVERSE

logger = get_logger(__name__)

# Map plan direction names to yfinance screen IDs
_SCREEN_MAP = {
    "gainers": "day_gainers",
    "losers": "day_losers",
    "actives": "most_actives",
}


class YFinanceClient:
    # ------------------------------------------------------------------
    # Market movers
    # ------------------------------------------------------------------

    def get_market_movers(self, direction: str = "actives", limit: int = 20) -> list[dict]:
        screen_id = _SCREEN_MAP.get(direction, "most_actives")
        cache_key = f"movers_{screen_id}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached[:limit]

        try:
            result = yf.screen(screen_id, size=limit)
            quotes = result.get("quotes", [])
        except Exception as e:
            logger.warning(f"yf.screen({screen_id}) failed: {e}")
            return []

        movers = []
        for q in quotes[:limit]:
            movers.append({
                "ticker": q.get("symbol", ""),
                "name": q.get("longName") or q.get("shortName", ""),
                "price": q.get("regularMarketPrice"),
                "change_pct": q.get("regularMarketChangePercent"),
                "volume": q.get("regularMarketVolume"),
                "market_cap": q.get("marketCap"),
            })

        cache_store.set(cache_key, movers)
        return movers

    # ------------------------------------------------------------------
    # Snapshot (current price + basic info)
    # ------------------------------------------------------------------

    def get_stock_snapshot(self, ticker: str) -> dict | None:
        cache_key = f"snapshot_{ticker.upper()}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info
        except Exception as e:
            logger.warning(f"fast_info failed for {ticker}: {e}")
            return None

        try:
            result = {
                "ticker": ticker.upper(),
                "price": getattr(fi, "last_price", None),
                "open": getattr(fi, "open", None),
                "high": getattr(fi, "day_high", None),
                "low": getattr(fi, "day_low", None),
                "prev_close": getattr(fi, "previous_close", None),
                "volume": getattr(fi, "last_volume", None),
                "market_cap": getattr(fi, "market_cap", None),
                "fifty_two_week_high": getattr(fi, "year_high", None),
                "fifty_two_week_low": getattr(fi, "year_low", None),
            }
            # Compute daily change pct
            if result["price"] and result["prev_close"]:
                result["change_pct"] = round(
                    (result["price"] - result["prev_close"]) / result["prev_close"] * 100, 2
                )
        except Exception as e:
            logger.warning(f"snapshot parse failed for {ticker}: {e}")
            return None

        cache_store.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # OHLCV bars
    # ------------------------------------------------------------------

    def get_ohlcv_bars(self, ticker: str, days: int = 60) -> list[dict]:
        cache_key = f"ohlcv_{ticker.upper()}_{days}d"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        try:
            hist = yf.Ticker(ticker).history(period=f"{days}d")
        except Exception as e:
            logger.warning(f"history() failed for {ticker}: {e}")
            return []

        if hist is None or hist.empty:
            return []

        bars = []
        for ts, row in hist.iterrows():
            bars.append({
                "date": ts.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })

        cache_store.set(cache_key, bars)
        return bars

    # ------------------------------------------------------------------
    # Financials (quarterly)
    # ------------------------------------------------------------------

    def get_financials(self, ticker: str) -> list[dict]:
        cache_key = f"financials_{ticker.upper()}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        try:
            t = yf.Ticker(ticker)
            qf = t.quarterly_financials  # columns = quarters, rows = line items
            qi = t.quarterly_income_stmt
        except Exception as e:
            logger.warning(f"quarterly_financials failed for {ticker}: {e}")
            return []

        if qf is None or qf.empty:
            return []

        quarters = []
        for col in qf.columns[:4]:  # last 4 quarters
            label = col.strftime("%Y-Q%q") if hasattr(col, "strftime") else str(col)[:7]

            def _get(df: Any, key: str) -> float | None:
                if df is None or df.empty:
                    return None
                for row_label in df.index:
                    if key.lower() in str(row_label).lower():
                        val = df.at[row_label, col]
                        if pd.notna(val):
                            return float(val)
                return None

            revenue = _get(qf, "Total Revenue") or _get(qf, "Revenue")
            net_income = _get(qf, "Net Income")
            eps = _get(qi, "Basic EPS") if qi is not None and not qi.empty else None
            operating_cf = None
            try:
                cf = t.quarterly_cashflow
                if cf is not None and not cf.empty and col in cf.columns:
                    operating_cf = _get(cf, "Operating Cash Flow") or _get(cf, "Cash Flow From Operations")
            except Exception:
                pass

            quarters.append({
                "period": label,
                "revenue": revenue,
                "net_income": net_income,
                "eps": eps,
                "free_cash_flow": operating_cf,
            })

        cache_store.set(cache_key, quarters)
        return quarters

    # ------------------------------------------------------------------
    # Ticker details (company metadata + forward estimates)
    # ------------------------------------------------------------------

    def get_ticker_details(self, ticker: str) -> dict | None:
        cache_key = f"details_{ticker.upper()}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        try:
            info = yf.Ticker(ticker).info
        except Exception as e:
            logger.warning(f"Ticker.info failed for {ticker}: {e}")
            return None

        if not info:
            return None

        result = {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "description": (info.get("longBusinessSummary", "") or "")[:500],
            "market_cap": info.get("marketCap"),
            "employees": info.get("fullTimeEmployees"),
            "country": info.get("country", ""),
            "website": info.get("website", ""),
            # Forward-looking estimates (key for catalyst investing)
            "forward_eps": info.get("forwardEps"),
            "forward_pe": info.get("forwardPE"),
            "trailing_pe": info.get("trailingPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "revenue_growth_yoy": info.get("revenueGrowth"),   # e.g. 0.42 = +42%
            "earnings_growth_yoy": info.get("earningsGrowth"),  # e.g. 0.81 = +81%
            "gross_margins": info.get("grossMargins"),
            "operating_margins": info.get("operatingMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "return_on_equity": info.get("returnOnEquity"),
            "analyst_target_price": info.get("targetMeanPrice"),
            "analyst_recommendation": info.get("recommendationKey"),  # e.g. "buy", "strong_buy"
            "analyst_count": info.get("numberOfAnalystOpinions"),
        }

        cache_store.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Relative strength vs benchmark
    # ------------------------------------------------------------------

    def get_relative_strength(self, ticker: str, benchmark: str = "SPY") -> dict:
        """
        Compute ticker's return vs benchmark over 1M and 3M periods.
        RS > 0 means outperforming the market.
        """
        cache_key = f"rs_{ticker.upper()}_{benchmark.upper()}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        result: dict = {"ticker": ticker.upper(), "benchmark": benchmark.upper()}

        try:
            ticker_bars = self.get_ohlcv_bars(ticker, days=65)
            bench_bars = self.get_ohlcv_bars(benchmark, days=65)

            if not ticker_bars or not bench_bars:
                return {"error": f"Insufficient data for {ticker} or {benchmark}"}

            def _period_return(bars: list[dict], lookback_days: int) -> float | None:
                if len(bars) < lookback_days:
                    return None
                start = bars[-lookback_days]["close"]
                end = bars[-1]["close"]
                return round((end - start) / start * 100, 2) if start else None

            t_1m = _period_return(ticker_bars, 21)
            t_3m = _period_return(ticker_bars, 63)
            b_1m = _period_return(bench_bars, 21)
            b_3m = _period_return(bench_bars, 63)

            result["return_1m_pct"] = t_1m
            result["return_3m_pct"] = t_3m
            result["benchmark_return_1m_pct"] = b_1m
            result["benchmark_return_3m_pct"] = b_3m
            result["rs_1m"] = round(t_1m - b_1m, 2) if t_1m is not None and b_1m is not None else None
            result["rs_3m"] = round(t_3m - b_3m, 2) if t_3m is not None and b_3m is not None else None

            # Classify relative strength
            rs_1m = result["rs_1m"]
            rs_3m = result["rs_3m"]
            if rs_1m is not None and rs_3m is not None:
                if rs_1m > 5 and rs_3m > 10:
                    result["rs_signal"] = "STRONG_OUTPERFORM"
                elif rs_1m > 0 and rs_3m > 0:
                    result["rs_signal"] = "OUTPERFORM"
                elif rs_1m < -5 and rs_3m < -10:
                    result["rs_signal"] = "STRONG_UNDERPERFORM"
                else:
                    result["rs_signal"] = "NEUTRAL"
            else:
                result["rs_signal"] = "UNKNOWN"

        except Exception as e:
            logger.warning(f"Relative strength failed for {ticker}: {e}")
            result["error"] = str(e)

        cache_store.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Earnings calendar
    # ------------------------------------------------------------------

    def get_earnings_calendar(self, ticker: str) -> dict:
        """
        Fetch next earnings date and related calendar events.
        """
        cache_key = f"calendar_{ticker.upper()}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        result: dict = {"ticker": ticker.upper()}

        try:
            t = yf.Ticker(ticker)
            cal = t.calendar  # dict or DataFrame depending on version

            # yfinance returns different formats — handle both
            if cal is None:
                result["earnings_date"] = None
            elif isinstance(cal, dict):
                dates = cal.get("Earnings Date", [])
                result["earnings_date"] = str(dates[0]) if dates else None
                result["earnings_high_estimate"] = cal.get("Earnings High")
                result["earnings_low_estimate"] = cal.get("Earnings Low")
                result["revenue_estimate"] = cal.get("Revenue High")
                result["ex_dividend_date"] = str(cal.get("Ex-Dividend Date", "")) or None
            else:
                # DataFrame: transpose so columns become keys
                try:
                    d = cal.T.to_dict()
                    first = next(iter(d.values()), {})
                    dates = first.get("Earnings Date", [])
                    result["earnings_date"] = str(dates[0]) if isinstance(dates, list) and dates else str(dates) if dates else None
                except Exception:
                    result["earnings_date"] = None

            # Days until earnings
            if result.get("earnings_date") and result["earnings_date"] != "None":
                from datetime import date as _date
                try:
                    edate = pd.to_datetime(result["earnings_date"]).date()
                    result["days_until_earnings"] = (edate - _date.today()).days
                except Exception:
                    result["days_until_earnings"] = None

        except Exception as e:
            logger.warning(f"Earnings calendar failed for {ticker}: {e}")
            result["error"] = str(e)

        cache_store.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Macro market context
    # ------------------------------------------------------------------

    def get_market_context(self) -> dict:
        """
        Fetch macro market context: SPY, QQQ, VIX, TLT.
        Returns price/change data + regime classification for stock selection.
        """
        cache_key = "market_context"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        symbols = {
            "SPY": "S&P 500 ETF",
            "QQQ": "NASDAQ 100 ETF",
            "^VIX": "VIX Fear Index",
            "TLT": "20Y Treasury Bond ETF",
        }

        result: dict = {}
        for sym, label in symbols.items():
            try:
                fi = yf.Ticker(sym).fast_info
                price = getattr(fi, "last_price", None)
                prev = getattr(fi, "previous_close", None)
                change_pct = round((price - prev) / prev * 100, 2) if price and prev else None
                result[sym] = {"label": label, "price": price, "change_pct": change_pct}
            except Exception as e:
                logger.warning(f"market_context failed for {sym}: {e}")
                result[sym] = {"label": label, "error": str(e)}

        # SPY vs EMA50 (trend regime signal)
        try:
            spy_bars = self.get_ohlcv_bars("SPY", days=60)
            if len(spy_bars) >= 50:
                closes = pd.Series([b["close"] for b in spy_bars])
                ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
                spy_price = result.get("SPY", {}).get("price")
                if spy_price:
                    result["SPY"]["ema_50"] = round(ema50, 2)
                    result["SPY"]["above_ema50"] = float(spy_price) > ema50
        except Exception as e:
            logger.warning(f"SPY EMA50 failed: {e}")

        # Regime classification
        vix = result.get("^VIX", {}).get("price")
        spy_above = result.get("SPY", {}).get("above_ema50")

        if vix and vix > 30:
            regime = "HIGH_FEAR"
        elif vix and vix > 20:
            regime = "ELEVATED_RISK"
        else:
            regime = "NORMAL"

        if spy_above is False:
            regime = f"{regime}_DOWNTREND"

        regime_notes = {
            "HIGH_FEAR": "VIX>30: 市場パニック状態。新規エントリーは極めて慎重に。確信度HIGHのみ検討。",
            "HIGH_FEAR_DOWNTREND": "VIX>30かつSPY<EMA50: ベアマーケット。防衛的姿勢。新規ロングは原則停止。",
            "ELEVATED_RISK": "VIX>20: リスク上昇中。確信度MEDIUMは見送り。HIGHのみ検討。",
            "ELEVATED_RISK_DOWNTREND": "VIX>20かつSPY<EMA50: 調整局面。慎重なエントリーのみ。ポジションサイズを半分以下に。",
            "NORMAL": "通常リスク環境。通常の判断基準を適用。",
            "NORMAL_DOWNTREND": "VIX低いがSPY<EMA50: 静かな下落。新規エントリーは控えめに。",
        }

        result["regime"] = regime
        result["regime_note"] = regime_notes.get(regime, "")

        cache_store.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Sector ETF relative strength ranking
    # ------------------------------------------------------------------

    def get_sector_rs(self) -> dict:
        """
        Compute relative strength of major sector ETFs vs SPY over 1M and 3M.
        Returns ranked sectors so Claude can prioritize candidates from leading sectors.
        """
        cache_key = "sector_rs"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        spy_bars = self.get_ohlcv_bars("SPY", days=65)

        def _period_return(bars: list[dict], lookback: int) -> float | None:
            if len(bars) < lookback:
                return None
            start = bars[-lookback]["close"]
            end = bars[-1]["close"]
            return round((end - start) / start * 100, 2) if start else None

        b_1m = _period_return(spy_bars, 21)
        b_3m = _period_return(spy_bars, 63)

        def _check_sector(sector: str, etf: str) -> dict:
            try:
                bars = self.get_ohlcv_bars(etf, days=65)
                if not bars:
                    return {"sector": sector, "etf": etf, "error": "no data"}

                t_1m = _period_return(bars, 21)
                t_3m = _period_return(bars, 63)
                rs_1m = round(t_1m - b_1m, 2) if t_1m is not None and b_1m is not None else None
                rs_3m = round(t_3m - b_3m, 2) if t_3m is not None and b_3m is not None else None

                if rs_1m is not None and rs_3m is not None:
                    if rs_1m > 3 and rs_3m > 5:
                        signal = "LEADING"
                    elif rs_1m < -3 and rs_3m < -5:
                        signal = "LAGGING"
                    else:
                        signal = "NEUTRAL"
                else:
                    signal = "UNKNOWN"

                return {
                    "sector": sector,
                    "etf": etf,
                    "return_1m": t_1m,
                    "return_3m": t_3m,
                    "rs_1m": rs_1m,
                    "rs_3m": rs_3m,
                    "signal": signal,
                }
            except Exception as e:
                logger.debug(f"Sector RS failed for {etf}: {e}")
                return {"sector": sector, "etf": etf, "error": str(e)}

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(_check_sector, s, e): s for s, e in SECTOR_ETFS.items()}
            for future in as_completed(futures):
                results.append(future.result())

        def _sort_key(x: dict) -> float:
            if "error" in x:
                return -999.0
            rs3 = x.get("rs_3m")
            rs1 = x.get("rs_1m")
            if rs3 is not None:
                return float(rs3)
            if rs1 is not None:
                return float(rs1)
            return -999.0

        results.sort(key=_sort_key, reverse=True)

        top = [r["sector"] for r in results if r.get("signal") == "LEADING"]
        bottom = [r["sector"] for r in results if r.get("signal") == "LAGGING"]

        output = {
            "spy_return_1m": b_1m,
            "spy_return_3m": b_3m,
            "ranked": results,
            "top_sectors": top,
            "bottom_sectors": bottom,
        }

        cache_store.set(cache_key, output)
        return output

    # ------------------------------------------------------------------
    # 52-week high breakout screener
    # ------------------------------------------------------------------

    def get_52w_breakouts(
        self,
        universe: list[str] | None = None,
        min_proximity_pct: float = 5.0,
        min_volume_ratio: float = 1.3,
    ) -> list[dict]:
        """
        Screen for stocks at or near 52-week highs with elevated volume.

        min_proximity_pct=5.0 means current price >= 52w_high * 0.95.
        min_volume_ratio=1.3 means today's volume >= 1.3x 3-month average.
        Returns results sorted by proximity (closest to 52w high first).
        """
        if universe is None:
            universe = GROWTH_UNIVERSE

        cache_key = f"screener_52w_{min_proximity_pct}_{min_volume_ratio}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        def _check(ticker: str) -> dict | None:
            try:
                fi = yf.Ticker(ticker).fast_info
                price = getattr(fi, "last_price", None)
                year_high = getattr(fi, "year_high", None)
                prev_close = getattr(fi, "previous_close", None)
                last_vol = getattr(fi, "last_volume", None)
                avg_vol_3m = getattr(fi, "three_month_average_volume", None)

                if not price or not year_high or year_high <= 0:
                    return None

                proximity_pct = round(price / year_high * 100, 1)
                if proximity_pct < (100 - min_proximity_pct):
                    return None

                change_pct = (
                    round((price - prev_close) / prev_close * 100, 2)
                    if price and prev_close else None
                )
                vol_ratio = (
                    round(last_vol / avg_vol_3m, 2)
                    if last_vol and avg_vol_3m and avg_vol_3m > 0 else None
                )

                return {
                    "ticker": ticker,
                    "price": round(price, 2),
                    "year_high": round(year_high, 2),
                    "proximity_pct": proximity_pct,
                    "change_pct": change_pct,
                    "volume_ratio": vol_ratio,
                    "volume_confirmed": vol_ratio is not None and vol_ratio >= min_volume_ratio,
                }
            except Exception as e:
                logger.debug(f"52w check failed for {ticker}: {e}")
                return None

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_check, t): t for t in universe}
            for future in as_completed(futures):
                r = future.result()
                if r is not None:
                    results.append(r)

        results.sort(key=lambda x: x["proximity_pct"], reverse=True)
        cache_store.set(cache_key, results)
        return results

    # ------------------------------------------------------------------
    # Earnings surprise screener
    # ------------------------------------------------------------------

    def get_earnings_surprises(
        self,
        universe: list[str] | None = None,
        min_surprise_pct: float = 5.0,
    ) -> list[dict]:
        """
        Find stocks whose most recent quarter showed a positive EPS surprise.

        min_surprise_pct=5.0 means actual EPS beat estimate by >= 5%.
        Returns results sorted by surprise % (largest beat first).
        """
        if universe is None:
            universe = GROWTH_UNIVERSE

        cache_key = f"screener_earn_surprise_{min_surprise_pct}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        def _check(ticker: str) -> dict | None:
            try:
                history = yf.Ticker(ticker).earnings_history
                if history is None or history.empty:
                    return None

                recent = history.iloc[-1]
                surprise_raw = recent.get("surprisePercent") if hasattr(recent, "get") else getattr(recent, "surprisePercent", None)
                if surprise_raw is None or pd.isna(surprise_raw):
                    return None

                # yfinance returns surprisePercent as fraction (0.08 = 8%)
                surprise_pct = round(float(surprise_raw) * 100, 1)
                if surprise_pct < min_surprise_pct:
                    return None

                actual = recent.get("epsActual") if hasattr(recent, "get") else getattr(recent, "epsActual", None)
                estimate = recent.get("epsEstimate") if hasattr(recent, "get") else getattr(recent, "epsEstimate", None)
                quarter = str(history.index[-1])[:10]

                # Only include if reported within the last 6 months
                try:
                    days_since = (pd.Timestamp.now() - pd.to_datetime(quarter)).days
                    if days_since > 180:
                        return None
                except Exception:
                    pass

                return {
                    "ticker": ticker,
                    "quarter": quarter,
                    "eps_actual": round(float(actual), 3) if actual is not None and not pd.isna(actual) else None,
                    "eps_estimate": round(float(estimate), 3) if estimate is not None and not pd.isna(estimate) else None,
                    "eps_surprise_pct": surprise_pct,
                }
            except Exception as e:
                logger.debug(f"Earnings surprise check failed for {ticker}: {e}")
                return None

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_check, t): t for t in universe}
            for future in as_completed(futures):
                r = future.result()
                if r is not None:
                    results.append(r)

        results.sort(key=lambda x: x["eps_surprise_pct"], reverse=True)
        cache_store.set(cache_key, results)
        return results

    # ------------------------------------------------------------------
    # Options flow (put/call ratio)
    # ------------------------------------------------------------------

    def get_options_flow(self, ticker: str, max_expirations: int = 3, max_days: int = 45) -> dict:
        """
        Compute put/call ratio from near-term options volume and open interest.

        Aggregates call/put volume and OI across the next `max_expirations` expirations
        within `max_days` days. Returns pc_vol_ratio, pc_oi_ratio, and a signal.

        Signal:
          BULLISH          — pc_vol < 0.7  (call-dominant, market expects upside)
          NEUTRAL_BULLISH  — 0.7 ≤ pc_vol < 1.0
          NEUTRAL_BEARISH  — 1.0 ≤ pc_vol < 1.3
          BEARISH          — pc_vol ≥ 1.3  (put-dominant, elevated downside protection)
        """
        cache_key = f"options_{ticker.upper()}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        result: dict = {"ticker": ticker.upper()}

        try:
            t = yf.Ticker(ticker)
            expirations = t.options  # sorted tuple of "YYYY-MM-DD" strings
            if not expirations:
                result["error"] = "No options data"
                return result

            cutoff = (pd.Timestamp.now() + pd.Timedelta(days=max_days)).date()
            near_exps = [
                exp for exp in expirations
                if pd.to_datetime(exp).date() <= cutoff
            ][:max_expirations]

            if not near_exps:
                # If no expirations within window, take the nearest one anyway
                near_exps = list(expirations[:1])

            total_call_vol = 0.0
            total_put_vol = 0.0
            total_call_oi = 0.0
            total_put_oi = 0.0

            for exp in near_exps:
                try:
                    chain = t.option_chain(exp)
                    calls = chain.calls
                    puts = chain.puts
                    total_call_vol += float(calls["volume"].fillna(0).sum())
                    total_put_vol += float(puts["volume"].fillna(0).sum())
                    total_call_oi += float(calls["openInterest"].fillna(0).sum())
                    total_put_oi += float(puts["openInterest"].fillna(0).sum())
                except Exception as e:
                    logger.debug(f"option_chain({exp}) failed for {ticker}: {e}")
                    continue

            pc_vol = round(total_put_vol / total_call_vol, 3) if total_call_vol > 0 else None
            pc_oi = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None

            if pc_vol is not None:
                if pc_vol < 0.7:
                    signal = "BULLISH"
                elif pc_vol < 1.0:
                    signal = "NEUTRAL_BULLISH"
                elif pc_vol < 1.3:
                    signal = "NEUTRAL_BEARISH"
                else:
                    signal = "BEARISH"
            else:
                signal = "UNKNOWN"

            result.update({
                "expirations_used": near_exps,
                "call_volume": int(total_call_vol),
                "put_volume": int(total_put_vol),
                "call_oi": int(total_call_oi),
                "put_oi": int(total_put_oi),
                "pc_vol_ratio": pc_vol,
                "pc_oi_ratio": pc_oi,
                "signal": signal,
            })

        except Exception as e:
            logger.warning(f"Options flow failed for {ticker}: {e}")
            result["error"] = str(e)

        cache_store.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Insider buying activity (SEC Form 4 via yfinance)
    # ------------------------------------------------------------------

    def get_insider_activity(self, ticker: str, lookback_days: int = 90) -> dict:
        """
        Summarize insider buying/selling from SEC Form 4 filings (last 90 days).

        Uses yfinance's insider_transactions DataFrame.
        Signal:
          NET_BUYER   — purchase value > sale value × 1.5 (insiders buying aggressively)
          MIXED_BUYER — purchases present but also significant selling
          NEUTRAL     — no recent transactions or balanced
          NET_SELLER  — sale value > purchase value × 1.5
        """
        cache_key = f"insider_{ticker.upper()}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        result: dict = {"ticker": ticker.upper()}

        try:
            t = yf.Ticker(ticker)
            df = t.insider_transactions

            if df is None or df.empty:
                result["signal"] = "NO_DATA"
                result["note"] = "No insider transaction data available"
                cache_store.set(cache_key, result)
                return result

            # Normalize column names (yfinance can vary)
            df.columns = [c.strip() for c in df.columns]

            # Filter to lookback window
            date_col = next((c for c in df.columns if "date" in c.lower()), None)
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                cutoff = pd.Timestamp.now() - pd.Timedelta(days=lookback_days)
                df = df[df[date_col] >= cutoff]

            if df.empty:
                result["signal"] = "NEUTRAL"
                result["note"] = f"No transactions in last {lookback_days} days"
                cache_store.set(cache_key, result)
                return result

            # Identify transaction type column
            tx_col = next((c for c in df.columns if "transaction" in c.lower() or "text" in c.lower()), None)
            val_col = next((c for c in df.columns if "value" in c.lower()), None)
            shares_col = next((c for c in df.columns if "shares" in c.lower()), None)

            buys = df[df[tx_col].str.contains("Purchase|Buy", case=False, na=False)] if tx_col else pd.DataFrame()
            sells = df[df[tx_col].str.contains("Sale|Sell", case=False, na=False)] if tx_col else pd.DataFrame()

            def _sum_col(sub_df: pd.DataFrame, col: str | None) -> float:
                if col is None or sub_df.empty or col not in sub_df.columns:
                    return 0.0
                return float(sub_df[col].fillna(0).abs().sum())

            buy_value = _sum_col(buys, val_col)
            sell_value = _sum_col(sells, val_col)
            buy_shares = _sum_col(buys, shares_col)
            sell_shares = _sum_col(sells, shares_col)

            # Signal logic
            if buy_value > 0 and sell_value == 0:
                signal = "NET_BUYER"
            elif sell_value > 0 and buy_value == 0:
                signal = "NET_SELLER"
            elif buy_value > sell_value * 1.5:
                signal = "NET_BUYER"
            elif sell_value > buy_value * 1.5:
                signal = "NET_SELLER"
            elif buy_value > 0:
                signal = "MIXED_BUYER"
            else:
                signal = "NEUTRAL"

            recent_buys = []
            if not buys.empty and tx_col and date_col:
                for _, row in buys.head(3).iterrows():
                    entry: dict = {}
                    if date_col in row.index:
                        entry["date"] = str(row[date_col])[:10]
                    insider_col = next((c for c in df.columns if "insider" in c.lower() or "name" in c.lower()), None)
                    if insider_col and insider_col in row.index:
                        entry["insider"] = str(row[insider_col])
                    pos_col = next((c for c in df.columns if "position" in c.lower() or "title" in c.lower()), None)
                    if pos_col and pos_col in row.index:
                        entry["position"] = str(row[pos_col])
                    if val_col and val_col in row.index:
                        entry["value"] = float(row[val_col]) if pd.notna(row[val_col]) else None
                    if shares_col and shares_col in row.index:
                        entry["shares"] = float(row[shares_col]) if pd.notna(row[shares_col]) else None
                    recent_buys.append(entry)

            result.update({
                "lookback_days": lookback_days,
                "buy_count": len(buys),
                "sell_count": len(sells),
                "buy_value_usd": round(buy_value) if buy_value else 0,
                "sell_value_usd": round(sell_value) if sell_value else 0,
                "buy_shares": round(buy_shares) if buy_shares else 0,
                "sell_shares": round(sell_shares) if sell_shares else 0,
                "signal": signal,
                "recent_purchases": recent_buys,
            })

        except Exception as e:
            logger.warning(f"Insider activity failed for {ticker}: {e}")
            result["error"] = str(e)
            result["signal"] = "ERROR"

        cache_store.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # News
    # ------------------------------------------------------------------

    def get_news(self, ticker: str, max_items: int = 10) -> list[dict]:
        cache_key = f"news_{ticker.upper()}"
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

        try:
            news_data = yf.Ticker(ticker).news
        except Exception as e:
            logger.warning(f"Ticker.news failed for {ticker}: {e}")
            return []

        if not news_data:
            return []

        articles = []
        for item in news_data[:max_items]:
            content = item.get("content", {})
            articles.append({
                "title": content.get("title", item.get("title", "")),
                "source": (content.get("provider", {}) or {}).get("displayName", ""),
                "url": (content.get("canonicalUrl", {}) or {}).get("url", ""),
                "published_at": content.get("pubDate", ""),
                "summary": content.get("summary", ""),
            })

        cache_store.set(cache_key, articles)
        return articles

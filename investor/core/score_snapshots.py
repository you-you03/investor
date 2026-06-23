"""Helpers for tracking scored tickers after research/watchlist reviews."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from investor.tools.market_tools import get_stock_snapshot
from investor.supabase_sync import sync_local_to_supabase
from investor.utils.logger import get_logger

logger = get_logger(__name__)

SNAPSHOTS_PATH = Path("data/score_snapshots.json")
WEEK_KEYS = ("week1", "week2", "week3", "week4")

CONVICTION_SCORE = {
    "HIGH": 8.0,
    "MEDIUM": 7.0,
    "LOW": 6.0,
}

SEMICONDUCTOR_TICKERS = {
    "NVDA", "AMD", "AVGO", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MU",
    "MRVL", "ARM", "ALAB", "COHR", "AAOI", "CRDO", "ON", "QCOM", "INTC",
}
SOFTWARE_TICKERS = {
    "TEAM", "CRM", "NOW", "SNOW", "DDOG", "CRWD", "PANW", "NET", "MDB",
    "PLTR", "ADBE", "MSFT", "ORCL", "ZS", "OKTA",
}
INDUSTRIAL_TICKERS = {"VRT", "ETN", "GE", "HON", "CAT", "DE"}
UTILITY_TICKERS = {"VST", "CEG", "NEE", "SO", "DUK", "TLN"}
SPACE_TICKERS = {"ASTS", "RKLB", "LUNR", "IRDM"}
FINANCIAL_TICKERS = {"JPM", "BAC", "GS", "MS", "C", "WFC", "SCHW", "HOOD"}
HEALTHCARE_TICKERS = {"WAT", "LLY", "NVO", "UNH", "ISRG", "TMO", "DHR"}
ENERGY_TICKERS = {"XOM", "CVX", "COP", "SLB", "OXY"}
AIRLINE_TICKERS = {"UAL", "DAL", "AAL", "LUV"}


def infer_conviction(score: float | int | None = None, conviction: str | None = None) -> str:
    """Normalize explicit conviction or infer it from the 0-10 score."""
    normalized = (conviction or "").strip().upper()
    if normalized in {"HIGH", "MEDIUM", "LOW"}:
        return normalized
    if score is None:
        return ""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return ""
    if value >= 8.0:
        return "HIGH"
    if value >= 7.0:
        return "MEDIUM"
    return "LOW"


def score_from_result(result: dict[str, Any]) -> float | None:
    """Return the score used for follow-up tracking."""
    for key in ("score", "new_score"):
        if result.get(key) is not None:
            try:
                return float(result[key])
            except (TypeError, ValueError):
                return None
    conviction = infer_conviction(conviction=result.get("conviction"))
    return CONVICTION_SCORE.get(conviction)


def sector_etf_for_ticker(ticker: str) -> str:
    """Map a ticker to the benchmark ETF used for sector-adjusted alpha."""
    symbol = ticker.upper()
    if symbol in SEMICONDUCTOR_TICKERS:
        return "SMH"
    if symbol in SOFTWARE_TICKERS:
        return "IGV"
    if symbol in INDUSTRIAL_TICKERS:
        return "XLI"
    if symbol in UTILITY_TICKERS:
        return "XLU"
    if symbol in SPACE_TICKERS:
        return "ARKK"
    if symbol in FINANCIAL_TICKERS:
        return "XLF"
    if symbol in HEALTHCARE_TICKERS:
        return "XLV"
    if symbol in ENERGY_TICKERS:
        return "XLE"
    if symbol in AIRLINE_TICKERS:
        return "JETS"
    return "QQQ"


def classify_market_regime(
    spy_return_pct: float | None,
    qqq_return_pct: float | None,
    sector_return_pct: float | None,
    vix_change_pct: float | None,
    ten_year_yield_change_bps: float | None,
) -> str:
    """Classify the broad regime for a scored ticker's follow-up window."""
    spy = spy_return_pct
    qqq = qqq_return_pct
    sector = sector_return_pct
    vix = vix_change_pct
    yield_bps = ten_year_yield_change_bps

    if spy is None:
        return "unknown"
    if spy <= -2.0 or (vix is not None and vix >= 15.0):
        return "risk_off"
    if yield_bps is not None and yield_bps >= 20.0 and qqq is not None and qqq < spy:
        return "rates_headwind"
    if sector is not None and sector >= spy + 2.0:
        return "sector_tailwind"
    if spy >= 2.0 and qqq is not None and qqq >= spy and (vix is None or vix <= 5.0):
        return "risk_on_growth"
    if spy >= 2.0:
        return "risk_on"
    return "neutral"


def _load_snapshots(path: Path | None = None) -> dict[str, Any]:
    target = path or SNAPSHOTS_PATH
    if target.exists():
        try:
            return json.loads(target.read_text())
        except Exception:
            pass
    return {"snapshots": []}


def _save_snapshots(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or SNAPSHOTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _fetch_price(ticker: str) -> tuple[float | None, str]:
    try:
        raw = json.loads(get_stock_snapshot(ticker))
    except Exception as e:
        logger.warning("snapshot price fetch failed for %s: %s", ticker, e)
        return None, ""
    price = raw.get("price") or raw.get("current_price")
    company_name = raw.get("company_name") or raw.get("name") or ""
    try:
        return float(price), str(company_name or "")
    except (TypeError, ValueError):
        return None, str(company_name or "")


def _empty_weeks(scored_at: date) -> dict[str, dict[str, Any]]:
    return {
        f"week{i}": {
            "target_date": (scored_at + timedelta(days=7 * i)).isoformat(),
            "price": None,
            "return_pct": None,
            "spy_return_pct": None,
            "qqq_return_pct": None,
            "sector_etf": None,
            "sector_return_pct": None,
            "alpha_pct": None,
            "alpha_vs_spy": None,
            "alpha_vs_qqq": None,
            "alpha_vs_sector": None,
            "vix_change_pct": None,
            "ten_year_yield_change_bps": None,
            "market_regime": None,
            "fetched_at": None,
        }
        for i in range(1, 5)
    }


def add_score_snapshots(
    *,
    run_id: str,
    source: str,
    results: list[dict[str, Any]],
    scored_at: date | None = None,
) -> int:
    """Append scored tickers to score_snapshots.json for 1-4 week tracking."""
    scored_date = scored_at or date.today()
    data = _load_snapshots()
    snapshots = data.setdefault("snapshots", [])
    existing_keys = {
        (
            str(item.get("run_id")),
            str(item.get("ticker", "")).upper(),
            str(item.get("source", "research")),
        )
        for item in snapshots
    }

    added = 0
    total = len(results)
    for rank, result in enumerate(results, 1):
        ticker = str(result.get("ticker") or "").upper()
        if not ticker:
            continue
        score = score_from_result(result)
        if score is None:
            continue
        key = (run_id, ticker, source)
        if key in existing_keys:
            continue

        price = result.get("price_at_score") or result.get("entry_price")
        company_name = result.get("company_name") or ""
        if price is None:
            price, fetched_name = _fetch_price(ticker)
            company_name = company_name or fetched_name
        try:
            price_at_score = float(price)
        except (TypeError, ValueError):
            logger.warning("skip score snapshot without price: %s", ticker)
            continue

        conviction = infer_conviction(score=score, conviction=result.get("conviction"))
        snapshot = {
            "run_id": run_id,
            "source": source,
            "scored_at": scored_date.isoformat(),
            "ticker": ticker,
            "company_name": company_name,
            "score": round(score, 2),
            "conviction": conviction,
            "score_breakdown": result.get("score_breakdown") or {},
            "rank_in_run": rank,
            "total_scored_in_run": total,
            "price_at_score": round(price_at_score, 4),
            "passed_threshold": score >= 7.0,
            "sector_etf": sector_etf_for_ticker(ticker),
            "macro_regime": result.get("macro_regime") or "",
        }
        snapshot.update(_empty_weeks(scored_date))
        for wk_key in WEEK_KEYS:
            snapshot[wk_key]["sector_etf"] = snapshot["sector_etf"]
        snapshots.append(snapshot)
        existing_keys.add(key)
        added += 1

    if added:
        _save_snapshots(data)
        logger.info("Added %d score snapshot(s) from %s | run_id=%s", added, source, run_id)
        sync_local_to_supabase("score_snapshots")
    return added

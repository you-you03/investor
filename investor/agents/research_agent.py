"""
Research Agent — pure data collection (no Anthropic SDK).

Claude Code (the current session) acts as the agent:
  1. run `python skills/research.py` to collect and print raw market data
  2. Claude reads the output, screens candidates, and analyzes each ticker
  3. Claude saves results to data/research_history.json

This module handles data collection and persistence only.
"""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

from investor.data.yfinance_client import SCREEN_UNIVERSE
from investor.tools.market_tools import (
    get_52w_breakouts,
    get_atr_targets,
    get_earnings_surprises,
    get_financials,
    get_insider_activity,
    get_market_context,
    get_market_movers,
    get_options_flow,
    get_sector_rs,
    get_stock_snapshot,
    get_technical_indicators,
    get_ticker_details,
)
from investor.tools.news_tools import get_news
from investor.core.score_snapshots import add_score_snapshots
from investor.utils.logger import get_logger

logger = get_logger(__name__)

HISTORY_PATH = Path("data/research_history.json")
WATCHLIST_PATH = Path("data/watchlist.json")
REPORTS_DIR = Path("reports/research")


def load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text())
        except Exception:
            pass
    return {"runs": []}


def _load_watchlist_tickers() -> list[str]:
    """Load active watchlist tickers from data/watchlist.json."""
    if not WATCHLIST_PATH.exists():
        return []
    try:
        data = json.loads(WATCHLIST_PATH.read_text())
        return [
            item["ticker"].upper()
            for item in data.get("items", [])
            if item.get("status") == "active" and item.get("ticker")
        ]
    except Exception as e:
        logger.warning(f"Failed to load watchlist: {e}")
        return []


def save_run(run_id: str, candidates: list[dict]) -> None:
    """Save a completed research run to data/research_history.json."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    history = load_history()
    history["runs"].append({
        "run_id": run_id,
        "date": today,
        "candidates": candidates,
    })
    HISTORY_PATH.write_text(json.dumps(history, indent=2))
    logger.info(f"Saved {len(candidates)} candidates | run_id={run_id}")
    add_score_snapshots(run_id=run_id, source="research", results=candidates, scored_at=date.fromisoformat(today))
    _save_research_markdown(run_id, today, candidates)


def _save_research_markdown(run_id: str, today: str, candidates: list[dict]) -> None:
    """Generate and save a markdown report to reports/research/research_{date}.md."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"research_{today}.md"

    conviction_label = {"HIGH": "HIGH確信", "MEDIUM": "MEDIUM確信", "LOW": "LOW確信"}

    lines: list[str] = [
        f"# リサーチレポート — {today}",
        "",
        f"**run_id**: `{run_id}`",
        "",
        "---",
        "",
        f"## 選択候補 ({len(candidates)} 銘柄)",
        "",
    ]

    for i, c in enumerate(candidates, 1):
        ticker = c.get("ticker", "—")
        conviction = c.get("conviction", "—")
        label = conviction_label.get(conviction, conviction)
        entry = c.get("entry_price")
        target = c.get("target_price")
        stop = c.get("stop_loss")
        alloc = c.get("allocation_pct")
        shares = c.get("shares")
        rationale = c.get("rationale", "—")
        risks = c.get("risks", "—")

        upside = f"+{(target - entry) / entry * 100:.1f}%" if target and entry else "—"
        downside = f"{(stop - entry) / entry * 100:.1f}%" if stop and entry else "—"

        lines += [
            f"### {i}. {ticker} — {label}",
            "",
            "| 項目 | 値 |",
            "|------|-----|",
            f"| エントリー | ${entry:.2f} |" if entry else "| エントリー | — |",
            f"| 目標 | ${target:.2f} ({upside}) |" if target else "| 目標 | — |",
            f"| ストップ | ${stop:.2f} ({downside}) |" if stop else "| ストップ | — |",
            f"| 配分 | {alloc}% / {shares}株 |" if alloc else "| 配分 | — |",
            "",
            f"**根拠**: {rationale}",
            "",
            f"**リスク**: {risks}",
            "",
            "---",
            "",
        ]

    lines += [
        f"*生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {HISTORY_PATH}*",
    ]

    report_path.write_text("\n".join(lines))
    logger.info(f"Saved markdown report to {report_path}")


def collect_ticker_data(ticker: str) -> dict:
    """Collect all available data for a single ticker. No AI calls."""
    result: dict = {"ticker": ticker}
    try:
        result["snapshot"] = json.loads(get_stock_snapshot(ticker))
    except Exception as e:
        result["snapshot"] = {"error": str(e)}
    try:
        result["technicals"] = json.loads(get_technical_indicators(ticker))
    except Exception as e:
        result["technicals"] = {"error": str(e)}
    try:
        result["financials"] = json.loads(get_financials(ticker))
    except Exception as e:
        result["financials"] = {"error": str(e)}
    try:
        result["details"] = json.loads(get_ticker_details(ticker))
    except Exception as e:
        result["details"] = {"error": str(e)}
    try:
        result["news"] = json.loads(get_news(ticker, limit=5))
    except Exception as e:
        result["news"] = {"error": str(e)}
    try:
        result["options_flow"] = json.loads(get_options_flow(ticker))
    except Exception as e:
        result["options_flow"] = {"error": str(e)}
    try:
        result["insider_activity"] = json.loads(get_insider_activity(ticker))
    except Exception as e:
        result["insider_activity"] = {"error": str(e)}

    # ATR targets using current price as entry estimate
    snapshot = result.get("snapshot", {})
    price = snapshot.get("price") or snapshot.get("current_price")
    if price and not snapshot.get("error"):
        try:
            result["atr_targets"] = json.loads(get_atr_targets(ticker, float(price)))
        except Exception as e:
            result["atr_targets"] = {"error": str(e)}

    return result


def collect_market_data(
    tickers: list[str] | None = None,
    max_tickers: int = 15,
    parallel: bool = True,
) -> dict:
    """
    Collect raw market data for research. Returns a dict with:
      - macro_context: SPY/QQQ/VIX regime classification
      - movers: top gainers/losers/actives
      - screeners: 52w_breakouts + earnings_surprises from GROWTH_UNIVERSE
      - ticker_data: per-ticker full data
      - run_id: UUID for this collection run
    """
    run_id = str(uuid.uuid4())

    # Always load watchlist tickers for inclusion
    watchlist_tickers = _load_watchlist_tickers()
    logger.info(f"Watchlist tickers ({len(watchlist_tickers)}): {watchlist_tickers}")

    # --- Phase 1: fetch macro context + screeners + movers in parallel ---
    logger.info("Fetching macro context, screeners, and market movers...")

    def _fetch_macro() -> dict:
        try:
            return json.loads(get_market_context())
        except Exception as e:
            return {"error": str(e)}

    def _fetch_sector_rs() -> dict:
        try:
            return json.loads(get_sector_rs())
        except Exception as e:
            logger.warning(f"Sector RS failed: {e}")
            return {"error": str(e)}

    def _fetch_52w() -> list:
        try:
            return json.loads(get_52w_breakouts())
        except Exception as e:
            logger.warning(f"52w breakout screener failed: {e}")
            return []

    def _fetch_earn_surprises() -> list:
        try:
            return json.loads(get_earnings_surprises())
        except Exception as e:
            logger.warning(f"Earnings surprise screener failed: {e}")
            return []

    if tickers:
        selected = [t.upper() for t in tickers]
        movers: dict = {"source": "user_specified", "tickers": selected}
        with ThreadPoolExecutor(max_workers=4) as executor:
            f_macro = executor.submit(_fetch_macro)
            f_sector = executor.submit(_fetch_sector_rs)
            f_52w = executor.submit(_fetch_52w)
            f_earn = executor.submit(_fetch_earn_surprises)
            macro_context = f_macro.result()
            sector_rs = f_sector.result()
            breakouts = f_52w.result()
            earn_surprises = f_earn.result()
    else:
        def _fetch_gainers() -> list:
            try:
                return json.loads(get_market_movers("gainers", limit=20))
            except Exception:
                return []

        def _fetch_actives() -> list:
            try:
                return json.loads(get_market_movers("actives", limit=20))
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=6) as executor:
            f_macro = executor.submit(_fetch_macro)
            f_sector = executor.submit(_fetch_sector_rs)
            f_52w = executor.submit(_fetch_52w)
            f_earn = executor.submit(_fetch_earn_surprises)
            f_gainers = executor.submit(_fetch_gainers)
            f_actives = executor.submit(_fetch_actives)

            macro_context = f_macro.result()
            sector_rs = f_sector.result()
            breakouts = f_52w.result()
            earn_surprises = f_earn.result()
            gainers = f_gainers.result()
            actives = f_actives.result()

        movers = {"gainers": gainers, "actives": actives, "watchlist": watchlist_tickers}

        # Combine and deduplicate: watchlist first (priority), then movers
        seen: set[str] = set()
        combined: list[str] = []

        # Watchlist tickers get priority slots (up to 5)
        for t in watchlist_tickers[:5]:
            if t not in seen:
                seen.add(t)
                combined.append(t)

        # Fill remaining slots with market movers
        for item in (gainers if isinstance(gainers, list) else []) + (actives if isinstance(actives, list) else []):
            t = item.get("ticker") or item.get("symbol") if isinstance(item, dict) else None
            if t and t not in seen:
                seen.add(t)
                combined.append(t)

        selected = combined[:max_tickers]

    top_sectors = sector_rs.get("top_sectors", []) if isinstance(sector_rs, dict) else []
    logger.info(
        f"Macro regime: {macro_context.get('regime', 'unknown')} | "
        f"Top sectors: {top_sectors} | "
        f"52w breakouts: {len(breakouts)} | "
        f"Earnings surprises: {len(earn_surprises)}"
    )
    logger.info(f"Collecting deep data for {len(selected)} tickers: {selected}")

    # --- Phase 2: deep per-ticker data collection ---
    ticker_data: dict[str, dict] = {}
    if parallel and len(selected) > 1:
        with ThreadPoolExecutor(max_workers=min(len(selected), 5)) as executor:
            futures = {executor.submit(collect_ticker_data, t): t for t in selected}
            for future in as_completed(futures):
                t = futures[future]
                try:
                    ticker_data[t] = future.result()
                    logger.info(f"  Collected: {t}")
                except Exception as e:
                    logger.warning(f"  Failed: {t} — {e}")
                    ticker_data[t] = {"ticker": t, "error": str(e)}
    else:
        for t in selected:
            ticker_data[t] = collect_ticker_data(t)
            logger.info(f"  Collected: {t}")

    return {
        "run_id": run_id,
        "date": date.today().isoformat(),
        "macro_context": macro_context,
        "sector_rs": sector_rs,
        "movers": movers,
        "screeners": {
            "52w_breakouts": breakouts,
            "earnings_surprises": earn_surprises,
        },
        "ticker_data": ticker_data,
    }


# ---------------------------------------------------------------------------
# Phase 1: Lightweight screen (snapshot + technicals only)
# ---------------------------------------------------------------------------

def collect_screen_ticker_data(ticker: str) -> dict:
    """Collect snapshot + technicals only. Used in Phase 1 wide screen."""
    result: dict = {"ticker": ticker}
    try:
        result["snapshot"] = json.loads(get_stock_snapshot(ticker))
    except Exception as e:
        result["snapshot"] = {"error": str(e)}
    try:
        result["technicals"] = json.loads(get_technical_indicators(ticker))
    except Exception as e:
        result["technicals"] = {"error": str(e)}
    return result


def collect_screen_data(
    extra_tickers: list[str] | None = None,
    parallel: bool = True,
) -> dict:
    """
    Phase 1 wide screen: collect snapshot + technicals for all SCREEN_UNIVERSE
    tickers plus any watchlist/extra tickers. Returns lightweight JSON for
    Claude to perform fast candidate shortlisting (no financials/news/options).
    """
    run_id = str(uuid.uuid4())

    # Merge SCREEN_UNIVERSE + watchlist + any caller-specified extras
    watchlist_tickers = _load_watchlist_tickers()
    seen: set[str] = set()
    universe: list[str] = []
    for t in (watchlist_tickers + SCREEN_UNIVERSE + (extra_tickers or [])):
        t = t.upper()
        if t not in seen:
            seen.add(t)
            universe.append(t)

    logger.info(f"Phase 1 screen: {len(universe)} tickers total")

    # Fetch macro context + sector RS in parallel while collecting ticker data
    def _fetch_macro() -> dict:
        try:
            return json.loads(get_market_context())
        except Exception as e:
            return {"error": str(e)}

    def _fetch_sector_rs() -> dict:
        try:
            return json.loads(get_sector_rs())
        except Exception as e:
            return {"error": str(e)}

    ticker_data: dict[str, dict] = {}
    if parallel:
        with ThreadPoolExecutor(max_workers=8) as executor:
            f_macro = executor.submit(_fetch_macro)
            f_sector = executor.submit(_fetch_sector_rs)
            futures = {executor.submit(collect_screen_ticker_data, t): t for t in universe}
            macro_context = f_macro.result()
            sector_rs = f_sector.result()
            for future in as_completed(futures):
                t = futures[future]
                try:
                    ticker_data[t] = future.result()
                except Exception as e:
                    ticker_data[t] = {"ticker": t, "error": str(e)}
    else:
        macro_context = _fetch_macro()
        sector_rs = _fetch_sector_rs()
        for t in universe:
            ticker_data[t] = collect_screen_ticker_data(t)
            logger.info(f"  Screened: {t}")

    logger.info(f"Phase 1 complete: {len(ticker_data)} tickers collected")

    return {
        "run_id": run_id,
        "date": date.today().isoformat(),
        "phase": "screen",
        "macro_context": macro_context,
        "sector_rs": sector_rs,
        "watchlist_tickers": watchlist_tickers,
        "ticker_data": ticker_data,
    }

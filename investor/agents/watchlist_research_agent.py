"""
Watchlist Research Agent — targeted deep research on active watchlist stocks.

No Anthropic SDK calls. Claude Code (the current session) acts as the analyst:
  1. `python skills/watchlist_research.py` → collects data for active watchlist tickers
  2. Claude reads the output, evaluates each ticker, proposes actions
  3. Claude calls `--save` to update watchlist.json and persist the run

Action options Claude may propose per ticker:
  ESCALATE  — strong setup, promote to /decision consideration
  MAINTAIN  — thesis intact, keep watching
  REMOVE    — thesis broken or stock deteriorated, remove from watchlist
  ADD_NOTE  — update score/note but no action change needed
"""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

from investor.agents.research_agent import collect_ticker_data
from investor.core.score_snapshots import add_score_snapshots
from investor.supabase_sync import sync_local_to_supabase
from investor.tools.market_tools import get_market_context, get_sector_rs
from investor.utils.logger import get_logger

logger = get_logger(__name__)

WATCHLIST_PATH = Path("data/watchlist.json")
WR_HISTORY_PATH = Path("data/watchlist_research_history.json")
REPORTS_DIR = Path("reports/research")


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_watchlist() -> dict:
    if WATCHLIST_PATH.exists():
        try:
            return json.loads(WATCHLIST_PATH.read_text())
        except Exception:
            pass
    return {"items": []}


def _save_watchlist(data: dict) -> None:
    WATCHLIST_PATH.write_text(json.dumps(data, indent=2))
    sync_local_to_supabase("watchlist")


def _load_wr_history() -> dict:
    if WR_HISTORY_PATH.exists():
        try:
            return json.loads(WR_HISTORY_PATH.read_text())
        except Exception:
            pass
    return {"runs": []}


def get_latest_wr_run_id() -> str | None:
    history = _load_wr_history()
    runs = history.get("runs", [])
    return runs[-1]["run_id"] if runs else None


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def collect_watchlist_research_data(parallel: bool = True) -> dict:
    """
    Collect deep research data for all active watchlist tickers.
    Returns structured JSON for Claude to analyze.
    """
    run_id = str(uuid.uuid4())
    watchlist = load_watchlist()
    active_items = [item for item in watchlist.get("items", []) if item.get("status") == "active"]

    if not active_items:
        logger.info("No active watchlist items found.")
        return {
            "run_id": run_id,
            "date": date.today().isoformat(),
            "watchlist_items": [],
            "ticker_data": {},
            "macro_context": {},
            "sector_rs": {},
        }

    tickers = [item["ticker"].upper() for item in active_items]
    logger.info(f"Watchlist research: {len(tickers)} active tickers: {tickers}")

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
    if parallel and len(tickers) > 1:
        with ThreadPoolExecutor(max_workers=min(len(tickers), 6)) as executor:
            f_macro = executor.submit(_fetch_macro)
            f_sector = executor.submit(_fetch_sector_rs)
            futures = {executor.submit(collect_ticker_data, t): t for t in tickers}
            macro_context = f_macro.result()
            sector_rs = f_sector.result()
            for future in as_completed(futures):
                t = futures[future]
                try:
                    ticker_data[t] = future.result()
                    logger.info(f"  Collected: {t}")
                except Exception as e:
                    logger.warning(f"  Failed: {t} — {e}")
                    ticker_data[t] = {"ticker": t, "error": str(e)}
    else:
        macro_context = _fetch_macro()
        sector_rs = _fetch_sector_rs()
        for t in tickers:
            ticker_data[t] = collect_ticker_data(t)
            logger.info(f"  Collected: {t}")

    return {
        "run_id": run_id,
        "date": date.today().isoformat(),
        "macro_context": macro_context,
        "sector_rs": sector_rs,
        "watchlist_items": active_items,
        "ticker_data": ticker_data,
    }


# ---------------------------------------------------------------------------
# Save Claude's analysis
# ---------------------------------------------------------------------------

def save_watchlist_research(run_id: str, results: list[dict]) -> None:
    """
    Apply Claude's analysis back to watchlist.json and persist the run.

    Each result dict should include:
      ticker        : str
      action        : ESCALATE | MAINTAIN | REMOVE | ADD_NOTE
      new_score     : float | None
      note          : str | None   (appended to reason)
      flag          : str | None   (replaces last_monitor_flag)
    """
    today = date.today().isoformat()

    watchlist = load_watchlist()
    items_map = {item["ticker"].upper(): item for item in watchlist.get("items", [])}

    for result in results:
        ticker = result.get("ticker", "").upper()
        if ticker not in items_map:
            continue
        item = items_map[ticker]
        action = result.get("action", "MAINTAIN").upper()

        item["last_monitor_date"] = today

        if result.get("new_score") is not None:
            item["last_score"] = result["new_score"]

        if result.get("note"):
            existing = item.get("reason", "")
            item["reason"] = f"{existing} | {today} {result['note']}" if existing else result["note"]

        if result.get("flag"):
            item["last_monitor_flag"] = result["flag"]

        if action == "REMOVE":
            item["status"] = "removed"
            item["last_monitor_flag"] = "REMOVED"
        elif action == "ESCALATE":
            item["last_monitor_flag"] = "ESCALATE_TO_DECISION"

    _save_watchlist(watchlist)
    logger.info(f"Updated watchlist.json with {len(results)} results")

    # Persist run to history
    WR_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = _load_wr_history()
    history["runs"].append({
        "run_id": run_id,
        "date": today,
        "results": results,
    })
    WR_HISTORY_PATH.write_text(json.dumps(history, indent=2))
    logger.info(f"Saved watchlist research run | run_id={run_id}")
    add_score_snapshots(run_id=run_id, source="watchlist_research", results=results, scored_at=date.fromisoformat(today))
    _save_watchlist_research_markdown(run_id, today, results)
    sync_local_to_supabase("watchlist_research", "report_artifacts")


def _save_watchlist_research_markdown(run_id: str, today: str, results: list[dict]) -> None:
    """Generate and save a markdown report to reports/research/watchlist_research_{date}.md."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"watchlist_research_{today}.md"

    action_icon = {
        "ESCALATE": "🚀",
        "MAINTAIN": "✅",
        "REMOVE": "❌",
        "ADD_NOTE": "📝",
    }

    escalated = [r for r in results if r.get("action", "").upper() == "ESCALATE"]
    removed = [r for r in results if r.get("action", "").upper() == "REMOVE"]

    lines: list[str] = [
        f"# ウォッチリストリサーチ — {today}",
        "",
        f"**run_id**: `{run_id}`",
        "",
        "---",
        "",
        "## サマリー",
        "",
        "| 指標 | 値 |",
        "|---|---|",
        f"| 対象銘柄 | {len(results)} 銘柄 |",
        f"| 🚀 ESCALATE | {len(escalated)} 銘柄 |",
        f"| ❌ REMOVE | {len(removed)} 銘柄 |",
        "",
        "---",
        "",
        "## 銘柄別結果",
        "",
        "| Ticker | アクション | スコア | メモ |",
        "|--------|-----------|-------|------|",
    ]

    for r in results:
        action = r.get("action", "—").upper()
        icon = action_icon.get(action, "")
        ticker = r.get("ticker", "—")
        score = r.get("new_score")
        note = r.get("note", "—")
        score_str = f"{score:.1f}" if score is not None else "—"
        lines.append(f"| {ticker} | {icon} {action} | {score_str} | {note} |")

    lines += [
        "",
        "---",
        "",
        f"*生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {WR_HISTORY_PATH}*",
    ]

    report_path.write_text("\n".join(lines))
    logger.info(f"Saved markdown report to {report_path}")


def load_wr_run(run_id: str) -> list[dict]:
    """Load results for a given watchlist research run_id."""
    history = _load_wr_history()
    for run in history.get("runs", []):
        if run.get("run_id") == run_id:
            return run.get("results", [])
    return []


# ---------------------------------------------------------------------------
# Format for /decision
# ---------------------------------------------------------------------------

def format_watchlist_for_decision(run_id: str | None = None) -> str:
    """
    Format watchlist research results as a decision context block.
    Called by decision_agent.py when --watchlist-run-id is provided.
    """
    history = _load_wr_history()
    runs = history.get("runs", [])
    if not runs:
        return "## Watchlist Research\nNo watchlist research runs found.\n"

    if run_id:
        run = next((r for r in runs if r["run_id"] == run_id), None)
        if not run:
            return f"## Watchlist Research\nRun not found: {run_id}\n"
    else:
        run = runs[-1]

    results = run.get("results", [])
    escalated = [r for r in results if r.get("action", "").upper() == "ESCALATE"]

    lines = [
        f"## Watchlist Research (run_id: {run['run_id']}, date: {run['date']})",
        f"Escalated: {len(escalated)} / Total: {len(results)}",
        "",
    ]

    if escalated:
        lines.append("### ESCALATED — prioritize in decision")
        for r in escalated:
            lines.append(
                f"- **{r['ticker']}** score={r.get('new_score', 'N/A')} | {r.get('note', '')}"
            )
        lines.append("")

    lines.append("### All Watchlist Results")
    lines.append("```json")
    lines.append(json.dumps(results, indent=2))
    lines.append("```")

    return "\n".join(lines)

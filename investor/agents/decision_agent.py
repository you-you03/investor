"""
Decision Agent — pure data load/format/notify (no Anthropic SDK).

Claude Code (the current session) acts as the debate agent:
  1. `python skills/decision.py` prints research candidates to stdout
  2. Claude reads, runs Bullish/Bearish/PM debate internally
  3. Claude calls `python skills/decision.py send --data '...'` to post to Slack

This module handles persistence reads, position sizing, and Slack delivery only.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from investor.config import settings
from investor.notifications.slack import SlackNotifier
from investor.utils.logger import get_logger

logger = get_logger(__name__)

HISTORY_PATH = Path("data/research_history.json")
PORTFOLIO_PATH = Path("data/portfolio.csv")
DECISION_HISTORY_PATH = Path("data/decision_history.json")

# Diversified position sizing (not Half Kelly).
# Max 25% per position to spread risk across 3-5 stocks.
_CONVICTION_FRACTION: dict[str, float] = {
    "HIGH": 0.225,  # 20-25% midpoint
    "MEDIUM": 0.15,
    "LOW": 0.10,
}


def load_run(run_id: str) -> list[dict]:
    """Load research candidates for a given run_id."""
    if not HISTORY_PATH.exists():
        return []
    try:
        history = json.loads(HISTORY_PATH.read_text())
        for run in history.get("runs", []):
            if run.get("run_id") == run_id:
                return run.get("candidates", [])
    except Exception:
        pass
    return []


def get_latest_run_id() -> str | None:
    if not HISTORY_PATH.exists():
        return None
    try:
        history = json.loads(HISTORY_PATH.read_text())
        runs = history.get("runs", [])
        if runs:
            return runs[-1]["run_id"]
    except Exception:
        pass
    return None


def load_open_positions() -> list[dict]:
    if not PORTFOLIO_PATH.exists():
        return []
    try:
        with open(PORTFOLIO_PATH) as f:
            reader = csv.DictReader(f)
            return [row for row in reader if row.get("status") == "open"]
    except Exception:
        return []


def compute_position_size(conviction: str) -> float:
    """Return position size in USD using diversified (non-concentrated) sizing."""
    fraction = _CONVICTION_FRACTION.get(conviction.upper(), 0.10)
    return settings.available_capital_usd * fraction


def enrich_proposals(raw_proposals: list[dict], candidates: list[dict]) -> list[dict]:
    """
    Enrich raw proposals (from Claude's analysis) with position sizing
    and research data. raw_proposals should be a list of dicts with keys:
      ticker, action, conviction, entry_price_range, rationale,
      key_catalysts, risk_factors, time_horizon
    """
    candidate_map = {c.get("ticker", "").upper(): c for c in candidates}
    proposals = []
    for p in raw_proposals:
        ticker = p.get("ticker", "UNKNOWN").upper()
        conviction = p.get("conviction", "LOW").upper()
        position_size_usd = compute_position_size(conviction)
        entry_price = _parse_entry_price(p.get("entry_price_range", ""))
        shares_suggested = position_size_usd / entry_price if entry_price else None

        research = candidate_map.get(ticker, {})
        proposals.append({
            "ticker": ticker,
            "action": p.get("action", "HOLD").upper(),
            "conviction": conviction,
            "entry_price_range": p.get("entry_price_range"),
            "target_price": p.get("target_price") or research.get("target_price"),
            "stop_loss": p.get("stop_loss") or research.get("stop_loss"),
            "position_size_usd": round(position_size_usd, 0),
            "shares_suggested": round(shares_suggested, 1) if shares_suggested else None,
            "rationale": p.get("rationale"),
            "key_catalysts": p.get("key_catalysts", []),
            "risk_factors": p.get("risk_factors", []),
            "time_horizon": p.get("time_horizon"),
        })
    return proposals


def send_proposals(proposals: list[dict]) -> None:
    """Send enriched proposals to Slack."""
    slack = SlackNotifier()
    slack.send_proposals(proposals)
    logger.info(f"Sent {len(proposals)} proposals to Slack")


def log_decision_history(
    proposals: list[dict],
    run_id: str,
    all_candidates: list[dict],
) -> None:
    """Append decision record to decision_history.json.

    Tracks which tickers were BUY vs PASS so calibration and weekly_review
    can compute PASS rates and no-trade weeks over time.
    """
    history: list[dict] = []
    if DECISION_HISTORY_PATH.exists():
        try:
            history = json.loads(DECISION_HISTORY_PATH.read_text())
        except Exception:
            history = []

    buy_tickers = [p["ticker"] for p in proposals if p.get("action") == "BUY"]
    all_tickers = [c.get("ticker", "") for c in all_candidates if c.get("ticker")]
    pass_tickers = [t for t in all_tickers if t not in buy_tickers]

    history.append({
        "date": date.today().isoformat(),
        "run_id": run_id,
        "candidates_evaluated": all_tickers,
        "buy_decisions": buy_tickers,
        "pass_decisions": pass_tickers,
        "no_trade_week": len(buy_tickers) == 0,
    })
    DECISION_HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    logger.info(f"Logged decision: {len(buy_tickers)} BUY / {len(pass_tickers)} PASS")


def _get_calibration_report() -> str:
    """Return calibration stats output for prepending to the decision context."""
    script = Path("scripts/show_calibration_stats.py")
    if not script.exists():
        return ""
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _parse_entry_price(entry_price_range: str) -> float | None:
    if not entry_price_range:
        return None
    try:
        parts = entry_price_range.replace("$", "").split("-")
        nums = [float(p.strip()) for p in parts if p.strip()]
        if len(nums) == 2:
            return (nums[0] + nums[1]) / 2
        if len(nums) == 1:
            return nums[0]
    except (ValueError, AttributeError):
        pass
    return None


def format_research_for_claude(run_id: str, watchlist_run_id: str | None = None) -> str:
    """
    Format research candidates as a markdown report for Claude to analyze.
    Optionally includes watchlist research results when watchlist_run_id is given.
    Watchlist-escalated tickers take priority over market-scan duplicates.
    """
    candidates = load_run(run_id)
    if not candidates:
        return f"No candidates found for run_id={run_id}"

    positions = load_open_positions()

    calibration = _get_calibration_report()
    lines = []
    if calibration:
        lines += ["## 確信度校正レポート（判断前参照）", "", "```", calibration, "```", ""]

    lines += [
        f"# Research Run: {run_id}",
        f"Date: {date.today().isoformat()}",
        f"Capital available: ${settings.available_capital_usd:,.0f}",
        "",
        f"## Open Positions ({len(positions)})",
    ]
    for pos in positions:
        lines.append(f"- {pos.get('ticker')} {pos.get('shares')} shares @ ${pos.get('entry_price')} (stop: ${pos.get('stop_loss')})")

    # Inject watchlist research context when available
    if watchlist_run_id or _has_watchlist_research():
        from investor.agents.watchlist_research_agent import (
            format_watchlist_for_decision,
            get_latest_wr_run_id,
        )
        wr_run = watchlist_run_id or get_latest_wr_run_id()
        if wr_run:
            lines += ["", "---", ""]
            lines.append(format_watchlist_for_decision(wr_run))
            lines += [
                "---",
                "",
                "> NOTE: When the same ticker appears in both Watchlist Research (ESCALATED) "
                "and Market Research, use the Watchlist Research data as the primary source.",
                "",
            ]

    lines += [f"## Market Research Candidates ({len(candidates)})", ""]
    lines.append("```json")
    lines.append(json.dumps(candidates, indent=2))
    lines.append("```")

    return "\n".join(lines)


def _has_watchlist_research() -> bool:
    """Return True if any watchlist research runs exist."""
    from pathlib import Path as _Path
    return _Path("data/watchlist_research_history.json").exists()

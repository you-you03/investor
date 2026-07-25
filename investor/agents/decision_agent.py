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
from investor.core.risk import (
    calculate_position_plan,
    portfolio_guard_violations,
    position_heat_usd,
    safe_float,
)
from investor.supabase_sync import sync_local_to_supabase
from investor.utils.price_parser import normalize_price_range, parse_entry_price
from investor.utils.logger import get_logger

logger = get_logger(__name__)

HISTORY_PATH = Path("data/research_history.json")
PORTFOLIO_PATH = Path(settings.default_portfolio_path)
LEGACY_PORTFOLIO_PATH = Path(settings.legacy_portfolio_path)
DECISION_HISTORY_PATH = Path("data/decision_history.json")

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


def load_open_positions(path: Path | None = None) -> list[dict]:
    portfolio_path = path or PORTFOLIO_PATH
    if not portfolio_path.exists():
        return []
    try:
        with open(portfolio_path) as f:
            reader = csv.DictReader(f)
            return [row for row in reader if row.get("status") == "open"]
    except Exception:
        return []


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
        requested_conviction = p.get("conviction", "LOW").upper()
        conviction = (
            "MEDIUM"
            if requested_conviction == "HIGH" and not settings.high_conviction_enabled
            else requested_conviction
        )
        action = p.get("action", "HOLD").upper()
        entry_price_range = normalize_price_range(p.get("entry_price_range", ""))
        entry_price = parse_entry_price(entry_price_range)
        research = candidate_map.get(ticker, {})
        stop_loss = p.get("stop_loss") or research.get("stop_loss")
        target_price = p.get("target_price") or research.get("target_price")
        requested_size = safe_float(p.get("position_size_usd"))
        requested_shares = safe_float(p.get("shares_suggested"))
        position_size_usd = 0.0
        shares_suggested = None
        planned_risk_usd = None
        risk_pct = None
        reward_risk_ratio = None
        sizing_error = None
        if action == "BUY":
            try:
                plan = calculate_position_plan(
                    entry_price=float(entry_price),
                    stop_loss=float(stop_loss),
                    target_price=float(target_price) if target_price not in (None, "") else None,
                    conviction=conviction,
                )
                position_size_usd = plan.notional_usd
                shares_suggested = plan.shares
                planned_risk_usd = plan.planned_risk_usd
                risk_pct = plan.risk_pct_of_capital
                reward_risk_ratio = plan.reward_risk_ratio
            except (TypeError, ValueError) as exc:
                sizing_error = str(exc)

        proposals.append({
            "ticker": ticker,
            "action": action,
            "conviction": conviction,
            "requested_conviction": requested_conviction,
            "entry_price_range": entry_price_range or p.get("entry_price_range"),
            "target_price": target_price,
            "stop_loss": stop_loss,
            "position_size_usd": round(position_size_usd, 2),
            "shares_suggested": shares_suggested,
            "planned_risk_usd": planned_risk_usd,
            "risk_pct_of_capital": risk_pct,
            "reward_risk_ratio": reward_risk_ratio,
            "sizing_basis": "entry_to_stop_with_gap_buffer",
            "sizing_error": sizing_error,
            "requested_position_size_usd": requested_size,
            "requested_shares": requested_shares,
            "strategy_version": settings.strategy_version,
            "rationale": p.get("rationale"),
            "key_catalysts": p.get("key_catalysts", []),
            "risk_factors": p.get("risk_factors", []),
            "time_horizon": p.get("time_horizon"),
            "note": p.get("note"),
            "hypothesis_id": p.get("hypothesis_id"),
            "expected_hold_weeks": p.get(
                "expected_hold_weeks",
                settings.evaluation_horizon_weeks,
            ),
            "review_week": p.get("review_week", 3),
            "early_exit_conditions": p.get(
                "early_exit_conditions",
                ["stop breach", "thesis broken", "sector reversal"],
            ),
            "signal_type": p.get("signal_type") or research.get("signal_type"),
            "research_score": p.get("research_score", research.get("score")),
            "factor_grades": p.get("factor_grades") or research.get("factor_grades") or {},
            "momentum_profile": p.get("momentum_profile") or research.get("momentum_profile") or {},
            "data_gap_flag": p.get("data_gap_flag", research.get("data_gap_flag", False)),
            "data_gap_flags": p.get("data_gap_flags") or research.get("data_gap_flags") or [],
        })
    return proposals


_MAX_POSITION_USD = settings.available_capital_usd * settings.max_position_pct
_MAX_OPEN_POSITIONS = settings.max_open_positions


def validate_proposals(proposals: list[dict], is_paper: bool = False) -> list[str]:
    """
    Check enriched proposals against mandate rules.
    Returns a list of violation strings; empty = all clear.

    is_paper: skip position-count check for B枠 paper decisions (paper tracks
    independently from the A-frame portfolio.csv).
    """
    violations: list[str] = []

    buy_proposals = [p for p in proposals if p.get("action") == "BUY"]
    open_positions = [] if is_paper else load_open_positions()

    if not is_paper:
        if buy_proposals and settings.block_new_buys_on_portfolio_violation:
            violations.extend(portfolio_guard_violations(open_positions))
        open_count = len(open_positions)
        if open_count + len(buy_proposals) > _MAX_OPEN_POSITIONS:
            violations.append(
                f"ポジション上限超過: open={open_count} + new_buy={len(buy_proposals)} > {_MAX_OPEN_POSITIONS}"
            )

    current_total_exposure = 0.0
    current_heat = 0.0
    for row in open_positions:
        ticker = str(row.get("ticker", "")).upper()
        try:
            shares = float(row.get("shares") or 0)
            entry_price = float(row.get("entry_price") or 0)
        except (TypeError, ValueError):
            continue
        current_total_exposure += shares * entry_price
        heat = position_heat_usd(row)
        if heat is not None:
            current_heat += heat

    new_total_exposure = 0.0
    new_heat = 0.0

    for p in buy_proposals:
        ticker = p.get("ticker", "?")
        size = safe_float(p.get("position_size_usd")) or 0.0
        if size > _MAX_POSITION_USD:
            violations.append(
                f"{ticker}: position_size_usd ${size:,.0f} > 上限 ${_MAX_POSITION_USD:,.0f}"
            )
        new_total_exposure += size
        if not p.get("ticker"):
            violations.append("ticker が未設定のプロポーザルがあります")
        if p.get("sizing_error"):
            violations.append(f"{ticker}: sizing failed — {p['sizing_error']}")
        proposed_shares = safe_float(p.get("shares_suggested"))
        if proposed_shares is None or proposed_shares <= 0:
            violations.append(f"{ticker}: executable shares could not be calculated")
        stop = p.get("stop_loss")
        if stop is None or stop == "":
            violations.append(f"{ticker}: stop_loss が未設定です（必須）")
        else:
            try:
                float(stop)
            except (TypeError, ValueError):
                violations.append(f"{ticker}: stop_loss '{stop}' が数値ではありません")
        target = p.get("target_price")
        if target is None or target == "":
            violations.append(f"{ticker}: target_price が未設定です（必須）")

        entry = parse_entry_price(str(p.get("entry_price_range") or ""))
        stop_value = safe_float(stop)
        target_value = safe_float(target)
        if entry is not None and stop_value is not None and stop_value >= entry:
            violations.append(f"{ticker}: stop_loss must be below planned entry")
        if entry is not None and target_value is not None and target_value <= entry:
            violations.append(f"{ticker}: target_price must be above planned entry")
        reward_risk = safe_float(p.get("reward_risk_ratio"))
        if reward_risk is None:
            violations.append(f"{ticker}: reward/risk could not be calculated")
        elif reward_risk < settings.min_reward_risk_ratio:
            violations.append(
                f"{ticker}: reward/risk {reward_risk:.2f} < "
                f"{settings.min_reward_risk_ratio:.2f}"
            )
        planned_risk = safe_float(p.get("planned_risk_usd"))
        if planned_risk is not None:
            new_heat += planned_risk
        else:
            violations.append(f"{ticker}: planned risk could not be calculated")

        score = safe_float(p.get("research_score"))
        if score is None:
            violations.append(f"{ticker}: research_score is missing")
        elif score < settings.min_live_score:
            violations.append(
                f"{ticker}: score {score:.1f} < live threshold {settings.min_live_score:.1f}"
            )

        grades = p.get("factor_grades") or {}
        for factor in ("fundamentals", "catalyst"):
            grade = str(grades.get(factor) or "").upper()
            if grade not in {"A", "B"}:
                violations.append(f"{ticker}: {factor} grade {grade or 'missing'} blocks BUY")
        for factor in ("technical", "sentiment"):
            grade = str(grades.get(factor) or "").upper()
            if grade not in {"A", "B", "C"}:
                violations.append(f"{ticker}: {factor} grade {grade or 'missing'} blocks BUY")

        momentum_profile = p.get("momentum_profile") or {}
        primary_mode = str(momentum_profile.get("primary_mode") or "").upper()
        extension_risk = str(momentum_profile.get("extension_risk") or "").upper()
        if primary_mode == "CHASE_MOMENTUM" or extension_risk == "HIGH":
            violations.append(
                f"{ticker}: chase/extension gate blocks live BUY "
                f"(mode={primary_mode or 'missing'}, extension={extension_risk or 'missing'})"
            )
        if p.get("data_gap_flag") or p.get("data_gap_flags"):
            violations.append(f"{ticker}: unresolved critical data gap blocks BUY")

        current_ticker_exposure = 0.0
        for row in open_positions:
            if str(row.get("ticker", "")).upper() != ticker:
                continue
            try:
                current_ticker_exposure += float(row.get("shares") or 0) * float(row.get("entry_price") or 0)
            except (TypeError, ValueError):
                continue

        total_exposure = current_ticker_exposure + size
        if total_exposure > _MAX_POSITION_USD:
            violations.append(
                f"{ticker}: 既存保有 ${current_ticker_exposure:,.0f} + 新規 ${size:,.0f} = "
                f"${total_exposure:,.0f} が上限 ${_MAX_POSITION_USD:,.0f} を超えます"
            )

    if not is_paper and current_total_exposure + new_total_exposure > settings.available_capital_usd:
        violations.append(
            f"20万円枠の総予算超過: existing=${current_total_exposure:,.0f} + "
            f"new=${new_total_exposure:,.0f} > ${settings.available_capital_usd:,.0f}"
        )
    if not is_paper:
        total_heat_pct = (current_heat + new_heat) / settings.available_capital_usd
        if total_heat_pct > settings.max_portfolio_heat_pct + 1e-9:
            violations.append(
                f"portfolio heat {total_heat_pct:.2%} > "
                f"{settings.max_portfolio_heat_pct:.2%}"
            )

    return violations


def send_proposals(proposals: list[dict]) -> None:
    """Send enriched proposals to Slack. Raises RuntimeError on failure."""
    slack = SlackNotifier()
    ok = slack.send_proposals(proposals)
    if not ok:
        raise RuntimeError(
            "Slack 送信失敗 — SLACK_WEBHOOK_URL を確認してください。"
            " BUY 通知が送信されていません。"
        )
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
    hold_cash = [p["ticker"] for p in proposals if p.get("action") in {"HOLD_CASH", "NO_TRADE"}]
    all_tickers = [c.get("ticker", "") for c in all_candidates if c.get("ticker")]
    pass_tickers = [t for t in all_tickers if t not in buy_tickers]
    candidate_map = {c.get("ticker", "").upper(): c for c in all_candidates if c.get("ticker")}
    pass_records = [
        {
            "ticker": ticker,
            "score": candidate_map.get(ticker, {}).get("score"),
            "conviction": candidate_map.get(ticker, {}).get("conviction"),
            "entry_price_range": candidate_map.get(ticker, {}).get("entry_price_range"),
            "signal_type": candidate_map.get(ticker, {}).get("signal_type"),
        }
        for ticker in pass_tickers
    ]
    proposal_records = [
        {
            "ticker": p.get("ticker"),
            "action": p.get("action"),
            "conviction": p.get("conviction"),
            "position_size_usd": p.get("position_size_usd"),
            "signal_type": p.get("signal_type"),
        }
        for p in proposals
    ]

    history.append({
        "date": date.today().isoformat(),
        "run_id": run_id,
        "candidates_evaluated": all_tickers,
        "buy_decisions": buy_tickers,
        "pass_decisions": pass_tickers,
        "hold_cash_decisions": hold_cash,
        "proposal_records": proposal_records,
        "pass_records": pass_records,
        "proposal_summary": {
            "buy_count": len(buy_tickers),
            "pass_count": len(pass_tickers),
            "hold_cash_count": len(hold_cash),
        },
        "no_trade_week": len(buy_tickers) == 0,
    })
    DECISION_HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    logger.info(f"Logged decision: {len(buy_tickers)} BUY / {len(pass_tickers)} PASS")
    sync_local_to_supabase("decisions", "workflow_tasks", "lineage")


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
    legacy_positions = load_open_positions(LEGACY_PORTFOLIO_PATH)

    calibration = _get_calibration_report()
    lines = []
    if calibration:
        lines += ["## 確信度校正レポート（判断前参照）", "", "```", calibration, "```", ""]

    lines += [
        f"# Research Run: {run_id}",
        f"Date: {date.today().isoformat()}",
        f"Default portfolio: 20万円枠 ({PORTFOLIO_PATH})",
        f"Capital available: ${settings.available_capital_usd:,.0f}",
        f"Strategy: {settings.strategy_version}",
        f"Rules: max positions={settings.max_open_positions}, max position={settings.max_position_pct:.0%}, "
        f"risk/trade={settings.risk_per_trade_pct:.2%}, portfolio heat={settings.max_portfolio_heat_pct:.1%}",
        "",
        f"## Default 20万円 Open Positions ({len(positions)})",
    ]
    for pos in positions:
        lines.append(f"- {pos.get('ticker')} {pos.get('shares')} shares @ ${pos.get('entry_price')} (stop: ${pos.get('stop_loss')})")
    if not positions:
        lines.append("- none")

    sim_exposure = 0.0
    for pos in legacy_positions:
        try:
            sim_exposure += float(pos.get("shares") or 0) * float(pos.get("entry_price") or 0)
        except (TypeError, ValueError):
            continue

    sim_budget_usd = settings.available_capital_usd * 5
    sim_utilization = sim_exposure / sim_budget_usd if sim_budget_usd else 0.0

    lines += [
        "",
        f"## Parallel 100万円 Simulation Positions ({len(legacy_positions)})",
        f"Simulation budget: ${sim_budget_usd:,.0f} | current exposure: ${sim_exposure:,.0f} | utilization: {sim_utilization:.0%}",
        "Purpose: decision-accuracy learning data only; not real execution capital.",
        "Simulation policy: keep the same quality gates, but when explicitly updating this book target 90-100% utilization if qualified candidates exist.",
    ]
    for pos in legacy_positions:
        lines.append(f"- {pos.get('ticker')} {pos.get('shares')} shares @ ${pos.get('entry_price')} (stop: ${pos.get('stop_loss')})")
    if not legacy_positions:
        lines.append("- none")

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

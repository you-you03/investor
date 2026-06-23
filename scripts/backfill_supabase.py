#!/usr/bin/env python
"""Backfill existing CSV/JSON/SQLite investor data into Supabase."""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from investor.supabase_store import (  # noqa: E402
    _clean_date,
    _clean_int,
    _clean_number,
    _stable_id,
    get_store,
    normalize_monitor_alert,
    normalize_monitor_position,
    normalize_monitor_run,
    normalize_position,
)

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
DOCS_DIR = ROOT / "docs"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _chunks(rows: list[dict], size: int = 500):
    for index in range(0, len(rows), size):
        yield rows[index:index + size]


def _upsert_many(store, table: str, rows: list[dict], on_conflict: str) -> int:
    keys = [key.strip() for key in on_conflict.split(",") if key.strip()]
    if keys:
        deduped: dict[tuple, dict] = {}
        passthrough: list[dict] = []
        for row in rows:
            key = tuple(row.get(name) for name in keys)
            if any(value is None or value == "" for value in key):
                passthrough.append(row)
                continue
            deduped[key] = row
        rows = [*deduped.values(), *passthrough]
    total = 0
    for chunk in _chunks(rows):
        store.upsert(table, chunk, on_conflict)
        total += len(chunk)
    return total


def backfill_positions(store) -> int:
    rows = []
    rows.extend(normalize_position(row, "real") for row in _read_csv(DATA_DIR / "portfolio.csv") if row.get("ticker"))
    rows.extend(normalize_position(row, "paper") for row in _read_csv(DATA_DIR / "paper_portfolio.csv") if row.get("ticker"))
    return _upsert_many(store, "positions", rows, "position_id")


def backfill_watchlist(store) -> int:
    data = _read_json(DATA_DIR / "watchlist.json", {"items": []})
    rows = []
    for item in data.get("items", []):
        ticker = str(item.get("ticker") or "").upper()
        if not ticker:
            continue
        rows.append({
            "ticker": ticker,
            "added_at": _clean_date(item.get("added_at")),
            "source": item.get("source"),
            "last_research_run_id": item.get("last_research_run_id"),
            "last_score": _clean_number(item.get("last_score")),
            "reference_price": _clean_number(item.get("reference_price")),
            "reason": item.get("reason"),
            "status": item.get("status"),
            "last_monitor_flag": item.get("last_monitor_flag"),
            "last_monitor_date": _clean_date(item.get("last_monitor_date")),
            "consecutive_drops": _clean_int(item.get("consecutive_drops")),
            "pipeline_status": item.get("pipeline_status"),
            "raw_payload": item,
        })
    return _upsert_many(store, "watchlist_items", rows, "ticker")


def backfill_monitor(store) -> tuple[int, int, int]:
    runs_data = _read_json(DATA_DIR / "monitor_history.json", [])
    run_rows: list[dict] = []
    position_rows: list[dict] = []
    alert_rows: list[dict] = []
    for index, record in enumerate(runs_data, 1):
        run = normalize_monitor_run(record, run_id=record.get("run_id") or _stable_id("monitor", index, record.get("date")))
        run_rows.append(run)
        for position in record.get("positions", []):
            if position.get("ticker"):
                position_rows.append(normalize_monitor_position(position, run["run_id"], run["run_date"]))
        for alert in record.get("alerts", []):
            if alert.get("ticker"):
                row = normalize_monitor_alert(alert, run["run_id"])
                row["raw_payload"] = {**row["raw_payload"], "suppress_automation": "true"}
                alert_rows.append(row)

    loose_alerts = _read_json(DATA_DIR / "monitor_alerts.json", [])
    for alert in loose_alerts:
        if alert.get("ticker"):
            row = normalize_monitor_alert(alert)
            row["raw_payload"] = {**row["raw_payload"], "suppress_automation": "true"}
            alert_rows.append(row)

    return (
        _upsert_many(store, "monitor_runs", run_rows, "run_id"),
        _upsert_many(store, "monitor_positions", position_rows, "run_id,ticker"),
        _upsert_many(store, "monitor_alerts", alert_rows, "alert_id"),
    )


def backfill_research(store) -> tuple[int, int]:
    data = _read_json(DATA_DIR / "research_history.json", {"runs": []})
    run_rows = []
    candidate_rows = []
    for run in data.get("runs", []):
        run_id = run.get("run_id")
        run_date = _clean_date(run.get("date"))
        if not run_id or not run_date:
            continue
        candidates = run.get("candidates", [])
        run_rows.append({
            "run_id": run_id,
            "run_date": run_date,
            "candidate_count": len(candidates),
            "raw_payload": run,
        })
        for candidate in candidates:
            ticker = str(candidate.get("ticker") or "").upper()
            if not ticker:
                continue
            outcome = candidate.get("outcome") or {}
            candidate_rows.append({
                "candidate_id": _stable_id("research", run_id, ticker),
                "run_id": run_id,
                "run_date": run_date,
                "ticker": ticker,
                "action": candidate.get("action"),
                "conviction": candidate.get("conviction"),
                "score": _clean_number(candidate.get("score") or candidate.get("new_score")),
                "entry_price": _clean_number(candidate.get("entry_price")),
                "entry_price_range": candidate.get("entry_price_range"),
                "target_price": _clean_number(candidate.get("target_price")),
                "stop_loss": _clean_number(candidate.get("stop_loss")),
                "signal_type": candidate.get("signal_type"),
                "rationale": candidate.get("rationale"),
                "outcome_status": outcome.get("status"),
                "outcome_type": outcome.get("outcome_type"),
                "realized_return_pct": _clean_number(outcome.get("realized_return_pct")),
                "alpha_pct": _clean_number(outcome.get("alpha_pct")),
                "raw_payload": candidate,
            })
    return (
        _upsert_many(store, "research_runs", run_rows, "run_id"),
        _upsert_many(store, "research_candidates", candidate_rows, "candidate_id"),
    )


def backfill_decisions(store) -> tuple[int, int]:
    data = _read_json(DATA_DIR / "decision_history.json", [])
    run_rows = []
    proposal_rows = []
    for record in data:
        run_id = record.get("run_id")
        run_date = _clean_date(record.get("date"))
        if not run_id or not run_date:
            continue
        summary = record.get("proposal_summary") or {}
        run_rows.append({
            "run_id": run_id,
            "run_date": run_date,
            "candidates_evaluated": record.get("candidates_evaluated") or [],
            "buy_decisions": record.get("buy_decisions") or [],
            "pass_decisions": record.get("pass_decisions") or [],
            "hold_cash_decisions": record.get("hold_cash_decisions") or [],
            "buy_count": _clean_int(summary.get("buy_count")) or len(record.get("buy_decisions") or []),
            "pass_count": _clean_int(summary.get("pass_count")) or len(record.get("pass_decisions") or []),
            "hold_cash_count": _clean_int(summary.get("hold_cash_count")) or len(record.get("hold_cash_decisions") or []),
            "no_trade_week": bool(record.get("no_trade_week")),
            "raw_payload": record,
        })
        for proposal in record.get("proposal_records") or []:
            ticker = str(proposal.get("ticker") or "").upper()
            if not ticker:
                continue
            proposal_rows.append({
                "proposal_id": _stable_id("proposal", run_id, ticker, proposal.get("action")),
                "run_id": run_id,
                "ticker": ticker,
                "action": proposal.get("action"),
                "conviction": proposal.get("conviction"),
                "position_size_usd": _clean_number(proposal.get("position_size_usd")),
                "signal_type": proposal.get("signal_type"),
                "raw_payload": proposal,
            })
    return (
        _upsert_many(store, "decision_runs", run_rows, "run_id"),
        _upsert_many(store, "investment_proposals", proposal_rows, "proposal_id"),
    )


def backfill_score_snapshots(store) -> int:
    data = _read_json(DATA_DIR / "score_snapshots.json", {"snapshots": []})
    rows = []
    seen_keys: dict[tuple, int] = {}
    for snapshot in data.get("snapshots", []):
        ticker = str(snapshot.get("ticker") or "").upper()
        if not ticker:
            continue
        natural_key = (snapshot.get("run_id"), snapshot.get("scored_at"), ticker)
        seen_keys[natural_key] = seen_keys.get(natural_key, 0) + 1
        occurrence = seen_keys[natural_key]
        snapshot_id = (
            _stable_id("score", snapshot.get("run_id"), snapshot.get("scored_at"), ticker)
            if occurrence == 1
            else _stable_id("score", snapshot.get("run_id"), snapshot.get("scored_at"), ticker, occurrence)
        )
        rows.append({
            "snapshot_id": snapshot_id,
            "run_id": snapshot.get("run_id"),
            "scored_at": _clean_date(snapshot.get("scored_at")),
            "ticker": ticker,
            "company_name": snapshot.get("company_name"),
            "score": _clean_number(snapshot.get("score")),
            "rank_in_run": _clean_int(snapshot.get("rank_in_run")),
            "total_scored_in_run": _clean_int(snapshot.get("total_scored_in_run")),
            "price_at_score": _clean_number(snapshot.get("price_at_score")),
            "passed_threshold": snapshot.get("passed_threshold"),
            "macro_regime": snapshot.get("macro_regime"),
            "sector_etf": snapshot.get("sector_etf"),
            "week1": snapshot.get("week1"),
            "week2": snapshot.get("week2"),
            "week3": snapshot.get("week3"),
            "week4": snapshot.get("week4"),
            "raw_payload": snapshot,
        })
    return _upsert_many(store, "score_snapshots", rows, "snapshot_id")


def backfill_trade_journal(store) -> int:
    data = _read_json(DATA_DIR / "trade_journal.json", [])
    rows = []
    for entry in data:
        trade_id = entry.get("trade_id")
        if not trade_id:
            continue
        rows.append({
            "trade_id": trade_id,
            "ticker": str(trade_id).split("_", 1)[0].upper(),
            "signal_type": entry.get("signal_type"),
            "conviction": entry.get("conviction"),
            "hold_days": _clean_int(entry.get("hold_days")),
            "pnl_pct": _clean_number(entry.get("pnl_pct")),
            "mae_pct": _clean_number(entry.get("mae_pct")),
            "mfe_pct": _clean_number(entry.get("mfe_pct")),
            "mfe_capture_pct": _clean_number(entry.get("mfe_capture_pct")),
            "rule_adherence_score": _clean_number(entry.get("rule_adherence_score")),
            "decision_quality": _clean_number(entry.get("decision_quality")),
            "outcome_quality": _clean_number(entry.get("outcome_quality")),
            "would_take_again": entry.get("would_take_again"),
            "what_i_missed": entry.get("what_i_missed"),
            "raw_payload": entry,
        })
    return _upsert_many(store, "trade_journal_entries", rows, "trade_id")


def backfill_market_news(store) -> tuple[int, int]:
    db_path = DATA_DIR / "market_news.sqlite"
    if not db_path.exists():
        return (0, 0)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    source_rows = []
    item_rows = []
    try:
        for row in conn.execute("select * from market_news_sources"):
            item = dict(row)
            source_rows.append({
                "source_id": f"market-news-source-{item.get('id')}",
                "source_type": item.get("source_type") or item.get("type"),
                "value": item.get("value"),
                "label": item.get("label"),
                "status": item.get("status"),
                "last_checked_at": item.get("last_checked_at"),
                "raw_payload": item,
            })
        for row in conn.execute("select * from market_news_items"):
            item = dict(row)
            item_rows.append({
                "item_id": f"market-news-item-{item.get('id')}",
                "source_id": f"market-news-source-{item.get('source_id')}" if item.get("source_id") else None,
                "title": item.get("title"),
                "url": item.get("url"),
                "publisher": item.get("publisher") or item.get("source"),
                "published_at": item.get("published_at"),
                "selected_for_monitor": bool(item.get("selected_for_monitor")),
                "summary": item.get("summary") or item.get("key_point"),
                "raw_payload": item,
            })
    finally:
        conn.close()
    return (
        _upsert_many(store, "market_news_sources", source_rows, "source_id"),
        _upsert_many(store, "market_news_items", item_rows, "item_id"),
    )


def backfill_daily_lite(store) -> tuple[int, int]:
    data = _read_json(DATA_DIR / "daily_lite_history.json", {"runs": []})
    run_rows = []
    action_rows = []
    for run in data.get("runs", []):
        run_id = run.get("run_id")
        run_date = _clean_date(run.get("date"))
        if not run_id or not run_date:
            continue
        pending_actions = run.get("pending_actions") or []
        run_rows.append({
            "run_id": run_id,
            "run_date": run_date,
            "position_count": len(run.get("positions") or []),
            "position_alert_count": len(run.get("position_alerts") or []),
            "watchlist_count": len(run.get("watchlist_results") or []),
            "research_candidate_count": len(run.get("research_candidates") or []),
            "pending_action_count": len(pending_actions),
            "report_path": run.get("report_path"),
            "macro_context": run.get("macro_context") or {},
            "raw_payload": run,
        })
        for index, action in enumerate(pending_actions, 1):
            ticker = str(action.get("ticker") or "").upper() or None
            action_rows.append({
                "action_id": _stable_id("daily-action", run_id, index, ticker, action.get("type")),
                "run_id": run_id,
                "run_date": run_date,
                "ticker": ticker,
                "action_type": action.get("type"),
                "command": action.get("command"),
                "detail": action.get("detail") or action.get("reason"),
                "raw_payload": action,
            })
    return (
        _upsert_many(store, "daily_lite_runs", run_rows, "run_id"),
        _upsert_many(store, "daily_lite_actions", action_rows, "action_id"),
    )


def backfill_watchlist_research(store) -> tuple[int, int]:
    data = _read_json(DATA_DIR / "watchlist_research_history.json", {"runs": []})
    run_rows = []
    result_rows = []
    for run in data.get("runs", []):
        run_id = run.get("run_id")
        run_date = _clean_date(run.get("date"))
        if not run_id or not run_date:
            continue
        results = run.get("results") or []
        run_rows.append({
            "run_id": run_id,
            "run_date": run_date,
            "result_count": len(results),
            "escalate_count": sum(1 for r in results if str(r.get("action", "")).upper() == "ESCALATE"),
            "remove_count": sum(1 for r in results if str(r.get("action", "")).upper() == "REMOVE"),
            "raw_payload": run,
        })
        for result in results:
            ticker = str(result.get("ticker") or "").upper()
            if not ticker:
                continue
            result_rows.append({
                "result_id": _stable_id("watchlist-research", run_id, ticker),
                "run_id": run_id,
                "run_date": run_date,
                "ticker": ticker,
                "action": result.get("action"),
                "new_score": _clean_number(result.get("new_score")),
                "flag": result.get("flag"),
                "note": result.get("note"),
                "raw_payload": result,
            })
    return (
        _upsert_many(store, "watchlist_research_runs", run_rows, "run_id"),
        _upsert_many(store, "watchlist_research_results", result_rows, "result_id"),
    )


def _report_type_for_path(path: Path) -> str:
    parts = path.parts
    if "reports" in parts:
        try:
            index = parts.index("reports")
            return parts[index + 1]
        except Exception:
            return "report"
    if "docs" in parts:
        return "docs"
    return "artifact"


def _date_from_name(path: Path) -> str | None:
    import re

    match = re.search(r"(20\d{2}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else None


def backfill_report_artifacts(store) -> int:
    paths = []
    for root in (REPORTS_DIR, DOCS_DIR):
        if root.exists():
            paths.extend(sorted(root.rglob("*.md")))
            paths.extend(sorted(root.rglob("*.html")))
    rows = []
    for path in paths:
        rel_path = path.relative_to(ROOT).as_posix()
        try:
            content = path.read_text()
        except Exception:
            continue
        title = ""
        for line in content.splitlines():
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                break
        rows.append({
            "artifact_id": _stable_id("artifact", rel_path),
            "report_type": _report_type_for_path(path),
            "report_date": _date_from_name(path),
            "title": title or path.stem,
            "path": rel_path,
            "content_markdown": content,
            "raw_payload": {
                "size_bytes": path.stat().st_size,
                "source": "backfill",
            },
        })
    return _upsert_many(store, "report_artifacts", rows, "artifact_id")


def _priority_from_severity(severity: str | None) -> str:
    return {
        "HIGH": "urgent",
        "MEDIUM": "high",
        "LOW": "low",
    }.get(str(severity or "").upper(), "normal")


def _task_type_from_monitor_alert(alert_type: str | None) -> str:
    return {
        "STOP_LOSS": "exit_review",
        "STOP_BREACH": "exit_review",
        "TARGET_REACHED": "exit_review",
        "STAGE1_HIT": "position_update",
        "STAGE2_HIT": "position_update",
        "SHARP_DROP": "risk_review",
        "SIGNIFICANT_DRAWDOWN": "risk_review",
    }.get(str(alert_type or "").upper(), "manual_review")


def _task_type_from_watchlist_alert(alert_type: str | None) -> str:
    return {
        "WATCHLIST_DECISION_NEEDED": "decision",
        "WATCHLIST_RESEARCH_NEEDED": "research",
    }.get(str(alert_type or "").upper(), "manual_review")


def _command_for_monitor_task(task_type: str, ticker: str) -> str | None:
    if task_type == "exit_review":
        return f"/decision --mode exit --ticker {ticker}"
    if task_type in {"risk_review", "position_update"}:
        return "/monitor"
    return None


def backfill_workflow_tasks(store) -> int:
    rows: list[dict] = []

    monitor_alerts = store.select("monitor_alerts", {"select": "*", "limit": "10000"})
    for alert in monitor_alerts:
        if (alert.get("raw_payload") or {}).get("suppress_automation") == "true":
            continue
        ticker = str(alert.get("ticker") or "").upper()
        task_type = _task_type_from_monitor_alert(alert.get("alert_type"))
        rows.append({
            "task_id": f"task:monitor_alert:{alert.get('alert_id')}",
            "ticker": ticker or None,
            "task_type": task_type,
            "priority": _priority_from_severity(alert.get("severity")),
            "status": "open",
            "command": _command_for_monitor_task(task_type, ticker),
            "title": f"{alert.get('alert_type')} for {ticker}",
            "detail": alert.get("message"),
            "source_table": "monitor_alerts",
            "source_id": alert.get("alert_id"),
            "source_run_id": alert.get("run_id"),
            "due_date": _clean_date(alert.get("alert_date")),
            "raw_payload": alert.get("raw_payload") or alert,
        })

    watchlist_alerts = store.select("watchlist_alerts", {"select": "*", "limit": "10000"})
    for alert in watchlist_alerts:
        if (alert.get("raw_payload") or {}).get("suppress_automation") == "true":
            continue
        ticker = str(alert.get("ticker") or "").upper()
        task_type = _task_type_from_watchlist_alert(alert.get("alert_type"))
        rows.append({
            "task_id": f"task:watchlist_alert:{alert.get('alert_id')}",
            "ticker": ticker or None,
            "task_type": task_type,
            "priority": _priority_from_severity(alert.get("severity")),
            "status": "open",
            "command": alert.get("next_step"),
            "title": f"{alert.get('alert_type')} for {ticker}",
            "detail": alert.get("message"),
            "source_table": "watchlist_alerts",
            "source_id": alert.get("alert_id"),
            "source_run_id": alert.get("run_id"),
            "due_date": _clean_date(alert.get("alert_date")),
            "raw_payload": alert.get("raw_payload") or alert,
        })

    daily_actions = store.select("daily_lite_actions", {"select": "*", "limit": "10000"})
    for action in daily_actions:
        command = action.get("command")
        action_type = str(action.get("action_type") or "").lower()
        if command and "decision" in command:
            task_type = "decision"
        elif command and "research" in command:
            task_type = "research"
        elif "review" in action_type:
            task_type = "manual_review"
        else:
            task_type = "manual_review"
        rows.append({
            "task_id": f"task:daily_lite_action:{action.get('action_id')}",
            "ticker": action.get("ticker"),
            "task_type": task_type,
            "priority": "normal",
            "status": "open",
            "command": command,
            "title": action.get("action_type") or "daily_lite_action",
            "detail": action.get("detail"),
            "source_table": "daily_lite_actions",
            "source_id": action.get("action_id"),
            "source_run_id": action.get("run_id"),
            "due_date": _clean_date(action.get("run_date")),
            "raw_payload": action.get("raw_payload") or action,
        })

    decision_requests = store.select("decision_requests", {"select": "*", "limit": "10000"})
    for request in decision_requests:
        ticker = str(request.get("ticker") or "").upper()
        request_type = str(request.get("request_type") or "")
        task_type = "exit_review" if "exit" in request_type else "decision"
        rows.append({
            "task_id": f"task:decision_request:{request.get('request_id')}",
            "ticker": ticker or None,
            "task_type": task_type,
            "priority": "high",
            "status": "open" if request.get("status") == "pending" else "done",
            "command": f"/decision --mode exit --ticker {ticker}" if task_type == "exit_review" else "/decision",
            "title": request_type or "decision_request",
            "detail": request.get("reason"),
            "source_table": "decision_requests",
            "source_id": request.get("request_id"),
            "source_run_id": None,
            "due_date": _clean_date(request.get("requested_at")),
            "resolved_at": request.get("resolved_at"),
            "raw_payload": request.get("raw_payload") or request,
        })

    return _upsert_many(store, "workflow_tasks", rows, "source_table,source_id,task_type")


def backfill_position_events(store) -> int:
    positions = store.select("positions", {"select": "*", "limit": "10000"})
    rows: list[dict] = []
    for position in positions:
        position_id = position.get("position_id")
        ticker = str(position.get("ticker") or "").upper()
        if not position_id or not ticker:
            continue
        rows.append({
            "event_id": f"position_event:{position_id}:entry",
            "position_id": position_id,
            "ticker": ticker,
            "portfolio_type": position.get("portfolio_type") or "real",
            "event_type": "entry",
            "event_date": _clean_date(position.get("entry_date")) or date.today().isoformat(),
            "shares_delta": _clean_number(position.get("shares")),
            "price": _clean_number(position.get("entry_price")),
            "stop_loss": _clean_number(position.get("stop_loss")),
            "target_price": _clean_number(position.get("target_price")),
            "reason": position.get("signal_type"),
            "source_table": "positions",
            "source_id": position_id,
            "raw_payload": position.get("raw_payload") or position,
        })
        if position.get("status") == "closed":
            rows.append({
                "event_id": f"position_event:{position_id}:exit",
                "position_id": position_id,
                "ticker": ticker,
                "portfolio_type": position.get("portfolio_type") or "real",
                "event_type": "exit",
                "event_date": (
                    _clean_date(position.get("exit_date"))
                    or _clean_date(position.get("entry_date"))
                    or date.today().isoformat()
                ),
                "shares_delta": -1 * (_clean_number(position.get("shares")) or 0),
                "price": _clean_number(position.get("exit_price")),
                "stop_loss": _clean_number(position.get("stop_loss")),
                "target_price": _clean_number(position.get("target_price")),
                "reason": position.get("note"),
                "source_table": "positions",
                "source_id": position_id,
                "raw_payload": position.get("raw_payload") or position,
            })
    return _upsert_many(store, "position_events", rows, "event_id")


def backfill_lineage(store) -> tuple[int, int]:
    proposal_rows = store.select(
        "investment_proposals",
        {"select": "proposal_id,run_id,ticker,research_candidate_id,created_at", "limit": "10000"},
    )
    candidate_rows = store.select(
        "research_candidates",
        {"select": "candidate_id,run_id,ticker,run_date", "limit": "10000"},
    )
    candidates_by_run_ticker = {
        (row.get("run_id"), str(row.get("ticker") or "").upper()): row.get("candidate_id")
        for row in candidate_rows
        if row.get("candidate_id")
    }

    proposal_updates = 0
    for proposal in proposal_rows:
        if proposal.get("research_candidate_id"):
            continue
        candidate_id = candidates_by_run_ticker.get((proposal.get("run_id"), str(proposal.get("ticker") or "").upper()))
        if not candidate_id:
            continue
        store.patch(
            "investment_proposals",
            {"proposal_id": f"eq.{proposal['proposal_id']}"},
            {"research_candidate_id": candidate_id},
        )
        proposal_updates += 1

    positions = store.select(
        "positions",
        {"select": "position_id,ticker,proposal_date,entry_date,proposal_id", "limit": "10000"},
    )
    proposals_by_ticker: dict[str, list[dict]] = {}
    for proposal in proposal_rows:
        proposals_by_ticker.setdefault(str(proposal.get("ticker") or "").upper(), []).append(proposal)

    position_updates = 0
    for position in positions:
        if position.get("proposal_id"):
            continue
        ticker = str(position.get("ticker") or "").upper()
        candidates = proposals_by_ticker.get(ticker) or []
        if not candidates:
            continue
        proposal_date = _clean_date(position.get("proposal_date")) or _clean_date(position.get("entry_date"))
        matching = [
            proposal for proposal in candidates
            if not proposal_date or _clean_date(proposal.get("created_at")) <= proposal_date
        ]
        selected = (matching or candidates)[-1]
        store.patch(
            "positions",
            {"position_id": f"eq.{position['position_id']}"},
            {"proposal_id": selected.get("proposal_id")},
        )
        position_updates += 1

    return proposal_updates, position_updates


def main() -> None:
    store = get_store()
    if not store:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が未設定です。接続情報を .env に入れてから再実行してください。")
        raise SystemExit(1)

    print("Backfilling Supabase...")
    print(f"positions: {backfill_positions(store)}")
    print(f"watchlist_items: {backfill_watchlist(store)}")
    monitor_runs, monitor_positions, monitor_alerts = backfill_monitor(store)
    print(f"monitor_runs: {monitor_runs}")
    print(f"monitor_positions: {monitor_positions}")
    print(f"monitor_alerts: {monitor_alerts}")
    research_runs, research_candidates = backfill_research(store)
    print(f"research_runs: {research_runs}")
    print(f"research_candidates: {research_candidates}")
    decision_runs, proposals = backfill_decisions(store)
    print(f"decision_runs: {decision_runs}")
    print(f"investment_proposals: {proposals}")
    print(f"score_snapshots: {backfill_score_snapshots(store)}")
    print(f"trade_journal_entries: {backfill_trade_journal(store)}")
    news_sources, news_items = backfill_market_news(store)
    print(f"market_news_sources: {news_sources}")
    print(f"market_news_items: {news_items}")
    daily_runs, daily_actions = backfill_daily_lite(store)
    print(f"daily_lite_runs: {daily_runs}")
    print(f"daily_lite_actions: {daily_actions}")
    wr_runs, wr_results = backfill_watchlist_research(store)
    print(f"watchlist_research_runs: {wr_runs}")
    print(f"watchlist_research_results: {wr_results}")
    print(f"report_artifacts: {backfill_report_artifacts(store)}")
    print(f"workflow_tasks: {backfill_workflow_tasks(store)}")
    print(f"position_events: {backfill_position_events(store)}")
    proposal_updates, position_updates = backfill_lineage(store)
    print(f"lineage investment_proposals updated: {proposal_updates}")
    print(f"lineage positions updated: {position_updates}")
    print("Done.")


if __name__ == "__main__":
    main()

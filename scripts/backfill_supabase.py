#!/usr/bin/env python
"""Backfill existing CSV/JSON/SQLite investor data into Supabase."""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
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
    for snapshot in data.get("snapshots", []):
        ticker = str(snapshot.get("ticker") or "").upper()
        if not ticker:
            continue
        rows.append({
            "snapshot_id": _stable_id("score", snapshot.get("run_id"), snapshot.get("scored_at"), ticker),
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
    print("Done.")


if __name__ == "__main__":
    main()

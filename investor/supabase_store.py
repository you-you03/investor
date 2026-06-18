"""Supabase persistence adapter.

This module is deliberately optional. If SUPABASE_URL or
SUPABASE_SERVICE_ROLE_KEY is missing, all public helpers become no-ops so the
file-based workflow keeps working.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

import httpx

from investor.config import settings
from investor.notifications.slack import SlackNotifier
from investor.utils.logger import get_logger

logger = get_logger(__name__)


def _is_blank(value: str | None) -> bool:
    return not value or value.startswith("https://your-project") or value.startswith("ey...")


def is_enabled() -> bool:
    return not _is_blank(settings.supabase_url) and not _is_blank(settings.supabase_service_role_key)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _stable_id(prefix: str, *parts: Any) -> str:
    source = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _clean_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else text


class SupabaseStore:
    def __init__(self) -> None:
        if not is_enabled():
            raise RuntimeError("Supabase is not configured")
        self.base_url = settings.supabase_url.rstrip("/")
        self.headers = {
            "apikey": settings.supabase_service_role_key or "",
            "authorization": f"Bearer {settings.supabase_service_role_key}",
            "content-type": "application/json",
        }

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        if not rows:
            return
        url = f"{self.base_url}/rest/v1/{table}"
        headers = {
            **self.headers,
            "prefer": "resolution=merge-duplicates,return=minimal",
        }
        params = {"on_conflict": on_conflict}
        payload = json.dumps(rows, ensure_ascii=False, default=_json_default)
        with httpx.Client(timeout=30) as client:
            response = client.post(url, headers=headers, params=params, content=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase upsert failed: {table} {response.status_code} {response.text}")

    def select(self, table: str, params: dict[str, str] | None = None) -> list[dict]:
        url = f"{self.base_url}/rest/v1/{table}"
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=self.headers, params=params or {})
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase select failed: {table} {response.status_code} {response.text}")
        return response.json()

    def patch(self, table: str, params: dict[str, str], values: dict) -> None:
        url = f"{self.base_url}/rest/v1/{table}"
        headers = {**self.headers, "prefer": "return=minimal"}
        payload = json.dumps(values, ensure_ascii=False, default=_json_default)
        with httpx.Client(timeout=30) as client:
            response = client.patch(url, headers=headers, params=params, content=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase patch failed: {table} {response.status_code} {response.text}")


def get_store() -> SupabaseStore | None:
    if not is_enabled():
        return None
    try:
        return SupabaseStore()
    except Exception as exc:
        logger.warning("Supabase disabled: %s", exc)
        return None


def normalize_position(row: dict, portfolio_type: str = "real") -> dict:
    position_id = row.get("position_id") or _stable_id("pos", portfolio_type, row.get("ticker"), row.get("entry_date"))
    return {
        "position_id": position_id,
        "portfolio_type": portfolio_type,
        "ticker": str(row.get("ticker") or "").upper(),
        "shares": _clean_number(row.get("shares")),
        "entry_price": _clean_number(row.get("entry_price")),
        "entry_date": _clean_date(row.get("entry_date")),
        "proposal_date": _clean_date(row.get("proposal_date")),
        "exit_price": _clean_number(row.get("exit_price")),
        "exit_date": _clean_date(row.get("exit_date")),
        "status": row.get("status") or "open",
        "target_price": _clean_number(row.get("target_price")),
        "stop_loss": _clean_number(row.get("stop_loss")),
        "note": row.get("note") or None,
        "signal_type": row.get("signal_type") or None,
        "conviction": row.get("conviction") or None,
        "hypothesis_id": row.get("hypothesis_id") or None,
        "exit_stage": row.get("exit_stage") or None,
        "mae_pct": _clean_number(row.get("mae_pct")),
        "mfe_pct": _clean_number(row.get("mfe_pct")),
        "mfe_capture_pct": _clean_number(row.get("mfe_capture_pct")),
        "rule_adherence_score": _clean_number(row.get("rule_adherence_score")),
        "raw_payload": row,
    }


def normalize_monitor_run(record: dict, run_id: str | None = None) -> dict:
    run_date = _clean_date(record.get("date")) or date.today().isoformat()
    resolved_run_id = run_id or record.get("run_id") or _stable_id("monitor", run_date, record.get("position_count"), record.get("alert_count"))
    return {
        "run_id": resolved_run_id,
        "run_date": run_date,
        "position_count": _clean_int(record.get("position_count")) or 0,
        "alert_count": _clean_int(record.get("alert_count")) or 0,
        "high_alert_count": _clean_int(record.get("high_alert_count")) or 0,
        "market_news": record.get("market_news") or {},
        "raw_payload": record,
    }


def normalize_monitor_position(position: dict, run_id: str, run_date: str) -> dict:
    return {
        "run_id": run_id,
        "run_date": run_date,
        "ticker": str(position.get("ticker") or "").upper(),
        "shares": _clean_number(position.get("shares")),
        "entry_price": _clean_number(position.get("entry_price")),
        "current_price": _clean_number(position.get("current_price")),
        "target_price": _clean_number(position.get("target_price")),
        "stop_loss": _clean_number(position.get("stop_loss")),
        "pnl_pct": _clean_number(position.get("pnl_pct")),
        "change_pct": _clean_number(position.get("change_pct")),
        "note": position.get("note") or None,
        "raw_payload": position,
    }


def normalize_monitor_alert(alert: dict, run_id: str | None = None) -> dict:
    alert_date = _clean_date(alert.get("date")) or date.today().isoformat()
    alert_id = alert.get("alert_id") or _stable_id(
        "alert",
        run_id,
        alert_date,
        alert.get("ticker"),
        alert.get("alert_type"),
        alert.get("message"),
    )
    return {
        "alert_id": alert_id,
        "run_id": run_id,
        "alert_date": alert_date,
        "ticker": str(alert.get("ticker") or "").upper(),
        "alert_type": alert.get("alert_type") or "UNKNOWN",
        "severity": alert.get("severity") or "LOW",
        "message": alert.get("message") or None,
        "current_price": _clean_number(alert.get("current_price")),
        "entry_price": _clean_number(alert.get("entry_price")),
        "unrealized_pnl_pct": _clean_number(alert.get("unrealized_pnl_pct")),
        "stop_loss": _clean_number(alert.get("stop_loss")),
        "target_price": _clean_number(alert.get("target_price")),
        "raw_payload": alert,
    }


def normalize_watchlist_monitor_run(record: dict) -> dict:
    run_date = _clean_date(record.get("date")) or date.today().isoformat()
    run_id = record.get("run_id") or _stable_id("watchlist-monitor", run_date, record.get("item_count"), record.get("alert_count"))
    return {
        "run_id": run_id,
        "run_date": run_date,
        "item_count": _clean_int(record.get("item_count")) or 0,
        "alert_count": _clean_int(record.get("alert_count")) or 0,
        "decision_needed_count": _clean_int(record.get("decision_needed_count")) or 0,
        "research_needed_count": _clean_int(record.get("research_needed_count")) or 0,
        "raw_payload": record,
    }


def normalize_watchlist_monitor_item(item: dict, run_id: str, run_date: str) -> dict:
    return {
        "run_id": run_id,
        "run_date": run_date,
        "ticker": str(item.get("ticker") or "").upper(),
        "price": _clean_number(item.get("price")),
        "change_pct": _clean_number(item.get("change_pct")),
        "reference_price": _clean_number(item.get("reference_price")),
        "ref_change_pct": _clean_number(item.get("ref_change_pct")),
        "rsi": _clean_number(item.get("rsi")),
        "macd_hist": _clean_number(item.get("macd_hist")),
        "ema20": _clean_number(item.get("ema20")),
        "days_until_earnings": _clean_int(item.get("days_until_earnings")),
        "last_score": _clean_number(item.get("last_score")),
        "flags": item.get("flags") or [],
        "action": item.get("action") or "watch",
        "next_step": item.get("next_step"),
        "raw_payload": item,
    }


def normalize_watchlist_alert(alert: dict, run_id: str | None = None) -> dict:
    alert_date = _clean_date(alert.get("date")) or date.today().isoformat()
    alert_id = alert.get("alert_id") or _stable_id(
        "watchlist-alert",
        run_id,
        alert_date,
        alert.get("ticker"),
        alert.get("alert_type"),
        alert.get("message"),
    )
    return {
        "alert_id": alert_id,
        "run_id": run_id,
        "alert_date": alert_date,
        "ticker": str(alert.get("ticker") or "").upper(),
        "alert_type": alert.get("alert_type") or "WATCHLIST",
        "severity": alert.get("severity") or "LOW",
        "message": alert.get("message"),
        "next_step": alert.get("next_step"),
        "raw_payload": alert,
    }


def sync_monitor_run(record: dict) -> None:
    store = get_store()
    if not store:
        return
    monitor_run = normalize_monitor_run(record)
    run_id = monitor_run["run_id"]
    run_date = monitor_run["run_date"]
    positions = [
        normalize_monitor_position(position, run_id=run_id, run_date=run_date)
        for position in record.get("positions", [])
        if position.get("ticker")
    ]
    alerts = [
        normalize_monitor_alert(alert, run_id=run_id)
        for alert in record.get("alerts", [])
        if alert.get("ticker")
    ]
    store.upsert("monitor_runs", [monitor_run], "run_id")
    store.upsert("monitor_positions", positions, "run_id,ticker")
    store.upsert("monitor_alerts", alerts, "alert_id")
    logger.info("Synced monitor run to Supabase | run_id=%s", run_id)


def sync_watchlist_monitor_run(record: dict) -> None:
    store = get_store()
    if not store:
        return
    monitor_run = normalize_watchlist_monitor_run(record)
    run_id = monitor_run["run_id"]
    run_date = monitor_run["run_date"]
    items = [
        normalize_watchlist_monitor_item(item, run_id=run_id, run_date=run_date)
        for item in record.get("items", [])
        if item.get("ticker")
    ]
    alerts = [
        normalize_watchlist_alert(alert, run_id=run_id)
        for alert in record.get("alerts", [])
        if alert.get("ticker")
    ]
    try:
        store.upsert("watchlist_monitor_runs", [monitor_run], "run_id")
        store.upsert("watchlist_monitor_items", items, "run_id,ticker")
        store.upsert("watchlist_alerts", alerts, "alert_id")
        logger.info("Synced watchlist monitor run to Supabase | run_id=%s", run_id)
    except Exception as exc:
        logger.warning("Watchlist monitor Supabase sync skipped: %s", exc)


def send_pending_notifications(limit: int = 25) -> int:
    store = get_store()
    if not store:
        logger.info("Supabase is not configured; skipping pending notifications")
        return 0
    rows = store.select(
        "notifications",
        {
            "status": "eq.pending",
            "channel": "eq.slack",
            "order": "created_at.asc",
            "limit": str(limit),
        },
    )
    if not rows:
        return 0

    slack = SlackNotifier()
    sent = 0
    for row in rows:
        payload = row.get("payload") or {}
        text = (
            f"[{payload.get('severity', row.get('severity', 'INFO'))}] "
            f"{payload.get('ticker', '-')}: {payload.get('alert_type', 'ALERT')} - "
            f"{payload.get('message', '')}"
        )
        try:
            ok = slack.send_text(text)
            if not ok:
                raise RuntimeError("Slack webhook returned failure")
            store.patch(
                "notifications",
                {"notification_id": f"eq.{row['notification_id']}"},
                {"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat(), "error": None},
            )
            sent += 1
        except Exception as exc:
            store.patch(
                "notifications",
                {"notification_id": f"eq.{row['notification_id']}"},
                {"status": "error", "error": str(exc)},
            )
            logger.warning("Failed to send notification %s: %s", row.get("notification_id"), exc)
    return sent

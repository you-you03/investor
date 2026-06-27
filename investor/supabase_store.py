"""Supabase persistence adapter.

This module is deliberately optional. If SUPABASE_URL or
SUPABASE_SERVICE_ROLE_KEY is missing, all public helpers become no-ops so the
file-based workflow keeps working.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from typing import Any

import httpx

from investor.config import settings
from investor.notifications.slack import SlackNotifier
from investor.utils.logger import get_logger

logger = get_logger(__name__)
VALIDATION_HORIZONS = ("week1", "week2", "week3", "week4", "week5", "week6", "week7", "week8")


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
        number = float(value)
        return number if math.isfinite(number) else None
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


def _clean_pct(value: Any) -> float | None:
    if value is None or value == "" or value == "N/A":
        return None
    if isinstance(value, str):
        value = value.replace("%", "").replace("+", "").strip()
    return _clean_number(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


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


def _format_pending_monitor_notification(row: dict) -> str:
    payload = row.get("payload") or {}
    severity = payload.get("severity", row.get("severity", "INFO"))
    ticker = str(payload.get("ticker") or "-").upper()
    alert_type = payload.get("alert_type") or "ALERT"
    message = payload.get("message") or ""

    def money(key: str) -> str:
        value = _clean_number(payload.get(key))
        return f"${value:,.2f}" if value is not None else "-"

    pnl = _clean_number(payload.get("unrealized_pnl_pct"))
    pnl_text = f"{pnl:+.1f}%" if pnl is not None else "-"

    lines = [
        f"*[{severity}] {ticker} — {alert_type}*",
        f"買値: *{money('entry_price')}* | 現在値: *{money('current_price')}*",
        f"Target: *{money('target_price')}* | Stop: *{money('stop_loss')}* | P&L: *{pnl_text}*",
    ]
    if message:
        lines.append(f"> {message}")
    return "\n".join(lines)


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


def _best_horizon_rows(validation_id: str, stats: dict) -> list[dict]:
    rows: list[dict] = []
    horizon_summary = stats.get("horizon_summary") or {}
    for conviction in ("HIGH", "MEDIUM", "LOW"):
        candidates = [
            (horizon, (horizon_summary.get(horizon) or {}).get(conviction) or {})
            for horizon in VALIDATION_HORIZONS
        ]
        candidates = [item for item in candidates if _clean_int(item[1].get("n"))]
        if not candidates:
            continue

        def best(metric: str) -> tuple[str | None, dict | None]:
            valid = [item for item in candidates if item[1].get(metric) is not None]
            if not valid:
                return None, None
            return max(valid, key=lambda item: float(item[1][metric]))

        return_horizon, return_row = best("avg_return")
        spy_horizon, spy_row = best("avg_alpha_spy")
        sector_horizon, sector_row = best("avg_alpha_sector")
        rows.append({
            "validation_id": validation_id,
            "conviction": conviction,
            "best_return_horizon": return_horizon,
            "best_return_pct": _clean_pct((return_row or {}).get("avg_return")),
            "best_return_sample_count": _clean_int((return_row or {}).get("n")),
            "best_spy_alpha_horizon": spy_horizon,
            "best_spy_alpha_pct": _clean_pct((spy_row or {}).get("avg_alpha_spy")),
            "best_spy_alpha_sample_count": _clean_int((spy_row or {}).get("n")),
            "best_sector_alpha_horizon": sector_horizon,
            "best_sector_alpha_pct": _clean_pct((sector_row or {}).get("avg_alpha_sector")),
            "best_sector_alpha_sample_count": _clean_int((sector_row or {}).get("n")),
            "raw_payload": {
                "return": {"horizon": return_horizon, **(return_row or {})},
                "spy": {"horizon": spy_horizon, **(spy_row or {})},
                "sector": {"horizon": sector_horizon, **(sector_row or {})},
            },
        })
    return rows


def normalize_validation_stats(
    stats: dict,
    report_markdown: str,
    report_path: str,
    validation_date: str | None = None,
) -> dict[str, list[dict]]:
    validation_date = _clean_date(validation_date) or date.today().isoformat()
    validation_id = _stable_id("validation", validation_date)
    run_row = {
        "validation_id": validation_id,
        "validation_date": validation_date,
        "period_start": _clean_date(stats.get("period_start")),
        "period_end": _clean_date(stats.get("period_end")),
        "snapshot_count": _clean_int(stats.get("total")) or 0,
        "passed_threshold_count": _clean_int(stats.get("passed_n")) or 0,
        "rejected_threshold_count": _clean_int(stats.get("rejected_n")) or 0,
        "report_path": report_path,
        "report_markdown": report_markdown,
        "raw_payload": _json_safe(stats),
    }

    horizon_ic_rows = []
    for horizon, item in (stats.get("ic") or {}).items():
        horizon_ic_rows.append({
            "validation_id": validation_id,
            "horizon": horizon,
            "sample_count": _clean_int(item.get("n")) or 0,
            "spearman_rho": _clean_number(item.get("rho")),
            "p_value": _clean_number(item.get("p")),
            "label": item.get("label"),
            "raw_payload": _json_safe(item),
        })

    score_bucket_rows = []
    for order, (label, item) in enumerate((stats.get("buckets") or {}).items(), 1):
        avgs = item.get("avgs") or {}
        score_bucket_rows.append({
            "validation_id": validation_id,
            "bucket_label": label,
            "bucket_order": order,
            "sample_count": _clean_int(item.get("n")) or 0,
            "week1_avg_return_pct": _clean_pct(avgs.get("week1")),
            "week2_avg_return_pct": _clean_pct(avgs.get("week2")),
            "week3_avg_return_pct": _clean_pct(avgs.get("week3")),
            "week4_avg_return_pct": _clean_pct(avgs.get("week4")),
            "raw_payload": _json_safe(item),
        })

    conviction_spy_rows = []
    for horizon, matrix in (stats.get("conviction_spy_matrix") or {}).items():
        rows = matrix.get("rows") or {}
        for conviction, buckets in rows.items():
            for bucket_label, item in (buckets or {}).items():
                conviction_spy_rows.append({
                    "validation_id": validation_id,
                    "horizon": horizon,
                    "conviction": conviction,
                    "spy_bucket_label": bucket_label,
                    "sample_count": _clean_int(item.get("n")) or 0,
                    "avg_return_pct": _clean_pct(item.get("avg_return")),
                    "spy_min_pct": _clean_pct(matrix.get("spy_min")),
                    "spy_max_pct": _clean_pct(matrix.get("spy_max")),
                    "raw_payload": _json_safe(item),
                })

    horizon_summary_rows = []
    for horizon, by_conviction in (stats.get("horizon_summary") or {}).items():
        for conviction, item in (by_conviction or {}).items():
            horizon_summary_rows.append({
                "validation_id": validation_id,
                "horizon": horizon,
                "conviction": conviction,
                "sample_count": _clean_int(item.get("n")) or 0,
                "avg_return_pct": _clean_pct(item.get("avg_return")),
                "median_return_pct": _clean_pct(item.get("median_return")),
                "avg_alpha_spy_pct": _clean_pct(item.get("avg_alpha_spy")),
                "avg_alpha_qqq_pct": _clean_pct(item.get("avg_alpha_qqq")),
                "avg_alpha_sector_pct": _clean_pct(item.get("avg_alpha_sector")),
                "raw_payload": _json_safe(item),
            })

    regime_rows = []
    for regime, item in (stats.get("regime_summary") or {}).items():
        regime_rows.append({
            "validation_id": validation_id,
            "regime": regime,
            "sample_count": _clean_int(item.get("n")) or 0,
            "avg_return_pct": _clean_pct(item.get("avg_return")),
            "raw_payload": _json_safe(item),
        })

    factor_ic_rows = []
    for factor, by_horizon in (stats.get("factor_ic") or {}).items():
        for horizon, item in (by_horizon or {}).items():
            factor_ic_rows.append({
                "validation_id": validation_id,
                "factor": factor,
                "horizon": horizon,
                "sample_count": _clean_int(item.get("n")) or 0,
                "spearman_rho": _clean_number(item.get("rho")),
                "raw_payload": _json_safe(item),
            })

    threshold_rows = []
    for horizon, item in (stats.get("threshold_comparison") or {}).items():
        threshold_rows.append({
            "validation_id": validation_id,
            "horizon": horizon,
            "passed_avg_return_pct": _clean_pct(item.get("passed_avg")),
            "rejected_avg_return_pct": _clean_pct(item.get("rejected_avg")),
            "raw_payload": _json_safe(item),
        })

    suggestion_rows = []
    for order, suggestion in enumerate(stats.get("calibration") or [], 1):
        suggestion_rows.append({
            "suggestion_id": _stable_id("validation-suggestion", validation_id, order, suggestion),
            "validation_id": validation_id,
            "suggestion_order": order,
            "suggestion": suggestion,
            "raw_payload": {"suggestion": suggestion},
        })

    return {
        "validation_runs": [run_row],
        "validation_horizon_ic": horizon_ic_rows,
        "validation_score_buckets": score_bucket_rows,
        "validation_conviction_spy_matrix": conviction_spy_rows,
        "validation_horizon_conviction_summary": horizon_summary_rows,
        "validation_best_horizons": _best_horizon_rows(validation_id, stats),
        "validation_regime_summary": regime_rows,
        "validation_factor_ic": factor_ic_rows,
        "validation_threshold_comparison": threshold_rows,
        "validation_calibration_suggestions": suggestion_rows,
    }


def sync_validation_stats(
    stats: dict,
    report_markdown: str,
    report_path: str,
    validation_date: str | None = None,
) -> None:
    store = get_store()
    if not store:
        return
    rows_by_table = normalize_validation_stats(
        stats=stats,
        report_markdown=report_markdown,
        report_path=report_path,
        validation_date=validation_date,
    )
    conflicts = {
        "validation_runs": "validation_id",
        "validation_horizon_ic": "validation_id,horizon",
        "validation_score_buckets": "validation_id,bucket_label",
        "validation_conviction_spy_matrix": "validation_id,horizon,conviction,spy_bucket_label",
        "validation_horizon_conviction_summary": "validation_id,horizon,conviction",
        "validation_best_horizons": "validation_id,conviction",
        "validation_regime_summary": "validation_id,regime",
        "validation_factor_ic": "validation_id,factor,horizon",
        "validation_threshold_comparison": "validation_id,horizon",
        "validation_calibration_suggestions": "suggestion_id",
    }
    for table, rows in rows_by_table.items():
        store.upsert(table, rows, conflicts[table])
    logger.info(
        "Synced validation stats to Supabase | validation_id=%s",
        rows_by_table["validation_runs"][0]["validation_id"],
    )


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
        if payload.get("ticker") and payload.get("alert_type"):
            text = _format_pending_monitor_notification(row)
        else:
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

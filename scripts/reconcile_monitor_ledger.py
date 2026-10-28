#!/usr/bin/env python3
"""Compare the live book with monitor alerts. Never invent a broker fill.

Live book: ``data/portfolio_20man.csv`` (``settings.default_portfolio_path``).
``data/portfolio.csv`` is the historical A-frame ledger from the earlier
¥1,000,000 operating book. It is not the live execution book. The same ticker
can differ in shares, stop, target, and status. ``data/portfolio_100man.csv``
is the simulation book. ``data/paper_portfolio.csv`` is the B-frame hypothesis
book and is not reconciled here.

The script flags STOP / TARGET alerts that are still ``open``. It does not
close a row. Pending exit review is reported when the journal or the note
already says so. There is no broker status field that means "filled", so
auto-close stays off.

Usage:
  .venv/bin/python scripts/reconcile_monitor_ledger.py
  .venv/bin/python scripts/reconcile_monitor_ledger.py --update-alerts
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investor.core.risk import latest_monitor_prices, safe_float
from investor.utils.portfolio_contract import read_portfolio_rows

LIVE_BOOK = Path("data/portfolio_20man.csv")
LEGACY_BOOK = Path("data/portfolio.csv")
ALERTS_PATH = Path("data/monitor_alerts.json")
JOURNAL_PATH = Path("data/trade_journal.json")
MONITOR_HISTORY_PATH = Path("data/monitor_history.json")
REPORTS_DIR = Path("reports/monitor")

STOP_TYPES = {"STOP_BREACH", "STOP_LOSS"}
TARGET_TYPES = {"TARGET_HIT", "TARGET_REACHED"}
PENDING_ORDER_STATUSES = {"pending_exit_review", "exit_review"}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _open_rows(path: Path) -> list[dict]:
    return [row for row in read_portfolio_rows(path) if row.get("status") == "open"]


def pending_exit_review(row: dict, journal: list[dict]) -> bool:
    """True only when an existing field already marks an exit review as pending."""
    note = str(row.get("note") or "").lower()
    if "pending" in note and "exit review" in note:
        return True
    if str(row.get("order_status") or "").strip().lower() in PENDING_ORDER_STATUSES:
        return True
    ticker = str(row.get("ticker") or "").upper()
    for entry in journal:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("journal_kind") or "") != "monitor_exit_review":
            continue
        if str(entry.get("status") or "").lower() != "open":
            continue
        if str(entry.get("ticker") or "").upper() == ticker:
            return True
    return False


def _latest_alerts(alerts: list[dict], ticker: str, entry_date: str) -> dict[str, dict]:
    chosen: dict[str, dict] = {}
    for alert in alerts:
        if str(alert.get("ticker") or "").upper() != ticker:
            continue
        alert_date = str(alert.get("date") or "")
        if entry_date and alert_date and alert_date < entry_date:
            continue
        kind = str(alert.get("alert_type") or "")
        if kind not in STOP_TYPES and kind not in TARGET_TYPES:
            continue
        bucket = "stop" if kind in STOP_TYPES else "target"
        previous = chosen.get(bucket)
        if previous is None or str(alert.get("date") or "") >= str(previous.get("date") or ""):
            chosen[bucket] = alert
    return chosen


def _legacy_difference(live: dict, legacy_rows: list[dict]) -> str:
    ticker = str(live.get("ticker") or "").upper()
    matches = [row for row in legacy_rows if str(row.get("ticker") or "").upper() == ticker]
    if not matches:
        return "not in portfolio.csv"
    open_matches = [row for row in matches if row.get("status") == "open"]
    legacy = open_matches[-1] if open_matches else matches[-1]
    bits = [f"portfolio.csv status={legacy.get('status') or 'blank'}"]
    for field in ("stop_loss", "target_price", "shares"):
        live_value = str(live.get(field) or "")
        legacy_value = str(legacy.get(field) or "")
        if live_value != legacy_value:
            bits.append(f"{field} live={live_value or 'blank'} legacy={legacy_value or 'blank'}")
    return "; ".join(bits)


def build_findings(
    live_rows: list[dict],
    alerts: list[dict],
    journal: list[dict],
    legacy_rows: list[dict],
    monitor_prices: dict[str, float],
    *,
    as_of: str,
) -> list[dict]:
    findings: list[dict] = []
    for row in live_rows:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        stop = safe_float(row.get("stop_loss"))
        target = safe_float(row.get("target_price"))
        price = monitor_prices.get(ticker)
        latest = _latest_alerts(alerts, ticker, str(row.get("entry_date") or ""))
        pending = pending_exit_review(row, journal)
        legacy = _legacy_difference(row, legacy_rows)

        if "stop" in latest:
            alert = latest["stop"]
            findings.append({
                "ticker": ticker,
                "reconcile_kind": "unresolved_stop_alert",
                "severity": "HIGH",
                "ledger_status": "open",
                "pending_exit_review": pending,
                "auto_closed": False,
                "alert_date": alert.get("date"),
                "alert_type": alert.get("alert_type"),
                "latest_monitor_price": price,
                "stop_loss": stop,
                "target_price": target,
                "legacy_book": legacy,
                "message": (
                    f"{ticker} still open after {alert.get('alert_type')} on {alert.get('date')}. "
                    "No broker fill is recorded. Leave the row open for exit review."
                ),
            })
        if price is not None and stop is not None and price <= stop:
            findings.append({
                "ticker": ticker,
                "reconcile_kind": "live_price_through_stop",
                "severity": "HIGH",
                "ledger_status": "open",
                "pending_exit_review": pending,
                "auto_closed": False,
                "alert_date": as_of,
                "alert_type": "STOP_BREACH",
                "latest_monitor_price": price,
                "stop_loss": stop,
                "target_price": target,
                "legacy_book": legacy,
                "message": (
                    f"{ticker} monitor price {price:.2f} is through stop {stop:.2f} and status is still open. "
                    "No broker fill is recorded. Do not auto-close."
                ),
            })
        if "target" in latest:
            alert = latest["target"]
            findings.append({
                "ticker": ticker,
                "reconcile_kind": "unresolved_target_alert",
                "severity": "HIGH",
                "ledger_status": "open",
                "pending_exit_review": pending,
                "auto_closed": False,
                "alert_date": alert.get("date"),
                "alert_type": alert.get("alert_type"),
                "latest_monitor_price": price,
                "stop_loss": stop,
                "target_price": target,
                "legacy_book": legacy,
                "message": (
                    f"{ticker} still open after {alert.get('alert_type')} on {alert.get('date')}. "
                    "Target contact is not a fill. Leave the row open for exit review."
                ),
            })
        if price is not None and target is not None and price >= target:
            findings.append({
                "ticker": ticker,
                "reconcile_kind": "live_price_through_target",
                "severity": "HIGH",
                "ledger_status": "open",
                "pending_exit_review": pending,
                "auto_closed": False,
                "alert_date": as_of,
                "alert_type": "TARGET_HIT",
                "latest_monitor_price": price,
                "stop_loss": stop,
                "target_price": target,
                "legacy_book": legacy,
                "message": (
                    f"{ticker} monitor price {price:.2f} is through target {target:.2f} and status is still open. "
                    "No broker fill is recorded. Do not auto-close."
                ),
            })
        if stop is None or target is None:
            findings.append({
                "ticker": ticker,
                "reconcile_kind": "open_row_missing_stop_or_target",
                "severity": "HIGH",
                "ledger_status": "open",
                "pending_exit_review": pending,
                "auto_closed": False,
                "alert_date": as_of,
                "alert_type": "RISK_DATA_MISSING",
                "latest_monitor_price": price,
                "stop_loss": stop,
                "target_price": target,
                "legacy_book": legacy,
                "message": f"{ticker} is open with stop={stop} target={target}. Risk fields are incomplete.",
            })
    return findings


def render_report(findings: list[dict], *, as_of: str, live_count: int, monitor_date: str | None) -> str:
    lines = [
        f"# Monitor ledger reconciliation — {as_of}",
        "",
        "## Books",
        "",
        "- Live book: `data/portfolio_20man.csv`. This is the ¥200,000 book in `settings.default_portfolio_path`.",
        "- `data/portfolio.csv` is the historical A-frame ledger. It is not the live execution book. Differences below are informational.",
        "- `data/portfolio_100man.csv` is the simulation book and is not reconciled here.",
        "- `data/paper_portfolio.csv` is the B-frame hypothesis book and is not reconciled here.",
        "",
        f"- Open live rows: {live_count}",
        f"- Latest monitor price date: {monitor_date or 'none'}",
        "- Auto-close: off. This job does not write `exit_price`, `exit_date`, or `status=closed`.",
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.append("No open live row has an unresolved stop or target alert.")
        lines.append("")
        return "\n".join(lines)
    lines.append("| Ticker | Kind | Pending exit review | Monitor price | Stop | Target | Legacy book |")
    lines.append("|---|---|---|---|---|---|---|")
    for finding in findings:
        price = finding.get("latest_monitor_price")
        price_text = "—" if price is None else f"{price:.2f}"
        stop = finding.get("stop_loss")
        target = finding.get("target_price")
        lines.append(
            f"| {finding['ticker']} | {finding['reconcile_kind']} | "
            f"{'yes' if finding['pending_exit_review'] else 'no'} | {price_text} | "
            f"{'—' if stop is None else stop} | {'—' if target is None else target} | {finding['legacy_book']} |"
        )
    lines.append("")
    for finding in findings:
        lines.append(f"- **{finding['ticker']}** ({finding['reconcile_kind']}): {finding['message']}")
    lines.append("")
    lines.append("Next step for a flagged open row is `/decision --mode exit`, after a human confirms the broker status.")
    lines.append("")
    return "\n".join(lines)


def alerts_to_append(findings: list[dict], existing: list[dict], *, as_of: str) -> list[dict]:
    seen = {
        (
            str(alert.get("date") or ""),
            str(alert.get("ticker") or "").upper(),
            str(alert.get("reconcile_kind") or ""),
        )
        for alert in existing
        if isinstance(alert, dict)
    }
    new_alerts = []
    for finding in findings:
        key = (as_of, finding["ticker"], finding["reconcile_kind"])
        if key in seen:
            continue
        seen.add(key)
        new_alerts.append({
            "date": as_of,
            "ticker": finding["ticker"],
            "alert_type": "LEDGER_RECONCILE",
            "severity": finding["severity"],
            "reconcile_kind": finding["reconcile_kind"],
            "message": finding["message"],
            "ledger_status": "open",
            "pending_exit_review": finding["pending_exit_review"],
            "auto_closed": False,
            "source": "reconcile_monitor_ledger",
            "current_price": finding.get("latest_monitor_price"),
            "stop_loss": finding.get("stop_loss"),
            "target_price": finding.get("target_price"),
        })
    return new_alerts


def run(*, as_of: str | None = None, update_alerts: bool = False) -> dict:
    today = as_of or date.today().isoformat()
    live_rows = _open_rows(LIVE_BOOK)
    legacy_rows = read_portfolio_rows(LEGACY_BOOK)
    alerts = _load_json(ALERTS_PATH, [])
    if not isinstance(alerts, list):
        alerts = []
    journal = _load_json(JOURNAL_PATH, [])
    if not isinstance(journal, list):
        journal = []
    monitor_date, prices = latest_monitor_prices(MONITOR_HISTORY_PATH)
    findings = build_findings(
        live_rows,
        alerts,
        journal,
        legacy_rows,
        prices,
        as_of=today,
    )
    report = render_report(findings, as_of=today, live_count=len(live_rows), monitor_date=monitor_date)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"reconcile_{today}.md"
    report_path.write_text(report, encoding="utf-8")
    appended = []
    if update_alerts:
        appended = alerts_to_append(findings, alerts, as_of=today)
        if appended:
            alerts.extend(appended)
            ALERTS_PATH.write_text(json.dumps(alerts, indent=2, ensure_ascii=False))
    print(report)
    print(f"\n→ report: {report_path}")
    print(f"→ findings: {len(findings)}; alerts appended: {len(appended)}")
    return {
        "findings": len(findings),
        "alerts_appended": len(appended),
        "report": str(report_path),
    }


def main() -> None:
    update_alerts = "--update-alerts" in sys.argv
    run(update_alerts=update_alerts)


if __name__ == "__main__":
    main()

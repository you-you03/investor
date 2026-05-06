"""
Monitor Agent — runs daily to check open positions and send alerts.

Flow:
  1. Load all open positions from data/portfolio.csv
  2. Fetch current price/snapshot via yfinance for each position
  3. Rule-based threshold checks (investor/core/monitor.py) — Python only, no Claude
  4. Save alert records to data/monitor_alerts.json
  5. Send Slack daily summary + separate HIGH severity alerts

Design: No Anthropic SDK calls. Claude Code (the session) reads the alerts
and provides commentary via /monitor command in CLAUDE.md.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from investor.core.monitor import Alert, check_all_positions
from investor.data.yfinance_client import YFinanceClient
from investor.notifications.slack import SlackNotifier
from investor.utils.logger import get_logger

logger = get_logger(__name__)

PORTFOLIO_PATH = Path("data/portfolio.csv")
ALERTS_PATH = Path("data/monitor_alerts.json")
HISTORY_PATH = Path("data/monitor_history.json")
REPORTS_DIR = Path("reports/monitor")


def _load_open_positions() -> list[dict]:
    if not PORTFOLIO_PATH.exists():
        return []
    try:
        with open(PORTFOLIO_PATH) as f:
            reader = csv.DictReader(f)
            return [row for row in reader if row.get("status") == "open"]
    except Exception as e:
        logger.warning(f"Failed to read portfolio: {e}")
        return []


def _save_alerts(alerts: list[dict]) -> None:
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if ALERTS_PATH.exists():
        try:
            history = json.loads(ALERTS_PATH.read_text())
        except Exception:
            pass
    history.extend(alerts)
    ALERTS_PATH.write_text(json.dumps(history, indent=2))


def _save_daily_summary(positions: list[dict], alerts: list[dict]) -> None:
    """Always save daily run record including price snapshots and alert count."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text())
        except Exception:
            pass
    record = {
        "date": date.today().isoformat(),
        "position_count": len(positions),
        "alert_count": len(alerts),
        "high_alert_count": sum(1 for a in alerts if a.get("severity") == "HIGH"),
        "positions": positions,
        "alerts": alerts,
    }
    history.append(record)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))
    _save_markdown_report(positions, alerts)


def _save_markdown_report(positions: list[dict], alerts: list[dict]) -> None:
    """Generate and save a markdown report to reports/monitor/monitor_{date}.md."""
    today = date.today().isoformat()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"monitor_{today}.md"

    severity_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}

    total_pnl = 0.0
    position_rows: list[str] = []
    for p in positions:
        current = p.get("current_price")
        entry = p.get("entry_price", 0.0)
        shares = p.get("shares", 0.0)
        target = p.get("target_price", "—")
        stop = p.get("stop_loss", "—")
        ticker = p.get("ticker", "")

        if current and entry and shares:
            pnl = (current - entry) * shares
            pnl_pct = (current - entry) / entry * 100
            total_pnl += pnl
            state = "✅" if pnl >= 0 else "⚠️"
            position_rows.append(
                f"| {ticker} | ${current:.2f} | ${entry:.2f} | {shares:.0f} "
                f"| {pnl:+.2f} | {pnl_pct:+.1f}% | ${stop} | ${target} | {state} |"
            )
        else:
            position_rows.append(
                f"| {ticker} | — | ${entry:.2f} | {shares:.0f} | — | — | ${stop} | ${target} | — |"
            )

    high_count = sum(1 for a in alerts if a.get("severity") == "HIGH")
    med_count = sum(1 for a in alerts if a.get("severity") == "MEDIUM")
    low_count = sum(1 for a in alerts if a.get("severity") == "LOW")

    alert_rows: list[str] = []
    for a in alerts:
        icon = severity_icon.get(a.get("severity", "LOW"), "🔵")
        alert_rows.append(
            f"| {icon} {a.get('severity', '—')} | {a.get('ticker', '—')} "
            f"| {a.get('alert_type', '—')} | {a.get('message', '—')} |"
        )

    lines: list[str] = [
        f"# Monitor Report — {today}",
        "",
        "## サマリー",
        "",
        "| 指標 | 値 |",
        "|---|---|",
        f"| オープンポジション | {len(positions)} 銘柄 |",
        f"| 合計未実現損益 | **{total_pnl:+.2f}** |",
        f"| 🔴 HIGH アラート | {high_count} 件 |",
        f"| 🟡 MEDIUM アラート | {med_count} 件 |",
        f"| 🔵 LOW アラート | {low_count} 件 |",
        "",
        "---",
        "",
        "## ポジション損益",
        "",
        "| Ticker | 現在値 | 買値 | 株数 | 損益 | 損益% | ストップ | 目標 | 状態 |",
        "|--------|-------|------|------|------|------|---------|------|------|",
    ]
    lines.extend(position_rows)
    lines += [
        "",
        "---",
        "",
        "## アラート",
        "",
    ]
    if alert_rows:
        lines += [
            "| 重要度 | Ticker | タイプ | メッセージ |",
            "|--------|--------|--------|-----------|",
        ]
        lines.extend(alert_rows)
    else:
        lines.append("アラートなし — 全ポジション正常範囲内。")

    lines += [
        "",
        "---",
        "",
        f"*生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {HISTORY_PATH}*",
    ]

    report_path.write_text("\n".join(lines))
    logger.info(f"Saved markdown report to {report_path}")


class MonitorAgent:
    def __init__(self) -> None:
        self.yf = YFinanceClient()
        self.slack = SlackNotifier()

    def run(self, dry_run: bool = False) -> list[dict]:
        """Execute daily monitoring for all open positions."""
        logger.info("Monitor Agent started")

        positions = _load_open_positions()
        if not positions:
            logger.info("No open positions to monitor")
            if not dry_run:
                self.slack.send_text(
                    f":chart_with_upwards_trend: Daily Summary — {date.today().isoformat()}\n"
                    "_No open positions._"
                )
            return []

        logger.info(f"Monitoring {len(positions)} open position(s)")

        # Step 1: Fetch snapshots for all positions
        snapshots: dict[str, dict] = {}
        for p in positions:
            ticker = p["ticker"].upper()
            logger.info(f"  Fetching snapshot for {ticker}")
            snapshot = self.yf.get_stock_snapshot(ticker)
            if snapshot:
                snapshots[ticker] = snapshot

        # Step 2: Rule-based threshold checks (no Claude)
        rule_alerts = check_all_positions(positions, snapshots)
        high_alerts = [a for a in rule_alerts if a.severity == "HIGH"]
        logger.info(
            f"Threshold checks complete: {len(rule_alerts)} alert(s), "
            f"{len(high_alerts)} HIGH"
        )

        # Step 3: Build alert records (rule-based only; Claude commentary via /monitor skill)
        today = date.today().isoformat()
        alert_records = []
        for alert in rule_alerts:
            record = {
                "date": today,
                **alert.to_dict(),
            }
            alert_records.append(record)

        if dry_run:
            logger.info("[DRY RUN] Alerts:\n" + json.dumps(alert_records, indent=2))
            return alert_records

        if alert_records:
            _save_alerts(alert_records)
            logger.info(f"Saved {len(alert_records)} alert(s)")

        # Step 4: Build enriched positions for Slack
        enriched_positions = []
        for p in positions:
            ticker = p["ticker"].upper()
            snap = snapshots.get(ticker, {})
            enriched_positions.append({
                "ticker": ticker,
                "shares": float(p.get("shares") or 0),
                "entry_price": float(p.get("entry_price") or 0),
                "current_price": snap.get("price"),
                "target_price": p.get("target_price") or None,
                "stop_loss": p.get("stop_loss") or None,
            })

        # Always save daily summary (even with 0 alerts)
        _save_daily_summary(enriched_positions, alert_records)
        logger.info(f"Saved daily summary to {HISTORY_PATH}")

        # Daily summary (always sent)
        self.slack.send_portfolio_summary(enriched_positions, alert_records)

        # Separate Slack message for each HIGH alert
        position_map = {p["ticker"]: p for p in enriched_positions}
        for record in alert_records:
            if record.get("severity") == "HIGH":
                position = position_map.get(record["ticker"])
                if position:
                    self.slack.send_sell_alert(record, position)

        return alert_records


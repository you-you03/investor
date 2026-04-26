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
from datetime import date
from pathlib import Path
from investor.core.monitor import Alert, check_all_positions
from investor.data.yfinance_client import YFinanceClient
from investor.notifications.slack import SlackNotifier
from investor.utils.logger import get_logger

logger = get_logger(__name__)

PORTFOLIO_PATH = Path("data/portfolio.csv")
ALERTS_PATH = Path("data/monitor_alerts.json")
HISTORY_PATH = Path("data/monitor_history.json")


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


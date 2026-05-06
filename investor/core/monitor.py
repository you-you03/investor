"""
Rule-based threshold checks for portfolio monitoring.
No Claude calls — pure Python business logic.

Threshold rules:
  current_price <= stop_loss          → HIGH  (STOP_LOSS)
  intraday change < -5%               → HIGH  (SHARP_DROP)
  current_price >= target_price       → HIGH  (TARGET_REACHED)
  cumulative P&L < -5%                → MEDIUM (SIGNIFICANT_DRAWDOWN)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AlertLevel = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass
class Alert:
    ticker: str
    alert_type: str
    severity: AlertLevel
    message: str
    current_price: float
    entry_price: float
    unrealized_pnl_pct: float
    stop_loss: float | None = None
    target_price: float | None = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "current_price": self.current_price,
            "entry_price": self.entry_price,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
        }


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or 0) or default
    except (ValueError, TypeError):
        return default


def check_position(position: dict, snapshot: dict) -> list[Alert]:
    """
    Run all threshold checks for a single position.

    Args:
        position: Row from portfolio.csv as dict
        snapshot: YFinanceClient.get_stock_snapshot() result

    Returns:
        List of Alert objects. Empty list means position is healthy.
    """
    alerts: list[Alert] = []
    ticker = position["ticker"].upper()

    entry_price = _safe_float(position.get("entry_price"))
    if entry_price <= 0 or not snapshot:
        return []

    current_price = snapshot.get("price")
    if not current_price:
        return []
    current_price = float(current_price)

    stop_loss = _safe_float(position.get("stop_loss")) or None
    target_price = _safe_float(position.get("target_price")) or None

    unrealized_pnl_pct = round((current_price - entry_price) / entry_price * 100, 2)

    base = dict(
        ticker=ticker,
        current_price=current_price,
        entry_price=entry_price,
        unrealized_pnl_pct=unrealized_pnl_pct,
        stop_loss=stop_loss,
        target_price=target_price,
    )

    # HIGH: stop loss triggered
    if stop_loss and current_price <= stop_loss:
        alerts.append(Alert(
            alert_type="STOP_LOSS",
            severity="HIGH",
            message=f"Price ${current_price:.2f} hit stop loss ${stop_loss:.2f}",
            **base,
        ))

    # HIGH: sharp intraday drop > 5%
    change_pct = snapshot.get("change_pct")
    if change_pct is not None and float(change_pct) < -5.0:
        alerts.append(Alert(
            alert_type="SHARP_DROP",
            severity="HIGH",
            message=f"Intraday drop {float(change_pct):.1f}%",
            **base,
        ))

    # HIGH: target price reached — triggers Slack sell alert
    if target_price and current_price >= target_price:
        alerts.append(Alert(
            alert_type="TARGET_REACHED",
            severity="HIGH",
            message=f"Price ${current_price:.2f} reached target ${target_price:.2f}",
            **base,
        ))

    # MEDIUM: cumulative drawdown exceeds 5% (early warning before stop-loss)
    if unrealized_pnl_pct < -5.0:
        alerts.append(Alert(
            alert_type="SIGNIFICANT_DRAWDOWN",
            severity="MEDIUM",
            message=f"Unrealized loss {unrealized_pnl_pct:.1f}%",
            **base,
        ))

    return alerts


def check_all_positions(
    positions: list[dict],
    snapshots: dict[str, dict],
) -> list[Alert]:
    """Run threshold checks for all positions and return combined alerts."""
    all_alerts: list[Alert] = []
    for position in positions:
        ticker = position["ticker"].upper()
        snapshot = snapshots.get(ticker) or {}
        all_alerts.extend(check_position(position, snapshot))
    return all_alerts

"""
Rule-based threshold checks for portfolio monitoring.
No Claude calls — pure Python business logic.

Threshold rules mirror AGENTS.md:
  current_price <= stop_loss          → HIGH   (STOP_BREACH)
  pnl_pct >= +5%, exit_stage 0        → HIGH   (STAGE1_HIT)
  pnl_pct >= +15%, exit_stage 1       → HIGH   (STAGE2_HIT)
  current_price <= trailing_stop      → HIGH   (TRAILING_STOP_HIT)
  current_price <= stop_loss * 1.03   → MEDIUM (NEAR_STOP)
  pnl_pct >= +12%, exit_stage 1       → MEDIUM (NEAR_STAGE2)
  pnl_pct <= -5%                      → MEDIUM (DOWN_5PCT)
  pnl_pct >= +25%, exit_stage 2       → INFO   (UP_25PCT_TRAILING)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AlertLevel = Literal["HIGH", "MEDIUM", "LOW", "INFO"]


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
    trailing_stop_price: float | None = None

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
            "trailing_stop_price": self.trailing_stop_price,
        }


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or 0) or default
    except (ValueError, TypeError):
        return default


def _exit_stage(position: dict) -> int:
    raw = position.get("exit_stage")
    if raw in (None, ""):
        raw = position.get("partial_exit_pct")
        if str(raw) == "50":
            return 2
    try:
        return int(float(raw or 0))
    except (TypeError, ValueError):
        return 0


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
    trailing_stop_price = _safe_float(position.get("trailing_stop_price")) or None
    exit_stage = _exit_stage(position)

    unrealized_pnl_pct = round((current_price - entry_price) / entry_price * 100, 2)

    base = dict(
        ticker=ticker,
        current_price=current_price,
        entry_price=entry_price,
        unrealized_pnl_pct=unrealized_pnl_pct,
        stop_loss=stop_loss,
        target_price=target_price,
        trailing_stop_price=trailing_stop_price,
    )

    # HIGH: hard stop triggered.
    if stop_loss and current_price <= stop_loss:
        alerts.append(Alert(
            alert_type="STOP_BREACH",
            severity="HIGH",
            message=f"Price ${current_price:.2f} hit stop loss ${stop_loss:.2f}",
            **base,
        ))

    # HIGH: trailing stop triggered after partial exit.
    if trailing_stop_price and current_price <= trailing_stop_price:
        alerts.append(Alert(
            alert_type="TRAILING_STOP_HIT",
            severity="HIGH",
            message=f"Price ${current_price:.2f} hit trailing stop ${trailing_stop_price:.2f}",
            **base,
        ))

    # HIGH: staged profit-taking rules.
    if unrealized_pnl_pct >= 5.0 and exit_stage == 0:
        alerts.append(Alert(
            alert_type="STAGE1_HIT",
            severity="HIGH",
            message=f"P&L {unrealized_pnl_pct:.1f}% reached Stage 1 profit-taking threshold",
            **base,
        ))
    if unrealized_pnl_pct >= 15.0 and exit_stage == 1:
        alerts.append(Alert(
            alert_type="STAGE2_HIT",
            severity="HIGH",
            message=f"P&L {unrealized_pnl_pct:.1f}% reached Stage 2 profit-taking threshold",
            **base,
        ))

    # MEDIUM: early warnings.
    if stop_loss and current_price <= stop_loss * 1.03 and current_price > stop_loss:
        alerts.append(Alert(
            alert_type="NEAR_STOP",
            severity="MEDIUM",
            message=f"Price ${current_price:.2f} is within 3% of stop ${stop_loss:.2f}",
            **base,
        ))
    if unrealized_pnl_pct >= 12.0 and exit_stage == 1:
        alerts.append(Alert(
            alert_type="NEAR_STAGE2",
            severity="MEDIUM",
            message=f"P&L {unrealized_pnl_pct:.1f}% is nearing Stage 2 threshold",
            **base,
        ))
    if unrealized_pnl_pct <= -5.0:
        alerts.append(Alert(
            alert_type="DOWN_5PCT",
            severity="MEDIUM",
            message=f"Unrealized loss {unrealized_pnl_pct:.1f}%",
            **base,
        ))
    if unrealized_pnl_pct >= 25.0 and exit_stage == 2:
        alerts.append(Alert(
            alert_type="UP_25PCT_TRAILING",
            severity="INFO",
            message=f"P&L {unrealized_pnl_pct:.1f}% while trailing stop is active",
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

"""Deterministic portfolio risk controls for Mandate V2.

The LLM may rank opportunities, but it does not choose final position size.
Sizing is derived from the planned entry, protective stop, and portfolio limits.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from investor.config import settings


MONITOR_HISTORY_PATH = Path("data/monitor_history.json")

_CONVICTION_RISK_MULTIPLIER = {
    "HIGH": 1.0,
    "MEDIUM": 0.75,
    "LOW": 0.5,
}


def safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PositionPlan:
    shares: float
    notional_usd: float
    planned_risk_usd: float
    risk_budget_usd: float
    risk_pct_of_capital: float
    stop_distance_usd: float
    buffered_risk_per_share_usd: float
    reward_risk_ratio: float | None


def calculate_position_plan(
    *,
    entry_price: float,
    stop_loss: float,
    target_price: float | None = None,
    conviction: str = "MEDIUM",
    capital_usd: float | None = None,
) -> PositionPlan:
    """Calculate a risk-sized position capped by max notional exposure."""
    capital = float(settings.available_capital_usd if capital_usd is None else capital_usd)
    entry = float(entry_price)
    stop = float(stop_loss)
    target = float(target_price) if target_price is not None else None

    if entry <= 0:
        raise ValueError("entry_price must be positive")
    if stop <= 0 or stop >= entry:
        raise ValueError("stop_loss must be positive and below entry_price")
    if target is not None and target <= entry:
        raise ValueError("target_price must be above entry_price")

    stop_distance = entry - stop
    gap_buffer = entry * settings.gap_slippage_buffer_pct
    buffered_risk_per_share = stop_distance + gap_buffer
    risk_multiplier = _CONVICTION_RISK_MULTIPLIER.get(conviction.upper(), 0.5)
    risk_budget = capital * settings.risk_per_trade_pct * risk_multiplier
    max_notional = capital * settings.max_position_pct

    shares_by_risk = risk_budget / buffered_risk_per_share
    shares_by_notional = max_notional / entry
    shares = min(shares_by_risk, shares_by_notional)
    if not settings.supports_fractional_shares:
        shares = math.floor(shares)
    else:
        shares = math.floor(shares * 1000) / 1000
    if shares <= 0:
        raise ValueError("risk limits result in zero executable shares")

    notional = shares * entry
    planned_risk = shares * buffered_risk_per_share
    reward_risk = (target - entry) / buffered_risk_per_share if target is not None else None
    return PositionPlan(
        shares=shares,
        notional_usd=round(notional, 2),
        planned_risk_usd=round(planned_risk, 2),
        risk_budget_usd=round(risk_budget, 2),
        risk_pct_of_capital=round(planned_risk / capital, 6),
        stop_distance_usd=round(stop_distance, 4),
        buffered_risk_per_share_usd=round(buffered_risk_per_share, 4),
        reward_risk_ratio=round(reward_risk, 2) if reward_risk is not None else None,
    )


def position_heat_usd(position: dict, *, mark_price: float | None = None) -> float | None:
    """Return loss to stop including a gap buffer; None means risk is undefined."""
    shares = safe_float(position.get("shares"))
    entry = safe_float(position.get("entry_price"))
    stop = safe_float(position.get("stop_loss"))
    if shares is None or entry is None or stop is None or shares <= 0 or entry <= 0:
        return None
    reference_price = float(mark_price) if mark_price is not None else entry
    if reference_price <= 0:
        return None
    downside_to_stop = max(reference_price - stop, 0.0)
    return shares * (downside_to_stop + reference_price * settings.gap_slippage_buffer_pct)


def latest_monitor_prices(path: Path | None = None) -> tuple[str | None, dict[str, float]]:
    """Read the newest saved monitor snapshot without making a network call."""
    target = path or MONITOR_HISTORY_PATH
    if not target.exists():
        return None, {}
    try:
        records = json.loads(target.read_text())
    except Exception:
        return None, {}
    if not isinstance(records, list) or not records:
        return None, {}
    latest = max(records, key=lambda row: str(row.get("date") or ""))
    prices: dict[str, float] = {}
    for position in latest.get("positions") or []:
        ticker = str(position.get("ticker") or "").upper()
        price = safe_float(position.get("current_price"))
        if ticker and price is not None:
            prices[ticker] = price
    return latest.get("date"), prices


def portfolio_guard_violations(
    positions: list[dict],
    *,
    monitor_path: Path | None = None,
) -> list[str]:
    """Audit open positions and return reasons that must block new BUY proposals."""
    violations: list[str] = []
    monitor_date, prices = latest_monitor_prices(monitor_path)
    total_heat = 0.0

    for position in positions:
        ticker = str(position.get("ticker") or "UNKNOWN").upper()
        shares = safe_float(position.get("shares"))
        entry = safe_float(position.get("entry_price"))
        stop = safe_float(position.get("stop_loss"))
        target = safe_float(position.get("target_price"))

        if shares is None or shares <= 0 or entry is None or entry <= 0:
            violations.append(f"{ticker}: open position has invalid shares/entry_price")
            continue
        if stop is None:
            violations.append(f"{ticker}: open position missing stop_loss")
        if target is None:
            violations.append(f"{ticker}: open position missing target_price")

        current_price = prices.get(ticker)
        reference_price = current_price if current_price is not None else entry
        exposure_pct = shares * reference_price / settings.available_capital_usd
        if exposure_pct > settings.max_position_pct + 1e-9:
            violations.append(
                f"{ticker}: existing exposure {exposure_pct:.1%} exceeds "
                f"{settings.max_position_pct:.0%} limit"
            )

        heat = position_heat_usd(position, mark_price=current_price)
        if heat is not None:
            total_heat += heat

        if stop is not None and current_price is not None and current_price <= stop:
            violations.append(
                f"{ticker}: unresolved STOP_BREACH (${current_price:.2f} <= ${stop:.2f}, "
                f"monitor={monitor_date or date.today().isoformat()})"
            )

    heat_pct = total_heat / settings.available_capital_usd
    if heat_pct > settings.max_portfolio_heat_pct + 1e-9:
        violations.append(
            f"portfolio heat {heat_pct:.2%} exceeds {settings.max_portfolio_heat_pct:.2%} limit"
        )
    return violations

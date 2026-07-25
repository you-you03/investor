import json

import pytest

from investor.config import settings
from investor.core.risk import (
    calculate_position_plan,
    portfolio_guard_violations,
    position_heat_usd,
)


def test_position_plan_is_capped_by_risk_and_notional():
    plan = calculate_position_plan(
        entry_price=100,
        stop_loss=95,
        target_price=112,
        conviction="MEDIUM",
    )

    assert plan.notional_usd <= settings.available_capital_usd * settings.max_position_pct
    assert plan.planned_risk_usd <= plan.risk_budget_usd
    assert plan.reward_risk_ratio >= settings.min_reward_risk_ratio


def test_position_plan_rejects_invalid_price_geometry():
    with pytest.raises(ValueError, match="stop_loss"):
        calculate_position_plan(entry_price=100, stop_loss=101, target_price=120)


def test_heat_keeps_gap_buffer_when_stop_is_above_entry():
    heat = position_heat_usd(
        {"shares": 2, "entry_price": 100, "stop_loss": 105},
        mark_price=110,
    )

    assert heat == pytest.approx(2 * ((110 - 105) + 110 * settings.gap_slippage_buffer_pct))


def test_portfolio_guard_blocks_missing_risk_and_saved_stop_breach(tmp_path):
    monitor_path = tmp_path / "monitor_history.json"
    monitor_path.write_text(json.dumps([{
        "date": "2026-07-25",
        "positions": [{"ticker": "TEST", "current_price": 89}],
    }]))
    positions = [{
        "ticker": "TEST",
        "shares": 1,
        "entry_price": 100,
        "stop_loss": 90,
        "target_price": "",
    }]

    violations = portfolio_guard_violations(positions, monitor_path=monitor_path)

    assert any("missing target_price" in violation for violation in violations)
    assert any("STOP_BREACH" in violation for violation in violations)

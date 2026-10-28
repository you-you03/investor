from investor.core.monitor import check_position


def _position(**overrides):
    base = {
        "ticker": "VRT",
        "entry_price": 100,
        "stop_loss": 90,
        "target_price": 130,
        "exit_stage": "0",
        "shares": "4",
    }
    base.update(overrides)
    return base


def _types(alerts):
    return {alert.alert_type for alert in alerts}


def test_stage1_hit_at_five_percent_gain_for_unstaged_position():
    alerts = check_position(_position(), {"price": 105})

    assert "STAGE1_HIT" in _types(alerts)
    assert next(a for a in alerts if a.alert_type == "STAGE1_HIT").severity == "HIGH"


def test_stage2_and_near_stage2_for_stage1_position():
    alerts = check_position(_position(exit_stage="1"), {"price": 115})

    assert {"STAGE2_HIT", "NEAR_STAGE2"} <= _types(alerts)


def test_trailing_stop_hit_for_stage2_position():
    alerts = check_position(
        _position(exit_stage="2", trailing_stop_price="112"),
        {"price": 111},
    )

    assert "TRAILING_STOP_HIT" in _types(alerts)


def test_near_stop_and_down_five_percent_match_monitor_rules():
    alerts = check_position(_position(stop_loss=94), {"price": 95})

    assert {"NEAR_STOP", "DOWN_5PCT"} <= _types(alerts)


def test_info_alert_for_large_gain_while_trailing():
    alerts = check_position(_position(exit_stage="2", trailing_stop_price="120"), {"price": 126})

    assert "UP_25PCT_TRAILING" in _types(alerts)


def test_small_position_does_not_trigger_partial_exit():
    alerts = check_position(_position(shares="2"), {"price": 105})

    assert "STAGE1_HIT" not in _types(alerts)
    assert "SMALL_POSITION_PROFIT_REVIEW" in _types(alerts)


def test_prime_exit_window_is_info_and_not_an_order():
    from datetime import date, timedelta

    inside = (date.today() - timedelta(days=5)).isoformat()
    alerts = check_position(_position(entry_date=inside, shares="1"), {"price": 101})

    alert = next(a for a in alerts if a.alert_type == "PRIME_EXIT_WINDOW")
    assert alert.severity == "INFO"
    assert "not an order" in alert.message

    too_early = (date.today() - timedelta(days=3)).isoformat()
    too_late = (date.today() - timedelta(days=8)).isoformat()
    assert "PRIME_EXIT_WINDOW" not in _types(check_position(_position(entry_date=too_early), {"price": 101}))
    assert "PRIME_EXIT_WINDOW" not in _types(check_position(_position(entry_date=too_late), {"price": 101}))


def test_target_hit_fires_even_when_target_is_below_entry():
    alerts = check_position(
        _position(entry_price=441, target_price=434.19, stop_loss=388.02, shares="1"),
        {"price": 436.87},
    )

    alert = next(a for a in alerts if a.alert_type == "TARGET_HIT")
    assert alert.severity == "HIGH"
    assert "do not close the ledger" in alert.message
    assert "STOP_BREACH" not in _types(alerts)


def test_missing_stop_or_target_is_high_risk_alert():
    alerts = check_position(_position(stop_loss="", target_price=""), {"price": 101})

    alert = next(a for a in alerts if a.alert_type == "RISK_DATA_MISSING")
    assert alert.severity == "HIGH"

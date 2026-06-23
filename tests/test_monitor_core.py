from investor.core.monitor import check_position


def _position(**overrides):
    base = {
        "ticker": "VRT",
        "entry_price": 100,
        "stop_loss": 90,
        "target_price": 130,
        "exit_stage": "0",
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

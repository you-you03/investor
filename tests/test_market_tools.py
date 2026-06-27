import pytest


def test_compute_setup_metrics_derives_early_chase_inputs():
    from investor.tools.market_tools import _compute_setup_metrics

    bars = []
    for i in range(26):
        close = 100.0 + i
        bars.append({
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000,
        })
    bars[-1]["volume"] = 2000

    metrics = _compute_setup_metrics(
        bars,
        ema_20=120.0,
        ema_50=115.0,
        bollinger_bands={"upper": 130.0, "middle": 120.0, "lower": 110.0},
    )

    assert metrics["return_5d_pct"] == pytest.approx(4.17)
    assert metrics["return_20d_pct"] == pytest.approx(19.05)
    assert metrics["pct_above_ema20"] == pytest.approx(4.17)
    assert metrics["pct_above_ema50"] == pytest.approx(8.7)
    assert metrics["volume_ratio_20d"] == pytest.approx(2.0)
    assert metrics["bb_width_pct"] == pytest.approx(16.67)
    assert metrics["bb_position"] == pytest.approx(0.75)
    assert metrics["pullback_from_20d_high_pct"] == pytest.approx(-0.79)

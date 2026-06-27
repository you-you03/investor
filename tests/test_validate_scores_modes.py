from scripts import validate_scores


def _week_payload(return_pct: float, alpha_pct: float) -> dict:
    return {
        "target_date": "2026-07-01",
        "return_pct": return_pct,
        "alpha_pct": alpha_pct,
        "alpha_vs_spy": alpha_pct,
        "alpha_vs_sector": alpha_pct - 1.0,
        "fetched_at": "2026-07-01T08:00:00",
    }


def test_analyze_builds_mode_reliability_for_extended_horizons(monkeypatch):
    monkeypatch.setattr(validate_scores, "MIN_SAMPLES", 3)

    snapshots = []
    factor_scores = [5.0, 7.0, 9.0]
    returns = [2.0, 6.0, 10.0]
    for factor_score, ret in zip(factor_scores, returns):
        snap = {
            "score": 7.5,
            "momentum_primary_mode": "EARLY_MOMENTUM",
            "score_breakdown": {
                "momentum": factor_score,
                "fundamentals": factor_score,
                "catalyst": factor_score,
                "technical": factor_score,
                "sentiment": factor_score,
            },
        }
        for wk in validate_scores.WEEK_KEYS:
            snap[wk] = _week_payload(return_pct=ret, alpha_pct=ret - 1.0)
        snapshots.append(snap)

    stats = validate_scores.analyze(snapshots)

    assert stats["counts"]["week8"] == 3
    assert stats["mode_summary"]["week7"]["EARLY_MOMENTUM"]["avg_return"] == 6.0
    assert stats["mode_summary"]["week8"]["EARLY_MOMENTUM"]["win_rate"] == 100.0

    reliability = stats["mode_factor_reliability"]["EARLY_MOMENTUM"]["fundamentals"]["week8"]
    assert reliability["n"] == 3
    assert reliability["rho"] == 1.0
    assert reliability["high_score_avg_alpha"] == 9.0
    assert reliability["low_score_avg_alpha"] == 1.0

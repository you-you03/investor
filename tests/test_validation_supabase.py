from investor.supabase_store import normalize_validation_stats


def test_normalize_validation_stats_expands_report_metrics():
    stats = {
        "period_start": "2026-04-19",
        "period_end": "2026-06-12",
        "total": 101,
        "passed_n": 33,
        "rejected_n": 68,
        "ic": {
            "week4": {"n": 71, "rho": 0.29, "p": 0.0121, "label": "positive"},
        },
        "buckets": {
            ">= 7.0": {
                "n": 33,
                "avgs": {"week1": "+4.6%", "week2": "+4.1%", "week3": "+12.3%", "week4": "+18.8%"},
            },
        },
        "conviction_spy_matrix": {
            "week4": {
                "spy_min": 0.3,
                "spy_max": 4.8,
                "rows": {
                    "HIGH": {
                        "+0%〜+2%": {"n": 3, "avg_return": 13.4},
                    },
                },
            },
        },
        "horizon_summary": {
            "week4": {
                "HIGH": {
                    "n": 6,
                    "avg_return": 19.4,
                    "median_return": 9.9,
                    "avg_alpha_spy": 16.9,
                    "avg_alpha_qqq": 13.5,
                    "avg_alpha_sector": 3.9,
                },
            },
        },
        "regime_summary": {"sector_tailwind": {"n": 39, "avg_return": 17.4}},
        "factor_ic": {"fundamentals": {"week4": {"n": 71, "rho": 0.47}}},
        "threshold_comparison": {"week4": {"passed_avg": "+18.8%", "rejected_avg": "+3.3%"}},
        "calibration": ["fundamentals strong"],
    }

    rows = normalize_validation_stats(
        stats=stats,
        report_markdown="# report",
        report_path="/tmp/validation.md",
        validation_date="2026-06-20",
    )

    assert rows["validation_runs"][0]["snapshot_count"] == 101
    assert rows["validation_horizon_ic"][0]["spearman_rho"] == 0.29
    assert rows["validation_score_buckets"][0]["week4_avg_return_pct"] == 18.8
    assert rows["validation_threshold_comparison"][0]["rejected_avg_return_pct"] == 3.3
    assert rows["validation_factor_ic"][0]["factor"] == "fundamentals"
    assert rows["validation_calibration_suggestions"][0]["suggestion"] == "fundamentals strong"
    assert rows["validation_best_horizons"][0]["best_return_horizon"] == "week4"

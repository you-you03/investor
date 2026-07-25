from scripts.build_score_reliability_dashboard import (
    VIEW_SPECS,
    _build_score_bucket_reliability_rows,
    _build_score_scatter,
    _dedupe_snapshots,
    build_html,
    fetch_dashboard_data_from_base_tables,
    fetch_dashboard_data,
    write_dashboard,
)


class FakeStore:
    def __init__(self):
        self.calls = []

    def select(self, table, params=None):
        self.calls.append((table, params))
        if table == "score_reliability_summary":
            return [{
                "overall_judgement": "使える: 4週目線の候補選別に有効",
                "recommended_action": "score>=7.0を候補順位付けに使う",
                "snapshot_count": 42,
                "passed_threshold_count": 12,
                "rejected_threshold_count": 30,
                "week4_ic": 0.31,
                "week4_sample_count": 35,
                "week4_threshold_spread": 5.2,
            }]
        return []


class FakeBaseTableStore:
    def select(self, table, params=None):
        if table == "validation_runs":
            return [{
                "validation_id": "validation-1",
                "validation_date": "2026-07-04",
                "snapshot_count": 40,
                "passed_threshold_count": 10,
                "rejected_threshold_count": 30,
            }]
        if table == "validation_horizon_ic":
            return [
                {"validation_id": "validation-1", "horizon": "week4", "sample_count": 35, "spearman_rho": 0.32, "p_value": 0.02},
                {"validation_id": "validation-1", "horizon": "week8", "sample_count": 20, "spearman_rho": 0.18, "p_value": 0.2},
            ]
        if table == "validation_threshold_comparison":
            return [{"validation_id": "validation-1", "horizon": "week4", "passed_avg_return_pct": 9.0, "rejected_avg_return_pct": 3.0}]
        if table == "validation_factor_ic":
            return [{"validation_id": "validation-1", "factor": "fundamentals", "horizon": "week4", "sample_count": 35, "spearman_rho": 0.4}]
        if table == "validation_calibration_suggestions":
            return [{"suggestion_order": 1, "suggestion": "fundamentals strong"}]
        if table == "score_snapshots":
            return [{
                "ticker": "TEST",
                "scored_at": "2026-06-01",
                "score": 7.8,
                "passed_threshold": True,
                "week4": {"target_date": "2026-06-29", "return_pct": 8.5, "alpha_spy_pct": 4.1},
            }]
        raise AssertionError(table)


def test_fetch_dashboard_data_reads_all_score_reliability_views():
    store = FakeStore()

    data = fetch_dashboard_data(store)

    assert [call[0] for call in store.calls] == [spec[1] for spec in VIEW_SPECS]
    assert data["summary"][0]["snapshot_count"] == 42
    assert "generatedAt" in data


def test_fetch_dashboard_data_from_base_tables_shapes_metabase_equivalent_data():
    data = fetch_dashboard_data_from_base_tables(FakeBaseTableStore())

    assert data["summary"][0]["overall_judgement"] == "診断シグナルあり: 12週OOS満期までは方針固定"
    assert data["thresholdLatest"][0]["spread_return_pct"] == 6.0
    assert data["factorLatest"][0]["action"] == "BUY根拠として重視"
    assert data["scoreScatter"][0]["ticker"] == "TEST"


def test_build_html_embeds_data_without_credentials():
    html = build_html({
        "generatedAt": "2026-07-04T10:00:00+09:00",
        "summary": [{"overall_judgement": "要見直し"}],
        "sourceViews": ["score_reliability_summary"],
    })

    assert "Score Reliability Dashboard" in html
    assert "要見直し" in html
    assert "SUPABASE_SERVICE_ROLE_KEY" not in html
    assert "</script><script" not in html


def test_dedupe_snapshots_keeps_one_row_per_ticker_and_scored_at():
    snapshots = [
        {
            "ticker": "NVDA",
            "scored_at": "2026-06-01T09:00:00+09:00",
            "score": 8.1,
            "week1": {"return_pct": 1.0},
        },
        {
            "ticker": "nvda",
            "scored_at": "2026-06-01",
            "company_name": "NVIDIA Corporation",
            "score": 8.1,
            "conviction": "HIGH",
            "score_breakdown": {"fundamentals": 8},
            "week1": {"return_pct": 1.0},
            "week2": {"return_pct": 2.0},
        },
    ]

    deduped = _dedupe_snapshots(snapshots)

    assert len(deduped) == 1
    assert deduped[0]["company_name"] == "NVIDIA Corporation"
    assert deduped[0]["conviction"] == "HIGH"


def test_score_bucket_reliability_counts_first_signal_per_ticker_and_horizon():
    snapshots = [
        {
            "ticker": "BIG",
            "scored_at": "2026-06-01",
            "score": 6.8,
            "week1": {"return_pct": 10.0, "alpha_spy_pct": 8.0},
        },
        {
            "ticker": "BIG",
            "scored_at": "2026-06-05",
            "score": 8.8,
            "week1": {"return_pct": 80.0, "alpha_spy_pct": 75.0},
        },
        {
            "ticker": "OTHER",
            "scored_at": "2026-06-02",
            "score": 8.9,
            "week1": {"return_pct": 4.0, "alpha_spy_pct": 2.0},
        },
    ]

    rows = _build_score_bucket_reliability_rows(snapshots)
    high = next(row for row in rows if row["horizon"] == "week1" and row["score_bucket"] == "≥ 8.5")
    low = next(row for row in rows if row["horizon"] == "week1" and row["score_bucket"] == "< 7.0")

    assert high["sample_count"] == 1
    assert high["avg_return_pct"] == 4.0
    assert low["sample_count"] == 1
    assert low["avg_return_pct"] == 10.0


def test_score_bucket_reliability_all_mode_counts_every_signal():
    snapshots = [
        {
            "ticker": "BIG",
            "scored_at": "2026-06-01",
            "score": 6.8,
            "week1": {"return_pct": 10.0, "alpha_spy_pct": 8.0},
        },
        {
            "ticker": "BIG",
            "scored_at": "2026-06-05",
            "score": 8.8,
            "week1": {"return_pct": 80.0, "alpha_spy_pct": 75.0},
        },
        {
            "ticker": "OTHER",
            "scored_at": "2026-06-02",
            "score": 8.9,
            "week1": {"return_pct": 4.0, "alpha_spy_pct": 2.0},
        },
    ]

    rows = _build_score_bucket_reliability_rows(snapshots, aggregation_mode="all")
    high = next(row for row in rows if row["horizon"] == "week1" and row["score_bucket"] == "≥ 8.5")

    assert high["sample_count"] == 2
    assert high["avg_return_pct"] == 42.0


def test_score_scatter_keeps_first_signal_per_ticker():
    snapshots = [
        {"ticker": "BIG", "scored_at": "2026-06-01", "score": 6.8, "week4": {"return_pct": 10.0}},
        {"ticker": "BIG", "scored_at": "2026-06-05", "score": 8.8, "week4": {"return_pct": 80.0}},
    ]

    rows = _build_score_scatter(snapshots)

    assert len(rows) == 1
    assert rows[0]["score"] == 6.8
    assert rows[0]["week4_return_pct"] == 10.0


def test_write_dashboard_creates_parent_directory(tmp_path):
    output = tmp_path / "nested" / "dashboard.html"

    written = write_dashboard({"generatedAt": "2026-07-04T10:00:00+09:00"}, output)

    assert written == output
    assert output.exists()

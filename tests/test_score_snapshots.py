from datetime import date


def test_add_score_snapshots_tracks_watchlist_results(tmp_path, monkeypatch):
    from investor.core import score_snapshots

    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(score_snapshots, "SNAPSHOTS_PATH", path)
    monkeypatch.setattr(score_snapshots, "_fetch_price", lambda ticker: (100.0, f"{ticker} Inc."))

    added = score_snapshots.add_score_snapshots(
        run_id="run-1",
        source="watchlist_research",
        scored_at=date(2026, 6, 12),
        results=[
            {"ticker": "NVDA", "new_score": 8.4, "action": "ESCALATE"},
            {"ticker": "TEAM", "new_score": 7.4, "action": "MAINTAIN"},
        ],
    )

    assert added == 2
    data = score_snapshots._load_snapshots(path)
    snapshots = data["snapshots"]
    assert snapshots[0]["ticker"] == "NVDA"
    assert snapshots[0]["conviction"] == "HIGH"
    assert snapshots[0]["sector_etf"] == "SMH"
    assert snapshots[0]["week3"]["target_date"] == "2026-07-03"
    assert snapshots[1]["ticker"] == "TEAM"
    assert snapshots[1]["conviction"] == "MEDIUM"
    assert snapshots[1]["sector_etf"] == "IGV"


def test_add_score_snapshots_is_idempotent(tmp_path, monkeypatch):
    from investor.core import score_snapshots

    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(score_snapshots, "SNAPSHOTS_PATH", path)
    monkeypatch.setattr(score_snapshots, "_fetch_price", lambda ticker: (100.0, "Test Inc."))

    kwargs = {
        "run_id": "run-1",
        "source": "research",
        "scored_at": date(2026, 6, 12),
        "results": [{"ticker": "AMAT", "score": 7.3}],
    }

    assert score_snapshots.add_score_snapshots(**kwargs) == 1
    assert score_snapshots.add_score_snapshots(**kwargs) == 0
    assert len(score_snapshots._load_snapshots(path)["snapshots"]) == 1


def test_classify_market_regime():
    from investor.core.score_snapshots import classify_market_regime

    assert classify_market_regime(3.0, 4.0, 5.5, -3.0, -5.0) == "sector_tailwind"
    assert classify_market_regime(-2.5, -3.0, -1.0, 8.0, 0.0) == "risk_off"
    assert classify_market_regime(2.5, 3.0, 2.0, -2.0, 0.0) == "risk_on_growth"

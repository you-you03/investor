import json

from scripts import backfill_supabase


class FakeStore:
    def __init__(self):
        self.calls = []
        self.tables = {}
        self.patches = []

    def upsert(self, table, rows, on_conflict=None):
        self.calls.append((table, rows, on_conflict))

    def select(self, table, params=None):
        return self.tables.get(table, [])

    def patch(self, table, params, values):
        self.patches.append((table, params, values))


def test_backfill_score_snapshots_preserves_duplicate_natural_keys(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    snapshot = {
        "run_id": "run-1",
        "scored_at": "2026-05-16",
        "ticker": "NVDA",
        "score": 7.5,
        "week1": {"target_date": "2026-05-23", "return_pct": 1.2},
    }
    (data_dir / "score_snapshots.json").write_text(
        json.dumps({"snapshots": [snapshot, {**snapshot, "score": 7.8}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(backfill_supabase, "DATA_DIR", data_dir)

    store = FakeStore()

    assert backfill_supabase.backfill_score_snapshots(store) == 2
    assert len(store.calls) == 1
    table, rows, on_conflict = store.calls[0]
    assert table == "score_snapshots"
    assert on_conflict == "snapshot_id"
    assert len(rows) == 2
    assert rows[0]["snapshot_id"] != rows[1]["snapshot_id"]
    assert {row["score"] for row in rows} == {7.5, 7.8}


def test_backfill_workflow_tasks_normalizes_agent_actions():
    store = FakeStore()
    store.tables = {
        "monitor_alerts": [
            {
                "alert_id": "a1",
                "run_id": "m1",
                "alert_date": "2026-06-20",
                "ticker": "MU",
                "alert_type": "STOP_LOSS",
                "severity": "HIGH",
                "message": "stop breached",
                "raw_payload": {},
            }
        ],
        "watchlist_alerts": [
            {
                "alert_id": "w1",
                "run_id": "wm1",
                "alert_date": "2026-06-20",
                "ticker": "VRT",
                "alert_type": "WATCHLIST_RESEARCH_NEEDED",
                "severity": "MEDIUM",
                "message": "setup",
                "next_step": "/research --seed VRT",
                "raw_payload": {},
            }
        ],
        "daily_lite_actions": [],
        "decision_requests": [],
    }

    assert backfill_supabase.backfill_workflow_tasks(store) == 2
    table, rows, on_conflict = store.calls[0]
    assert table == "workflow_tasks"
    assert on_conflict == "source_table,source_id,task_type"
    assert rows[0]["task_type"] == "exit_review"
    assert rows[0]["priority"] == "urgent"
    assert rows[0]["command"] == "/decision --mode exit --ticker MU"
    assert rows[1]["task_type"] == "research"
    assert rows[1]["command"] == "/research --seed VRT"


def test_backfill_position_events_splits_entry_and_exit_events():
    store = FakeStore()
    store.tables = {
        "positions": [
            {
                "position_id": "pos-1",
                "portfolio_type": "real",
                "ticker": "MU",
                "shares": 2,
                "entry_price": 100,
                "entry_date": "2026-06-01",
                "exit_price": 110,
                "exit_date": "2026-06-20",
                "status": "closed",
                "stop_loss": 95,
                "target_price": 120,
                "signal_type": "technical_breakout",
                "note": "target hit",
                "raw_payload": {},
            }
        ]
    }

    assert backfill_supabase.backfill_position_events(store) == 2
    table, rows, on_conflict = store.calls[0]
    assert table == "position_events"
    assert on_conflict == "event_id"
    assert [row["event_type"] for row in rows] == ["entry", "exit"]
    assert rows[0]["shares_delta"] == 2
    assert rows[1]["shares_delta"] == -2

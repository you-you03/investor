import json
from datetime import date
from pathlib import Path

from investor.config import settings


def test_save_run_keeps_candidates_when_risk_blocks(tmp_path, monkeypatch):
    from investor.agents import research_agent
    from investor.core import score_snapshots

    history_path = tmp_path / "research_history.json"
    snap_path = tmp_path / "score_snapshots.json"
    gate_path = tmp_path / "gates.json"
    book = tmp_path / "portfolio_20man.csv"
    book.write_text(
        "ticker,shares,entry_price,status,stop_loss,target_price\n"
        "TSM,1,441,open,,434\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(research_agent, "HISTORY_PATH", history_path)
    monkeypatch.setattr(research_agent, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(research_agent, "sync_local_to_supabase", lambda *args, **kwargs: None)
    monkeypatch.setattr(score_snapshots, "SNAPSHOTS_PATH", snap_path)
    monkeypatch.setattr(score_snapshots, "GATE_COUNTERFACTUAL_PATH", gate_path)
    monkeypatch.setattr(score_snapshots, "sync_local_to_supabase", lambda *args, **kwargs: None)
    monkeypatch.setattr(score_snapshots, "_fetch_price", lambda ticker: (10.0, "Test"))
    monkeypatch.setattr(settings, "default_portfolio_path", str(book))
    monkeypatch.setattr(settings, "block_new_buys_on_portfolio_violation", True)

    research_agent.save_run(
        "run-risk",
        [
            {
                "ticker": "NVDA",
                "score": 8.2,
                "price_at_score": 100,
                "score_breakdown": {"momentum": 8, "fundamentals": 8, "catalyst": 3},
                "score_evidence": {"catalyst": "no news and analyst data missing"},
                "momentum_profile": {"primary_mode": "CHASE_MOMENTUM", "extension_risk": "HIGH"},
            },
            {
                "ticker": "LOW",
                "score": 6.0,
                "price_at_score": 20,
                "factor_grades": {"catalyst": "D"},
                "catalyst_quality": "WEAK",
                "score_evidence": {"catalyst": "dated product delay, source confirmed"},
            },
        ],
    )

    history = json.loads(history_path.read_text())
    run = history["runs"][0]
    assert run["blocked_by_risk"] is True
    assert run["candidates"][0]["ticker"] == "NVDA"
    assert run["candidates"][0]["blocked_by_risk"] is True
    assert any("stop_loss" in reason for reason in run["blocked_by_risk_reasons"])
    assert all(row["ticker"] != "LOW" for row in run["candidates"])

    snapshots = json.loads(snap_path.read_text())["snapshots"]
    by_ticker = {row["ticker"]: row for row in snapshots}
    assert by_ticker["NVDA"]["blocked_by_risk"] is True
    assert by_ticker["NVDA"]["catalyst_data_missing"] is True
    assert by_ticker["NVDA"]["catalyst_data_status"] == "missing"
    assert by_ticker["NVDA"]["gate_pass_counterfactual"]["gate"] == "CHASE_OR_EXTENSION"
    assert by_ticker["LOW"]["catalyst_data_status"] == "weak"
    assert by_ticker["LOW"]["catalyst_data_missing"] is False
    assert "LOW" in {row["ticker"] for row in snapshots}

    index = json.loads(gate_path.read_text())
    nvda = next(row for row in index["entries"] if row["ticker"] == "NVDA" and row["run_id"] == "run-risk")
    assert nvda["week4"] is None
    assert nvda["week12"] is None


def test_catalyst_missing_is_excluded_from_factor_ic(monkeypatch):
    from scripts import validate_scores

    monkeypatch.setattr(validate_scores, "MIN_SAMPLES", 3)
    snapshots = []
    for score, ret, missing in (
        (5.0, 1.0, False),
        (7.0, 2.0, False),
        (9.0, 3.0, False),
        (1.0, 50.0, True),
    ):
        snapshots.append({
            "score": 7.0,
            "catalyst_data_missing": missing,
            "catalyst_data_status": "missing" if missing else "present",
            "score_breakdown": {
                "momentum": score,
                "fundamentals": score,
                "catalyst": score,
                "technical": score,
                "sentiment": score,
            },
            "week4": {
                "return_pct": ret,
                "alpha_pct": ret,
                "alpha_vs_spy": ret,
                "fetched_at": "2026-08-01T00:00:00",
            },
        })

    stats = validate_scores.analyze(snapshots)
    assert stats["catalyst_missing_excluded"] == 1
    assert stats["factor_ic"]["catalyst"]["week4"]["n"] == 3
    assert stats["factor_ic"]["momentum"]["week4"]["n"] == 4


def test_reconcile_flags_open_stop_without_closing(tmp_path, monkeypatch):
    from scripts import reconcile_monitor_ledger as reconcile

    live = tmp_path / "portfolio_20man.csv"
    legacy = tmp_path / "portfolio.csv"
    alerts = tmp_path / "alerts.json"
    journal = tmp_path / "journal.json"
    monitor = tmp_path / "monitor_history.json"
    reports = tmp_path / "reports"
    header = "ticker,shares,entry_price,status,stop_loss,target_price,note,order_status\n"
    live.write_text(
        header + "TSM,1,441,open,388,434,pending Yuta broker confirm / exit review,\n",
        encoding="utf-8",
    )
    legacy.write_text(header + "TSM,10,180,closed,170,200,old book,\n", encoding="utf-8")
    alerts.write_text(json.dumps([
        {
            "date": "2026-07-29",
            "ticker": "TSM",
            "alert_type": "STOP_BREACH",
            "severity": "HIGH",
            "message": "historical stop",
        }
    ]), encoding="utf-8")
    journal.write_text(json.dumps([
        {"ticker": "TSM", "journal_kind": "monitor_exit_review", "status": "open"}
    ]), encoding="utf-8")
    monitor.write_text(json.dumps([
        {"date": "2026-10-25", "positions": [{"ticker": "TSM", "current_price": 418.51}]}
    ]), encoding="utf-8")
    monkeypatch.setattr(reconcile, "LIVE_BOOK", live)
    monkeypatch.setattr(reconcile, "LEGACY_BOOK", legacy)
    monkeypatch.setattr(reconcile, "ALERTS_PATH", alerts)
    monkeypatch.setattr(reconcile, "JOURNAL_PATH", journal)
    monkeypatch.setattr(reconcile, "MONITOR_HISTORY_PATH", monitor)
    monkeypatch.setattr(reconcile, "REPORTS_DIR", reports)

    result = reconcile.run(as_of="2026-10-28", update_alerts=True)

    assert result["findings"] >= 1
    assert "status,open" in live.read_text() or ",open," in live.read_text()
    assert "closed" not in live.read_text().splitlines()[-1]
    stored = json.loads(alerts.read_text())
    assert stored[-1]["alert_type"] == "LEDGER_RECONCILE"
    assert stored[-1]["auto_closed"] is False
    assert stored[-1]["pending_exit_review"] is True
    assert (reports / "reconcile_2026-10-28.md").exists()


def test_hypothesis_parser_reports_overdue_without_editing_tracker(tmp_path, monkeypatch):
    from scripts import check_hypotheses

    tracker = tmp_path / "hypothesis-tracker.md"
    tracker.write_text(
        "### H-2: example\n\n**検証期間**: 2026-05-10 〜 2026-07-10\n\n"
        "## H-9: start only\n\n**検証開始日**: 2026-07-12\n",
        encoding="utf-8",
    )
    paper = tmp_path / "paper.csv"
    paper.write_text(
        "ticker,status,hypothesis_id,note\nREZI,open,H-2,[H-2] still open\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_hypotheses, "TRACKER_PATH", tracker)
    monkeypatch.setattr(check_hypotheses, "PAPER_PATH", paper)
    monkeypatch.setattr(check_hypotheses, "REPORTS_DIR", tmp_path)

    parsed = check_hypotheses.parse_hypotheses(tracker.read_text())
    assert check_hypotheses.classify(parsed[0], date(2026, 10, 28)) == "overdue"
    assert check_hypotheses.classify(parsed[1], date(2026, 10, 28)) == "end_date_missing"
    original = tracker.read_text()
    check_hypotheses.main()
    assert tracker.read_text() == original
    report = next(tmp_path.glob("hypothesis_due_*.md")).read_text()
    assert "H-2" in report
    assert "end_date_missing" in report
    assert "Left open" in report


def test_completed_section_is_decided_not_overdue():
    from datetime import date

    from scripts import check_hypotheses

    text = (
        "### H-6: open\n\n**検証開始日**: 2026-07-12\n\n"
        "## 完了済み仮説\n\n"
        "### H-1: closed\n\n**検証期間**: 2026-05-10 〜 2026-08-10\n"
    )
    parsed = check_hypotheses.parse_hypotheses(text)
    states = {row["hypothesis_id"]: check_hypotheses.classify(row, date(2026, 10, 28)) for row in parsed}
    assert states["H-1"] == "decided"
    assert states["H-6"] == "end_date_missing"


def test_weight_sensitivity_is_diagnostic_only():
    from scripts.weight_sensitivity import LIVE_WEIGHTS, build_report

    config_before = Path("investor/config.py").read_text()
    report = build_report(
        [
            {
                "run_id": "r1",
                "score_breakdown": {"fundamentals": 9, "momentum": 8, "catalyst": 7},
                "week12": {"alpha_vs_spy": 4.0, "fetched_at": "2026-10-01"},
            },
            {
                "run_id": "r1",
                "catalyst_data_missing": True,
                "catalyst_data_status": "missing",
                "score_breakdown": {"fundamentals": 1, "momentum": 1, "catalyst": 1},
                "week12": {"alpha_vs_spy": 20.0, "fetched_at": "2026-10-01"},
            },
        ],
        today="2026-10-28",
    )
    assert "Live weights were not changed" in report
    assert "does not clear that gate" in report
    assert LIVE_WEIGHTS["fundamentals"] == 0.60
    assert Path("investor/config.py").read_text() == config_before


def test_record_outcomes_adds_research_run_id(tmp_path, monkeypatch):
    from scripts import record_outcomes
    from investor.core import lineage

    research = tmp_path / "research_history.json"
    portfolio = tmp_path / "book.csv"
    journal = tmp_path / "trade_journal.json"
    decisions = tmp_path / "decision_history.json"
    research.write_text(json.dumps({
        "runs": [{
            "run_id": "run-xyz",
            "date": "2026-06-20",
            "candidates": [{
                "ticker": "TSM",
                "outcome": {"status": "closed", "realized_return_pct": 1.0},
            }],
        }]
    }), encoding="utf-8")
    portfolio.write_text("ticker,status\n", encoding="utf-8")
    journal.write_text(json.dumps([{"trade_id": "TSM_2026-06-24", "pnl_pct": 1}]), encoding="utf-8")
    decisions.write_text(json.dumps([{"date": "2026-06-21", "run_id": "run-xyz", "proposal_records": [{"ticker": "TSM"}]}]), encoding="utf-8")
    monkeypatch.setattr(record_outcomes, "RESEARCH_HISTORY_PATH", research)
    monkeypatch.setattr(record_outcomes, "PORTFOLIO_PATH", portfolio)
    monkeypatch.setattr(record_outcomes, "sync_local_to_supabase", lambda *args, **kwargs: None)
    monkeypatch.setattr(lineage, "DECISION_HISTORY_PATH", decisions)
    monkeypatch.setattr(lineage, "TRADE_JOURNAL_PATH", journal)

    record_outcomes.record_outcomes(dry_run=False)
    stored = json.loads(research.read_text())
    assert stored["runs"][0]["candidates"][0]["outcome"]["research_run_id"] == "run-xyz"
    assert json.loads(journal.read_text())[0]["research_run_id"] == "run-xyz"
    decision = json.loads(decisions.read_text())[0]
    assert decision["research_run_id"] == "run-xyz"
    assert decision["proposal_records"][0]["research_run_id"] == "run-xyz"


def test_score_validation_workflow_does_not_notify_slack():
    text = Path(".github/workflows/score-validation.yml").read_text()
    assert "scripts/fetch_returns.py" in text
    assert "scripts/record_outcomes.py" in text
    assert "scripts/validate_scores.py" in text
    assert "SLACK_WEBHOOK_URL: \"\"" in text
    assert "auto-merge" in text
    assert "SlackNotifier" not in text

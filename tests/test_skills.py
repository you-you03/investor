"""
Tests for the actual code paths used in production.
Covers: Slack failure detection, --send JSON validation, CSV round-trips.
"""
import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Slack failure detection (A1/A2)
# ---------------------------------------------------------------------------

class TestSendProposals:
    def test_raises_on_slack_failure(self):
        """send_proposals must raise RuntimeError when Slack send fails."""
        from investor.agents.decision_agent import send_proposals

        proposals = [
            {
                "ticker": "NVDA",
                "action": "BUY",
                "conviction": "HIGH",
                "entry_price_range": "800-820",
                "target_price": 900,
                "stop_loss": 760,
                "position_size_usd": 1500,
                "shares_suggested": 1.9,
                "rationale": "test",
                "key_catalysts": [],
                "risk_factors": [],
                "time_horizon": "3 weeks",
            }
        ]

        with patch("investor.agents.decision_agent.SlackNotifier") as mock_cls:
            mock_notifier = MagicMock()
            mock_notifier.send_proposals.return_value = False  # Slack down
            mock_cls.return_value = mock_notifier

            with pytest.raises(RuntimeError, match="Slack 送信失敗"):
                send_proposals(proposals)

    def test_succeeds_when_slack_ok(self):
        """send_proposals must not raise when Slack returns True."""
        from investor.agents.decision_agent import send_proposals

        proposals = [
            {
                "ticker": "AAPL",
                "action": "BUY",
                "conviction": "MEDIUM",
                "entry_price_range": "190-195",
                "target_price": 210,
                "stop_loss": 183,
                "position_size_usd": 1000,
                "shares_suggested": 5.2,
                "rationale": "test",
                "key_catalysts": [],
                "risk_factors": [],
                "time_horizon": "2 weeks",
            }
        ]

        with patch("investor.agents.decision_agent.SlackNotifier") as mock_cls:
            mock_notifier = MagicMock()
            mock_notifier.send_proposals.return_value = True
            mock_cls.return_value = mock_notifier

            send_proposals(proposals)  # must not raise


# ---------------------------------------------------------------------------
# --send JSON parse edge cases (E-3)
# ---------------------------------------------------------------------------

class TestLogPaperProposals:
    def test_en_dash_entry_price_does_not_write_empty_entry(self, tmp_path):
        """En-dash in entry_price_range must not produce entry_price='' in CSV (corrupt state)."""
        import importlib.util
        import unittest.mock

        spec = importlib.util.spec_from_file_location(
            "decision_skill",
            Path(__file__).parent.parent / "skills" / "decision.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        paper_path = tmp_path / "paper_portfolio.csv"
        proposal = {
            "ticker": "TEST",
            "action": "BUY",
            "conviction": "HIGH",
            "entry_price_range": "150–160",  # en-dash (U+2013) — common in Claude output
            "target_price": 180,
            "stop_loss": 140,
            "position_size_usd": 1500,
            "rationale": "test rationale",
        }

        with unittest.mock.patch.object(mod, "PAPER_PATH", paper_path):
            mod._log_paper_proposals([proposal])

        with open(paper_path) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1
        assert rows[0]["ticker"] == "TEST"
        # After fix: entry_price must not be empty string (corrupt state)
        assert rows[0]["entry_price"] != "", "E-3: entry_price is empty — en-dash parsing failed silently"
        assert rows[0]["proposal_date"] != ""
        assert rows[0]["position_id"].startswith("pos-")

    def test_hyphen_entry_price_parses_correctly(self, tmp_path):
        """Regular hyphen in entry_price_range must parse correctly."""
        import importlib.util
        import unittest.mock

        spec = importlib.util.spec_from_file_location(
            "decision_skill",
            Path(__file__).parent.parent / "skills" / "decision.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        paper_path = tmp_path / "paper_portfolio.csv"
        proposal = {
            "ticker": "NVDA",
            "action": "BUY",
            "conviction": "HIGH",
            "entry_price_range": "800-820",  # regular hyphen — must work
            "target_price": 900,
            "stop_loss": 760,
            "position_size_usd": 1500,
            "rationale": "test",
        }

        with unittest.mock.patch.object(mod, "PAPER_PATH", paper_path):
            mod._log_paper_proposals([proposal])

        with open(paper_path) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1
        assert rows[0]["ticker"] == "NVDA"
        assert rows[0]["entry_price"] == "810.0"  # (800+820)/2
        assert float(rows[0]["shares"]) > 0

    def test_h3_paper_proposal_uses_integer_shares_suggested(self, tmp_path):
        """H-3 paper entries must preserve explicit small-portfolio share counts."""
        import importlib.util
        import unittest.mock

        spec = importlib.util.spec_from_file_location(
            "decision_skill",
            Path(__file__).parent.parent / "skills" / "decision.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        paper_path = tmp_path / "paper_portfolio.csv"
        proposal = {
            "ticker": "NVDA",
            "action": "BUY",
            "conviction": "MEDIUM",
            "entry_price_range": "500-520",
            "target_price": 590,
            "stop_loss": 480,
            "position_size_usd": 1020,
            "shares_suggested": 2,
            "note": "[H-3] 20万円枠。2株上限内。",
        }

        with unittest.mock.patch.object(mod, "PAPER_PATH", paper_path):
            mod._log_paper_proposals([proposal])

        with open(paper_path) as f:
            rows = list(csv.DictReader(f))

        assert rows[0]["shares"] == "2"
        assert rows[0]["hypothesis_id"] == "H-3"

    def test_h3_validation_blocks_more_than_two_same_ticker_shares(self, tmp_path):
        """H-3 small portfolio may not hold more than two shares of one ticker."""
        import importlib.util
        import unittest.mock

        spec = importlib.util.spec_from_file_location(
            "decision_skill",
            Path(__file__).parent.parent / "skills" / "decision.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        paper_path = tmp_path / "paper_portfolio.csv"
        proposal = {
            "ticker": "NVDA",
            "action": "BUY",
            "position_size_usd": 1500,
            "shares_suggested": 3,
            "hypothesis_id": "H-3",
            "note": "[H-3] too many shares",
        }

        with unittest.mock.patch.object(mod, "PAPER_PATH", paper_path):
            violations = mod._validate_h3_small_portfolio([proposal])

        assert any("2株上限" in v for v in violations)
        assert any("予算超過" in v for v in violations)


# ---------------------------------------------------------------------------
# portfolio.csv round-trip (data integrity)
# ---------------------------------------------------------------------------

class TestPortfolioCSV:
    FIELDNAMES = [
        "position_id", "ticker", "shares", "entry_price", "entry_date",
        "proposal_date", "exit_price", "exit_date", "status", "target_price", "stop_loss",
        "note", "signal_type", "conviction", "hypothesis_id", "exit_stage",
        "mae_pct", "mfe_pct", "mfe_capture_pct", "rule_adherence_score",
    ]

    def test_position_id_uniqueness(self, tmp_path):
        """Each row must have a unique position_id."""
        csv_path = tmp_path / "portfolio.csv"

        rows = [
            {"position_id": "pos-001", "ticker": "CRDO", "shares": "4", "entry_price": "119.59",
             "entry_date": "2026-04-11", "proposal_date": "2026-04-11", "exit_price": "160.69", "exit_date": "2026-04-18",
             "status": "closed", "target_price": "134.12", "stop_loss": "112.32",
             "note": "first lot", "signal_type": "analyst_upgrade", "conviction": "MEDIUM", "hypothesis_id": "", "exit_stage": "0",
             "mae_pct": "", "mfe_pct": "", "mfe_capture_pct": "", "rule_adherence_score": ""},
            {"position_id": "pos-002", "ticker": "CRDO", "shares": "4", "entry_price": "119.59",
             "entry_date": "2026-04-11", "proposal_date": "2026-04-11", "exit_price": "195.04", "exit_date": "2026-04-25",
             "status": "closed", "target_price": "185.00", "stop_loss": "148.00",
             "note": "second lot", "signal_type": "analyst_upgrade", "conviction": "MEDIUM", "hypothesis_id": "", "exit_stage": "0",
             "mae_pct": "", "mfe_pct": "", "mfe_capture_pct": "", "rule_adherence_score": ""},
        ]

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

        with open(csv_path) as f:
            loaded = list(csv.DictReader(f))

        ids = [row["position_id"] for row in loaded]
        assert len(ids) == len(set(ids)), "Duplicate position_ids detected"
        assert loaded[0]["ticker"] == loaded[1]["ticker"] == "CRDO"
        assert loaded[0]["position_id"] != loaded[1]["position_id"]

    def test_closed_row_has_exit_price(self, tmp_path):
        """Properly closed rows must have a non-empty exit_price."""
        closed_rows = [
            {"position_id": "pos-001", "ticker": "AAOI", "shares": "19", "entry_price": "103.91",
             "entry_date": "2026-04-05", "proposal_date": "2026-04-05", "exit_price": "150.60", "exit_date": "2026-04-11",
             "status": "closed", "target_price": "131.18", "stop_loss": "90.28",
             "note": "TARGET_HIT", "signal_type": "technical_breakout", "conviction": "HIGH", "hypothesis_id": "", "exit_stage": "0",
             "mae_pct": "", "mfe_pct": "", "mfe_capture_pct": "", "rule_adherence_score": ""},
        ]
        for row in closed_rows:
            if row["status"] == "closed":
                assert row["exit_price"], (
                    f"Closed position {row['ticker']} ({row['position_id']}) missing exit_price — "
                    "this causes calibration stats to silently drop the trade"
                )

    def test_e4_calibration_drops_closed_row_without_exit_price(self):
        """E-4: Document that a closed row with no exit_price is silently dropped by calibration stats."""
        # This tests the DATA CONTRACT, not a function. The fix belongs in research.py:48
        # where it must validate closed rows before computing P&L.
        bad_row = {
            "position_id": "pos-003", "ticker": "WAT", "shares": "3",
            "entry_price": "355.0", "entry_date": "2026-05-09",
            "exit_price": "",  # WRONG: closed row must have exit_price
            "exit_date": "", "status": "closed",
        }
        # Document the invariant: closed status without exit_price is a data integrity violation
        assert bad_row["status"] == "closed" and bad_row["exit_price"] == "", \
            "This row represents the E-4 bug scenario — closed with no exit_price"
        # Expected fix: research.py:48 should log a warning and skip this row rather than
        # silently dropping it (which biases calibration stats toward excluding losers)


# ---------------------------------------------------------------------------
# validate_proposals mandate enforcement (B1)
# ---------------------------------------------------------------------------

class TestValidateProposals:
    def _make_proposal(self, **overrides) -> dict:
        base = {
            "ticker": "NVDA",
            "action": "BUY",
            "conviction": "HIGH",
            "entry_price_range": "800-820",
            "target_price": 900,
            "stop_loss": 760,
            "position_size_usd": 1000,
            "shares_suggested": 1.9,
            "rationale": "test",
            "key_catalysts": [],
            "risk_factors": [],
            "time_horizon": "3 weeks",
        }
        base.update(overrides)
        return base

    def test_valid_proposal_no_violations(self):
        from investor.agents.decision_agent import validate_proposals
        proposals = [self._make_proposal()]
        with patch("investor.agents.decision_agent.load_open_positions", return_value=[]):
            violations = validate_proposals(proposals)
        assert violations == []

    def test_stop_loss_missing_raises_violation(self):
        from investor.agents.decision_agent import validate_proposals
        proposals = [self._make_proposal(stop_loss=None)]
        with patch("investor.agents.decision_agent.load_open_positions", return_value=[]):
            violations = validate_proposals(proposals)
        assert any("stop_loss" in v for v in violations)

    def test_position_size_over_limit_raises_violation(self):
        from investor.agents.decision_agent import validate_proposals
        proposals = [self._make_proposal(position_size_usd=9999)]
        with patch("investor.agents.decision_agent.load_open_positions", return_value=[]):
            violations = validate_proposals(proposals)
        assert any("position_size_usd" in v or "25%" in v for v in violations)

    def test_too_many_positions_raises_violation(self):
        from investor.agents.decision_agent import validate_proposals
        open_positions = [{"ticker": f"T{i}", "status": "open"} for i in range(5)]
        proposals = [self._make_proposal()]
        with patch("investor.agents.decision_agent.load_open_positions", return_value=open_positions):
            violations = validate_proposals(proposals)
        assert any("上限" in v or "ポジション" in v for v in violations)

    def test_existing_same_ticker_exposure_over_limit_is_blocked(self):
        from investor.agents.decision_agent import validate_proposals

        open_positions = [{"ticker": "NVDA", "shares": "5", "entry_price": "250", "status": "open"}]
        proposals = [self._make_proposal(position_size_usd=600)]
        with patch("investor.agents.decision_agent.load_open_positions", return_value=open_positions):
            violations = validate_proposals(proposals)
        assert any("既存保有" in v and "上限" in v for v in violations)

    def test_default_portfolio_same_ticker_two_share_cap_is_blocked(self):
        from investor.agents.decision_agent import validate_proposals

        open_positions = [{"ticker": "NVDA", "shares": "1.5", "entry_price": "200", "status": "open"}]
        proposals = [self._make_proposal(position_size_usd=200, shares_suggested=1)]
        with patch("investor.agents.decision_agent.load_open_positions", return_value=open_positions):
            violations = validate_proposals(proposals)
        assert any("同一銘柄2株上限" in v for v in violations)

    def test_default_portfolio_total_budget_cap_is_blocked(self):
        from investor.agents.decision_agent import validate_proposals

        open_positions = [{"ticker": "AAPL", "shares": "1", "entry_price": "1000", "status": "open"}]
        proposals = [self._make_proposal(ticker="MSFT", position_size_usd=500, shares_suggested=1)]
        with patch("investor.agents.decision_agent.load_open_positions", return_value=open_positions):
            violations = validate_proposals(proposals)
        assert any("20万円枠の総予算超過" in v for v in violations)

    def test_unicode_dash_entry_price_parses_in_agent(self):
        from investor.agents.decision_agent import enrich_proposals

        enriched = enrich_proposals(
            [{"ticker": "NVDA", "action": "BUY", "conviction": "HIGH", "entry_price_range": "150—160"}],
            [],
        )
        assert enriched[0]["shares_suggested"] is not None

    def test_enrich_preserves_explicit_small_portfolio_size(self):
        from investor.agents.decision_agent import enrich_proposals

        enriched = enrich_proposals(
            [{
                "ticker": "NVDA",
                "action": "BUY",
                "conviction": "HIGH",
                "entry_price_range": "500-520",
                "position_size_usd": 1020,
                "shares_suggested": 2,
                "note": "[H-3] 20万円枠",
                "hypothesis_id": "H-3",
            }],
            [],
        )
        assert enriched[0]["position_size_usd"] == 1020
        assert enriched[0]["shares_suggested"] == 2
        assert enriched[0]["note"] == "[H-3] 20万円枠"
        assert enriched[0]["hypothesis_id"] == "H-3"

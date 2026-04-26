"""
Unit tests for agent logic.
Mocks Claude API responses — no real API keys required.
"""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from investor.db.database import create_db, get_session
from investor.db.models import Position, ResearchReport


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def in_memory_db(tmp_path, monkeypatch):
    """Use a temporary SQLite database for each test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(
        "investor.db.database.engine",
        __import__("sqlmodel", fromlist=["create_engine"]).create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        ),
    )
    create_db()


@pytest.fixture
def sample_research_json() -> str:
    return json.dumps(
        [
            {
                "ticker": "NVDA",
                "company_name": "NVIDIA Corporation",
                "score": 8.5,
                "current_price": 875.0,
                "score_breakdown": {"momentum": 9, "fundamentals": 8, "catalyst": 9, "technical": 7},
                "thesis": "NVIDIA leads AI infrastructure spending with strong demand for H200.",
                "key_catalysts": ["GTC conference", "H200 supply ramp"],
                "key_risks": ["Valuation stretched"],
                "entry_zone": "860-880",
                "target_price": 1000,
                "stop_loss": 820,
                "time_horizon": "4-6 weeks",
            }
        ]
    )


@pytest.fixture
def sample_decision_json() -> str:
    return json.dumps(
        [
            {
                "ticker": "NVDA",
                "action": "BUY",
                "conviction": "HIGH",
                "shares_suggested": 3,
                "entry_price_range": "860-880",
                "target_price": 1000,
                "stop_loss": 820,
                "position_size_usd": 2640,
                "rationale": "High-conviction AI infrastructure play with clear catalyst.",
                "key_catalysts": ["GTC"],
                "risk_factors": ["Valuation"],
                "time_horizon": "4-6 weeks",
            }
        ]
    )


# ---------------------------------------------------------------------------
# Research Agent tests
# ---------------------------------------------------------------------------


def test_research_agent_saves_reports(sample_research_json):
    from investor.agents.research_agent import ResearchAgent

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=sample_research_json, type="text")]

    with patch("investor.agents.research_agent.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        agent = ResearchAgent()
        run_id = agent.run()

    assert run_id is not None
    with get_session() as session:
        reports = session.exec(
            __import__("sqlmodel", fromlist=["select"]).select(ResearchReport).where(
                ResearchReport.run_id == run_id
            )
        ).all()

    assert len(reports) == 1
    assert reports[0].ticker == "NVDA"
    assert reports[0].score == 8.5
    assert reports[0].target_price == 1000


def test_research_agent_handles_malformed_json():
    from investor.agents.research_agent import ResearchAgent

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text="This is not JSON at all.", type="text")]

    with patch("investor.agents.research_agent.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        agent = ResearchAgent()
        run_id = agent.run()

    # Should not crash, just save no reports
    with get_session() as session:
        from sqlmodel import select
        reports = session.exec(
            select(ResearchReport).where(ResearchReport.run_id == run_id)
        ).all()
    assert reports == []


def test_research_agent_dry_run_does_not_save(sample_research_json):
    from investor.agents.research_agent import ResearchAgent

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=sample_research_json, type="text")]

    with patch("investor.agents.research_agent.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        agent = ResearchAgent()
        run_id = agent.run(dry_run=True)

    from sqlmodel import select
    with get_session() as session:
        reports = session.exec(
            select(ResearchReport).where(ResearchReport.run_id == run_id)
        ).all()
    assert reports == []


# ---------------------------------------------------------------------------
# Monitor Agent: stop-loss detection
# ---------------------------------------------------------------------------


def test_monitor_agent_detects_stop_loss():
    """If current price is below stop_loss, agent should flag it as STOP_LOSS / HIGH."""
    from investor.agents.monitor_agent import MonitorAgent

    stop_loss_json = json.dumps(
        [
            {
                "ticker": "TSLA",
                "current_price": 195.0,
                "unrealized_pnl_pct": -11.4,
                "action": "SELL",
                "alert_type": "STOP_LOSS",
                "severity": "HIGH",
                "reasoning": "Stop-loss breached. Price fell below $200 stop level.",
                "updated_stop_loss": None,
            }
        ]
    )

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=stop_loss_json, type="text")]

    # Create a position in the test DB
    with get_session() as session:
        position = Position(
            ticker="TSLA",
            shares=5,
            entry_price=220.0,
            entry_date=date.today(),
            stop_loss=200.0,
            status="open",
        )
        session.add(position)
        session.commit()
        session.refresh(position)

    with (
        patch("investor.agents.monitor_agent.anthropic.Anthropic") as MockAnthropic,
        patch.object(MonitorAgent, "_gather_market_data", return_value={"TSLA": {"snapshot": {"price": 195.0}, "rsi_14": 28, "macd": None, "recent_news_headlines": []}}),
        patch.object(MonitorAgent, "_send_notifications"),
    ):
        MockAnthropic.return_value.messages.create.return_value = mock_response
        agent = MonitorAgent()
        alerts = agent.run()

    assert len(alerts) == 1
    assert alerts[0].ticker == "TSLA"
    assert alerts[0].severity == "HIGH"
    assert alerts[0].alert_type == "STOP_LOSS"

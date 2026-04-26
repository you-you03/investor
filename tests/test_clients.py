"""
Unit tests for API clients.
Uses respx to mock httpx calls — no real API keys required.
"""

import json

import pytest
import respx
from httpx import Response

# ---------------------------------------------------------------------------
# Polygon client tests
# ---------------------------------------------------------------------------


@pytest.fixture
def polygon_snapshot_response() -> dict:
    return {
        "ticker": {
            "ticker": "AAPL",
            "lastTrade": {"p": 175.50},
            "prevDay": {"c": 172.00},
            "day": {"o": 173.0, "h": 176.0, "l": 172.5, "v": 50000000, "vw": 174.5, "c": 175.50},
        }
    }


@respx.mock
def test_polygon_get_snapshot_success(polygon_snapshot_response):
    from investor.clients.polygon_client import PolygonClient

    respx.get(
        "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/AAPL"
    ).mock(return_value=Response(200, json=polygon_snapshot_response))

    client = PolygonClient()
    result = client.get_stock_snapshot("AAPL")

    assert result is not None
    assert result["ticker"] == "AAPL"
    assert result["price"] == 175.50
    assert result["prev_close"] == 172.00
    assert abs(result["change_pct"] - 2.03) < 0.1


@respx.mock
def test_polygon_get_snapshot_404_returns_none():
    from investor.clients.polygon_client import PolygonClient

    respx.get(
        "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/FAKE"
    ).mock(return_value=Response(404, json={"status": "NOT_FOUND"}))

    client = PolygonClient()
    result = client.get_stock_snapshot("FAKE")
    assert result is None


@respx.mock
def test_polygon_get_market_movers():
    from investor.clients.polygon_client import PolygonClient

    mock_response = {
        "tickers": [
            {
                "ticker": "NVDA",
                "lastTrade": {"p": 900.0},
                "prevDay": {"c": 850.0},
                "day": {"v": 30000000, "c": 900.0},
            }
        ]
    }
    respx.get(
        "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers"
    ).mock(return_value=Response(200, json=mock_response))

    client = PolygonClient()
    result = client.get_market_movers("gainers", limit=5)

    assert len(result) == 1
    assert result[0]["ticker"] == "NVDA"
    assert result[0]["price"] == 900.0
    assert abs(result[0]["change_pct"] - 5.88) < 0.1


# ---------------------------------------------------------------------------
# NewsAPI client tests
# ---------------------------------------------------------------------------


@respx.mock
def test_news_client_returns_articles():
    from investor.clients.news_client import NewsClient

    mock_response = {
        "articles": [
            {
                "title": "NVDA beats earnings",
                "source": {"name": "Reuters"},
                "publishedAt": "2026-04-03T10:00:00Z",
                "url": "https://example.com/nvda",
                "description": "NVIDIA beats Q1 estimates",
            }
        ]
    }
    respx.get("https://newsapi.org/v2/everything").mock(
        return_value=Response(200, json=mock_response)
    )

    client = NewsClient()
    articles = client.get_news("NVDA", days_back=7)

    assert len(articles) == 1
    assert articles[0]["title"] == "NVDA beats earnings"
    assert articles[0]["source"] == "Reuters"


@respx.mock
def test_news_client_api_error_returns_empty():
    from investor.clients.news_client import NewsClient

    respx.get("https://newsapi.org/v2/everything").mock(
        return_value=Response(401, json={"message": "Unauthorized"})
    )

    client = NewsClient()
    result = client.get_news("NVDA")
    assert result == []


# ---------------------------------------------------------------------------
# Slack client tests
# ---------------------------------------------------------------------------


@respx.mock
def test_slack_client_sends_correct_payload(monkeypatch):
    from investor.clients.slack_client import SlackClient

    # Patch settings to avoid requiring .env
    monkeypatch.setattr(
        "investor.clients.slack_client.settings",
        type("S", (), {"slack_webhook_url": "https://hooks.slack.com/test"})(),
    )

    sent_payload = {}

    def capture(request):
        sent_payload.update(json.loads(request.content))
        return Response(200, text="ok")

    respx.post("https://hooks.slack.com/test").mock(side_effect=capture)

    client = SlackClient()
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}]
    result = client.send_message(blocks, text="hello")

    assert result is True
    assert "blocks" in sent_payload
    assert sent_payload["text"] == "hello"

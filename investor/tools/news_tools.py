"""
News and web search tool functions and their Claude JSON Schema definitions.
yfinance.Ticker.news is the primary source (no API key required).
Perplexity and Grok are optional — silently skipped when keys are absent.
"""

import json

from investor.data.yfinance_client import YFinanceClient
from investor.utils.logger import get_logger

logger = get_logger(__name__)
_yf = YFinanceClient()


def _get_perplexity_client():
    """Return PerplexityClient if API key is available, else None."""
    try:
        from investor.config import settings
        if not settings.perplexity_api_key:
            return None
        from investor.clients.news_client import PerplexityClient
        return PerplexityClient()
    except Exception:
        return None


def _get_grok_client():
    """Return GrokClient if API key is available, else None."""
    try:
        from investor.config import settings
        if not settings.xai_api_key:
            return None
        from investor.clients.xai_client import GrokClient
        return GrokClient()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Tool functions
# --------------------------------------------------------------------------- #

def get_news(ticker: str, days_back: int = 7) -> str:
    """Fetch news via yfinance (primary). Falls back to empty list."""
    articles = _yf.get_news(ticker, max_items=10)
    if not articles:
        return json.dumps({"error": f"No news found for {ticker}"})
    return json.dumps(articles)


def get_web_search(query: str) -> str:
    """Web search via Perplexity Sonar. Returns error JSON if key not set."""
    client = _get_perplexity_client()
    if client is None:
        return json.dumps({"error": "PERPLEXITY_API_KEY not set — web search unavailable"})
    result = client.search(query)
    if result is None:
        return json.dumps({"error": "Web search returned no results"})
    return json.dumps({"result": result})


def get_x_search(query: str, days_back: int = 7) -> str:
    """Search X posts via Grok. Returns error JSON if key not set."""
    client = _get_grok_client()
    if client is None:
        return json.dumps({"error": "XAI_API_KEY not set — X search unavailable"})
    result = client.x_search(query, days_back=days_back)
    if result is None:
        return json.dumps({"error": "X search returned no results"})
    return json.dumps({"query": query, "x_sentiment_summary": result})


def get_analyst_ratings(ticker: str) -> str:
    """Get analyst ratings via Perplexity. Returns error JSON if key not set."""
    client = _get_perplexity_client()
    if client is None:
        return json.dumps({"error": "PERPLEXITY_API_KEY not set — analyst ratings unavailable"})
    query = (
        f"What are the latest Wall Street analyst ratings, price targets, and consensus "
        f"for {ticker} stock? Include buy/hold/sell counts and median price target. "
        f"Focus on ratings from the past 30 days."
    )
    result = client.search(query, max_tokens=400)
    if result is None:
        return json.dumps({"error": f"No analyst data found for {ticker}"})
    return json.dumps({"ticker": ticker, "analyst_summary": result})


# --------------------------------------------------------------------------- #
#  Claude tool definitions
# --------------------------------------------------------------------------- #

NEWS_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_news",
        "description": (
            "Fetch recent news articles mentioning a stock ticker. "
            "Returns title, source, publish date, and summary for up to 10 articles."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search (default 7)",
                    "default": 7,
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_web_search",
        "description": (
            "Run a real-time web search using Perplexity Sonar (optional). "
            "Use this for open-ended research: earnings calls, management changes, "
            "industry trends. Returns error if PERPLEXITY_API_KEY is not set — skip and continue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_x_search",
        "description": (
            "Search X (Twitter) posts via Grok (optional). "
            "Returns error if XAI_API_KEY is not set — skip and continue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search (default 7)",
                    "default": 7,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_analyst_ratings",
        "description": (
            "Get the latest Wall Street analyst ratings via Perplexity (optional). "
            "Returns error if PERPLEXITY_API_KEY is not set — skip and continue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    },
]

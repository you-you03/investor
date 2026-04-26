"""
NewsAPI and Perplexity Sonar API clients for news and web search.
"""

from datetime import date, timedelta
from typing import Optional

import httpx

from investor.config import settings
from investor.utils.logger import get_logger

logger = get_logger(__name__)


class NewsClient:
    BASE_URL = "https://newsapi.org/v2"

    def get_news(self, ticker: str, days_back: int = 7) -> list[dict]:
        """
        Fetch recent news articles mentioning the ticker.
        Returns list of {title, source, published_at, url, description}
        Free tier: 100 requests/day, no real-time data.
        """
        from_date = (date.today() - timedelta(days=days_back)).isoformat()
        try:
            response = httpx.get(
                f"{self.BASE_URL}/everything",
                params={
                    "q": f"{ticker} stock",
                    "from": from_date,
                    "sortBy": "relevancy",
                    "language": "en",
                    "pageSize": 10,
                    "apiKey": settings.newsapi_key,
                },
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(f"NewsAPI failed for {ticker}: {e}")
            return []

        articles = response.json().get("articles", [])
        return [
            {
                "title": a.get("title"),
                "source": a.get("source", {}).get("name"),
                "published_at": a.get("publishedAt"),
                "url": a.get("url"),
                "description": a.get("description"),
            }
            for a in articles
        ]


class PerplexityClient:
    BASE_URL = "https://api.perplexity.ai"

    @classmethod
    def is_available(cls) -> bool:
        """Return True if PERPLEXITY_API_KEY is configured."""
        try:
            from investor.config import settings as s
            return bool(s.perplexity_api_key)
        except Exception:
            return False

    def search(self, query: str, max_tokens: int = 600) -> Optional[str]:
        """
        Run a real-time web search via Perplexity Sonar.
        Returns synthesized text answer with citations embedded.
        """
        try:
            response = httpx.post(
                f"{self.BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.perplexity_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sonar",
                    "messages": [{"role": "user", "content": query}],
                    "max_tokens": max_tokens,
                },
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(f"Perplexity search failed: {e}")
            return None

        choices = response.json().get("choices", [])
        if not choices:
            return None
        return choices[0].get("message", {}).get("content")

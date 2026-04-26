"""
xAI (Grok) client — uses the Responses API with x_search tool to search X posts.

Grok's x_search grabs real-time X content and returns a synthesized summary,
which is more useful than raw tweet streams for investment signal extraction.
"""

from datetime import date, timedelta
from typing import Optional

import httpx

from investor.config import settings
from investor.utils.logger import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://api.x.ai/v1"
_MODEL = "grok-4-0709"  # grok-4 family required for server-side tools (x_search)


class GrokClient:
    def __init__(self) -> None:
        self.api_key = settings.xai_api_key

    @classmethod
    def is_available(cls) -> bool:
        """Return True if XAI_API_KEY is configured."""
        try:
            from investor.config import settings as s
            return bool(s.xai_api_key)
        except Exception:
            return False

    def _is_configured(self) -> bool:
        return bool(self.api_key)

    def x_search(
        self,
        query: str,
        days_back: int = 7,
        max_tokens: int = 800,
    ) -> Optional[str]:
        """
        Search X posts via Grok's x_search tool and return a synthesized summary.

        Args:
            query: Natural language search query
            days_back: How many days back to search (default 7)
            max_tokens: Max tokens for Grok's response

        Returns:
            Synthesized text summary of relevant X posts, or None on failure.
        """
        if not self._is_configured():
            logger.warning("XAI_API_KEY not set — skipping X search")
            return None

        from_date = (date.today() - timedelta(days=days_back)).isoformat()
        to_date = date.today().isoformat()

        payload = {
            "model": _MODEL,
            "max_output_tokens": max_tokens,
            "input": [
                {
                    "role": "user",
                    "content": (
                        f"{query}\n\n"
                        "Summarize what X users are saying. Focus on: "
                        "sentiment (bullish/bearish/neutral), key themes, "
                        "notable accounts or analysts mentioned, and any "
                        "specific price targets or catalysts discussed. "
                        "Be concise and factual."
                    ),
                }
            ],
            "tools": [
                {
                    "type": "x_search",
                    "from_date": from_date,
                    "to_date": to_date,
                }
            ],
        }

        try:
            response = httpx.post(
                f"{_BASE_URL}/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(f"xAI Responses API error: {e.response.status_code} {e.response.text[:200]}")
            return None
        except httpx.TimeoutException:
            logger.warning("xAI Responses API timed out")
            return None

        data = response.json()
        # Responses API returns output array; extract the last message text
        for item in reversed(data.get("output", [])):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        return content.get("text")

        logger.warning(f"Unexpected xAI response structure: {str(data)[:300]}")
        return None

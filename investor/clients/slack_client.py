"""
Slack Incoming Webhook client.
All messages use Slack Block Kit for structured, scannable formatting.
"""

import httpx

from investor.config import settings
from investor.utils.logger import get_logger

logger = get_logger(__name__)


class SlackClient:
    def send_message(self, blocks: list[dict], text: str = "") -> bool:
        """
        Send a Block Kit message to the configured Slack webhook.
        `text` is the fallback for notifications that don't render blocks.
        Returns True on success.
        """
        payload: dict = {"blocks": blocks}
        if text:
            payload["text"] = text

        try:
            response = httpx.post(
                settings.slack_webhook_url,
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("Slack message sent")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Slack send failed: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Slack send error: {e}")
            return False

    def send_text(self, message: str) -> bool:
        """Convenience method for plain text messages."""
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": message}}
        ]
        return self.send_message(blocks, text=message)

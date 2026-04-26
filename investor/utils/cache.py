"""
24-hour TTL JSON cache for yfinance data.
Cached files: data/cache/{ticker}_{date}.json
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from investor.utils.logger import get_logger

logger = get_logger(__name__)

CACHE_DIR = Path("data/cache")


def _cache_path(key: str) -> Path:
    today = date.today().isoformat()
    safe_key = key.replace("/", "_").replace(" ", "_")
    return CACHE_DIR / f"{safe_key}_{today}.json"


def get(key: str) -> dict | list | None:
    path = _cache_path(key)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            logger.debug(f"Cache hit: {key}")
            return data
        except Exception:
            pass
    return None


def set(key: str, data: dict | list) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(key)
    try:
        path.write_text(json.dumps(data))
        logger.debug(f"Cache set: {key}")
    except Exception as e:
        logger.warning(f"Cache write failed for {key}: {e}")

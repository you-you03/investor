from __future__ import annotations

import re

_DASH_RE = re.compile(r"[\u2010-\u2015\u2212]")


def normalize_price_range(value: str | None) -> str:
    if not value:
        return ""
    return _DASH_RE.sub("-", value).strip()


def parse_entry_price(entry_price_range: str | None) -> float | None:
    normalized = normalize_price_range(entry_price_range).replace("$", "")
    if not normalized:
        return None

    try:
        parts = [float(part.strip()) for part in normalized.split("-") if part.strip()]
    except ValueError:
        return None

    if len(parts) == 2:
        return (parts[0] + parts[1]) / 2
    if len(parts) == 1:
        return parts[0]
    return None

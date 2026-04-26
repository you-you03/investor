#!/usr/bin/env python
"""
CLI dispatcher for investor data tools.
Usage: .venv/bin/python scripts/tool.py <tool_name> [--key value ...]
Output: JSON string to stdout
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _parse_kwargs(args: list[str]) -> dict:
    """Parse --key value pairs from argv, auto-casting int/float."""
    kwargs: dict = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                val: int | float | str = args[i + 1]
                try:
                    val = int(val)  # type: ignore[assignment]
                except ValueError:
                    try:
                        val = float(val)  # type: ignore[assignment]
                    except ValueError:
                        pass
                kwargs[key] = val
                i += 2
            else:
                kwargs[key] = True
                i += 1
        else:
            i += 1
    return kwargs


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: tool.py <tool_name> [--key value ...]"}))
        sys.exit(1)

    tool_name = sys.argv[1]
    kwargs = _parse_kwargs(sys.argv[2:])

    from investor.tools.market_tools import (
        get_atr_targets,
        get_earnings_calendar,
        get_financials,
        get_market_context,
        get_market_movers,
        get_relative_strength,
        get_stock_snapshot,
        get_technical_indicators,
        get_ticker_details,
    )
    from investor.tools.news_tools import (
        get_analyst_ratings,
        get_news,
        get_web_search,
        get_x_search,
    )

    tools = {
        "get_market_context": get_market_context,
        "get_market_movers": get_market_movers,
        "get_stock_snapshot": get_stock_snapshot,
        "get_financials": get_financials,
        "get_technical_indicators": get_technical_indicators,
        "get_atr_targets": get_atr_targets,
        "get_ticker_details": get_ticker_details,
        "get_relative_strength": get_relative_strength,
        "get_earnings_calendar": get_earnings_calendar,
        "get_news": get_news,
        "get_web_search": get_web_search,
        "get_x_search": get_x_search,
        "get_analyst_ratings": get_analyst_ratings,
    }

    fn = tools.get(tool_name)
    if fn is None:
        available = ", ".join(tools.keys())
        print(json.dumps({"error": f"Unknown tool: {tool_name}. Available: {available}"}))
        sys.exit(1)

    try:
        result = fn(**kwargs)
        print(result)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

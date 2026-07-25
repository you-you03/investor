#!/usr/bin/env python3
"""Audit the live portfolio before any new BUY workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investor.config import settings
from investor.core.risk import portfolio_guard_violations
from investor.utils.portfolio_contract import read_portfolio_rows


def build_audit(path: Path) -> dict:
    rows = read_portfolio_rows(path)
    open_rows = [row for row in rows if row.get("status") == "open"]
    violations = portfolio_guard_violations(open_rows)
    return {
        "strategy_version": settings.strategy_version,
        "portfolio_path": str(path),
        "new_buys_blocked": bool(violations),
        "open_position_count": len(open_rows),
        "limits": {
            "max_open_positions": settings.max_open_positions,
            "max_position_pct": settings.max_position_pct,
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "max_portfolio_heat_pct": settings.max_portfolio_heat_pct,
        },
        "violations": violations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--portfolio",
        default=settings.default_portfolio_path,
        help="Portfolio CSV to audit",
    )
    args = parser.parse_args()
    result = build_audit(Path(args.portfolio))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2 if result["new_buys_blocked"] else 0)


if __name__ == "__main__":
    main()

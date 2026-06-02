#!/usr/bin/env python
"""
Phase 3G: Post-trade feedback loop.

Matches research_history.json candidates to portfolio.csv positions,
computes realized/unrealized returns, and writes outcome data back to
research_history.json.

Usage:
  .venv/bin/python scripts/record_outcomes.py          # update all open/closed
  .venv/bin/python scripts/record_outcomes.py --dry-run # preview without writing
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from investor.utils.portfolio_contract import closed_row_issues

PORTFOLIO_PATH = Path("data/portfolio.csv")
RESEARCH_HISTORY_PATH = Path("data/research_history.json")


def _read_portfolio() -> list[dict]:
    if not PORTFOLIO_PATH.exists():
        return []
    with open(PORTFOLIO_PATH) as f:
        return list(csv.DictReader(f))


def _load_history() -> dict:
    if not RESEARCH_HISTORY_PATH.exists():
        return {"runs": []}
    return json.loads(RESEARCH_HISTORY_PATH.read_text())


def _save_history(history: dict) -> None:
    RESEARCH_HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False))


def _days_between(d1_str: str, d2_str: str) -> Optional[int]:
    try:
        d1 = datetime.fromisoformat(d1_str).date()
        d2 = datetime.fromisoformat(d2_str).date()
        return (d2 - d1).days
    except Exception:
        return None


def _determine_outcome_type(
    exit_price: float,
    entry_price: float,
    target_price: Optional[float],
    stop_price: Optional[float],
) -> str:
    """Classify exit reason based on price vs target/stop thresholds."""
    if target_price and exit_price >= target_price * 0.97:
        return "TARGET_HIT"
    if stop_price and exit_price <= stop_price * 1.03:
        return "STOP_HIT"
    return "TIME_EXIT"


def _get_current_price(ticker: str) -> Optional[float]:
    """Fetch live price via yfinance (bypasses cache for freshness)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        price = info.get("last_price") or info.get("lastPrice")
        return float(price) if price else None
    except Exception:
        return None


def _get_spy_return(start_date: str, end_date: Optional[str] = None) -> Optional[float]:
    """
    Compute SPY return between start_date and end_date (or today).
    Fetches 5 extra days before start_date to handle weekends/holidays.
    """
    try:
        import yfinance as yf
        from datetime import timedelta
        end = end_date or date.today().isoformat()
        # Fetch 5 calendar days before start to ensure we get a trading day
        fetch_start = (datetime.fromisoformat(start_date).date() - timedelta(days=5)).isoformat()
        hist = yf.Ticker("SPY").history(start=fetch_start, end=end, auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return None
        # Use the last bar at or before start_date as the baseline
        start_dt = datetime.fromisoformat(start_date).date()
        hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
        before_start = hist[hist.index.date <= start_dt]
        if before_start.empty:
            return None
        spy_start = before_start["Close"].iloc[-1]
        spy_end = hist["Close"].iloc[-1]
        return round((spy_end - spy_start) / spy_start * 100, 2)
    except Exception:
        return None


def build_outcome(
    candidate: dict,
    portfolio_rows: list[dict],
) -> Optional[dict]:
    """
    Build an outcome dict for a candidate by matching it to portfolio.csv.
    Returns None if no matching position found.
    """
    ticker = candidate.get("ticker", "").upper()

    # Find all portfolio rows for this ticker, prefer open → closed order
    matching = [r for r in portfolio_rows if r.get("ticker", "").upper() == ticker]
    if not matching:
        return None

    # Prefer the row whose entry_date is closest to the research run date
    run_date = candidate.get("_run_date", "")  # injected by caller
    if run_date and len(matching) > 1:
        def date_distance(row: dict) -> int:
            d = _days_between(run_date, row.get("entry_date", run_date))
            return abs(d) if d is not None else 9999
        matching = sorted(matching, key=date_distance)

    row = matching[0]
    issues = closed_row_issues(row)
    if issues:
        print(f"WARNING: {' | '.join(issues)}", file=sys.stderr)
        return None
    status = row.get("status", "open")
    entry_price_str = row.get("entry_price") or ""
    if not entry_price_str:
        return None

    entry_price = float(entry_price_str)
    entry_date = row.get("entry_date", "")

    # Parse target/stop from portfolio row (may be empty)
    target_raw = row.get("target_price") or candidate.get("target_price")
    stop_raw = row.get("stop_loss") or candidate.get("stop_loss")
    target_price = float(target_raw) if target_raw else None
    stop_price = float(stop_raw) if stop_raw else None

    shares_raw = row.get("shares", "0")
    shares = float(shares_raw) if shares_raw else 0.0

    if status == "closed":
        exit_price_str = row.get("exit_price") or ""
        exit_date = row.get("exit_date") or ""
        if not exit_price_str:
            return None
        exit_price = float(exit_price_str)
        realized_return_pct = round((exit_price - entry_price) / entry_price * 100, 2)
        outcome_type = _determine_outcome_type(exit_price, entry_price, target_price, stop_price)
        days_held = _days_between(entry_date, exit_date)
        pnl_usd = round((exit_price - entry_price) * shares, 2) if shares > 0 else None
        spy_return = _get_spy_return(entry_date, exit_date) if entry_date else None

        return {
            "status": "closed",
            "outcome_type": outcome_type,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "days_held": days_held,
            "realized_return_pct": realized_return_pct,
            "pnl_usd": pnl_usd,
            "spy_return_pct": spy_return,
            "alpha_pct": round(realized_return_pct - spy_return, 2) if spy_return is not None else None,
            "win": realized_return_pct > 0,
            "recorded_at": date.today().isoformat(),
        }

    else:  # open position — compute unrealized
        current_price = _get_current_price(ticker)
        if current_price is None:
            return {
                "status": "open",
                "outcome_type": "OPEN",
                "entry_price": entry_price,
                "entry_date": entry_date,
                "current_price": None,
                "unrealized_return_pct": None,
                "recorded_at": date.today().isoformat(),
            }

        unrealized_pct = round((current_price - entry_price) / entry_price * 100, 2)
        days_held = _days_between(entry_date, date.today().isoformat())
        pnl_usd = round((current_price - entry_price) * shares, 2) if shares > 0 else None
        spy_return = _get_spy_return(entry_date) if entry_date else None

        # Determine if open position has hit target/stop
        if target_price and current_price >= target_price * 0.97:
            outcome_type = "AT_TARGET"
        elif stop_price and current_price <= stop_price * 1.03:
            outcome_type = "AT_STOP"
        else:
            outcome_type = "OPEN"

        return {
            "status": "open",
            "outcome_type": outcome_type,
            "entry_price": entry_price,
            "entry_date": entry_date,
            "current_price": current_price,
            "days_held": days_held,
            "unrealized_return_pct": unrealized_pct,
            "pnl_usd": pnl_usd,
            "spy_return_pct": spy_return,
            "alpha_pct": round(unrealized_pct - spy_return, 2) if spy_return is not None else None,
            "recorded_at": date.today().isoformat(),
        }


def record_outcomes(dry_run: bool = False) -> dict:
    """
    Main entry point. Returns a summary dict with counts.
    """
    portfolio_rows = _read_portfolio()
    history = _load_history()

    updated_count = 0
    skipped_count = 0
    new_count = 0

    for run in history.get("runs", []):
        run_date = run.get("date", "")
        for candidate in run.get("candidates", []):
            # Inject run_date for date-proximity matching
            candidate["_run_date"] = run_date

            existing_outcome = candidate.get("outcome")
            outcome = build_outcome(candidate, portfolio_rows)

            # Clean up the injected key
            candidate.pop("_run_date", None)

            if outcome is None:
                skipped_count += 1
                continue

            # Don't overwrite a closed outcome with an open one
            if existing_outcome and existing_outcome.get("status") == "closed":
                skipped_count += 1
                continue

            if existing_outcome:
                updated_count += 1
            else:
                new_count += 1

            candidate["outcome"] = outcome

    if not dry_run:
        _save_history(history)

    return {
        "new": new_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "dry_run": dry_run,
    }


def print_summary(history: dict) -> None:
    """Print a quick outcome summary table for all candidates that have outcomes."""
    rows_with_outcome = []
    for run in history.get("runs", []):
        run_date = run.get("date", "")
        for c in run.get("candidates", []):
            outcome = c.get("outcome")
            if not outcome:
                continue
            rows_with_outcome.append({
                "run_date": run_date,
                "ticker": c.get("ticker", ""),
                "score": c.get("score", "?"),
                "conviction": c.get("conviction", "?"),
                "status": outcome.get("status", ""),
                "outcome_type": outcome.get("outcome_type", ""),
                "return_pct": outcome.get("realized_return_pct") or outcome.get("unrealized_return_pct"),
                "alpha_pct": outcome.get("alpha_pct"),
                "days_held": outcome.get("days_held"),
            })

    if not rows_with_outcome:
        print("No outcome data recorded yet.")
        return

    print(f"\n{'Run Date':<12} {'Ticker':<8} {'Score':<6} {'Conv':<8} {'Status':<10} {'Type':<12} {'Return%':>8} {'Alpha%':>8} {'Days':>5}")
    print("-" * 90)
    for r in rows_with_outcome:
        ret = f"{r['return_pct']:+.1f}%" if r['return_pct'] is not None else "—"
        alp = f"{r['alpha_pct']:+.1f}%" if r['alpha_pct'] is not None else "—"
        days = str(r["days_held"]) if r["days_held"] is not None else "—"
        print(f"{r['run_date']:<12} {r['ticker']:<8} {str(r['score']):<6} {r['conviction']:<8} {r['status']:<10} {r['outcome_type']:<12} {ret:>8} {alp:>8} {days:>5}")


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    print(f"Recording outcomes {'(DRY RUN)' if dry_run else ''}...")

    result = record_outcomes(dry_run=dry_run)
    print(f"  New outcomes: {result['new']}")
    print(f"  Updated:      {result['updated']}")
    print(f"  Skipped:      {result['skipped']}")

    if not dry_run:
        history = _load_history()
        print_summary(history)


if __name__ == "__main__":
    main()

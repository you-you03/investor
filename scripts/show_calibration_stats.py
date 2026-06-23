#!/usr/bin/env python3
"""
show_calibration_stats.py — 判断前に読む校正レポート

research_history.json の outcome を主データとして使い、
alpha を中心に conviction / signal / 保有日数 / 直近EV を集計する。
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean, median

from investor.config import settings
from investor.utils.portfolio_contract import closed_row_issues

RESEARCH_HISTORY_PATH = Path("data/research_history.json")
PORTFOLIO_PATH = Path(settings.default_portfolio_path)


def _infer_conviction(candidate: dict) -> str:
    conviction = (candidate.get("conviction") or "").strip().upper()
    if conviction in ("HIGH", "MEDIUM", "LOW"):
        return conviction
    score = candidate.get("score")
    if score is not None:
        try:
            s = float(score)
            if s >= 8.0:
                return "HIGH"
            if s >= 7.0:
                return "MEDIUM"
            return "LOW"
        except (TypeError, ValueError):
            pass
    return ""


def _load_history() -> dict:
    if not RESEARCH_HISTORY_PATH.exists():
        return {"runs": []}
    try:
        return json.loads(RESEARCH_HISTORY_PATH.read_text())
    except Exception as e:
        print(f"ERROR: Failed to read research_history.json: {e}", file=sys.stderr)
        return {"runs": []}


def _load_portfolio_index() -> dict[tuple[str, str], dict]:
    if not PORTFOLIO_PATH.exists():
        return {}

    index: dict[tuple[str, str], dict] = {}
    with PORTFOLIO_PATH.open() as f:
        for row in csv.DictReader(f):
            issues = closed_row_issues(row)
            if issues:
                for issue in issues:
                    print(f"WARNING: {issue}", file=sys.stderr)
                continue
            ticker = str(row.get("ticker", "")).upper()
            entry_date = row.get("entry_date", "")
            if ticker and entry_date:
                index[(ticker, entry_date)] = row
    return index


def _bucket_days(days_held: int | None) -> str:
    if days_held is None:
        return "unknown"
    if days_held <= 3:
        return "1-3d"
    if days_held <= 7:
        return "4-7d"
    if days_held <= 14:
        return "8-14d"
    return "15d+"


def _load_rows() -> list[dict]:
    history = _load_history()
    portfolio_index = _load_portfolio_index()
    rows: list[dict] = []

    for run in history.get("runs", []):
        run_date = run.get("date", "")
        for candidate in run.get("candidates", []):
            outcome = candidate.get("outcome") or {}
            if not outcome:
                continue

            conviction = _infer_conviction(candidate)
            if conviction not in ("HIGH", "MEDIUM", "LOW"):
                continue

            status = outcome.get("status", "")
            return_pct = (
                outcome.get("realized_return_pct")
                if status == "closed"
                else outcome.get("unrealized_return_pct")
            )
            entry_date = outcome.get("entry_date", "")
            portfolio_row = portfolio_index.get((candidate.get("ticker", "").upper(), entry_date), {})
            rows.append({
                "run_date": run_date,
                "ticker": candidate.get("ticker", ""),
                "conviction": conviction,
                "status": status,
                "return_pct": return_pct,
                "alpha_pct": outcome.get("alpha_pct"),
                "days_held": outcome.get("days_held"),
                "signal_type": portfolio_row.get("signal_type") or candidate.get("signal_type") or "",
                "hold_bucket": _bucket_days(outcome.get("days_held")),
            })
    return rows


def _compute_conviction_stats(rows: list[dict]) -> dict[str, dict]:
    groups = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for row in rows:
        groups[row["conviction"]].append(row)

    result: dict[str, dict] = {}
    for conviction, items in groups.items():
        closed = [r for r in items if r["status"] == "closed" and r["return_pct"] is not None]
        open_ = [r for r in items if r["status"] == "open"]
        returns = [r["return_pct"] for r in closed]
        alphas = [r["alpha_pct"] for r in closed if r["alpha_pct"] is not None]
        wins = [r for r in closed if r["return_pct"] > 0]
        result[conviction] = {
            "total": len(items),
            "closed": len(closed),
            "open": len(open_),
            "win_rate": len(wins) / len(closed) * 100 if closed else None,
            "avg_return": mean(returns) if returns else None,
            "median_return": median(returns) if returns else None,
            "avg_alpha": mean(alphas) if alphas else None,
            "median_alpha": median(alphas) if alphas else None,
        }
    return result


def _top_signal_lines(rows: list[dict]) -> list[str]:
    signal_groups: dict[str, list[dict]] = {}
    for row in rows:
        if row["status"] != "closed" or row["alpha_pct"] is None or not row["signal_type"]:
            continue
        signal_groups.setdefault(row["signal_type"], []).append(row)

    lines: list[str] = []
    for signal_type, items in sorted(
        signal_groups.items(),
        key=lambda item: mean(r["alpha_pct"] for r in item[1]),
        reverse=True,
    ):
        avg_alpha = mean(r["alpha_pct"] for r in items)
        avg_return = mean(r["return_pct"] for r in items if r["return_pct"] is not None)
        lines.append(
            f"- {signal_type}: avg alpha {avg_alpha:+.1f}% | avg return {avg_return:+.1f}% | n={len(items)}"
        )
    return lines or ["- signal_type 別のクローズデータなし"]


def _hold_bucket_lines(rows: list[dict]) -> list[str]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        if row["status"] != "closed" or row["alpha_pct"] is None:
            continue
        buckets.setdefault(row["hold_bucket"], []).append(row)

    ordered = ["1-3d", "4-7d", "8-14d", "15d+", "unknown"]
    lines: list[str] = []
    for bucket in ordered:
        items = buckets.get(bucket, [])
        if not items:
            continue
        avg_alpha = mean(r["alpha_pct"] for r in items)
        avg_return = mean(r["return_pct"] for r in items if r["return_pct"] is not None)
        lines.append(f"- {bucket}: avg alpha {avg_alpha:+.1f}% | avg return {avg_return:+.1f}% | n={len(items)}")
    return lines or ["- 保有日数バケットのクローズデータなし"]


def _recent_ev_line(rows: list[dict]) -> str:
    closed = [r for r in rows if r["status"] == "closed" and r["return_pct"] is not None]
    if not closed:
        return "- クローズデータなし"

    def sort_key(row: dict) -> datetime:
        raw = row.get("run_date") or "1970-01-01"
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return datetime.fromisoformat("1970-01-01")

    closed_sorted = sorted(closed, key=sort_key)
    full_ev = mean(r["return_pct"] for r in closed_sorted)
    recent_sample = closed_sorted[-5:]
    recent_ev = mean(r["return_pct"] for r in recent_sample)
    recent_alpha_values = [r["alpha_pct"] for r in recent_sample if r["alpha_pct"] is not None]
    recent_alpha = mean(recent_alpha_values) if recent_alpha_values else None
    deterioration = ""
    if len(closed_sorted) >= 5 and full_ev > 0 and recent_ev < full_ev * 0.5:
        deterioration = " | WARNING recent EV deterioration"

    alpha_text = f" | recent alpha {recent_alpha:+.1f}%" if recent_alpha is not None else ""
    return (
        f"- full EV {full_ev:+.1f}% | recent 5 EV {recent_ev:+.1f}%"
        f"{alpha_text}{deterioration}"
    )


def main() -> None:
    rows = _load_rows()

    print("=== 判断前 校正レポート ===")
    if not rows:
        print("outcome データなし。scripts/record_outcomes.py を先に実行してください。")
        print()
        return

    conviction_stats = _compute_conviction_stats(rows)
    total_n = sum(s["total"] for s in conviction_stats.values())
    closed_total = sum(s["closed"] for s in conviction_stats.values())
    print(f"対象: {total_n}件 | closed={closed_total}")
    print(
        f"{'Conviction':<12} {'n':>3} {'closed':>7} {'win':>7} {'avg alpha':>11} "
        f"{'med alpha':>11} {'avg ret':>10}"
    )
    print("-" * 70)

    for conviction in ("HIGH", "MEDIUM", "LOW"):
        stats = conviction_stats[conviction]
        if stats["closed"] == 0:
            print(
                f"{conviction:<12} {stats['total']:>3} {stats['closed']:>7} {'—':>7} "
                f"{'—':>11} {'—':>11} {'—':>10}"
            )
            continue
        print(
            f"{conviction:<12} {stats['total']:>3} {stats['closed']:>7} "
            f"{stats['win_rate']:>6.0f}% {stats['avg_alpha']:>+10.1f}% "
            f"{stats['median_alpha']:>+10.1f}% {stats['avg_return']:>+9.1f}%"
        )

    print("\nSignal alpha")
    for line in _top_signal_lines(rows):
        print(line)

    print("\nHold period alpha")
    for line in _hold_bucket_lines(rows):
        print(line)

    print("\nRecent EV")
    print(_recent_ev_line(rows))

    if closed_total < 20:
        print(f"\nWARNING: sample size is still thin (closed={closed_total} < 20)")

    print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
show_calibration_stats.py — 確信度校正レポート

research_history.json の outcome データを集計し、
確信度別（HIGH / MEDIUM / LOW）の勝率・平均リターン・SPY Alpha を表示する。

Usage:
  .venv/bin/python scripts/show_calibration_stats.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean, median

RESEARCH_HISTORY_PATH = Path("data/research_history.json")


def _infer_conviction(candidate: dict) -> str:
    """conviction フィールドが欠損している場合、score から推論する。"""
    conviction = (candidate.get("conviction") or "").strip().upper()
    if conviction in ("HIGH", "MEDIUM", "LOW"):
        return conviction
    score = candidate.get("score")
    if score is not None:
        try:
            s = float(score)
            if s >= 8.0:
                return "HIGH"
            elif s >= 7.0:
                return "MEDIUM"
            else:
                return "LOW"
        except (TypeError, ValueError):
            pass
    return ""


def _load_outcomes() -> list[dict]:
    if not RESEARCH_HISTORY_PATH.exists():
        return []
    try:
        history = json.loads(RESEARCH_HISTORY_PATH.read_text())
    except Exception as e:
        print(f"ERROR: Failed to read research_history.json: {e}", file=sys.stderr)
        return []

    rows = []
    for run in history.get("runs", []):
        run_date = run.get("date", "")
        for candidate in run.get("candidates", []):
            outcome = candidate.get("outcome")
            if not outcome:
                continue
            conviction = _infer_conviction(candidate)
            if conviction not in ("HIGH", "MEDIUM", "LOW"):
                continue
            rows.append({
                "run_date": run_date,
                "ticker": candidate.get("ticker", ""),
                "conviction": conviction,
                "status": outcome.get("status", ""),
                "return_pct": outcome.get("realized_return_pct")
                    if outcome.get("status") == "closed"
                    else outcome.get("unrealized_return_pct"),
                "alpha_pct": outcome.get("alpha_pct"),
                "days_held": outcome.get("days_held"),
            })
    return rows


def _compute_stats(rows: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for row in rows:
        c = row["conviction"]
        if c in groups:
            groups[c].append(row)

    result = {}
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
            "win_count": len(wins),
            "win_rate": len(wins) / len(closed) * 100 if closed else None,
            "avg_return": mean(returns) if returns else None,
            "median_return": median(returns) if returns else None,
            "avg_alpha": mean(alphas) if alphas else None,
        }
    return result


def main() -> None:
    rows = _load_outcomes()

    if not rows:
        print("=== 確信度校正レポート ===")
        print("アウトカムデータなし。record_outcomes.py を先に実行してください。")
        print()
        return

    stats = _compute_stats(rows)
    total_n = sum(s["total"] for s in stats.values())
    closed_total = sum(s["closed"] for s in stats.values())

    print(f"\n=== 確信度校正レポート (n={total_n}, closed={closed_total}) ===")
    print(
        f"{'確信度':<8} {'n(全)':<7} {'n(終)':<7} {'勝率':>7} {'平均リターン':>13} {'中央値':>9} {'平均Alpha':>10}"
    )
    print("-" * 68)

    for conviction in ("HIGH", "MEDIUM", "LOW"):
        s = stats[conviction]
        open_note = f" (+{s['open']} open)" if s["open"] > 0 else ""

        if s["closed"] == 0:
            win_str = "—"
            avg_str = f"({s['open']}件 open)" if s["open"] > 0 else "—"
            med_str = "—"
            alpha_str = "—"
            open_note = ""
        else:
            win_str = f"{s['win_rate']:.0f}%" if s["win_rate"] is not None else "—"
            avg_str = f"{s['avg_return']:+.1f}%" if s["avg_return"] is not None else "—"
            med_str = f"{s['median_return']:+.1f}%" if s["median_return"] is not None else "—"
            alpha_str = f"{s['avg_alpha']:+.1f}%" if s["avg_alpha"] is not None else "—"

        print(
            f"{conviction:<8} {s['total']:<7} {s['closed']:<7} {win_str:>7} "
            f"{avg_str:>13} {med_str:>9} {alpha_str:>10}{open_note}"
        )

    print()

    # Warnings
    if closed_total < 20:
        print(f"⚠ サンプル数が少なすぎて統計的意味なし（closed={closed_total} < 20）")

    dates = sorted({r["run_date"] for r in rows if r["run_date"]})
    if len(dates) >= 2:
        print(f"⚠ データ期間: {dates[0]} 〜 {dates[-1]}（相場環境の偏りに注意）")
    elif dates:
        print(f"⚠ データ期間: {dates[0]} のみ（相場環境の偏りに注意）")

    print()


if __name__ == "__main__":
    main()

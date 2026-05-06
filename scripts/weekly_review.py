#!/usr/bin/env python3
"""
weekly_review.py — 週次パフォーマンスレビュー

portfolio.csv + research_history.json + decision_history.json を集計し、
SPY ベンチマーク比較・確信度別 Alpha・PASS 判断数を含む週次レポートを生成する。

Usage:
  .venv/bin/python scripts/weekly_review.py                    # 先週を対象
  .venv/bin/python scripts/weekly_review.py --week 2026-04-21  # 特定週（月曜日付）を指定

cron (毎週月曜 JST 8時):
  0 8 * * 1 cd "/Users/yutaobayashi/PERSONAL DEV/investor" && .venv/bin/python scripts/weekly_review.py >> logs/cron.log 2>&1
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

PORTFOLIO_PATH = Path("data/portfolio.csv")
RESEARCH_HISTORY_PATH = Path("data/research_history.json")
DECISION_HISTORY_PATH = Path("data/decision_history.json")
REPORTS_DIR = Path("reports/review")


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
            elif s >= 7.0:
                return "MEDIUM"
            else:
                return "LOW"
        except (TypeError, ValueError):
            pass
    return "?"


def _week_range(ref: date) -> tuple[date, date]:
    monday = ref - timedelta(days=ref.weekday())
    return monday, monday + timedelta(days=6)


def _load_portfolio() -> list[dict]:
    if not PORTFOLIO_PATH.exists():
        return []
    with open(PORTFOLIO_PATH) as f:
        return list(csv.DictReader(f))


def _load_history() -> dict:
    if not RESEARCH_HISTORY_PATH.exists():
        return {"runs": []}
    return json.loads(RESEARCH_HISTORY_PATH.read_text())


def _load_decision_history() -> list[dict]:
    if not DECISION_HISTORY_PATH.exists():
        return []
    try:
        return json.loads(DECISION_HISTORY_PATH.read_text())
    except Exception:
        return []


def _get_outcome(ticker: str, entry_date: str, history: dict) -> dict | None:
    """Match portfolio row to research_history outcome by ticker + entry_date proximity."""
    best: dict | None = None
    best_delta = 9999
    for run in history.get("runs", []):
        run_date = run.get("date", "")
        for candidate in run.get("candidates", []):
            if candidate.get("ticker", "").upper() != ticker.upper():
                continue
            outcome = candidate.get("outcome")
            if not outcome:
                continue
            try:
                delta = abs(
                    (datetime.fromisoformat(run_date).date()
                     - datetime.fromisoformat(entry_date).date()).days
                )
            except Exception:
                delta = 9999
            if delta < best_delta:
                best_delta = delta
                best = {
                    "conviction": _infer_conviction(candidate),
                    **outcome,
                }
    return best


def _generate(week_start: date, week_end: date) -> str:
    portfolio = _load_portfolio()
    history = _load_history()
    decision_history = _load_decision_history()

    # Positions active during this week
    rows = []
    for row in portfolio:
        entry_str = row.get("entry_date", "")
        if not entry_str:
            continue
        try:
            entry_dt = datetime.fromisoformat(entry_str).date()
        except Exception:
            continue

        exit_str = row.get("exit_date", "")
        try:
            exit_dt = datetime.fromisoformat(exit_str).date() if exit_str else None
        except Exception:
            exit_dt = None

        if entry_dt > week_end:
            continue
        if exit_dt and exit_dt < week_start:
            continue

        outcome = _get_outcome(row["ticker"], entry_str, history)
        conviction = outcome.get("conviction", "?") if outcome else "?"

        entry_price = float(row.get("entry_price") or 0)
        exit_price_str = row.get("exit_price", "")
        exit_price = float(exit_price_str) if exit_price_str else None

        if row.get("status") == "closed" and exit_price:
            return_pct = round((exit_price - entry_price) / entry_price * 100, 2)
        else:
            return_pct = None

        rows.append({
            "ticker": row["ticker"],
            "status": row.get("status", "open"),
            "conviction": conviction,
            "entry_date": entry_str,
            "exit_date": exit_str or "open",
            "return_pct": return_pct,
            "spy_return": outcome.get("spy_return_pct") if outcome else None,
            "alpha_pct": outcome.get("alpha_pct") if outcome else None,
        })

    lines: list[str] = [
        f"## 週次パフォーマンスレビュー ({week_start} 〜 {week_end})",
        f"生成: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "### ポジション損益",
        "",
        "| Ticker | 確信度 | ステータス | リターン | SPY同期間 | Alpha |",
        "|--------|--------|-----------|---------|----------|-------|",
    ]

    closed_rows = [r for r in rows if r["status"] == "closed" and r["return_pct"] is not None]
    open_rows = [r for r in rows if r["status"] == "open"]

    for r in closed_rows:
        ret = f"{r['return_pct']:+.1f}%" if r["return_pct"] is not None else "—"
        spy = f"{r['spy_return']:+.1f}%" if r["spy_return"] is not None else "—"
        alp = f"{r['alpha_pct']:+.1f}%" if r["alpha_pct"] is not None else "—"
        lines.append(f"| {r['ticker']} | {r['conviction']} | closed | {ret} | {spy} | {alp} |")

    for r in open_rows:
        lines.append(f"| {r['ticker']} | {r['conviction']} | open | — | — | — |")

    if not rows:
        lines.append("| — | — | — | — | — | — |")

    lines += ["", "### 累積確信度校正（クローズド済み全ポジション）", ""]

    # All-time conviction stats from research_history
    all_closed: list[dict] = []
    for run in history.get("runs", []):
        for candidate in run.get("candidates", []):
            outcome = candidate.get("outcome", {}) or {}
            if outcome.get("status") == "closed" and outcome.get("alpha_pct") is not None:
                all_closed.append({
                    "conviction": _infer_conviction(candidate),
                    "alpha_pct": outcome["alpha_pct"],
                })

    for conviction in ("HIGH", "MEDIUM", "LOW"):
        items = [r for r in all_closed if r["conviction"] == conviction]
        if not items:
            lines.append(f"{conviction} の平均 Alpha: データなし")
            continue
        avg_alpha = mean(r["alpha_pct"] for r in items)
        lines.append(f"{conviction} の平均 Alpha: {avg_alpha:+.1f}%  (n={len(items)})")

    lines += ["", "### 判断数サマリー", ""]

    # Decision history for this week
    week_decisions = [
        d for d in decision_history
        if week_start.isoformat() <= d.get("date", "") <= week_end.isoformat()
    ]

    if week_decisions:
        total_buy = sum(len(d.get("buy_decisions", [])) for d in week_decisions)
        total_pass = sum(len(d.get("pass_decisions", [])) for d in week_decisions)
        no_trade_count = sum(1 for d in week_decisions if d.get("no_trade_week", False))
        lines.append(
            f"BUY実行: {total_buy}件 / PASS: {total_pass}件 / 今週エントリーなし: {no_trade_count}件"
        )
    else:
        lines.append("BUY実行: 不明 / PASS: 不明（decision_history.json に記録なし）")

    lines += ["", "---"]
    return "\n".join(lines)


def main() -> None:
    week_start: date | None = None
    args = sys.argv[1:]
    if "--week" in args:
        idx = args.index("--week")
        try:
            week_start = datetime.fromisoformat(args[idx + 1]).date()
        except (IndexError, ValueError) as e:
            print(f"ERROR: --week requires a YYYY-MM-DD date: {e}", file=sys.stderr)
            sys.exit(1)

    if week_start is None:
        week_start, _ = _week_range(date.today() - timedelta(days=7))

    _, week_end = _week_range(week_start)
    report = _generate(week_start, week_end)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"review_{week_start}.md"
    report_path.write_text(report)

    print(report)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()

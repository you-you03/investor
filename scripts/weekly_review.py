#!/usr/bin/env python3
"""
weekly_review.py — 提案と実約定を分けて振り返る週次レビュー
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

from investor.utils.portfolio_contract import closed_row_issues, read_portfolio_rows

PORTFOLIO_PATH = Path("data/portfolio.csv")
PAPER_PATH = Path("data/paper_portfolio.csv")
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
            if s >= 7.0:
                return "MEDIUM"
            return "LOW"
        except (TypeError, ValueError):
            pass
    return "?"


def _week_range(ref: date) -> tuple[date, date]:
    monday = ref - timedelta(days=ref.weekday())
    return monday, monday + timedelta(days=6)


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


def _date_in_range(value: str, week_start: date, week_end: date) -> bool:
    if not value:
        return False
    try:
        current = datetime.fromisoformat(value).date()
    except ValueError:
        return False
    return week_start <= current <= week_end


def _portfolio_rows(path: Path) -> list[dict]:
    rows = read_portfolio_rows(path)
    valid_rows: list[dict] = []
    for row in rows:
        issues = closed_row_issues(row)
        if issues:
            continue
        valid_rows.append(row)
    return valid_rows


def _get_outcome(ticker: str, entry_date: str, history: dict) -> dict | None:
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
                    (
                        datetime.fromisoformat(run_date).date()
                        - datetime.fromisoformat(entry_date).date()
                    ).days
                )
            except Exception:
                delta = 9999
            if delta < best_delta:
                best_delta = delta
                best = {"conviction": _infer_conviction(candidate), **outcome}
    return best


def _proposal_summary(decision_history: list[dict], week_start: date, week_end: date) -> list[str]:
    week_decisions = [
        d for d in decision_history if week_start.isoformat() <= d.get("date", "") <= week_end.isoformat()
    ]
    if not week_decisions:
        return [
            "### 提案サマリー",
            "",
            "- BUY提案: 不明 / PASS提案: 不明（decision_history.json に記録なし）",
            "",
        ]

    total_buy = 0
    total_pass = 0
    total_hold_cash = 0
    for decision in week_decisions:
        summary = decision.get("proposal_summary") or {}
        total_buy += summary.get("buy_count", len(decision.get("buy_decisions", [])))
        total_pass += summary.get("pass_count", len(decision.get("pass_decisions", [])))
        total_hold_cash += summary.get("hold_cash_count", len(decision.get("hold_cash_decisions", [])))

    no_trade_count = sum(1 for d in week_decisions if d.get("no_trade_week", False))
    return [
        "### 提案サマリー",
        "",
        f"- BUY提案: {total_buy}件",
        f"- PASS提案: {total_pass}件",
        f"- HOLD_CASH / NO_TRADE: {total_hold_cash}件",
        f"- 今週エントリー見送り回数: {no_trade_count}件",
        "",
    ]


def _execution_summary(history: dict, week_start: date, week_end: date) -> list[str]:
    portfolio = _portfolio_rows(PORTFOLIO_PATH)
    week_entries = [r for r in portfolio if _date_in_range(r.get("entry_date", ""), week_start, week_end)]
    week_closes = [
        r for r in portfolio
        if r.get("status") == "closed" and _date_in_range(r.get("exit_date", ""), week_start, week_end)
    ]

    realized_pnl = 0.0
    alpha_values: list[float] = []
    lines = [
        "### 実約定サマリー",
        "",
        f"- 実約定数: {len(week_entries)}件",
        f"- 実クローズ数: {len(week_closes)}件",
    ]

    for row in week_closes:
        try:
            realized_pnl += (float(row["exit_price"]) - float(row["entry_price"])) * float(row["shares"])
        except (TypeError, ValueError):
            continue
        outcome = _get_outcome(row["ticker"], row["entry_date"], history)
        alpha = outcome.get("alpha_pct") if outcome else None
        if alpha is not None:
            alpha_values.append(alpha)

    lines.append(f"- 実現損益: {realized_pnl:+,.2f} USD")
    lines.append(
        f"- SPY alpha: {mean(alpha_values):+.1f}%" if alpha_values
        else "- SPY alpha: データなし"
    )
    lines.append("")

    lines += [
        "| Ticker | 確信度 | ステータス | リターン | SPY同期間 | Alpha |",
        "|--------|--------|-----------|---------|----------|-------|",
    ]

    active_rows = [
        r for r in portfolio
        if _date_in_range(r.get("entry_date", ""), week_start, week_end)
        or (
            r.get("status") == "open"
            and not _date_in_range(r.get("entry_date", ""), week_start, week_end)
        )
        or (
            r.get("status") == "closed"
            and _date_in_range(r.get("exit_date", ""), week_start, week_end)
        )
    ]
    seen = set()
    for row in active_rows:
        position_id = row.get("position_id", "")
        if position_id and position_id in seen:
            continue
        seen.add(position_id)

        outcome = _get_outcome(row["ticker"], row["entry_date"], history)
        conviction = outcome.get("conviction", row.get("conviction") or "?") if outcome else (row.get("conviction") or "?")
        ret = "—"
        spy = "—"
        alpha = "—"
        if row.get("status") == "closed" and row.get("exit_price"):
            try:
                ret_value = (float(row["exit_price"]) - float(row["entry_price"])) / float(row["entry_price"]) * 100
                ret = f"{ret_value:+.1f}%"
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            if outcome:
                if outcome.get("spy_return_pct") is not None:
                    spy = f"{outcome['spy_return_pct']:+.1f}%"
                if outcome.get("alpha_pct") is not None:
                    alpha = f"{outcome['alpha_pct']:+.1f}%"
        lines.append(f"| {row['ticker']} | {conviction} | {row.get('status', '')} | {ret} | {spy} | {alpha} |")

    if len(lines) == 7:
        lines.append("| — | — | — | — | — | — |")

    lines.append("")
    return lines


def _paper_summary(week_start: date, week_end: date) -> list[str]:
    paper_rows = _portfolio_rows(PAPER_PATH)
    real_rows = _portfolio_rows(PORTFOLIO_PATH)
    week_paper = [
        r for r in paper_rows
        if _date_in_range(r.get("entry_date", ""), week_start, week_end)
        or _date_in_range(r.get("exit_date", ""), week_start, week_end)
    ]

    if not week_paper and not paper_rows:
        return ["### B枠 仮説検証", "", "- B枠トレードなし", ""]

    def _closed_returns(rows: list[dict]) -> list[float]:
        values = []
        for row in rows:
            if row.get("status") != "closed" or not row.get("exit_price"):
                continue
            try:
                values.append((float(row["exit_price"]) - float(row["entry_price"])) / float(row["entry_price"]) * 100)
            except (TypeError, ValueError, ZeroDivisionError):
                continue
        return values

    paper_closed = _closed_returns(paper_rows)
    real_closed = _closed_returns(real_rows)
    lines = [
        "### B枠 仮説検証",
        "",
        f"- 週内B枠トレード数: {len(week_paper)}件",
        f"- Paper平均リターン: {mean(paper_closed):+.1f}%" if paper_closed else "- Paper平均リターン: データなし",
        f"- Paper勝率: {sum(1 for r in paper_closed if r > 0)/len(paper_closed):.0%}" if paper_closed else "- Paper勝率: データなし",
        f"- Real平均リターン: {mean(real_closed):+.1f}%" if real_closed else "- Real平均リターン: データなし",
        f"- Real勝率: {sum(1 for r in real_closed if r > 0)/len(real_closed):.0%}" if real_closed else "- Real勝率: データなし",
        "",
    ]
    return lines


def _generate(week_start: date, week_end: date) -> str:
    history = _load_history()
    decision_history = _load_decision_history()

    lines: list[str] = [
        f"## 週次レビュー ({week_start} 〜 {week_end})",
        f"生成: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    lines += _proposal_summary(decision_history, week_start, week_end)
    lines += _execution_summary(history, week_start, week_end)
    lines += _paper_summary(week_start, week_end)
    lines += ["---"]
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

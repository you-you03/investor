#!/usr/bin/env python
"""
Research Skill — data collection entry point.

This script collects raw market data and prints it as a JSON report to stdout.
Claude Code (the current session) reads this output and performs:
  - candidate screening (which tickers are worth investing)
  - per-ticker deep analysis
  - saving results to data/research_history.json

Usage:
  python skills/research.py               # collect top movers (parallel)
  python skills/research.py --sequential  # collect sequentially
  python skills/research.py --tickers NVDA,TSLA  # specific tickers
  python skills/research.py --save '{"run_id":"...","candidates":[...]}' # save Claude's analysis
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from investor.utils.portfolio_contract import closed_row_issues

app = typer.Typer(add_completion=False)
console = Console(stderr=True)  # progress messages go to stderr


def _print_calibration_stats() -> None:
    """portfolio.csv の実績を確信度別に集計して stderr に出力する。"""
    csv_path = Path(__file__).parent.parent / "data" / "portfolio.csv"
    if not csv_path.exists():
        return

    buckets: dict[str, list[float]] = {"HIGH": [], "MEDIUM": [], "LOW": []}

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") != "closed":
                continue
            issues = closed_row_issues(row)
            if issues:
                for issue in issues:
                    console.print(f"[yellow]WARN {issue}[/yellow]")
                continue
            note = row.get("note", "")
            try:
                ret_pct = (float(row["exit_price"]) - float(row["entry_price"])) / float(row["entry_price"]) * 100
            except (ValueError, ZeroDivisionError):
                continue
            # parse conviction from note (e.g. "HIGH確信", "MEDIUM確信")
            conviction = None
            for level in ("HIGH", "MEDIUM", "LOW"):
                if f"{level}確信" in note:
                    conviction = level
                    break
            if conviction:
                buckets[conviction].append(ret_pct)

    lines = []
    for level in ("HIGH", "MEDIUM", "LOW"):
        returns = buckets[level]
        if not returns:
            continue
        wins = sum(1 for r in returns if r > 0)
        avg = sum(returns) / len(returns)
        lines.append(f"  {level}: 勝率 {wins}/{len(returns)} ({wins/len(returns)*100:.0f}%), 平均リターン {avg:+.1f}%")

    if lines:
        console.print("[bold cyan]## 過去実績（校正データ — スコアリング時に参照）[/bold cyan]")
        for line in lines:
            console.print(f"[cyan]{line}[/cyan]")
        console.print("[cyan]  → 上記実績を踏まえてスコアリング・確信度判定を行うこと[/cyan]")
        console.print("")


def _print_feedback_stats() -> None:
    """portfolio.csv と trade_journal.json からフィードバック統計を集計して stderr に出力する。"""
    from datetime import datetime
    import json as _json

    csv_path = Path(__file__).parent.parent / "data" / "portfolio.csv"
    journal_path = Path(__file__).parent.parent / "data" / "trade_journal.json"
    if not csv_path.exists():
        return

    signal_returns: dict[str, list[float]] = {}
    hold_buckets: dict[str, list[float]] = {
        "1-3d": [], "4-7d": [], "8-14d": [], "15d+": []
    }
    mfe_captures: list[float] = []
    all_returns: list[float] = []

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") != "closed":
                continue
            issues = closed_row_issues(row)
            if issues:
                for issue in issues:
                    console.print(f"[yellow]WARN {issue}[/yellow]")
                continue
            try:
                ret_pct = (float(row["exit_price"]) - float(row["entry_price"])) / float(row["entry_price"]) * 100
            except (ValueError, ZeroDivisionError):
                continue
            all_returns.append(ret_pct)
            sig = row.get("signal_type", "")
            if sig:
                signal_returns.setdefault(sig, []).append(ret_pct)
            try:
                entry_dt = datetime.strptime(row["entry_date"], "%Y-%m-%d")
                exit_dt = datetime.strptime(row["exit_date"], "%Y-%m-%d")
                days = (exit_dt - entry_dt).days
                bucket = "1-3d" if days <= 3 else "4-7d" if days <= 7 else "8-14d" if days <= 14 else "15d+"
                hold_buckets[bucket].append(ret_pct)
            except (ValueError, KeyError):
                pass

    if not all_returns:
        return

    lines = []
    all_ev = sum(all_returns) / len(all_returns)
    recent = all_returns[-10:]
    recent_ev = sum(recent) / len(recent)
    warn = " ⚠️ エッジ減衰の兆候" if len(recent) >= 5 and all_ev > 0 and recent_ev < all_ev * 0.5 else ""
    lines.append(f"  全期間EV: {all_ev:+.1f}% (n={len(all_returns)}) | 直近10: {recent_ev:+.1f}%{warn}")

    if signal_returns:
        lines.append("  [シグナル別EV]")
        for sig, rets in sorted(signal_returns.items(), key=lambda x: -(sum(x[1]) / len(x[1]))):
            lines.append(f"    {sig}: EV {sum(rets)/len(rets):+.1f}% (n={len(rets)})")

    hold_lines = [(b, r) for b, r in hold_buckets.items() if r]
    if hold_lines:
        lines.append("  [保有日数別EV]")
        for bucket, rets in hold_lines:
            lines.append(f"    {bucket}: EV {sum(rets)/len(rets):+.1f}% (n={len(rets)})")

    if mfe_captures:
        lines.append(f"  MFE捕捉率平均: {sum(mfe_captures)/len(mfe_captures):.0f}% (n={len(mfe_captures)})")

    if journal_path.exists():
        try:
            journal = _json.loads(journal_path.read_text())
            for entry in journal:
                mfe_cap = entry.get("mfe_capture_pct")
                if mfe_cap not in ("", None):
                    try:
                        mfe_captures.append(float(mfe_cap))
                    except (TypeError, ValueError):
                        pass
            score3 = [e["pnl_pct"] for e in journal if e.get("rule_adherence_score") == 3]
            score1 = [e["pnl_pct"] for e in journal if e.get("rule_adherence_score") == 1]
            if score3:
                lines.append(f"  ルール完全遵守(score=3): EV {sum(score3)/len(score3):+.1f}% (n={len(score3)})")
            if score1:
                lines.append(f"  ルール逸脱(score=1):     EV {sum(score1)/len(score1):+.1f}% (n={len(score1)})")
            lucky = [e for e in journal if e.get("decision_quality", 3) == 1 and e.get("outcome_quality", 1) >= 2]
            if lucky:
                lines.append(f"  ⚠️ ラッキートレード（悪い判断・良い結果）: {len(lucky)}件 — 過信注意")
        except (_json.JSONDecodeError, KeyError):
            pass

    if lines:
        console.print("[bold magenta]## フィードバックループ統計[/bold magenta]")
        for line in lines:
            console.print(f"[magenta]{line}[/magenta]")
        console.print("")


@app.command()
def main(
    parallel: bool = typer.Option(True, "--parallel/--sequential"),
    tickers: str = typer.Option("", "--tickers", help="Comma-separated tickers"),
    save: str = typer.Option("", "--save", help="JSON string from Claude to save as a research run"),
    max_tickers: int = typer.Option(15, "--max-tickers", help="Max tickers to collect data for"),
) -> None:
    """
    Collect market data and print JSON report to stdout for Claude to analyze.
    Or save Claude's analysis with --save.
    """
    from investor.agents.research_agent import collect_market_data, save_run

    # --save mode: persist Claude's analysis result
    if save.strip():
        try:
            data = json.loads(save)
            run_id = data.get("run_id")
            candidates = data.get("candidates", [])
            if not run_id:
                console.print("[red]--save JSON must include 'run_id'[/red]")
                raise typer.Exit(1)
            save_run(run_id, candidates)
            console.print(f"[green]Saved {len(candidates)} candidates | run_id: {run_id}[/green]")
            print(run_id)  # stdout for caller
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON: {e}[/red]")
            raise typer.Exit(1)
        return

    # Data collection mode
    _print_calibration_stats()
    _print_feedback_stats()

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None

    if ticker_list:
        console.print(f"[cyan]Collecting data for: {ticker_list}[/cyan]")
    else:
        console.print(f"[cyan]Collecting top market movers (max {max_tickers} tickers)...[/cyan]")

    data = collect_market_data(
        tickers=ticker_list,
        max_tickers=max_tickers,
        parallel=parallel,
    )

    # Print collected data as JSON to stdout for Claude to read
    print(json.dumps(data, indent=2, default=str))
    console.print(f"[green]Data collection complete | run_id: {data['run_id']}[/green]")
    console.print("[yellow]→ Claude: analyze the JSON above, select top 3-5 candidates, then call:[/yellow]")
    console.print(f'[yellow]  python skills/research.py --save \'{{\"run_id\":\"{data["run_id"]}\",\"candidates\":[...]}}\' [/yellow]')


if __name__ == "__main__":
    app()

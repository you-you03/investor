#!/usr/bin/env python
"""
Paper Portfolio (B枠) — virtual position tracking for hypothesis validation.

Logs decisions made by /decision --paper without real execution or Slack.
Enables side-by-side comparison with the real (A枠) portfolio.

Usage:
  python skills/paper_portfolio.py list
  python skills/paper_portfolio.py add --ticker NVDA --shares 10 --price 875.00 --conviction HIGH
  python skills/paper_portfolio.py close --ticker NVDA --price 950.00
  python skills/paper_portfolio.py snapshot
  python skills/paper_portfolio.py compare   # compare paper vs real returns
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table
from investor.utils.portfolio_contract import (
    build_position_id,
    read_portfolio_rows,
    write_portfolio_rows,
)

app = typer.Typer(add_completion=False)
console = Console()

PAPER_PATH = Path("data/paper_portfolio.csv")
REAL_PATH = Path("data/portfolio.csv")
DECISION_HISTORY_PATH = Path("data/decision_history.json")


def _load_decision_history() -> list[dict]:
    if not DECISION_HISTORY_PATH.exists():
        return []
    try:
        import json

        return json.loads(DECISION_HISTORY_PATH.read_text())
    except Exception:
        return []


def _find_proposal_date(ticker: str, entry_date: str, decision_history: list[dict]) -> str | None:
    try:
        entry_dt = date.fromisoformat(entry_date)
    except ValueError:
        return None

    candidates: list[date] = []
    for decision in decision_history:
        raw_date = decision.get("date")
        if not raw_date:
            continue
        try:
            decision_dt = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if decision_dt > entry_dt:
            continue

        proposal_records = decision.get("proposal_records") or []
        if proposal_records:
            for proposal in proposal_records:
                if proposal.get("action") == "BUY" and proposal.get("ticker", "").upper() == ticker.upper():
                    candidates.append(decision_dt)
        elif ticker.upper() in {t.upper() for t in decision.get("buy_decisions", [])}:
            candidates.append(decision_dt)

    if not candidates:
        return None
    return max(candidates).isoformat()


@app.command()
def list() -> None:
    """Show all open paper positions."""
    rows = read_portfolio_rows(PAPER_PATH)
    open_rows = [r for r in rows if r.get("status") == "open"]

    if not open_rows:
        console.print("[yellow]No open paper positions (B枠).[/yellow]")
        return

    table = Table(title="Paper Portfolio — B枠 (Virtual)")
    for col in ["ticker", "shares", "entry_price", "entry_date", "target_price", "stop_loss", "hypothesis_id", "note"]:
        table.add_column(col)
    for r in open_rows:
        table.add_row(*[str(r.get(c, "")) for c in ["ticker", "shares", "entry_price", "entry_date", "target_price", "stop_loss", "hypothesis_id", "note"]])
    console.print(table)


@app.command()
def add(
    ticker: str = typer.Option(..., "--ticker"),
    shares: float = typer.Option(..., "--shares"),
    price: float = typer.Option(..., "--price"),
    target: float = typer.Option(0.0, "--target"),
    stop: float = typer.Option(0.0, "--stop"),
    conviction: str = typer.Option("MEDIUM", "--conviction"),
    signal: str = typer.Option("", "--signal"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Record a virtual paper trade entry."""
    rows = read_portfolio_rows(PAPER_PATH)
    rows.append({
        "position_id": build_position_id(rows),
        "ticker": ticker.upper(),
        "shares": shares,
        "entry_price": price,
        "entry_date": date.today().isoformat(),
        "proposal_date": date.today().isoformat(),
        "exit_price": "",
        "exit_date": "",
        "status": "open",
        "target_price": target or "",
        "stop_loss": stop or "",
        "note": note or f"[B枠] {conviction}確信",
        "signal_type": signal,
        "conviction": conviction.upper(),
        "hypothesis_id": "",
        "exit_stage": "0",
        "mae_pct": "",
        "mfe_pct": "",
        "mfe_capture_pct": "",
        "rule_adherence_score": "",
    })
    write_portfolio_rows(PAPER_PATH, rows)
    console.print(f"[green][B枠] Added {ticker.upper()} {shares}shares @ ${price}[/green]")


@app.command()
def close(
    ticker: str = typer.Option(..., "--ticker"),
    price: float = typer.Option(..., "--price"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Record a virtual paper trade exit."""
    rows = read_portfolio_rows(PAPER_PATH)
    closed = False
    for r in rows:
        if r.get("ticker", "").upper() == ticker.upper() and r.get("status") == "open":
            entry = float(r["entry_price"])
            pnl = (price - entry) / entry * 100
            r["exit_price"] = price
            r["exit_date"] = date.today().isoformat()
            r["status"] = "closed"
            r["note"] = (r.get("note", "") + f" | [B枠] EXIT {pnl:+.1f}%").strip(" |")
            if note:
                r["note"] += f" {note}"
            closed = True
            console.print(f"[green][B枠] Closed {ticker.upper()} @ ${price} ({pnl:+.1f}%)[/green]")
            break
    if not closed:
        console.print(f"[red]No open paper position found for {ticker.upper()}[/red]")
        raise typer.Exit(1)
    write_portfolio_rows(PAPER_PATH, rows)


@app.command()
def snapshot() -> None:
    """Show current prices vs paper entry prices via yfinance."""
    rows = read_portfolio_rows(PAPER_PATH)
    open_rows = [r for r in rows if r.get("status") == "open"]
    if not open_rows:
        console.print("[yellow]No open paper positions.[/yellow]")
        return

    try:
        import yfinance as yf
    except ImportError:
        console.print("[red]yfinance not installed.[/red]")
        raise typer.Exit(1)

    table = Table(title="Paper Portfolio Snapshot (B枠)")
    table.add_column("Ticker")
    table.add_column("Shares")
    table.add_column("Entry")
    table.add_column("Current")
    table.add_column("P&L %")
    table.add_column("Stop")
    table.add_column("Target")

    for r in open_rows:
        ticker = r["ticker"]
        try:
            current = yf.Ticker(ticker).fast_info.last_price
            entry = float(r["entry_price"])
            pnl = (current - entry) / entry * 100
            color = "green" if pnl >= 0 else "red"
            table.add_row(
                ticker,
                r["shares"],
                f"${entry:.2f}",
                f"${current:.2f}",
                f"[{color}]{pnl:+.1f}%[/{color}]",
                r.get("stop_loss", ""),
                r.get("target_price", ""),
            )
        except Exception:
            table.add_row(ticker, r["shares"], r["entry_price"], "N/A", "N/A", "", "")

    console.print(table)


@app.command()
def compare() -> None:
    """Compare closed paper (B枠) vs real (A枠) trade returns and execution behavior."""
    from datetime import datetime

    from scripts.record_outcomes import _get_spy_return

    paper_rows = read_portfolio_rows(PAPER_PATH)
    real_rows = read_portfolio_rows(REAL_PATH)
    decision_history = _load_decision_history()

    def _closed_stats(rows):
        results = []
        for r in rows:
            if r.get("status") == "closed" and r.get("entry_price") and r.get("exit_price"):
                try:
                    entry = float(r["entry_price"])
                    exit_price = float(r["exit_price"])
                    ret = (exit_price - entry) / entry * 100
                    alpha = _get_spy_return(r["entry_date"], r["exit_date"])
                    hold_days = None
                    if r.get("entry_date") and r.get("exit_date"):
                        hold_days = (
                            datetime.fromisoformat(r["exit_date"]).date()
                            - datetime.fromisoformat(r["entry_date"]).date()
                        ).days
                    proposal_gap = None
                    proposal_date = r.get("proposal_date") or _find_proposal_date(
                        r.get("ticker", ""),
                        r.get("entry_date", ""),
                        decision_history,
                    )
                    if proposal_date and r.get("entry_date"):
                        proposal_gap = (
                            datetime.fromisoformat(r["entry_date"]).date()
                            - datetime.fromisoformat(proposal_date).date()
                        ).days
                    results.append({
                        "return_pct": ret,
                        "alpha_pct": alpha,
                        "hold_days": hold_days,
                        "proposal_gap_days": proposal_gap,
                    })
                except (ValueError, ZeroDivisionError):
                    pass
        return results

    def _print_side(label: str, stats: list[dict]) -> None:
        console.print(f"\n  {label} trades closed: {len(stats)}")
        if not stats:
            return
        returns = [s["return_pct"] for s in stats]
        alphas = [s["alpha_pct"] for s in stats if s["alpha_pct"] is not None]
        hold_days = [s["hold_days"] for s in stats if s["hold_days"] is not None]
        gaps = [s["proposal_gap_days"] for s in stats if s["proposal_gap_days"] is not None]
        console.print(f"  {label} avg return:   {sum(returns)/len(returns):+.1f}%")
        console.print(f"  {label} win rate:     {sum(1 for r in returns if r > 0)/len(returns):.0%}")
        console.print(
            f"  {label} avg alpha:    {sum(alphas)/len(alphas):+.1f}%" if alphas
            else f"  {label} avg alpha:    N/A"
        )
        console.print(
            f"  {label} avg hold:     {sum(hold_days)/len(hold_days):.1f}d" if hold_days
            else f"  {label} avg hold:     N/A"
        )
        console.print(
            f"  {label} proposal gap: {sum(gaps)/len(gaps):.1f}d" if gaps
            else f"  {label} proposal gap: N/A"
        )

    console.print("\n[bold]B枠 (Paper) vs A枠 (Real) comparison[/bold]")
    _print_side("Paper", _closed_stats(paper_rows))
    _print_side("Real", _closed_stats(real_rows))


if __name__ == "__main__":
    app()

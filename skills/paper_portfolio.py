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

import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False)
console = Console()

PAPER_PATH = Path("data/paper_portfolio.csv")
REAL_PATH = Path("data/portfolio.csv")
FIELDNAMES = [
    "ticker", "shares", "entry_price", "entry_date",
    "exit_price", "exit_date", "status",
    "target_price", "stop_loss", "note",
    "signal_type", "exit_stage", "mae_pct", "mfe_pct",
]


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return [row for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


@app.command()
def list() -> None:
    """Show all open paper positions."""
    rows = _read_csv(PAPER_PATH)
    open_rows = [r for r in rows if r.get("status") == "open"]

    if not open_rows:
        console.print("[yellow]No open paper positions (B枠).[/yellow]")
        return

    table = Table(title="Paper Portfolio — B枠 (Virtual)")
    for col in ["ticker", "shares", "entry_price", "entry_date", "target_price", "stop_loss", "note"]:
        table.add_column(col)
    for r in open_rows:
        table.add_row(*[str(r.get(c, "")) for c in ["ticker", "shares", "entry_price", "entry_date", "target_price", "stop_loss", "note"]])
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
    rows = _read_csv(PAPER_PATH)
    rows.append({
        "ticker": ticker.upper(),
        "shares": shares,
        "entry_price": price,
        "entry_date": date.today().isoformat(),
        "exit_price": "",
        "exit_date": "",
        "status": "open",
        "target_price": target or "",
        "stop_loss": stop or "",
        "note": note or f"[B枠] {conviction}確信",
        "signal_type": signal,
        "exit_stage": "0",
        "mae_pct": "",
        "mfe_pct": "",
    })
    _write_csv(PAPER_PATH, rows)
    console.print(f"[green][B枠] Added {ticker.upper()} {shares}shares @ ${price}[/green]")


@app.command()
def close(
    ticker: str = typer.Option(..., "--ticker"),
    price: float = typer.Option(..., "--price"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Record a virtual paper trade exit."""
    rows = _read_csv(PAPER_PATH)
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
    _write_csv(PAPER_PATH, rows)


@app.command()
def snapshot() -> None:
    """Show current prices vs paper entry prices via yfinance."""
    rows = _read_csv(PAPER_PATH)
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
    """Compare closed paper (B枠) vs real (A枠) trade returns."""
    paper_rows = _read_csv(PAPER_PATH)
    real_rows = _read_csv(REAL_PATH)

    def _returns(rows):
        results = []
        for r in rows:
            if r.get("status") == "closed" and r.get("entry_price") and r.get("exit_price"):
                try:
                    ret = (float(r["exit_price"]) - float(r["entry_price"])) / float(r["entry_price"]) * 100
                    results.append(ret)
                except (ValueError, ZeroDivisionError):
                    pass
        return results

    paper_rets = _returns(paper_rows)
    real_rets = _returns(real_rows)

    console.print("\n[bold]B枠 (Paper) vs A枠 (Real) comparison[/bold]")
    console.print(f"  Paper trades closed: {len(paper_rets)}")
    if paper_rets:
        console.print(f"  Paper avg return:  {sum(paper_rets)/len(paper_rets):+.1f}%")
        console.print(f"  Paper win rate:    {sum(1 for r in paper_rets if r > 0)/len(paper_rets):.0%}")

    console.print(f"\n  Real trades closed: {len(real_rets)}")
    if real_rets:
        console.print(f"  Real avg return:   {sum(real_rets)/len(real_rets):+.1f}%")
        console.print(f"  Real win rate:     {sum(1 for r in real_rets if r > 0)/len(real_rets):.0%}")


if __name__ == "__main__":
    app()

#!/usr/bin/env python
"""
Portfolio Skill — entry point for /portfolio slash command.

Usage:
  python skills/portfolio.py list
  python skills/portfolio.py add --ticker NVDA --shares 10 --price 875.00
  python skills/portfolio.py close --ticker NVDA --price 950.00
  python skills/portfolio.py snapshot
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

PORTFOLIO_PATH = Path("data/portfolio.csv")
FIELDNAMES = ["ticker", "shares", "entry_price", "entry_date", "exit_price", "exit_date", "status", "target_price", "stop_loss", "note"]


def _read_portfolio() -> list[dict]:
    if not PORTFOLIO_PATH.exists():
        return []
    with open(PORTFOLIO_PATH) as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def _write_portfolio(rows: list[dict]) -> None:
    PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PORTFOLIO_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


@app.command()
def list() -> None:
    """Show all open positions."""
    rows = _read_portfolio()
    open_rows = [r for r in rows if r.get("status") == "open"]

    if not open_rows:
        console.print("[yellow]No open positions.[/yellow]")
        return

    table = Table(title="Open Positions")
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
    target: Optional[float] = typer.Option(None, "--target"),
    stop: Optional[float] = typer.Option(None, "--stop"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Add a new position to portfolio.csv."""
    rows = _read_portfolio()
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
        "note": note,
    })
    _write_portfolio(rows)
    console.print(f"[green]Added {shares} shares of {ticker.upper()} @ ${price}[/green]")


@app.command()
def close(
    ticker: str = typer.Option(..., "--ticker"),
    price: float = typer.Option(..., "--price"),
) -> None:
    """Close an open position."""
    rows = _read_portfolio()
    closed = False
    for row in rows:
        if row["ticker"].upper() == ticker.upper() and row["status"] == "open":
            row["exit_price"] = price
            row["exit_date"] = date.today().isoformat()
            row["status"] = "closed"
            entry = float(row["entry_price"])
            shares = float(row["shares"])
            pnl = (price - entry) * shares
            pnl_pct = (price - entry) / entry * 100
            console.print(f"[green]Closed {ticker.upper()} @ ${price} | P&L: {'+' if pnl >= 0 else ''}${pnl:,.0f} ({pnl_pct:+.1f}%)[/green]")
            closed = True
            break
    if not closed:
        console.print(f"[red]No open position found for {ticker.upper()}[/red]")
        return
    _write_portfolio(rows)


@app.command()
def snapshot() -> None:
    """Show portfolio P&L snapshot using current yfinance prices."""
    rows = _read_portfolio()
    open_rows = [r for r in rows if r.get("status") == "open"]
    if not open_rows:
        console.print("[yellow]No open positions.[/yellow]")
        return

    from investor.data.yfinance_client import YFinanceClient
    yf_client = YFinanceClient()

    table = Table(title=f"Portfolio Snapshot — {date.today().isoformat()}")
    for col in ["Ticker", "Shares", "Entry", "Current", "Change%", "P&L", "Target", "Stop"]:
        table.add_column(col)

    total_pnl = 0.0
    for r in open_rows:
        ticker = r["ticker"].upper()
        snap = yf_client.get_stock_snapshot(ticker)
        current = snap["price"] if snap and snap.get("price") else None
        entry = float(r["entry_price"])
        shares = float(r["shares"])
        if current:
            pnl = (current - entry) * shares
            pnl_pct = (current - entry) / entry * 100
            total_pnl += pnl
            table.add_row(
                ticker,
                str(r["shares"]),
                f"${entry:,.2f}",
                f"${current:,.2f}",
                f"{pnl_pct:+.1f}%",
                f"{'+' if pnl >= 0 else ''}${pnl:,.0f}",
                f"${float(r['target_price']):,.2f}" if r.get("target_price") else "—",
                f"${float(r['stop_loss']):,.2f}" if r.get("stop_loss") else "—",
            )
        else:
            table.add_row(ticker, str(r["shares"]), f"${entry:,.2f}", "N/A", "—", "—",
                         r.get("target_price", "—"), r.get("stop_loss", "—"))

    console.print(table)
    console.print(f"[bold]Total P&L: {'+' if total_pnl >= 0 else ''}${total_pnl:,.0f}[/bold]")


if __name__ == "__main__":
    app()

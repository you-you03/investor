#!/usr/bin/env python
"""
Portfolio Skill — entry point for /portfolio slash command.

Usage:
  python skills/portfolio.py list
  python skills/portfolio.py add --ticker NVDA --shares 10 --price 875.00
  python skills/portfolio.py close --ticker NVDA --price 950.00
  python skills/portfolio.py snapshot
"""

import sys
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table
from investor.config import settings
from investor.utils.portfolio_contract import (
    build_position_id,
    read_portfolio_rows,
    write_portfolio_rows,
)

app = typer.Typer(add_completion=False)
console = Console()

PORTFOLIO_PATH = Path(settings.default_portfolio_path)
PORTFOLIO_100MAN_PATH = Path(settings.legacy_portfolio_path)


def _resolve_portfolio_path(portfolio: str) -> Path:
    key = portfolio.lower().strip()
    if key in {"default", "20man", "20", "small"}:
        return PORTFOLIO_PATH
    if key in {"100man", "100", "legacy", "main"}:
        return PORTFOLIO_100MAN_PATH
    return Path(portfolio)


@app.command()
def list(portfolio: str = typer.Option("default", "--portfolio", help="default/20man or 100man")) -> None:
    """Show all open positions."""
    path = _resolve_portfolio_path(portfolio)
    rows = read_portfolio_rows(path)
    open_rows = [r for r in rows if r.get("status") == "open"]

    if not open_rows:
        console.print(f"[yellow]No open positions in {path}.[/yellow]")
        return

    table = Table(title=f"Open Positions — {path}")
    for col in ["position_id", "ticker", "shares", "entry_price", "entry_date", "target_price", "stop_loss", "signal_type", "note"]:
        table.add_column(col)
    for r in open_rows:
        table.add_row(*[str(r.get(c, "")) for c in ["position_id", "ticker", "shares", "entry_price", "entry_date", "target_price", "stop_loss", "signal_type", "note"]])
    console.print(table)


@app.command()
def add(
    ticker: str = typer.Option(..., "--ticker"),
    shares: float = typer.Option(..., "--shares"),
    price: float = typer.Option(..., "--price"),
    target: Optional[float] = typer.Option(None, "--target"),
    stop: Optional[float] = typer.Option(None, "--stop"),
    note: str = typer.Option("", "--note"),
    signal: str = typer.Option("", "--signal"),
    conviction: str = typer.Option("", "--conviction"),
    proposal_date: Optional[str] = typer.Option(None, "--proposal-date"),
    portfolio: str = typer.Option("default", "--portfolio", help="default/20man or 100man"),
) -> None:
    """Add a new position to portfolio.csv."""
    path = _resolve_portfolio_path(portfolio)
    rows = read_portfolio_rows(path)
    rows.append({
        "position_id": build_position_id(rows),
        "ticker": ticker.upper(),
        "shares": shares,
        "entry_price": price,
        "entry_date": date.today().isoformat(),
        "proposal_date": proposal_date or date.today().isoformat(),
        "exit_price": "",
        "exit_date": "",
        "status": "open",
        "target_price": target or "",
        "stop_loss": stop or "",
        "note": note,
        "signal_type": signal,
        "conviction": conviction.upper(),
    })
    write_portfolio_rows(path, rows)
    console.print(f"[green]Added {shares} shares of {ticker.upper()} @ ${price} to {path}[/green]")


@app.command()
def close(
    ticker: str = typer.Option(..., "--ticker"),
    price: float = typer.Option(..., "--price"),
    portfolio: str = typer.Option("default", "--portfolio", help="default/20man or 100man"),
) -> None:
    """Close an open position."""
    path = _resolve_portfolio_path(portfolio)
    rows = read_portfolio_rows(path)
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
    write_portfolio_rows(path, rows)


@app.command()
def snapshot(portfolio: str = typer.Option("default", "--portfolio", help="default/20man or 100man")) -> None:
    """Show portfolio P&L snapshot using current yfinance prices."""
    path = _resolve_portfolio_path(portfolio)
    rows = read_portfolio_rows(path)
    open_rows = [r for r in rows if r.get("status") == "open"]
    if not open_rows:
        console.print(f"[yellow]No open positions in {path}.[/yellow]")
        return

    from investor.data.yfinance_client import YFinanceClient
    yf_client = YFinanceClient()

    table = Table(title=f"Portfolio Snapshot — {path} — {date.today().isoformat()}")
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

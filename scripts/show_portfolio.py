#!/usr/bin/env python
"""
Display current portfolio: open positions, watchlist, and recent proposals.

Usage:
  python scripts/show_portfolio.py
  python scripts/show_portfolio.py --history     # include closed positions
  python scripts/show_portfolio.py --watchlist   # show watchlist
  python scripts/show_portfolio.py --proposals   # show recent proposals
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from investor.clients.polygon_client import PolygonClient
from investor.db.database import create_db, get_session
from investor.db.models import InvestmentProposal, Position, WatchlistItem

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    history: bool = typer.Option(False, "--history", help="Include closed positions"),
    watchlist: bool = typer.Option(False, "--watchlist", help="Show watchlist"),
    proposals: bool = typer.Option(False, "--proposals", help="Show recent proposals"),
    live_prices: bool = typer.Option(False, "--live", help="Fetch current prices (uses API calls)"),
) -> None:
    """Show portfolio summary."""
    create_db()

    _show_positions(history=history, live_prices=live_prices)

    if watchlist:
        _show_watchlist()

    if proposals:
        _show_proposals()


def _show_positions(history: bool, live_prices: bool) -> None:
    with get_session() as session:
        query = select(Position)
        if not history:
            query = query.where(Position.status == "open")
        positions = session.exec(query.order_by(Position.entry_date.desc())).all()

    if not positions:
        console.print("[yellow]No positions found.[/yellow]")
        return

    polygon = PolygonClient() if live_prices else None
    current_prices: dict[str, float] = {}
    if live_prices:
        for p in positions:
            if p.status == "open":
                snap = polygon.get_stock_snapshot(p.ticker)
                if snap:
                    current_prices[p.ticker] = snap["price"]

    table = Table(title="Positions", show_lines=True)
    table.add_column("Ticker", style="bold")
    table.add_column("Shares", justify="right")
    table.add_column("Entry $", justify="right")
    table.add_column("Current $", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("P&L %", justify="right")
    table.add_column("Target $", justify="right")
    table.add_column("Stop $", justify="right")
    table.add_column("Status")

    total_pnl = 0.0
    for p in positions:
        if p.status == "open":
            current = current_prices.get(p.ticker, p.entry_price)
            note = "_(delayed)_" if live_prices else "_(no fetch)_"
        else:
            current = p.exit_price or p.entry_price
            note = ""

        pnl = (current - p.entry_price) * p.shares
        pnl_pct = (current - p.entry_price) / p.entry_price * 100 if p.entry_price else 0
        if p.status == "open":
            total_pnl += pnl

        sign = "+" if pnl >= 0 else ""
        pnl_color = "green" if pnl >= 0 else "red"
        status_color = "green" if p.status == "open" else "dim"

        table.add_row(
            p.ticker,
            f"{p.shares:.2f}",
            f"${p.entry_price:,.2f}",
            f"${current:,.2f}" if (live_prices or p.status == "closed") else "—",
            f"[{pnl_color}]{sign}${pnl:,.0f}[/{pnl_color}]" if (live_prices or p.status == "closed") else "—",
            f"[{pnl_color}]{sign}{pnl_pct:.1f}%[/{pnl_color}]" if (live_prices or p.status == "closed") else "—",
            f"${p.target_price:,.2f}" if p.target_price else "—",
            f"${p.stop_loss:,.2f}" if p.stop_loss else "—",
            f"[{status_color}]{p.status}[/{status_color}]",
        )

    console.print(table)
    if live_prices:
        console.print(f"[dim]Total unrealized P&L: {'+'if total_pnl >= 0 else ''}${total_pnl:,.0f} (15-min delay)[/dim]")


def _show_watchlist() -> None:
    with get_session() as session:
        items = session.exec(
            select(WatchlistItem)
            .where(WatchlistItem.status == "active")
            .order_by(WatchlistItem.added_at.desc())
        ).all()

    if not items:
        console.print("[yellow]Watchlist is empty.[/yellow]")
        return

    table = Table(title="Watchlist (active)", show_lines=True)
    table.add_column("Ticker", style="bold")
    table.add_column("Added")
    table.add_column("Reason")

    for item in items:
        table.add_row(
            item.ticker,
            item.added_at.strftime("%Y-%m-%d"),
            item.reason or "—",
        )
    console.print(table)


def _show_proposals() -> None:
    with get_session() as session:
        proposals = session.exec(
            select(InvestmentProposal)
            .order_by(InvestmentProposal.created_at.desc())
            .limit(10)
        ).all()

    if not proposals:
        console.print("[yellow]No proposals found.[/yellow]")
        return

    table = Table(title="Recent Proposals (last 10)", show_lines=True)
    table.add_column("Date")
    table.add_column("Ticker", style="bold")
    table.add_column("Action")
    table.add_column("Conviction")
    table.add_column("Target $", justify="right")
    table.add_column("Stop $", justify="right")
    table.add_column("Decision")

    for p in proposals:
        action_color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(p.action, "white")
        decision_color = {"approved": "green", "rejected": "red", "pending": "yellow"}.get(
            p.human_decision, "white"
        )
        table.add_row(
            p.created_at.strftime("%m-%d"),
            p.ticker,
            f"[{action_color}]{p.action}[/{action_color}]",
            p.conviction,
            f"${p.target_price:,.2f}" if p.target_price else "—",
            f"${p.stop_loss:,.2f}" if p.stop_loss else "—",
            f"[{decision_color}]{p.human_decision}[/{decision_color}]",
        )
    console.print(table)


if __name__ == "__main__":
    app()

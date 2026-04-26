#!/usr/bin/env python
"""
Record a new stock purchase as an open position.

Usage:
  python scripts/add_position.py NVDA 3 875.00
  python scripts/add_position.py NVDA 3 875.00 --target 1000 --stop 820 --note "GTC catalyst play"
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console

from investor.db.database import create_db, get_session
from investor.db.models import Position, WatchlistItem
from sqlmodel import select

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    ticker: str = typer.Argument(..., help="Stock ticker symbol"),
    shares: float = typer.Argument(..., help="Number of shares purchased"),
    price: float = typer.Argument(..., help="Purchase price per share"),
    target: float = typer.Option(None, "--target", help="Target price for taking profits"),
    stop: float = typer.Option(None, "--stop", help="Stop-loss price"),
    note: str = typer.Option(None, "--note", help="Optional note"),
) -> None:
    """Record a new position after manually executing a trade."""
    create_db()
    ticker = ticker.upper()

    with get_session() as session:
        position = Position(
            ticker=ticker,
            shares=shares,
            entry_price=price,
            entry_date=date.today(),
            target_price=target,
            stop_loss=stop,
            status="open",
            note=note,
        )
        session.add(position)

        # Update watchlist status if present
        watchlist_item = session.exec(
            select(WatchlistItem).where(
                WatchlistItem.ticker == ticker,
                WatchlistItem.status == "active",
            )
        ).first()
        if watchlist_item:
            watchlist_item.status = "converted"

        session.commit()
        session.refresh(position)

    total = shares * price
    console.print(f"[green]Position added:[/green] {shares} × {ticker} @ ${price:,.2f} = ${total:,.2f}")
    if target:
        console.print(f"  Target: ${target:,.2f}")
    if stop:
        console.print(f"  Stop loss: ${stop:,.2f}")


if __name__ == "__main__":
    app()

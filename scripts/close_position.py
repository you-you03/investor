#!/usr/bin/env python
"""
Record a stock sale, closing an open position.

Usage:
  python scripts/close_position.py NVDA 920.00
  python scripts/close_position.py NVDA 920.00 --note "Target reached"
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from sqlmodel import select

from investor.db.database import create_db, get_session
from investor.db.models import InvestmentProposal, Position, ProposalResult

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    ticker: str = typer.Argument(..., help="Stock ticker symbol"),
    exit_price: float = typer.Argument(..., help="Sale price per share"),
    note: str = typer.Option(None, "--note", help="Optional note"),
) -> None:
    """Record the sale of an open position."""
    create_db()
    ticker = ticker.upper()

    with get_session() as session:
        position = session.exec(
            select(Position).where(
                Position.ticker == ticker,
                Position.status == "open",
            )
        ).first()

        if position is None:
            console.print(f"[red]No open position found for {ticker}[/red]")
            raise typer.Exit(code=1)

        position.exit_price = exit_price
        position.exit_date = date.today()
        position.status = "closed"
        if note:
            position.note = (position.note or "") + f" | Exit: {note}"

        session.commit()
        session.refresh(position)

    pnl = (exit_price - position.entry_price) * position.shares
    pnl_pct = (exit_price - position.entry_price) / position.entry_price * 100
    sign = "+" if pnl >= 0 else ""
    color = "green" if pnl >= 0 else "red"

    console.print(f"[{color}]Position closed:[/{color}] {position.shares} × {ticker}")
    console.print(f"  Entry: ${position.entry_price:,.2f} → Exit: ${exit_price:,.2f}")
    console.print(f"  P&L: [{color}]{sign}${pnl:,.2f} ({sign}{pnl_pct:.1f}%)[/{color}]")

    # Write ProposalResult for the Reflection loop
    with get_session() as session:
        proposal = session.exec(
            select(InvestmentProposal)
            .where(
                InvestmentProposal.ticker == ticker,
                InvestmentProposal.action == "BUY",
            )
            .order_by(InvestmentProposal.created_at.desc())
        ).first()

        if proposal is not None:
            if pnl_pct > 0:
                outcome = "win"
            elif pnl_pct < 0:
                outcome = "loss"
            else:
                outcome = "neutral"

            result = ProposalResult(
                proposal_id=proposal.id,
                ticker=ticker,
                entry_price=position.entry_price,
                exit_price=exit_price,
                exit_date=date.today(),
                actual_return_pct=round(pnl_pct, 4),
                outcome=outcome,
                notes=note,
            )
            session.add(result)
            session.commit()
            console.print(f"  [dim]ProposalResult recorded: {outcome} ({sign}{pnl_pct:.1f}%)[/dim]")
        else:
            console.print(f"  [dim]No matching InvestmentProposal found for {ticker} — ProposalResult skipped[/dim]")


if __name__ == "__main__":
    app()

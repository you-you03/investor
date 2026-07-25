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
from investor.core.risk import calculate_position_plan, portfolio_guard_violations
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
    columns = [
        "position_id", "ticker", "shares", "entry_price", "entry_date",
        "target_price", "stop_loss", "planned_risk_usd", "strategy_version",
        "signal_type", "note",
    ]
    for col in columns:
        table.add_column(col)
    for r in open_rows:
        table.add_row(*[str(r.get(c, "")) for c in columns])
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
    """Add an executed position after deterministic risk validation."""
    path = _resolve_portfolio_path(portfolio)
    rows = read_portfolio_rows(path)
    open_rows = [row for row in rows if row.get("status") == "open"]

    if target is None or stop is None:
        raise typer.BadParameter("--target and --stop are required for every new position")
    if not (0 < stop < price < target):
        raise typer.BadParameter("required price relationship: 0 < stop < price < target")

    if path == PORTFOLIO_PATH:
        guard_issues = portfolio_guard_violations(open_rows)
        if guard_issues and settings.block_new_buys_on_portfolio_violation:
            console.print("[red]New BUY blocked by existing portfolio violations:[/red]")
            for issue in guard_issues:
                console.print(f"  - {issue}")
            raise typer.Exit(code=2)
        if len(open_rows) >= settings.max_open_positions:
            raise typer.BadParameter(
                f"open position limit reached ({len(open_rows)}/{settings.max_open_positions})"
            )

    plan = calculate_position_plan(
        entry_price=price,
        stop_loss=stop,
        target_price=target,
        conviction=conviction or "MEDIUM",
        capital_usd=(
            settings.available_capital_usd
            if path == PORTFOLIO_PATH
            else settings.legacy_capital_usd
        ),
    )
    if shares > plan.shares + 1e-9:
        raise typer.BadParameter(
            f"{shares:g} shares exceeds risk-sized maximum {plan.shares:g} "
            f"(${plan.planned_risk_usd:.2f} planned risk)"
        )
    exposure = shares * price
    portfolio_capital = (
        settings.available_capital_usd
        if path == PORTFOLIO_PATH
        else settings.legacy_capital_usd
    )
    max_exposure = portfolio_capital * settings.max_position_pct
    if path == PORTFOLIO_PATH and exposure > max_exposure + 1e-9:
        raise typer.BadParameter(
            f"position exposure ${exposure:.2f} exceeds {settings.max_position_pct:.0%} "
            f"limit (${max_exposure:.2f})"
        )
    actual_risk = shares * plan.buffered_risk_per_share_usd

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
        "exit_stage": "0",
        "trailing_stop_price": "",
        "high_water_mark": "",
        "planned_risk_usd": round(actual_risk, 2),
        "risk_pct_of_capital": round(actual_risk / portfolio_capital, 6),
        "strategy_version": settings.strategy_version,
        "order_status": "executed",
        "broker_stop_order_id": "",
    })
    write_portfolio_rows(path, rows)
    console.print(
        f"[green]Added {shares:g} shares of {ticker.upper()} @ ${price} to {path}[/green] "
        f"| planned risk ${actual_risk:.2f} "
        f"({actual_risk / portfolio_capital:.2%} of capital)"
    )


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

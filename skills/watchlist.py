#!/usr/bin/env python
"""
Watchlist Skill — entry point for /watchlist slash command.

Usage:
  python skills/watchlist.py list
  python skills/watchlist.py add --ticker NVDA --reason "AI chip momentum"
  python skills/watchlist.py remove --ticker NVDA
"""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table
from investor.supabase_sync import sync_local_to_supabase

app = typer.Typer(add_completion=False)
console = Console()

WATCHLIST_PATH = Path("data/watchlist.json")


def _read_watchlist() -> dict:
    if WATCHLIST_PATH.exists():
        try:
            return json.loads(WATCHLIST_PATH.read_text())
        except Exception:
            pass
    return {"items": []}


def _write_watchlist(data: dict) -> None:
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_PATH.write_text(json.dumps(data, indent=2))
    sync_local_to_supabase("watchlist")


@app.command()
def list() -> None:
    """Show active watchlist items."""
    data = _read_watchlist()
    active = [i for i in data["items"] if i.get("status") != "removed"]
    if not active:
        console.print("[yellow]Watchlist is empty.[/yellow]")
        return
    table = Table(title="Watchlist")
    for col in ["Ticker", "Added", "Reason"]:
        table.add_column(col)
    for item in active:
        table.add_row(item["ticker"], item.get("added_at", ""), item.get("reason", ""))
    console.print(table)


@app.command()
def add(
    ticker: str = typer.Option(..., "--ticker"),
    reason: str = typer.Option("", "--reason"),
) -> None:
    """Add a ticker to the watchlist."""
    data = _read_watchlist()
    # Avoid duplicates
    for item in data["items"]:
        if item["ticker"].upper() == ticker.upper() and item.get("status") != "removed":
            console.print(f"[yellow]{ticker.upper()} is already on the watchlist.[/yellow]")
            return
    data["items"].append({
        "ticker": ticker.upper(),
        "added_at": date.today().isoformat(),
        "reason": reason,
        "status": "active",
    })
    _write_watchlist(data)
    console.print(f"[green]Added {ticker.upper()} to watchlist.[/green]")


@app.command()
def remove(
    ticker: str = typer.Option(..., "--ticker"),
) -> None:
    """Remove a ticker from the watchlist."""
    data = _read_watchlist()
    found = False
    for item in data["items"]:
        if item["ticker"].upper() == ticker.upper() and item.get("status") != "removed":
            item["status"] = "removed"
            found = True
            break
    if not found:
        console.print(f"[red]{ticker.upper()} not found on watchlist.[/red]")
        return
    _write_watchlist(data)
    console.print(f"[green]Removed {ticker.upper()} from watchlist.[/green]")


if __name__ == "__main__":
    app()

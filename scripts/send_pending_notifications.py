#!/usr/bin/env python
"""Send pending Supabase notification rows to Slack."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console

from investor.supabase_store import send_pending_notifications

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(limit: int = typer.Option(25, "--limit", help="Maximum notifications to send")) -> None:
    sent = send_pending_notifications(limit=limit)
    console.print(f"[green]Sent {sent} pending notification(s)[/green]")


if __name__ == "__main__":
    app()

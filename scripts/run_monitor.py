#!/usr/bin/env python
"""
Run the Monitor Agent for all open positions.
Intended to be called daily via cron:
  0 7 * * 1-5 cd /path/to/investor && /path/to/.venv/bin/python scripts/run_monitor.py

Usage:
  python scripts/run_monitor.py
  python scripts/run_monitor.py --dry-run
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console

from investor.agents.monitor_agent import MonitorAgent

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print output without saving or sending Slack"),
) -> None:
    """Run daily monitoring for all open positions."""
    console.rule("[bold blue]Monitor Agent[/bold blue]")
    monitor = MonitorAgent()
    alerts = monitor.run(dry_run=dry_run)
    watchlist_result = monitor.run_watchlist_monitor(dry_run=dry_run)
    high = [a for a in alerts if a.get("severity") == "HIGH"]
    watchlist_alerts = watchlist_result.get("alerts", [])
    console.print(
        f"[green]Monitoring complete[/green] | "
        f"portfolio={len(alerts)} alert(s), {len(high)} HIGH | "
        f"watchlist={len(watchlist_alerts)} alert(s)"
    )


if __name__ == "__main__":
    app()

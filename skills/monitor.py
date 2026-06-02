#!/usr/bin/env python
"""
Monitor Skill — entry point for /monitor slash command.

Usage:
  python skills/monitor.py [--dry-run]

Runs MonitorAgent on all open positions and sends daily summary to Slack.
Intended for daily cron execution (weekdays 7:00 AM):
  0 7 * * 1-5 cd "/Users/yutaobayashi/PERSONAL DEV/1_now/investor" && \
    .venv/bin/python skills/monitor.py >> logs/cron.log 2>&1
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print output without saving or sending Slack"),
) -> None:
    """Run daily monitoring for all open positions."""
    from investor.agents.monitor_agent import MonitorAgent

    console.rule("[bold blue]Monitor Agent[/bold blue]")
    monitor = MonitorAgent()
    alerts = monitor.run(dry_run=dry_run)

    high = [a for a in alerts if a.get("severity") == "HIGH"]
    console.print(
        f"[green]Monitoring complete[/green] | "
        f"{len(alerts)} alert(s), {len(high)} HIGH severity"
    )
    for a in alerts:
        severity = a.get("severity", "LOW")
        color = "red" if severity == "HIGH" else "yellow" if severity == "MEDIUM" else "white"
        console.print(
            f"  [{color}]{a.get('ticker')}[/{color}] — "
            f"{a.get('action')} | {severity} | {a.get('alert_type')}"
        )


if __name__ == "__main__":
    app()

#!/usr/bin/env python
"""
Daily Lite Skill.

One-shot lightweight daily pass:
  - monitor-lite
  - watchlist-lite
  - research-lite
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table

from investor.agents.daily_lite_agent import DailyLiteAgent

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write history/watchlist or send Slack"),
    max_research_candidates: int = typer.Option(5, "--max-research-candidates", help="Max market seed candidates"),
) -> None:
    """Run the lightweight daily investor workflow in one execution."""
    console.rule("[bold blue]Daily Lite[/bold blue]")

    agent = DailyLiteAgent()
    result = agent.run(
        dry_run=dry_run,
        max_research_candidates=max_research_candidates,
    )

    regime = result.macro_context.get("regime", "UNKNOWN")
    console.print(f"[cyan]Macro regime:[/cyan] {regime}")
    console.print(
        f"[green]Done[/green] | "
        f"alerts={len(result.position_alerts)} | "
        f"watchlist={len(result.watchlist_results)} | "
        f"research={len(result.research_candidates)} | "
        f"pending={len(result.pending_actions)}"
    )

    if result.pending_actions:
        table = Table(title="Pending Actions")
        table.add_column("Ticker")
        table.add_column("Type")
        table.add_column("Command")
        for item in result.pending_actions[:10]:
            table.add_row(str(item["ticker"]), str(item["type"]), str(item["command"]))
        console.print(table)

    console.print(f"Report: {result.report_path}")
    console.print(f"Slack: {'sent' if result.slack_sent else 'skipped'}")


if __name__ == "__main__":
    app()

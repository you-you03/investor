#!/usr/bin/env python
"""
Run a full Research + Decision Agent cycle.

Usage:
  python scripts/run_research.py
  python scripts/run_research.py --dry-run
  python scripts/run_research.py --sequential
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console

from investor.agents.decision_agent import DecisionAgent
from investor.agents.research_agent import ResearchAgent

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print output without saving or sending Slack"),
    parallel: bool = typer.Option(True, "--parallel/--sequential", help="Use parallel per-ticker research (default)"),
) -> None:
    """Run Research Agent followed by Decision Agent."""
    console.rule("[bold blue]Research Agent[/bold blue]")
    research = ResearchAgent()
    if parallel:
        console.print("[cyan]Mode: parallel[/cyan]")
        run_id = research.run_parallel(dry_run=dry_run)
    else:
        run_id = research.run(dry_run=dry_run)
    console.print(f"[green]Research complete[/green] | run_id: {run_id}")

    if dry_run:
        console.print("[yellow]Dry run: skipping Decision Agent[/yellow]")
        return

    console.rule("[bold blue]Decision Agent[/bold blue]")
    decision = DecisionAgent()
    proposals = decision.run(run_id=run_id)

    if proposals:
        console.print(f"[green]{len(proposals)} proposal(s) sent to Slack[/green]")
        for p in proposals:
            console.print(f"  {p['action']} {p['ticker']} ({p['conviction']}) | target ${p.get('target_price')}")
    else:
        console.print("[yellow]No actionable proposals generated[/yellow]")


if __name__ == "__main__":
    app()

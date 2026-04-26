#!/usr/bin/env python
"""
Decision Skill — research read + Slack send entry point.

This script prints research data for Claude to analyze (debate mode),
or sends Claude's proposals to Slack (send mode).

Claude Code (the current session) performs:
  - Bullish analyst reasoning
  - Bearish analyst reasoning
  - Portfolio Manager final decision

Usage:
  python skills/decision.py                    # print latest research for Claude to debate
  python skills/decision.py --run-id <uuid>    # print specific run
  python skills/decision.py --send '[{...}]'   # send Claude's proposals to Slack
  python skills/decision.py --dry-run          # print without sending
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console

app = typer.Typer(add_completion=False)
console = Console(stderr=True)


@app.command()
def main(
    run_id: str = typer.Option("", "--run-id", help="Research run_id to use (default: latest)"),
    watchlist_run_id: str = typer.Option("", "--watchlist-run-id", help="Watchlist research run_id to merge (default: latest if exists)"),
    send: str = typer.Option("", "--send", help="JSON array of proposals from Claude to send to Slack"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print proposals without sending to Slack"),
) -> None:
    """
    Print research data for Claude to debate, or send Claude's proposals to Slack.

    When a watchlist research run exists, it is automatically merged into the
    decision context. Watchlist-escalated tickers take priority over market-scan
    duplicates. Use --watchlist-run-id to pin a specific watchlist run.
    """
    from investor.agents.decision_agent import (
        enrich_proposals,
        format_research_for_claude,
        get_latest_run_id,
        load_run,
        send_proposals,
    )

    # --send mode: deliver Claude's decision to Slack
    if send.strip():
        try:
            raw_proposals = json.loads(send)
            if not isinstance(raw_proposals, list):
                console.print("[red]--send must be a JSON array[/red]")
                raise typer.Exit(1)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON: {e}[/red]")
            raise typer.Exit(1)

        target_run_id = run_id.strip() or get_latest_run_id()
        candidates = load_run(target_run_id) if target_run_id else []
        proposals = enrich_proposals(raw_proposals, candidates)

        if dry_run:
            console.print("[yellow][DRY RUN] Proposals:[/yellow]")
            print(json.dumps(proposals, indent=2))
            return

        send_proposals(proposals)
        console.print(f"[green]Sent {len(proposals)} proposal(s) to Slack[/green]")
        for p in proposals:
            console.print(f"  {p['action']} {p['ticker']} ({p['conviction']}) | size ${p.get('position_size_usd'):,.0f}")
        return

    # Read mode: print research data for Claude to analyze
    target_run_id = run_id.strip() or get_latest_run_id()
    if not target_run_id:
        console.print("[red]No research run found. Run `python skills/research.py` first.[/red]")
        raise typer.Exit(1)

    wr_run_id = watchlist_run_id.strip() or None  # None = auto-detect latest

    report = format_research_for_claude(target_run_id, watchlist_run_id=wr_run_id)
    print(report)  # stdout for Claude to read

    console.print(f"[cyan]run_id: {target_run_id}[/cyan]")
    if wr_run_id:
        console.print(f"[cyan]watchlist_run_id: {wr_run_id}[/cyan]")
    console.print("[yellow]→ Claude: debate the candidates above (Bullish / Bearish / PM), then call:[/yellow]")
    console.print(f'[yellow]  python skills/decision.py --run-id {target_run_id} --send \'[{{...proposals...}}]\' [/yellow]')


if __name__ == "__main__":
    app()

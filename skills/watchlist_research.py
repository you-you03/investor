#!/usr/bin/env python
"""
Watchlist Research Skill — targeted deep research on active watchlist stocks.

This script collects raw market data for all active watchlist tickers and
prints it as JSON to stdout. Claude Code (the current session) reads this
output and:
  - Evaluates each ticker's setup against its original thesis
  - Assigns an action: ESCALATE / MAINTAIN / REMOVE / ADD_NOTE
  - Calls --save to update watchlist.json and persist the run

Usage:
  python skills/watchlist_research.py               # collect + print for Claude
  python skills/watchlist_research.py --sequential  # sequential (not parallel)
  python skills/watchlist_research.py --save '...'  # save Claude's analysis
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
    parallel: bool = typer.Option(True, "--parallel/--sequential"),
    save: str = typer.Option("", "--save", help="JSON string from Claude to save"),
) -> None:
    """
    Collect active watchlist data for Claude to analyze, or save Claude's analysis.

    --save JSON format:
      {
        "run_id": "<uuid from collection>",
        "results": [
          {
            "ticker": "NVDA",
            "action": "ESCALATE",   // ESCALATE | MAINTAIN | REMOVE | ADD_NOTE
            "new_score": 8.2,
            "note": "52w高値ブレイク、RSI冷却済み、エントリーゾーン$205-210",
            "flag": "ESCALATE_TO_DECISION"
          }
        ]
      }
    """
    from investor.agents.watchlist_research_agent import (
        collect_watchlist_research_data,
        save_watchlist_research,
    )

    # --save mode: persist Claude's analysis
    if save.strip():
        try:
            data = json.loads(save)
            run_id = data.get("run_id")
            results = data.get("results", [])
            if not run_id:
                console.print("[red]--save JSON must include 'run_id'[/red]")
                raise typer.Exit(1)
            save_watchlist_research(run_id, results)
            escalated = sum(1 for r in results if r.get("action", "").upper() == "ESCALATE")
            removed = sum(1 for r in results if r.get("action", "").upper() == "REMOVE")
            console.print(
                f"[green]Saved {len(results)} results | "
                f"ESCALATE: {escalated} | REMOVE: {removed} | "
                f"run_id: {run_id}[/green]"
            )
            print(run_id)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON: {e}[/red]")
            raise typer.Exit(1)
        return

    # Data collection mode
    console.print("[cyan]Collecting deep data for active watchlist tickers...[/cyan]")
    data = collect_watchlist_research_data(parallel=parallel)

    n_tickers = len(data.get("ticker_data", {}))
    n_watchlist = len(data.get("watchlist_items", []))

    print(json.dumps(data, indent=2, default=str))

    console.print(f"[green]Done | {n_tickers}/{n_watchlist} tickers collected | run_id: {data['run_id']}[/green]")
    console.print("[yellow]→ Claude: analyze each ticker vs. original thesis, then call:[/yellow]")
    console.print(
        f'[yellow]  python skills/watchlist_research.py --save \''
        f'{{"run_id":"{data["run_id"]}","results":[...]}}\' [/yellow]'
    )


if __name__ == "__main__":
    app()

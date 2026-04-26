#!/usr/bin/env python
"""
Research Skill — data collection entry point.

This script collects raw market data and prints it as a JSON report to stdout.
Claude Code (the current session) reads this output and performs:
  - candidate screening (which tickers are worth investing)
  - per-ticker deep analysis
  - saving results to data/research_history.json

Usage:
  python skills/research.py               # collect top movers (parallel)
  python skills/research.py --sequential  # collect sequentially
  python skills/research.py --tickers NVDA,TSLA  # specific tickers
  python skills/research.py --save '{"run_id":"...","candidates":[...]}' # save Claude's analysis
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console

app = typer.Typer(add_completion=False)
console = Console(stderr=True)  # progress messages go to stderr


@app.command()
def main(
    parallel: bool = typer.Option(True, "--parallel/--sequential"),
    tickers: str = typer.Option("", "--tickers", help="Comma-separated tickers"),
    save: str = typer.Option("", "--save", help="JSON string from Claude to save as a research run"),
    max_tickers: int = typer.Option(15, "--max-tickers", help="Max tickers to collect data for"),
) -> None:
    """
    Collect market data and print JSON report to stdout for Claude to analyze.
    Or save Claude's analysis with --save.
    """
    from investor.agents.research_agent import collect_market_data, save_run

    # --save mode: persist Claude's analysis result
    if save.strip():
        try:
            data = json.loads(save)
            run_id = data.get("run_id")
            candidates = data.get("candidates", [])
            if not run_id:
                console.print("[red]--save JSON must include 'run_id'[/red]")
                raise typer.Exit(1)
            save_run(run_id, candidates)
            console.print(f"[green]Saved {len(candidates)} candidates | run_id: {run_id}[/green]")
            print(run_id)  # stdout for caller
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON: {e}[/red]")
            raise typer.Exit(1)
        return

    # Data collection mode
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None

    if ticker_list:
        console.print(f"[cyan]Collecting data for: {ticker_list}[/cyan]")
    else:
        console.print(f"[cyan]Collecting top market movers (max {max_tickers} tickers)...[/cyan]")

    data = collect_market_data(
        tickers=ticker_list,
        max_tickers=max_tickers,
        parallel=parallel,
    )

    # Print collected data as JSON to stdout for Claude to read
    print(json.dumps(data, indent=2, default=str))
    console.print(f"[green]Data collection complete | run_id: {data['run_id']}[/green]")
    console.print("[yellow]→ Claude: analyze the JSON above, select top 3-5 candidates, then call:[/yellow]")
    console.print(f'[yellow]  python skills/research.py --save \'{{\"run_id\":\"{data["run_id"]}\",\"candidates\":[...]}}\' [/yellow]')


if __name__ == "__main__":
    app()

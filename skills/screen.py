#!/usr/bin/env python
"""
Screen Skill — Phase 1 lightweight wide scan.

Collects snapshot + technicals for all SCREEN_UNIVERSE tickers (~150-200),
then prints JSON to stdout for Claude to shortlist 10-15 candidates.

Claude reads the output and selects candidates, then runs:
  python skills/research.py --tickers TICKER1,TICKER2,...

Usage:
  python skills/screen.py               # scan full SCREEN_UNIVERSE (parallel)
  python skills/screen.py --sequential  # sequential (slower, for debugging)
  python skills/screen.py --extra RKLB,IONQ  # append extra tickers
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
    extra: str = typer.Option("", "--extra", help="Comma-separated extra tickers to append"),
) -> None:
    """
    Phase 1: Wide lightweight screen across all sectors.
    Prints JSON to stdout for Claude to shortlist candidates for Phase 2.
    """
    from investor.agents.research_agent import collect_screen_data
    from investor.data.yfinance_client import SCREEN_UNIVERSE

    extra_list = [t.strip().upper() for t in extra.split(",") if t.strip()] if extra else None

    console.print(f"[cyan]Phase 1 screen: {len(SCREEN_UNIVERSE)} base tickers"
                  + (f" + {len(extra_list)} extra" if extra_list else "") + "[/cyan]")
    console.print("[cyan]Collecting snapshot + technicals only (lightweight)...[/cyan]")

    data = collect_screen_data(extra_tickers=extra_list, parallel=parallel)

    valid = sum(
        1 for v in data["ticker_data"].values()
        if not v.get("snapshot", {}).get("error") and not v.get("technicals", {}).get("error")
    )
    console.print(f"[green]Collected {valid}/{len(data['ticker_data'])} tickers successfully[/green]")
    console.print("[yellow]→ Claude: read the JSON below, apply SCREEN_PROMPT, then run:[/yellow]")
    console.print("[yellow]  python skills/research.py --tickers TICKER1,TICKER2,...[/yellow]")

    print(json.dumps(data, indent=2, default=str))


if __name__ == "__main__":
    app()

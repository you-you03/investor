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
  python skills/screen.py --mode contrarian  # oversold contrarian candidates only
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
    mode: str = typer.Option("momentum", "--mode", help="Screen mode: 'momentum' (default) or 'contrarian'"),
) -> None:
    """
    Phase 1: Wide lightweight screen across all sectors.
    Prints JSON to stdout for Claude to shortlist candidates for Phase 2.

    --mode contrarian: screens for oversold / deeply discounted tickers
    instead of momentum breakouts. Use when seeking sector diversification
    or in a low-momentum market environment.
    """
    if mode == "contrarian":
        _run_contrarian_screen()
    else:
        _run_momentum_screen(extra, parallel)


def _run_momentum_screen(extra: str, parallel: bool) -> None:
    from investor.agents.research_agent import collect_screen_data
    from investor.data.yfinance_client import SCREEN_UNIVERSE

    extra_list = [t.strip().upper() for t in extra.split(",") if t.strip()] if extra else None

    console.print(f"[cyan]Phase 1 screen (momentum): {len(SCREEN_UNIVERSE)} base tickers"
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


def _run_contrarian_screen() -> None:
    from investor.data.yfinance_client import YFinanceClient, SCREEN_UNIVERSE

    console.print(f"[cyan]Phase 1 screen (contrarian): {len(SCREEN_UNIVERSE)} tickers[/cyan]")
    console.print("[cyan]Criteria: RSI≤32 + price≤200MA×0.92 + ≥3連続陰線 + 時価総額≥$500M[/cyan]")
    console.print("[yellow]※ 200日分のデータ取得のため通常スクリーンより時間がかかります...[/yellow]")

    yf = YFinanceClient()
    results = yf.get_contrarian_candidates()

    if not results:
        console.print("[yellow]該当銘柄なし — 現在のユニバースでは逆張り条件を満たす銘柄がゼロです[/yellow]")
        output = {
            "screen_mode": "contrarian",
            "candidates_found": 0,
            "candidates": [],
            "note": "No oversold candidates found. Market may be in a momentum phase — try default mode.",
        }
    else:
        console.print(f"[green]{len(results)}件の逆張り候補を発見[/green]")
        extreme = [r for r in results if r["oversold_severity"] == "EXTREME"]
        moderate = [r for r in results if r["oversold_severity"] == "MODERATE"]
        if extreme:
            console.print(f"[red]  EXTREME ({len(extreme)}件): " + ", ".join(r["ticker"] for r in extreme) + "[/red]")
        if moderate:
            console.print(f"[yellow]  MODERATE ({len(moderate)}件): " + ", ".join(r["ticker"] for r in moderate) + "[/yellow]")
        console.print("[yellow]→ Claude: contrarian_tag=true の候補はモメンタム候補とは別扱いで評価してください[/yellow]")
        console.print("[yellow]  セクター分散・カタリスト有無・ファンダメンタルズ劣化なしを必ず確認[/yellow]")

        output = {
            "screen_mode": "contrarian",
            "candidates_found": len(results),
            "extreme_count": len(extreme),
            "moderate_count": len(moderate),
            "candidates": results,
        }

    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    app()

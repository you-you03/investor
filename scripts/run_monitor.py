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
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table

from investor.agents.monitor_agent import MonitorAgent

app = typer.Typer(add_completion=False)
console = Console()


def _money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _pct(value) -> str:
    try:
        number = float(value)
        return f"{number:+.2f}%"
    except (TypeError, ValueError):
        return "-"


def _position_change(position: dict) -> tuple[str, str]:
    current = position.get("current_price")
    entry = position.get("entry_price")
    shares = position.get("shares")
    try:
        change_per_share = float(current) - float(entry)
        change_total = change_per_share * float(shares or 0)
        change_pct = change_per_share / float(entry) * 100
        return f"{change_per_share:+.2f}/sh ({change_total:+.2f})", f"{change_pct:+.2f}%"
    except (TypeError, ValueError, ZeroDivisionError):
        return "-", "-"


def _portfolio_decision_label(position: dict, alerts: list[dict]) -> str:
    ticker = str(position.get("ticker", "")).upper()
    ticker_alerts = [a for a in alerts if str(a.get("ticker", "")).upper() == ticker]
    if any(a.get("alert_type") in {"STOP_LOSS", "TARGET_REACHED", "SHARP_DROP"} for a in ticker_alerts):
        return "decision_needed"
    if any(a.get("severity") == "MEDIUM" for a in ticker_alerts):
        return "review"
    return "hold"


def _build_markdown_summary(portfolio_record: dict, watchlist_record: dict) -> str:
    positions = portfolio_record.get("positions", [])
    portfolio_alerts = portfolio_record.get("alerts", [])
    watchlist_items = watchlist_record.get("items", [])
    watchlist_action_items = [
        item for item in watchlist_items
        if item.get("action") in {"decision_needed", "research_needed"}
    ]

    lines = [
        "# Investor Monitor",
        "",
        "## 保有銘柄",
        "",
        "| Ticker | 現在値 | 買値 | 変動幅 | 変動率 | 判断 | 利確目安 | 損切り |",
        "|---|---:|---:|---:|---:|---|---:|---:|",
    ]
    if positions:
        for position in positions:
            change_amount, change_pct = _position_change(position)
            lines.append(
                "| {ticker} | {current} | {entry} | {change_amount} | {change_pct} | {decision} | {target} | {stop} |".format(
                    ticker=position.get("ticker", "-"),
                    current=_money(position.get("current_price")),
                    entry=_money(position.get("entry_price")),
                    change_amount=change_amount,
                    change_pct=change_pct,
                    decision=_portfolio_decision_label(position, portfolio_alerts),
                    target=_money(position.get("target_price")),
                    stop=_money(position.get("stop_loss")),
                )
            )
    else:
        lines.append("| - | - | - | - | - | no_open_positions | - | - |")

    if portfolio_alerts:
        lines += [
            "",
            "### 保有銘柄アラート",
            "",
            "| Ticker | Severity | Type | Message |",
            "|---|---|---|---|",
        ]
        for alert in portfolio_alerts:
            lines.append(
                f"| {alert.get('ticker', '-')} | {alert.get('severity', '-')} | "
                f"{alert.get('alert_type', '-')} | {alert.get('message', '-')} |"
            )

    lines += [
        "",
        "## Watchlist",
        "",
        "| Ticker | 価格 | Score | Action | Next step | Flags |",
        "|---|---:|---:|---|---|---|",
    ]
    if watchlist_action_items:
        for item in watchlist_action_items:
            flags = ", ".join(item.get("flags") or [])
            lines.append(
                "| {ticker} | {price} | {score} | {action} | {next_step} | {flags} |".format(
                    ticker=item.get("ticker", "-"),
                    price=_money(item.get("price")),
                    score=item.get("last_score") if item.get("last_score") is not None else "-",
                    action=item.get("action", "-"),
                    next_step=item.get("next_step") or "-",
                    flags=flags or "-",
                )
            )
    else:
        lines.append("| - | - | - | no_action | - | - |")

    return "\n".join(lines) + "\n"


def _write_github_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(markdown)


def _print_console_tables(portfolio_record: dict, watchlist_record: dict) -> None:
    position_table = Table(title="Portfolio Monitor")
    for column in ("Ticker", "Current", "Entry", "Change", "Change %", "Decision", "Target", "Stop"):
        position_table.add_column(column)
    for position in portfolio_record.get("positions", []):
        change_amount, change_pct = _position_change(position)
        position_table.add_row(
            str(position.get("ticker", "-")),
            _money(position.get("current_price")),
            _money(position.get("entry_price")),
            change_amount,
            change_pct,
            _portfolio_decision_label(position, portfolio_record.get("alerts", [])),
            _money(position.get("target_price")),
            _money(position.get("stop_loss")),
        )
    console.print(position_table)

    watchlist_table = Table(title="Watchlist Actions")
    for column in ("Ticker", "Price", "Score", "Action", "Next step", "Flags"):
        watchlist_table.add_column(column)
    for item in watchlist_record.get("items", []):
        if item.get("action") not in {"decision_needed", "research_needed"}:
            continue
        watchlist_table.add_row(
            str(item.get("ticker", "-")),
            _money(item.get("price")),
            str(item.get("last_score") if item.get("last_score") is not None else "-"),
            str(item.get("action", "-")),
            str(item.get("next_step") or "-"),
            ", ".join(item.get("flags") or []) or "-",
        )
    console.print(watchlist_table)


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
    portfolio_record = monitor.last_portfolio_record or {"positions": [], "alerts": alerts}
    watchlist_record = monitor.last_watchlist_record or watchlist_result
    _print_console_tables(portfolio_record, watchlist_record)
    _write_github_summary(_build_markdown_summary(portfolio_record, watchlist_record))
    console.print(
        f"[green]Monitoring complete[/green] | "
        f"portfolio={len(alerts)} alert(s), {len(high)} HIGH | "
        f"watchlist={len(watchlist_alerts)} alert(s)"
    )


if __name__ == "__main__":
    app()

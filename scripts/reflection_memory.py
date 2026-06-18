#!/usr/bin/env python
"""Read/write reflection memory in Supabase.

This gives Codex a stable path:
  1. read compact inputs from Supabase
  2. think/review in the agent
  3. write the reflection back to Supabase
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console

from investor.supabase_store import _stable_id, get_store

app = typer.Typer(add_completion=False)
console = Console()


@app.command("dump-inputs")
def dump_inputs(
    limit: int = typer.Option(200, "--limit", help="Max rows from report_reflection_inputs"),
    output: Path | None = typer.Option(None, "--output", help="Optional JSON output path"),
) -> None:
    """Dump review inputs for Codex analysis."""
    store = get_store()
    if not store:
        raise typer.BadParameter("Supabase is not configured")
    rows = store.select(
        "report_reflection_inputs",
        {"select": "*", "order": "date.desc", "limit": str(limit)},
    )
    payload = {"generated_at": date.today().isoformat(), "rows": rows}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        console.print(f"[green]Wrote {len(rows)} row(s) to {output}[/green]")
    else:
        console.print(text)


@app.command("write")
def write_reflection(
    scope: str = typer.Option(..., "--scope", help="Scope, e.g. weekly, monthly, decision_quality"),
    summary: str = typer.Option(..., "--summary", help="Short summary"),
    conclusion: str = typer.Option("", "--conclusion", help="Conclusion / next policy"),
    period_start: str | None = typer.Option(None, "--period-start"),
    period_end: str | None = typer.Option(None, "--period-end"),
    findings_json: Path | None = typer.Option(None, "--findings-json", help="JSON list of findings"),
) -> None:
    """Write a Codex reflection and optional findings back to Supabase."""
    store = get_store()
    if not store:
        raise typer.BadParameter("Supabase is not configured")

    reflection_id = _stable_id("reflection", scope, period_start, period_end, summary)
    reflection = {
        "reflection_id": reflection_id,
        "reflection_date": date.today().isoformat(),
        "scope": scope,
        "period_start": period_start,
        "period_end": period_end,
        "trigger_source": "codex",
        "summary": summary,
        "conclusion": conclusion,
        "raw_payload": {},
    }
    store.upsert("reflection_runs", [reflection], "reflection_id")

    findings = []
    if findings_json:
        findings = json.loads(findings_json.read_text())
    rows = []
    for index, finding in enumerate(findings, 1):
        rows.append({
            "finding_id": finding.get("finding_id") or _stable_id("finding", reflection_id, index, finding.get("title")),
            "reflection_id": reflection_id,
            "ticker": finding.get("ticker"),
            "finding_type": finding.get("finding_type") or "observation",
            "severity": finding.get("severity"),
            "title": finding.get("title") or "Untitled finding",
            "evidence": finding.get("evidence"),
            "recommendation": finding.get("recommendation"),
            "status": finding.get("status") or "open",
            "raw_payload": finding,
        })
    if rows:
        store.upsert("reflection_findings", rows, "finding_id")
    console.print(f"[green]Wrote reflection {reflection_id} with {len(rows)} finding(s)[/green]")


if __name__ == "__main__":
    app()

#!/usr/bin/env python3
"""Report overdue H-* hypotheses and open paper rows. Does not rewrite verdicts.

Reads ``docs/hypothesis-tracker.md`` and ``data/paper_portfolio.csv``.
A missing end date is reported as missing. The tracker file is left unchanged.

Usage:
  .venv/bin/python scripts/check_hypotheses.py
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investor.utils.portfolio_contract import read_portfolio_rows

TRACKER_PATH = Path("docs/hypothesis-tracker.md")
PAPER_PATH = Path("data/paper_portfolio.csv")
REPORTS_DIR = Path("reports/validation")

HEADING_RE = re.compile(r"^#{2,3}\s+(H-\d+)\b.*$", re.MULTILINE)
PERIOD_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*[〜~\-–—]+\s*(\d{4}-\d{2}-\d{2})"
)
START_RE = re.compile(r"検証開始日\**[:：]\s*(\d{4}-\d{2}-\d{2})")
HYPOTHESIS_RE = re.compile(r"H-\d+")


def parse_hypotheses(text: str) -> list[dict]:
    decided_at = text.find("## 完了済み仮説")
    matches = list(HEADING_RE.finditer(text))
    rows = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        period = PERIOD_RE.search(body)
        start_only = START_RE.search(body)
        row = {
            "hypothesis_id": match.group(1),
            "start": None,
            "end": None,
            "due_state": "end_date_missing",
        }
        if period:
            row["start"] = period.group(1)
            row["end"] = period.group(2)
            row["due_state"] = "dated"
        elif start_only:
            row["start"] = start_only.group(1)
            row["due_state"] = "end_date_missing"
        if decided_at >= 0 and match.start() > decided_at:
            row["due_state"] = "decided"
        rows.append(row)
    return rows


def classify(row: dict, today: date) -> str:
    if row.get("due_state") == "decided":
        return "decided"
    if row["due_state"] != "dated" or not row.get("end"):
        return "end_date_missing"
    end = date.fromisoformat(row["end"])
    if end < today:
        return "overdue"
    return "open"


def paper_notes(rows: list[dict], hypotheses: list[dict], today: date) -> list[str]:
    by_id = {item["hypothesis_id"]: item for item in hypotheses}
    notes = []
    for row in rows:
        if str(row.get("status") or "").lower() != "open":
            continue
        blob = " ".join(
            str(row.get(field) or "")
            for field in ("hypothesis_id", "note")
        )
        ids = HYPOTHESIS_RE.findall(blob)
        hypothesis_id = (row.get("hypothesis_id") or (ids[0] if ids else "")).strip()
        hypothesis = by_id.get(hypothesis_id)
        state = "no_hypothesis_id" if not hypothesis else classify(hypothesis, today)
        notes.append(
            f"- {row.get('position_id') or 'paper'} {row.get('ticker')} "
            f"hypothesis={hypothesis_id or 'blank'} window={state}. "
            "Left open. This script does not close paper rows or rewrite the tracker."
        )
    return notes


def render(hypotheses: list[dict], paper_lines: list[str], today: date) -> str:
    lines = [
        f"# Hypothesis due check — {today.isoformat()}",
        "",
        "Verdicts in `docs/hypothesis-tracker.md` were not rewritten.",
        "Overdue means the written end date is before today and the heading is still outside `## 完了済み仮説`.",
        "`decided` means that heading sits in the completed section. This script does not close paper rows.",
        "",
        "## Hypotheses",
        "",
        "| ID | Start | End | State |",
        "|---|---|---|---|",
    ]
    for row in hypotheses:
        state = classify(row, today)
        lines.append(
            f"| {row['hypothesis_id']} | {row['start'] or '—'} | {row['end'] or '—'} | {state} |"
        )
    lines.append("")
    lines.append("## Open paper book")
    lines.append("")
    if paper_lines:
        lines.extend(paper_lines)
    else:
        lines.append("- No open paper rows.")
    lines.append("")
    lines.append("Review command: `python skills/paper_portfolio.py list`")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    today = date.today()
    text = TRACKER_PATH.read_text(encoding="utf-8") if TRACKER_PATH.exists() else ""
    hypotheses = parse_hypotheses(text)
    paper_rows = read_portfolio_rows(PAPER_PATH)
    paper_lines = paper_notes(paper_rows, hypotheses, today)
    report = render(hypotheses, paper_lines, today)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"hypothesis_due_{today.isoformat()}.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"→ {out}")


if __name__ == "__main__":
    main()

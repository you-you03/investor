from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

PORTFOLIO_FIELDNAMES = [
    "position_id",
    "ticker",
    "shares",
    "entry_price",
    "entry_date",
    "proposal_date",
    "exit_price",
    "exit_date",
    "status",
    "target_price",
    "stop_loss",
    "note",
    "signal_type",
    "conviction",
    "hypothesis_id",
    "exit_stage",
    "mae_pct",
    "mfe_pct",
    "mfe_capture_pct",
    "rule_adherence_score",
]


def read_portfolio_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return [normalize_portfolio_row(row) for row in csv.DictReader(f)]


def write_portfolio_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_rows = [normalize_portfolio_row(row) for row in rows]
    with tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        suffix=".tmp",
        dir=path.parent,
        newline="",
    ) as tf:
        writer = csv.DictWriter(tf, fieldnames=PORTFOLIO_FIELDNAMES)
        writer.writeheader()
        writer.writerows(normalized_rows)
        tmp_name = tf.name
    os.replace(tmp_name, path)


def normalize_portfolio_row(row: dict | None) -> dict:
    source = row or {}
    normalized = {field: source.get(field, "") for field in PORTFOLIO_FIELDNAMES}
    for key in ("ticker", "status", "signal_type", "conviction", "hypothesis_id"):
        if normalized[key] is None:
            normalized[key] = ""
    if normalized["ticker"]:
        normalized["ticker"] = str(normalized["ticker"]).upper()
    if normalized["status"]:
        normalized["status"] = str(normalized["status"]).lower()
    return normalized


def build_position_id(existing_rows: list[dict]) -> str:
    max_num = 0
    for row in existing_rows:
        position_id = str(row.get("position_id", ""))
        if position_id.startswith("pos-"):
            try:
                max_num = max(max_num, int(position_id.split("-", 1)[1]))
            except ValueError:
                continue
    return f"pos-{max_num + 1:03d}"


def closed_row_issues(row: dict) -> list[str]:
    if row.get("status") != "closed":
        return []

    issues: list[str] = []
    ticker = row.get("ticker") or "UNKNOWN"
    if not row.get("exit_price"):
        issues.append(f"{ticker}: closed row missing exit_price")
    if not row.get("exit_date"):
        issues.append(f"{ticker}: closed row missing exit_date")
    if not row.get("entry_price"):
        issues.append(f"{ticker}: closed row missing entry_price")
    if not row.get("entry_date"):
        issues.append(f"{ticker}: closed row missing entry_date")
    return issues

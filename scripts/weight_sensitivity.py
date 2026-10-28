#!/usr/bin/env python3
"""Offline weight-sensitivity report. Does not change live score weights.

Live Strategy V2 weights stay:

    fundamentals 0.60 + momentum 0.25 + catalyst 0.15

Review gates stay in force:

- fewer than 10 independent matured runs: no live weight change
- HIGH conviction stays disabled until 30 matured OOS observations

This script only writes ``reports/validation/weight_sensitivity_{date}.md``.

Usage:
  .venv/bin/python scripts/weight_sensitivity.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.validate_scores import WEEK_KEYS, spearman

SNAPSHOTS_PATH = Path("data/score_snapshots.json")
REPORTS_DIR = Path("reports/validation")

# Must match docs/strategy-v2.md. This file does not write investor/config.py.
LIVE_WEIGHTS = {
    "fundamentals": 0.60,
    "momentum": 0.25,
    "catalyst": 0.15,
}
ALTERNATES = [
    ("live", LIVE_WEIGHTS),
    ("more_fundamental", {"fundamentals": 0.70, "momentum": 0.20, "catalyst": 0.10}),
    ("more_momentum", {"fundamentals": 0.50, "momentum": 0.35, "catalyst": 0.15}),
    ("more_catalyst", {"fundamentals": 0.60, "momentum": 0.15, "catalyst": 0.25}),
    ("balanced_momentum", {"fundamentals": 0.40, "momentum": 0.40, "catalyst": 0.20}),
    ("equal", {"fundamentals": 1 / 3, "momentum": 1 / 3, "catalyst": 1 / 3}),
]
MIN_MATURED_RUNS_FOR_WEIGHT_CHANGE = 10
MIN_OOS_FOR_HIGH_CONVICTION = 30


def _blend(snapshot: dict, weights: dict[str, float]) -> float | None:
    breakdown = snapshot.get("score_breakdown") or {}
    total = 0.0
    for factor, weight in weights.items():
        value = breakdown.get(factor)
        if value is None:
            return None
        try:
            total += float(value) * weight
        except (TypeError, ValueError):
            return None
    return total


def _pairs(snapshots: list[dict], week: str, weights: dict[str, float]) -> list[tuple[float, float]]:
    rows = []
    for snapshot in snapshots:
        if str(snapshot.get("catalyst_data_status") or "").lower() == "missing":
            continue
        if snapshot.get("catalyst_data_missing") is True:
            continue
        score = _blend(snapshot, weights)
        payload = snapshot.get(week) or {}
        alpha = payload.get("alpha_vs_spy", payload.get("alpha_pct"))
        if score is None or alpha is None or payload.get("fetched_at") is None:
            continue
        rows.append((score, float(alpha)))
    return rows


def matured_run_count(snapshots: list[dict], week: str = "week12") -> int:
    runs = set()
    for snapshot in snapshots:
        payload = snapshot.get(week) or {}
        run_id = str(snapshot.get("run_id") or "")
        if run_id and payload.get("fetched_at") and payload.get("alpha_vs_spy", payload.get("alpha_pct")) is not None:
            runs.add(run_id)
    return len(runs)


def build_report(snapshots: list[dict], today: str | None = None) -> str:
    as_of = today or date.today().isoformat()
    week12_runs = matured_run_count(snapshots, "week12")
    lines = [
        f"# Offline weight sensitivity — {as_of}",
        "",
        "Live weights were not changed. `investor/config.py` and the research score formula were not written.",
        "",
        f"- Live mix: fundamentals {LIVE_WEIGHTS['fundamentals']:.2f} / "
        f"momentum {LIVE_WEIGHTS['momentum']:.2f} / catalyst {LIVE_WEIGHTS['catalyst']:.2f}",
        f"- Run ids with any week12 alpha fetched (all strategy versions, diagnostic): {week12_runs}",
        f"- /review gate is unchanged: no live weight change below {MIN_MATURED_RUNS_FOR_WEIGHT_CHANGE} "
        "independent matured Strategy V2 runs, and this report does not clear that gate.",
        f"- HIGH conviction stays disabled until {MIN_OOS_FOR_HIGH_CONVICTION} matured OOS observations.",
        "- Catalyst rows tagged `catalyst_data_missing` are left out of these blends.",
        "- Spearman below is diagnostic pooled IC of the blended score versus SPY alpha. It is not a permission to retune.",
        "",
        "| Mix | Horizon | N | Spearman ρ |",
        "|---|---|---|---|",
    ]
    for name, weights in ALTERNATES:
        for week in ("week4", "week12"):
            if week not in WEEK_KEYS and week not in {"week4", "week12"}:
                continue
            pairs = _pairs(snapshots, week, weights)
            if len(pairs) < 3:
                rho = "N/A"
            else:
                scores, alphas = zip(*pairs)
                value, _ = spearman(list(scores), list(alphas))
                rho = "N/A" if value != value else f"{value:+.3f}"
            lines.append(f"| {name} | {week} | {len(pairs)} | {rho} |")
    lines.append("")
    lines.append("Next live decision remains: keep Strategy V2 weights fixed until the review gates say otherwise.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    if not SNAPSHOTS_PATH.exists():
        print(f"ERROR: {SNAPSHOTS_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    snapshots = json.loads(SNAPSHOTS_PATH.read_text()).get("snapshots", [])
    report = build_report(snapshots)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"weight_sensitivity_{date.today().isoformat()}.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"→ {out}")


if __name__ == "__main__":
    main()

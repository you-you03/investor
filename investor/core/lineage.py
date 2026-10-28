"""Optional run_id links across research, decisions, monitor, and the journal.

Readers that do not know these fields must keep working. Missing keys mean
"not linked yet", and this module only fills blanks.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

RESEARCH_HISTORY_PATH = Path("data/research_history.json")
SNAPSHOTS_PATH = Path("data/score_snapshots.json")
DECISION_HISTORY_PATH = Path("data/decision_history.json")
TRADE_JOURNAL_PATH = Path("data/trade_journal.json")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def latest_research_run_ids(
    tickers: list[str],
    *,
    research_path: Path | None = None,
    snapshots_path: Path | None = None,
) -> dict[str, str]:
    """Return the newest research run_id known for each ticker."""
    wanted = {str(ticker or "").upper() for ticker in tickers if ticker}
    if not wanted:
        return {}
    found: dict[str, tuple[str, str]] = {}

    def consider(ticker: str, run_id: str, on_date: str) -> None:
        symbol = str(ticker or "").upper()
        if symbol not in wanted or not run_id:
            return
        previous = found.get(symbol)
        if previous is None or str(on_date or "") >= previous[0]:
            found[symbol] = (str(on_date or ""), str(run_id))

    history = _load_json(research_path or RESEARCH_HISTORY_PATH, {"runs": []})
    for run in history.get("runs", []) if isinstance(history, dict) else []:
        run_id = str(run.get("run_id") or "")
        on_date = str(run.get("date") or "")
        for candidate in run.get("candidates") or []:
            consider(candidate.get("ticker"), run_id, on_date)

    snapshots = _load_json(snapshots_path or SNAPSHOTS_PATH, {"snapshots": []})
    rows = snapshots.get("snapshots", []) if isinstance(snapshots, dict) else []
    for snapshot in rows:
        if str(snapshot.get("source") or "research") not in {"research", "watchlist_research"}:
            continue
        consider(snapshot.get("ticker"), str(snapshot.get("run_id") or ""), str(snapshot.get("scored_at") or ""))

    return {ticker: run_id for ticker, (_, run_id) in found.items()}


def _journal_ticker(entry: dict) -> str:
    ticker = str(entry.get("ticker") or "").upper()
    if ticker:
        return ticker
    trade_id = str(entry.get("trade_id") or "")
    head = trade_id.split("_", 1)[0]
    if head.isalpha() and 1 <= len(head) <= 6:
        return head.upper()
    return ""


def _journal_day(entry: dict) -> date | None:
    for key in ("entry_date", "review_date", "exit_date"):
        parsed = _parse_day(entry.get(key))
        if parsed is not None:
            return parsed
    trade_id = str(entry.get("trade_id") or "")
    parts = trade_id.split("_")
    if len(parts) >= 2:
        return _parse_day(parts[1])
    return None


def _research_index(history: dict) -> list[tuple[str, str, date | None]]:
    rows: list[tuple[str, str, date | None]] = []
    for run in history.get("runs", []):
        run_id = str(run.get("run_id") or "")
        run_day = _parse_day(run.get("date"))
        if not run_id:
            continue
        for candidate in run.get("candidates") or []:
            ticker = str(candidate.get("ticker") or "").upper()
            if ticker:
                rows.append((ticker, run_id, run_day))
    return rows


def _closest_run_id(ticker: str, on_day: date | None, index: list[tuple[str, str, date | None]]) -> str:
    best_id = ""
    best_distance = 10**9
    for candidate_ticker, run_id, run_day in index:
        if candidate_ticker != ticker:
            continue
        if on_day is None or run_day is None:
            distance = 10**6
        else:
            distance = abs((on_day - run_day).days)
        if distance < best_distance:
            best_distance = distance
            best_id = run_id
    return best_id


def propagate_run_links(
    history: dict | None = None,
    *,
    research_path: Path | None = None,
    decision_path: Path | None = None,
    journal_path: Path | None = None,
    save: bool = True,
) -> dict[str, int]:
    """Fill blank research_run_id fields. Does not overwrite an existing link."""
    research_file = research_path or RESEARCH_HISTORY_PATH
    decision_file = decision_path or DECISION_HISTORY_PATH
    journal_file = journal_path or TRADE_JOURNAL_PATH
    if history is None:
        loaded = _load_json(research_file, {"runs": []})
        history = loaded if isinstance(loaded, dict) else {"runs": []}

    outcome_links = 0
    for run in history.get("runs", []):
        run_id = str(run.get("run_id") or "")
        if not run_id:
            continue
        for candidate in run.get("candidates") or []:
            outcome = candidate.get("outcome")
            if isinstance(outcome, dict) and not outcome.get("research_run_id"):
                outcome["research_run_id"] = run_id
                outcome_links += 1

    index = _research_index(history)
    journal = _load_json(journal_file, [])
    journal_links = 0
    if isinstance(journal, list):
        for entry in journal:
            if not isinstance(entry, dict) or entry.get("research_run_id"):
                continue
            ticker = _journal_ticker(entry)
            run_id = _closest_run_id(ticker, _journal_day(entry), index)
            if not run_id:
                continue
            entry["research_run_id"] = run_id
            journal_links += 1

    decisions = _load_json(decision_file, [])
    decision_links = 0
    if isinstance(decisions, list):
        for record in decisions:
            if not isinstance(record, dict):
                continue
            run_id = str(record.get("research_run_id") or record.get("run_id") or "")
            if record.get("run_id") and not record.get("research_run_id"):
                record["research_run_id"] = record.get("run_id")
                decision_links += 1
            for key in ("proposal_records", "pass_records"):
                for item in record.get(key) or []:
                    if isinstance(item, dict) and run_id and not item.get("research_run_id"):
                        item["research_run_id"] = run_id
                        decision_links += 1

    if save:
        if outcome_links and research_path is None:
            # Caller that already holds history saves the research file itself.
            pass
        if journal_links and isinstance(journal, list):
            journal_file.parent.mkdir(parents=True, exist_ok=True)
            journal_file.write_text(json.dumps(journal, indent=2, ensure_ascii=False))
        if decision_links and isinstance(decisions, list):
            decision_file.parent.mkdir(parents=True, exist_ok=True)
            decision_file.write_text(json.dumps(decisions, indent=2, ensure_ascii=False))

    return {
        "outcome_links": outcome_links,
        "journal_links": journal_links,
        "decision_links": decision_links,
    }

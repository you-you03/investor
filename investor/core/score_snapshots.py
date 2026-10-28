"""Helpers for tracking scored tickers after research/watchlist reviews."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from investor.config import settings
from investor.tools.market_tools import get_stock_snapshot
from investor.supabase_sync import sync_local_to_supabase
from investor.utils.logger import get_logger

logger = get_logger(__name__)

SNAPSHOTS_PATH = Path("data/score_snapshots.json")
GATE_COUNTERFACTUAL_PATH = Path("data/gate_pass_counterfactuals.json")
TRACKING_HORIZON_WEEKS = tuple(range(1, settings.evaluation_horizon_weeks + 1))
WEEK_KEYS = tuple(f"week{week}" for week in TRACKING_HORIZON_WEEKS)

CONVICTION_SCORE = {
    "HIGH": 8.0,
    "MEDIUM": 7.0,
    "LOW": 6.0,
}

FACTOR_KEYS = ("momentum", "fundamentals", "catalyst", "technical", "sentiment")

SEMICONDUCTOR_TICKERS = {
    "NVDA", "AMD", "AVGO", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MU",
    "MRVL", "ARM", "ALAB", "COHR", "AAOI", "CRDO", "ON", "QCOM", "INTC",
}
SOFTWARE_TICKERS = {
    "TEAM", "CRM", "NOW", "SNOW", "DDOG", "CRWD", "PANW", "NET", "MDB",
    "PLTR", "ADBE", "MSFT", "ORCL", "ZS", "OKTA",
}
INDUSTRIAL_TICKERS = {"VRT", "ETN", "GE", "HON", "CAT", "DE"}
UTILITY_TICKERS = {"VST", "CEG", "NEE", "SO", "DUK", "TLN"}
SPACE_TICKERS = {"ASTS", "RKLB", "LUNR", "IRDM"}
FINANCIAL_TICKERS = {"JPM", "BAC", "GS", "MS", "C", "WFC", "SCHW", "HOOD"}
HEALTHCARE_TICKERS = {"WAT", "LLY", "NVO", "UNH", "ISRG", "TMO", "DHR"}
ENERGY_TICKERS = {"XOM", "CVX", "COP", "SLB", "OXY"}
AIRLINE_TICKERS = {"UAL", "DAL", "AAL", "LUV"}


def infer_conviction(score: float | int | None = None, conviction: str | None = None) -> str:
    """Normalize explicit conviction or infer it from the 0-10 score."""
    normalized = (conviction or "").strip().upper()
    if normalized in {"HIGH", "MEDIUM", "LOW"}:
        return normalized
    if score is None:
        return ""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return ""
    if value >= 8.0:
        return "HIGH"
    if value >= 7.0:
        return "MEDIUM"
    return "LOW"


def score_from_result(result: dict[str, Any]) -> float | None:
    """Return the score used for follow-up tracking."""
    for key in ("score", "new_score"):
        if result.get(key) is not None:
            try:
                return float(result[key])
            except (TypeError, ValueError):
                return None
    conviction = infer_conviction(conviction=result.get("conviction"))
    return CONVICTION_SCORE.get(conviction)


def conviction_source_from_result(result: dict[str, Any]) -> str:
    """Track whether conviction was explicitly assigned or inferred from score."""
    normalized = (result.get("conviction") or "").strip().upper()
    if normalized in {"HIGH", "MEDIUM", "LOW"}:
        return "explicit"
    if result.get("score") is not None or result.get("new_score") is not None:
        return "inferred_from_score"
    return "missing"


def _normalize_grade(value: Any) -> str:
    grade = str(value or "").strip().upper()
    return grade if grade in {"A", "B", "C", "D"} else ""


def factor_grades_from_result(result: dict[str, Any]) -> dict[str, str]:
    """Extract per-factor quality grades from explicit fields or score_evidence."""
    explicit = result.get("factor_grades") or result.get("quality_grades") or {}
    evidence = result.get("score_evidence") or {}
    grades: dict[str, str] = {}
    for factor in FACTOR_KEYS:
        grade = (
            explicit.get(factor)
            or result.get(f"{factor}_grade")
            or evidence.get(f"{factor}_grade")
        )
        if isinstance(evidence.get(factor), dict):
            grade = grade or evidence[factor].get(f"{factor}_grade") or evidence[factor].get("grade")
        grades[factor] = _normalize_grade(grade)
    return grades


_CATALYST_MISSING_MARKERS = (
    "data missing",
    "data_missing",
    "no news",
    "news unavailable",
    "news missing",
    "analyst data missing",
    "catalyst data missing",
    "catalyst missing",
    "insufficient catalyst",
    "missing catalyst",
    "データ不足",
    "ニュースなし",
    "材料不明",
    "材料データなし",
)


def classify_catalyst_data(result: dict[str, Any]) -> tuple[str, bool]:
    """Separate a real weak catalyst from missing news or analyst data.

    Returns ``(status, missing)`` where status is ``present``, ``weak``, or
    ``missing``. Missing means the catalyst score must not enter IC aggregation.
    """
    status = str(result.get("catalyst_data_status") or "").strip().lower()
    if result.get("catalyst_data_missing") is True or status == "missing":
        return "missing", True
    if status == "weak":
        return "weak", False
    if status == "present":
        return "present", False

    grades = factor_grades_from_result(result)
    grade = grades.get("catalyst") or ""
    breakdown = result.get("score_breakdown") or {}
    has_score = breakdown.get("catalyst") is not None
    evidence = result.get("score_evidence") or {}
    catalyst_evidence = evidence.get("catalyst")
    if isinstance(catalyst_evidence, dict):
        evidence_text = " ".join(str(value) for value in catalyst_evidence.values())
    else:
        evidence_text = str(catalyst_evidence or "")
    gap_flags = [str(flag) for flag in (result.get("data_gap_flags") or [])]
    blob = " ".join(
        [
            evidence_text,
            str(result.get("data_notes") or ""),
            str(result.get("catalyst_quality") or ""),
            " ".join(gap_flags),
        ]
    ).lower()
    gap_hit = any(
        any(token in flag.lower() for token in ("catalyst", "news", "analyst"))
        and any(token in flag.lower() for token in ("missing", "gap", "unavailable", "不足"))
        for flag in gap_flags
    )
    if gap_hit or any(marker in blob for marker in _CATALYST_MISSING_MARKERS):
        return "missing", True

    quality = str(result.get("catalyst_quality") or "").strip().upper()
    if quality == "WEAK" or grade == "D":
        return "weak", False
    if grade in {"A", "B", "C"} or has_score or evidence_text.strip():
        return "present", False
    return "missing", True


def gate_pass_counterfactual_from_fields(
    primary_mode: str | None,
    extension_risk: str | None,
) -> dict[str, Any] | None:
    """Record a chase/extension block so later week returns can grade the gate."""
    mode = str(primary_mode or "").strip().upper()
    extension = str(extension_risk or "").strip().upper()
    if mode != "CHASE_MOMENTUM" and extension != "HIGH":
        return None
    return {
        "gate": "CHASE_OR_EXTENSION",
        "primary_mode": mode,
        "extension_risk": extension,
        "recorded": True,
        "evaluate_horizons": ["week4", "week12"],
        "note": (
            "Scored while the live chase/extension gate would block a BUY. "
            "Week returns on the linked snapshot are the counterfactual path."
        ),
    }


def gate_pass_counterfactual_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
    explicit = result.get("gate_pass_counterfactual")
    if isinstance(explicit, dict) and explicit.get("gate"):
        return explicit
    profile = result.get("momentum_profile") or {}
    return gate_pass_counterfactual_from_fields(
        profile.get("primary_mode") or result.get("momentum_primary_mode"),
        profile.get("extension_risk") or result.get("extension_risk"),
    )


def _counterfactual_entry(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    counterfactual = snapshot.get("gate_pass_counterfactual")
    if not isinstance(counterfactual, dict) or not counterfactual.get("gate"):
        profile = snapshot.get("momentum_profile") or {}
        counterfactual = gate_pass_counterfactual_from_fields(
            snapshot.get("momentum_primary_mode") or profile.get("primary_mode"),
            snapshot.get("extension_risk") or profile.get("extension_risk"),
        )
    if not counterfactual:
        return None
    return {
        "run_id": snapshot.get("run_id") or "",
        "ticker": str(snapshot.get("ticker") or "").upper(),
        "source": snapshot.get("source") or "research",
        "scored_at": snapshot.get("scored_at") or "",
        "score": snapshot.get("score"),
        "strategy_version": snapshot.get("strategy_version") or "",
        "gate": counterfactual.get("gate"),
        "primary_mode": counterfactual.get("primary_mode") or "",
        "extension_risk": counterfactual.get("extension_risk") or "",
        "evaluate_horizons": counterfactual.get("evaluate_horizons") or ["week4", "week12"],
        "note": counterfactual.get("note") or "",
        "week4": _horizon_outcome(snapshot, "week4"),
        "week12": _horizon_outcome(snapshot, "week12"),
    }


def _horizon_outcome(snapshot: dict[str, Any], week: str) -> dict[str, Any] | None:
    """Copy a fetched week outcome onto the gate index. None means not due yet."""
    payload = snapshot.get(week) or {}
    if not isinstance(payload, dict) or payload.get("fetched_at") is None:
        return None
    alpha = payload.get("alpha_vs_spy", payload.get("alpha_pct"))
    if alpha is None and payload.get("return_pct") is None:
        return None
    return {
        "return_pct": payload.get("return_pct"),
        "alpha_vs_spy": alpha,
        "fetched_at": payload.get("fetched_at"),
    }


def _merge_counterfactual_entry(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Keep the first index row and fill week outcomes from a later duplicate."""
    merged = dict(existing)
    for week in ("week4", "week12"):
        if merged.get(week) is None and incoming.get(week) is not None:
            merged[week] = incoming[week]
    return merged


def rebuild_gate_counterfactual_index(
    *,
    snapshots_path: Path | None = None,
    index_path: Path | None = None,
) -> int:
    """Write the chase/extension counterfactual index without changing scores.

    Historical snapshots are indexed from ``momentum_primary_mode`` and
    ``extension_risk``. The index is the join key for week4/week12 outcomes.
    """
    data = _load_snapshots(snapshots_path)
    entries: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], int] = {}
    for snapshot in data.get("snapshots", []):
        entry = _counterfactual_entry(snapshot)
        if entry is None or not entry["ticker"]:
            continue
        key = (str(entry["run_id"]), entry["ticker"], str(entry["source"]))
        if key in seen:
            index = seen[key]
            entries[index] = _merge_counterfactual_entry(entries[index], entry)
            continue
        seen[key] = len(entries)
        entries.append(entry)
    entries.sort(key=lambda row: (str(row.get("scored_at") or ""), row["ticker"], str(row.get("run_id") or "")))
    payload = {
        "description": (
            "Tickers scored while CHASE_MOMENTUM or extension_risk=HIGH would "
            "block a live BUY. week4 and week12 are copied from the linked "
            "score snapshot when fetched. Null means the horizon is not in yet. "
            "This file does not authorize trades."
        ),
        "as_of": date.today().isoformat(),
        "entries": entries,
    }
    target = index_path or GATE_COUNTERFACTUAL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return len(entries)


def sector_etf_for_ticker(ticker: str) -> str:
    """Map a ticker to the benchmark ETF used for sector-adjusted alpha."""
    symbol = ticker.upper()
    if symbol in SEMICONDUCTOR_TICKERS:
        return "SMH"
    if symbol in SOFTWARE_TICKERS:
        return "IGV"
    if symbol in INDUSTRIAL_TICKERS:
        return "XLI"
    if symbol in UTILITY_TICKERS:
        return "XLU"
    if symbol in SPACE_TICKERS:
        return "ARKK"
    if symbol in FINANCIAL_TICKERS:
        return "XLF"
    if symbol in HEALTHCARE_TICKERS:
        return "XLV"
    if symbol in ENERGY_TICKERS:
        return "XLE"
    if symbol in AIRLINE_TICKERS:
        return "JETS"
    return "QQQ"


def classify_market_regime(
    spy_return_pct: float | None,
    qqq_return_pct: float | None,
    sector_return_pct: float | None,
    vix_change_pct: float | None,
    ten_year_yield_change_bps: float | None,
) -> str:
    """Classify the broad regime for a scored ticker's follow-up window."""
    spy = spy_return_pct
    qqq = qqq_return_pct
    sector = sector_return_pct
    vix = vix_change_pct
    yield_bps = ten_year_yield_change_bps

    if spy is None:
        return "unknown"
    if spy <= -2.0 or (vix is not None and vix >= 15.0):
        return "risk_off"
    if yield_bps is not None and yield_bps >= 20.0 and qqq is not None and qqq < spy:
        return "rates_headwind"
    if sector is not None and sector >= spy + 2.0:
        return "sector_tailwind"
    if spy >= 2.0 and qqq is not None and qqq >= spy and (vix is None or vix <= 5.0):
        return "risk_on_growth"
    if spy >= 2.0:
        return "risk_on"
    return "neutral"


def _load_snapshots(path: Path | None = None) -> dict[str, Any]:
    target = path or SNAPSHOTS_PATH
    if target.exists():
        try:
            data = json.loads(target.read_text())
            for snapshot in data.get("snapshots", []):
                ensure_tracking_horizons(snapshot)
            return data
        except Exception:
            pass
    return {"snapshots": []}


def _save_snapshots(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or SNAPSHOTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _fetch_price(ticker: str) -> tuple[float | None, str]:
    try:
        raw = json.loads(get_stock_snapshot(ticker))
    except Exception as e:
        logger.warning("snapshot price fetch failed for %s: %s", ticker, e)
        return None, ""
    price = raw.get("price") or raw.get("current_price")
    company_name = raw.get("company_name") or raw.get("name") or ""
    try:
        return float(price), str(company_name or "")
    except (TypeError, ValueError):
        return None, str(company_name or "")


def _empty_weeks(scored_at: date) -> dict[str, dict[str, Any]]:
    return {
        f"week{week}": {
            "target_date": (scored_at + timedelta(days=7 * week)).isoformat(),
            "price": None,
            "return_pct": None,
            "spy_return_pct": None,
            "qqq_return_pct": None,
            "sector_etf": None,
            "sector_return_pct": None,
            "alpha_pct": None,
            "alpha_vs_spy": None,
            "alpha_vs_qqq": None,
            "alpha_vs_sector": None,
            "vix_change_pct": None,
            "ten_year_yield_change_bps": None,
            "market_regime": None,
            "fetched_at": None,
        }
        for week in TRACKING_HORIZON_WEEKS
    }


def ensure_tracking_horizons(snapshot: dict[str, Any]) -> bool:
    """Backfill missing horizon checkpoints on older snapshot records."""
    scored_at_raw = snapshot.get("scored_at")
    if not scored_at_raw:
        return False

    try:
        scored_at = date.fromisoformat(str(scored_at_raw))
    except ValueError:
        return False

    changed = False
    for week_key, payload in _empty_weeks(scored_at).items():
        if week_key not in snapshot:
            snapshot[week_key] = payload
            changed = True
        elif snapshot[week_key].get("sector_etf") is None:
            snapshot[week_key]["sector_etf"] = snapshot.get("sector_etf")
            changed = True
    return changed


def add_score_snapshots(
    *,
    run_id: str,
    source: str,
    results: list[dict[str, Any]],
    scored_at: date | None = None,
) -> int:
    """Append scored tickers to score_snapshots.json for multi-week tracking."""
    scored_date = scored_at or date.today()
    data = _load_snapshots()
    snapshots = data.setdefault("snapshots", [])
    existing_keys = {
        (
            str(item.get("run_id")),
            str(item.get("ticker", "")).upper(),
            str(item.get("source", "research")),
        )
        for item in snapshots
    }

    added = 0
    total = len(results)
    for rank, result in enumerate(results, 1):
        ticker = str(result.get("ticker") or "").upper()
        if not ticker:
            continue
        score = score_from_result(result)
        if score is None:
            continue
        key = (run_id, ticker, source)
        if key in existing_keys:
            continue

        price = result.get("price_at_score") or result.get("entry_price")
        company_name = result.get("company_name") or ""
        if price is None:
            price, fetched_name = _fetch_price(ticker)
            company_name = company_name or fetched_name
        try:
            price_at_score = float(price)
        except (TypeError, ValueError):
            logger.warning("skip score snapshot without price: %s", ticker)
            continue

        conviction = infer_conviction(score=score, conviction=result.get("conviction"))
        conviction_source = conviction_source_from_result(result)
        momentum_profile = result.get("momentum_profile") or {}
        factor_grades = factor_grades_from_result(result)
        score_evidence = result.get("score_evidence") or {}
        catalyst_status, catalyst_missing = classify_catalyst_data(result)
        risk_reasons = result.get("blocked_by_risk_reasons") or []
        if isinstance(risk_reasons, str):
            risk_reasons = [risk_reasons]
        elif not isinstance(risk_reasons, list):
            risk_reasons = [str(risk_reasons)]
        snapshot = {
            "run_id": run_id,
            "source": source,
            "strategy_version": result.get("strategy_version") or settings.strategy_version,
            "scored_at": scored_date.isoformat(),
            "ticker": ticker,
            "company_name": company_name,
            "score": round(score, 2),
            "conviction": conviction,
            "conviction_source": conviction_source,
            "score_breakdown": result.get("score_breakdown") or {},
            "score_evidence": score_evidence,
            "factor_grades": factor_grades,
            "fundamentals_grade": factor_grades.get("fundamentals") or "",
            "catalyst_grade": factor_grades.get("catalyst") or "",
            "technical_grade": factor_grades.get("technical") or "",
            "momentum_grade": factor_grades.get("momentum") or "",
            "sentiment_grade": factor_grades.get("sentiment") or "",
            "momentum_profile": momentum_profile,
            "momentum_primary_mode": momentum_profile.get("primary_mode") or "",
            "early_momentum_score": momentum_profile.get("early_momentum_score"),
            "chase_momentum_score": momentum_profile.get("chase_momentum_score"),
            "extension_risk": momentum_profile.get("extension_risk") or "",
            "blocked_by_risk": bool(result.get("blocked_by_risk")) or bool(risk_reasons),
            "blocked_by_risk_reasons": [str(reason) for reason in risk_reasons],
            "gate_pass_counterfactual": gate_pass_counterfactual_from_result(result),
            "catalyst_data_status": catalyst_status,
            "catalyst_data_missing": catalyst_missing,
            "conviction_rationale": result.get("conviction_rationale") or "",
            "rank_in_run": rank,
            "total_scored_in_run": total,
            "price_at_score": round(price_at_score, 4),
            "passed_threshold": score >= 7.5,
            "sector_etf": sector_etf_for_ticker(ticker),
            "macro_regime": result.get("macro_regime") or "",
        }
        snapshot.update(_empty_weeks(scored_date))
        for wk_key in WEEK_KEYS:
            snapshot[wk_key]["sector_etf"] = snapshot["sector_etf"]
        snapshots.append(snapshot)
        existing_keys.add(key)
        added += 1

    if added:
        _save_snapshots(data)
        rebuild_gate_counterfactual_index(snapshots_path=SNAPSHOTS_PATH)
        logger.info("Added %d score snapshot(s) from %s | run_id=%s", added, source, run_id)
        sync_local_to_supabase("score_snapshots")
    return added

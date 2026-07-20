#!/usr/bin/env python3
"""Build a local static HTML dashboard for score reliability metrics.

The generated HTML contains only data snapshots, never Supabase credentials.
Run after applying supabase/migrations/012_score_reliability_dashboard_views.sql
and after syncing validation stats with scripts/validate_scores.py.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from investor.supabase_store import SupabaseStore, get_store


DEFAULT_OUTPUT_PATH = Path("reports/score_reliability_dashboard.html")
CONVICTIONS = ("HIGH", "MEDIUM", "LOW")
WEEK_KEYS = tuple(f"week{i}" for i in range(1, 9))
FACTORS = ("momentum", "fundamentals", "catalyst", "technical", "sentiment")
SCORE_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("≥ 8.5", 8.5, None),
    ("8.0–8.4", 8.0, 8.5),
    ("7.5–7.9", 7.5, 8.0),
    ("7.0–7.4", 7.0, 7.5),
    ("< 7.0", None, 7.0),
)

VIEW_SPECS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("summary", "score_reliability_summary", {"select": "*"}),
    ("horizonLatest", "score_reliability_horizon_latest", {"select": "*", "order": "horizon_weeks.asc"}),
    ("horizonHistory", "score_reliability_horizon_history", {"select": "*", "order": "validation_date.asc,horizon_weeks.asc"}),
    ("thresholdLatest", "score_reliability_threshold_latest", {"select": "*", "order": "horizon_weeks.asc"}),
    ("thresholdHistory", "score_reliability_threshold_history", {"select": "*", "order": "validation_date.asc,horizon_weeks.asc"}),
    ("factorLatest", "score_reliability_factor_latest", {"select": "*", "order": "factor.asc,horizon_weeks.asc"}),
    ("maturity", "score_reliability_maturity", {"select": "*", "order": "horizon_weeks.asc"}),
    ("returnDistribution", "score_reliability_return_distribution", {"select": "*", "order": "horizon_weeks.asc,return_pct.asc"}),
    ("scoreScatter", "score_reliability_score_scatter", {"select": "*", "order": "score.asc", "limit": "500"}),
    ("suggestions", "score_reliability_suggestions", {"select": "*", "order": "suggestion_order.asc"}),
)


def fetch_dashboard_data(store: SupabaseStore) -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        for key, view_name, params in VIEW_SPECS:
            data[key] = store.select(view_name, params)
    except RuntimeError as exc:
        if "score_reliability_" not in str(exc) and "PGRST205" not in str(exc):
            raise
        data = fetch_dashboard_data_from_base_tables(store)
    _attach_local_conviction_data(data)
    data["generatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    data.setdefault("sourceViews", [view for _, view, _ in VIEW_SPECS])
    return data


def fetch_dashboard_data_from_base_tables(store: SupabaseStore) -> dict[str, Any]:
    runs = store.select(
        "validation_runs",
        {"select": "validation_id,validation_date,period_start,period_end,snapshot_count,passed_threshold_count,rejected_threshold_count", "order": "validation_date.desc", "limit": "50"},
    )
    latest = runs[0] if runs else {}
    latest_id = latest.get("validation_id")
    run_date_by_id = {row.get("validation_id"): row.get("validation_date") for row in runs}

    horizon_all = _with_validation_dates(
        store.select("validation_horizon_ic", {"select": "*", "limit": "5000"}),
        run_date_by_id,
    )
    threshold_all = _with_validation_dates(
        store.select("validation_threshold_comparison", {"select": "*", "limit": "5000"}),
        run_date_by_id,
    )
    factor_latest = _sort_by_horizon([
        _shape_factor({**row, "validation_date": latest.get("validation_date")}) for row in store.select(
            "validation_factor_ic",
            {"select": "*", "validation_id": f"eq.{latest_id}", "limit": "5000"},
        )
    ]) if latest_id else []
    suggestions = store.select(
        "validation_calibration_suggestions",
        {"select": "suggestion_order,suggestion", "validation_id": f"eq.{latest_id}", "order": "suggestion_order.asc"},
    ) if latest_id else []
    snapshots = _dedupe_snapshots(store.select(
        "score_snapshots",
        {"select": "ticker,scored_at,score,passed_threshold,macro_regime,sector_etf,week1,week2,week3,week4,week5,week6,week7,week8", "limit": "5000"},
    ))

    horizon_history = _sort_history([_shape_horizon(row) for row in horizon_all])
    threshold_history = _sort_history([_shape_threshold(row) for row in threshold_all])
    horizon_latest = [row for row in horizon_history if row.get("validation_date") == latest.get("validation_date")]
    threshold_latest = [row for row in threshold_history if row.get("validation_date") == latest.get("validation_date")]

    data = {
        "summary": [_shape_summary(latest, horizon_latest, threshold_latest)] if latest else [],
        "horizonLatest": _sort_by_horizon(horizon_latest),
        "horizonHistory": horizon_history,
        "thresholdLatest": _sort_by_horizon(threshold_latest),
        "thresholdHistory": threshold_history,
        "factorLatest": factor_latest,
        "maturity": _build_maturity(snapshots),
        "returnDistribution": _build_return_distribution(snapshots),
        "scoreScatter": _build_score_scatter(snapshots),
        "scoreBucketReliability": _build_score_bucket_reliability_rows(snapshots),
        "scoreBucketObservations": _build_score_bucket_observation_rows(snapshots),
        "convictionReliability": _build_conviction_reliability_rows(snapshots),
        "convictionHorizon": _build_conviction_horizon_rows(snapshots),
        "convictionScoreBuckets": _build_conviction_score_bucket_rows(snapshots),
        "convictionObservations": _build_conviction_observation_rows(snapshots),
        "suggestions": suggestions,
        "sourceViews": [],
        "sourceTables": ["validation_runs", "validation_horizon_ic", "validation_threshold_comparison", "validation_factor_ic", "validation_calibration_suggestions", "score_snapshots"],
    }
    _attach_aggregation_modes(data, snapshots)
    return data


def fetch_dashboard_data_from_local_files() -> dict[str, Any]:
    snapshots = _load_local_snapshots()
    horizon_latest = _build_local_horizon_latest(snapshots)
    threshold_latest = _build_local_threshold_latest(snapshots)
    data = {
        "summary": [_build_local_summary(snapshots, horizon_latest, threshold_latest)] if snapshots else [],
        "horizonLatest": horizon_latest,
        "horizonHistory": horizon_latest,
        "thresholdLatest": threshold_latest,
        "thresholdHistory": threshold_latest,
        "factorLatest": _build_local_factor_latest(snapshots),
        "maturity": _build_maturity(snapshots),
        "returnDistribution": _build_return_distribution(snapshots),
        "scoreScatter": _build_score_scatter(snapshots),
        "scoreBucketReliability": _build_score_bucket_reliability_rows(snapshots),
        "scoreBucketObservations": _build_score_bucket_observation_rows(snapshots),
        "convictionReliability": _build_conviction_reliability_rows(snapshots),
        "convictionHorizon": _build_conviction_horizon_rows(snapshots),
        "convictionScoreBuckets": _build_conviction_score_bucket_rows(snapshots),
        "convictionObservations": _build_conviction_observation_rows(snapshots),
        "suggestions": [],
        "sourceViews": [],
        "sourceTables": ["data/score_snapshots.json"],
    }
    _attach_aggregation_modes(data, snapshots)
    data["generatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return data


def _build_aggregation_mode_data(snapshots: list[dict], aggregation_mode: str) -> dict[str, Any]:
    horizon_latest = _build_local_horizon_latest(snapshots, aggregation_mode)
    threshold_latest = _build_local_threshold_latest(snapshots, aggregation_mode)
    return {
        "summary": [_build_local_summary(snapshots, horizon_latest, threshold_latest)] if snapshots else [],
        "horizonLatest": horizon_latest,
        "horizonHistory": [],
        "thresholdLatest": threshold_latest,
        "thresholdHistory": [],
        "factorLatest": _build_local_factor_latest(snapshots, aggregation_mode),
        "maturity": _build_maturity(snapshots),
        "returnDistribution": _build_return_distribution(snapshots, aggregation_mode),
        "scoreScatter": _build_score_scatter(snapshots, aggregation_mode),
        "scoreBucketReliability": _build_score_bucket_reliability_rows(snapshots, aggregation_mode),
        "scoreBucketObservations": _build_score_bucket_observation_rows(snapshots, aggregation_mode),
        "convictionReliability": _build_conviction_reliability_rows(snapshots, aggregation_mode),
        "convictionHorizon": _build_conviction_horizon_rows(snapshots, aggregation_mode),
        "convictionScoreBuckets": _build_conviction_score_bucket_rows(snapshots, aggregation_mode),
        "convictionObservations": _build_conviction_observation_rows(snapshots, aggregation_mode),
    }


def _attach_aggregation_modes(data: dict[str, Any], snapshots: list[dict]) -> None:
    if not snapshots:
        data.setdefault("aggregationModes", {})
        return
    modes = {
        "first": _build_aggregation_mode_data(snapshots, "first"),
        "all": _build_aggregation_mode_data(snapshots, "all"),
    }
    for mode_data in modes.values():
        mode_data["suggestions"] = data.get("suggestions", [])
    data["aggregationModes"] = modes
    data["aggregationMode"] = "first"


def _load_local_snapshots() -> list[dict]:
    path = ROOT_DIR / "data" / "score_snapshots.json"
    if not path.exists():
        return []
    try:
        return _dedupe_snapshots(json.loads(path.read_text()).get("snapshots", []))
    except (json.JSONDecodeError, OSError):
        return []


def _snapshot_completeness(snapshot: dict) -> tuple[int, int, int, int]:
    company_present = 1 if snapshot.get("company_name") else 0
    week_returns = sum(
        1
        for week in range(1, 9)
        if _to_float(_week_data(snapshot, week).get("return_pct")) is not None
    )
    breakdown_present = 1 if snapshot.get("score_breakdown") else 0
    conviction_present = 1 if snapshot.get("conviction") else 0
    return (company_present, week_returns, breakdown_present, conviction_present)


def _dedupe_snapshots(snapshots: list[dict]) -> list[dict]:
    unique: dict[tuple[str, str], dict] = {}
    passthrough: list[dict] = []
    for snapshot in snapshots:
        ticker = str(snapshot.get("ticker") or "").strip().upper()
        scored_at = str(snapshot.get("scored_at") or "").strip()[:10]
        if not ticker or not scored_at:
            passthrough.append(snapshot)
            continue
        key = (ticker, scored_at)
        current = unique.get(key)
        if current is None or _snapshot_completeness(snapshot) > _snapshot_completeness(current):
            unique[key] = snapshot
    return [*passthrough, *unique.values()]


def _attach_local_conviction_data(data: dict[str, Any]) -> None:
    snapshots = _load_local_snapshots()
    if not snapshots:
        data.setdefault("aggregationModes", {})
        data.setdefault("scoreBucketReliability", [])
        data.setdefault("scoreBucketObservations", [])
        data.setdefault("convictionReliability", [])
        data.setdefault("convictionHorizon", [])
        data.setdefault("convictionScoreBuckets", [])
        return
    _attach_aggregation_modes(data, snapshots)


def _horizon_weeks(horizon: Any) -> int | None:
    digits = "".join(ch for ch in str(horizon or "") if ch.isdigit())
    return int(digits) if digits else None


def _with_validation_dates(rows: list[dict], run_date_by_id: dict[Any, Any]) -> list[dict]:
    shaped = []
    for row in rows:
        item = dict(row)
        item["validation_date"] = run_date_by_id.get(row.get("validation_id"))
        shaped.append(item)
    return [row for row in shaped if row.get("validation_date")]


def _sort_by_horizon(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (row.get("horizon_weeks") is None, row.get("horizon_weeks") or 0, str(row.get("factor") or "")))


def _sort_history(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (str(row.get("validation_date") or ""), row.get("horizon_weeks") or 0))


def _shape_horizon(row: dict) -> dict:
    return {
        "validation_date": row.get("validation_date"),
        "horizon": row.get("horizon"),
        "horizon_weeks": _horizon_weeks(row.get("horizon")),
        "sample_count": row.get("sample_count"),
        "spearman_rho": row.get("spearman_rho"),
        "p_value": row.get("p_value"),
        "label": row.get("label"),
    }


def _shape_threshold(row: dict) -> dict:
    passed = _to_float(row.get("passed_avg_return_pct"))
    rejected = _to_float(row.get("rejected_avg_return_pct"))
    spread = None if passed is None or rejected is None else passed - rejected
    return {
        "validation_date": row.get("validation_date"),
        "horizon": row.get("horizon"),
        "horizon_weeks": _horizon_weeks(row.get("horizon")),
        "passed_avg_return_pct": passed,
        "rejected_avg_return_pct": rejected,
        "spread_return_pct": spread,
    }


def _shape_factor(row: dict) -> dict:
    sample_count = _to_float(row.get("sample_count")) or 0
    rho = _to_float(row.get("spearman_rho"))
    factor = row.get("factor")
    judgement = _judge_factor(sample_count, rho)
    return {
        "validation_date": row.get("validation_date"),
        "factor": factor,
        "horizon": row.get("horizon"),
        "horizon_weeks": _horizon_weeks(row.get("horizon")),
        "sample_count": row.get("sample_count"),
        "spearman_rho": rho,
        "judgement": judgement,
        "action": _factor_action(factor, rho),
    }


def _judge_factor(sample_count: float, rho: float | None) -> str:
    if sample_count < 30:
        return "判断保留"
    if rho is not None and rho >= 0.30:
        return "強い: 配点引き上げ候補"
    if rho is not None and rho >= 0.15:
        return "有効: 配点維持"
    if rho is not None and rho > 0:
        return "弱い: 補助扱い"
    return "弱い/逆効果: 配点引き下げ候補"


def _factor_action(factor: Any, rho: float | None) -> str:
    if factor == "fundamentals" and rho is not None and rho >= 0.20:
        return "BUY根拠として重視"
    if factor in ("technical", "catalyst") and (rho is None or rho < 0.10):
        return "単独の買い理由にしない"
    if factor == "sentiment" and rho is not None and rho >= 0.15:
        return "補助材料として使う"
    return "継続監視"


def _shape_summary(latest: dict, horizons: list[dict], thresholds: list[dict]) -> dict:
    by_horizon = {row.get("horizon"): row for row in horizons}
    by_threshold = {row.get("horizon"): row for row in thresholds}
    week4_ic = _to_float((by_horizon.get("week4") or {}).get("spearman_rho"))
    week8_ic = _to_float((by_horizon.get("week8") or {}).get("spearman_rho"))
    week4_spread = _to_float((by_threshold.get("week4") or {}).get("spread_return_pct"))
    week8_spread = _to_float((by_threshold.get("week8") or {}).get("spread_return_pct"))
    row = dict(latest)
    row.update({
        "week4_ic": week4_ic,
        "week4_sample_count": (by_horizon.get("week4") or {}).get("sample_count"),
        "week4_p_value": (by_horizon.get("week4") or {}).get("p_value"),
        "week8_ic": week8_ic,
        "week8_sample_count": (by_horizon.get("week8") or {}).get("sample_count"),
        "week8_p_value": (by_horizon.get("week8") or {}).get("p_value"),
        "week4_threshold_spread": week4_spread,
        "week8_threshold_spread": week8_spread,
    })
    row["overall_judgement"] = _overall_judgement(week4_ic, week8_ic, week4_spread, week8_spread)
    row["recommended_action"] = _recommended_action(_to_float(latest.get("snapshot_count")) or 0, week4_ic, week4_spread)
    return row


def _overall_judgement(week4_ic: float | None, week8_ic: float | None, week4_spread: float | None, week8_spread: float | None) -> str:
    if week4_ic is not None and week4_ic >= 0.20 and week4_spread is not None and week4_spread > 0:
        return "使える: 4週目線の候補選別に有効"
    if week8_ic is not None and week8_ic >= 0.20 and week8_spread is not None and week8_spread > 0:
        return "条件付きで使える: 長めの保有期間では有効"
    if week4_spread is not None and week4_spread > 0:
        return "足切りには使える: ランキング精度は弱い"
    return "要見直し: スコア閾値または配点の再検証が必要"


def _recommended_action(snapshot_count: float, week4_ic: float | None, week4_spread: float | None) -> str:
    if snapshot_count < 30:
        return "判断保留: 検証データを蓄積"
    if week4_ic is not None and week4_ic >= 0.20 and week4_spread is not None and week4_spread > 0:
        return "score>=7.0を候補順位付けに使う"
    if week4_spread is not None and week4_spread > 0:
        return "score>=7.0を足切りに使い、順位付けは補助扱い"
    return "次回/reviewで配点と閾値を見直す"


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 2)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 2)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    pos = (len(ordered) - 1) * pct
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo), 2)


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) - 1 and indexed[j + 1][1] == indexed[j][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def _spearman(x_values: list[float], y_values: list[float]) -> float | None:
    if len(x_values) < 3:
        return None
    x_ranks = _rank(x_values)
    y_ranks = _rank(y_values)
    x_mean = sum(x_ranks) / len(x_ranks)
    y_mean = sum(y_ranks) / len(y_ranks)
    numerator = sum((x_ranks[i] - x_mean) * (y_ranks[i] - y_mean) for i in range(len(x_ranks)))
    x_den = sum((value - x_mean) ** 2 for value in x_ranks) ** 0.5
    y_den = sum((value - y_mean) ** 2 for value in y_ranks) ** 0.5
    if x_den == 0 or y_den == 0:
        return None
    return round(numerator / (x_den * y_den), 4)


def _local_ic_label(sample_count: int, rho: float | None) -> str:
    if sample_count < 30:
        return f"データ不足（N={sample_count} < 30）"
    if rho is not None and rho >= 0.40:
        return "強い正の相関"
    if rho is not None and rho >= 0.20:
        return "正の相関あり"
    if rho is not None and rho >= 0.05:
        return "弱い正の相関"
    return "相関なし"


def _week_data(snapshot: dict, week: int) -> dict:
    data = snapshot.get(f"week{week}") or {}
    return data if isinstance(data, dict) else {}


def _ticker_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _scored_at_key(value: Any) -> str:
    return str(value or "").strip()[:10]


def _first_rows_by_ticker(rows: list[dict]) -> list[dict]:
    first: dict[str, dict] = {}
    for row in sorted(rows, key=lambda item: (_ticker_key(item.get("ticker")), _scored_at_key(item.get("scored_at")), str(item.get("ticker") or ""))):
        ticker = _ticker_key(row.get("ticker"))
        if ticker and ticker not in first:
            first[ticker] = row
    return list(first.values())


def _first_snapshots_by_ticker(snapshots: list[dict]) -> list[dict]:
    return _first_rows_by_ticker(snapshots)


def _rows_for_aggregation_mode(rows: list[dict], aggregation_mode: str) -> list[dict]:
    return rows if aggregation_mode == "all" else _first_rows_by_ticker(rows)


def _snapshots_for_aggregation_mode(snapshots: list[dict], aggregation_mode: str) -> list[dict]:
    return snapshots if aggregation_mode == "all" else _first_snapshots_by_ticker(snapshots)


def _build_local_horizon_latest(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    rows = []
    for week in range(1, 9):
        signal_rows = []
        for snapshot in snapshots:
            score = _to_float(snapshot.get("score"))
            ret = _to_float(_week_data(snapshot, week).get("return_pct"))
            if score is None or ret is None or abs(ret) > 100:
                continue
            signal_rows.append({
                "ticker": snapshot.get("ticker"),
                "scored_at": snapshot.get("scored_at"),
                "score": score,
                "return_pct": ret,
            })
        first_rows = _rows_for_aggregation_mode(signal_rows, aggregation_mode)
        pairs = [(row["score"], row["return_pct"]) for row in first_rows]
        rho = _spearman([pair[0] for pair in pairs], [pair[1] for pair in pairs]) if len(pairs) >= 3 else None
        rows.append({
            "validation_date": datetime.now().date().isoformat(),
            "horizon": f"week{week}",
            "horizon_weeks": week,
            "sample_count": len(pairs),
            "spearman_rho": rho,
            "p_value": None,
            "label": _local_ic_label(len(pairs), rho),
        })
    return rows


def _build_local_threshold_latest(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    rows = []
    for week in range(1, 9):
        passed = []
        rejected = []
        for snapshot in _snapshots_for_aggregation_mode([
            snapshot
            for snapshot in snapshots
            if _to_float(_week_data(snapshot, week).get("return_pct")) is not None
        ], aggregation_mode):
            ret = _to_float(_week_data(snapshot, week).get("return_pct"))
            if ret is None or abs(ret) > 100:
                continue
            target = passed if snapshot.get("passed_threshold") else rejected
            target.append(ret)
        passed_avg = _mean(passed)
        rejected_avg = _mean(rejected)
        spread = None if passed_avg is None or rejected_avg is None else round(passed_avg - rejected_avg, 2)
        rows.append({
            "validation_date": datetime.now().date().isoformat(),
            "horizon": f"week{week}",
            "horizon_weeks": week,
            "passed_avg_return_pct": passed_avg,
            "rejected_avg_return_pct": rejected_avg,
            "spread_return_pct": spread,
        })
    return rows


def _build_local_factor_latest(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    rows = []
    for factor in FACTORS:
        for week in range(1, 9):
            signal_rows = []
            for snapshot in snapshots:
                factor_score = _to_float((snapshot.get("score_breakdown") or {}).get(factor))
                ret = _to_float(_week_data(snapshot, week).get("return_pct"))
                if factor_score is None or ret is None or abs(ret) > 100:
                    continue
                signal_rows.append({
                    "ticker": snapshot.get("ticker"),
                    "scored_at": snapshot.get("scored_at"),
                    "factor_score": factor_score,
                    "return_pct": ret,
                })
            first_rows = _rows_for_aggregation_mode(signal_rows, aggregation_mode)
            pairs = [(row["factor_score"], row["return_pct"]) for row in first_rows]
            rho = _spearman([pair[0] for pair in pairs], [pair[1] for pair in pairs]) if len(pairs) >= 3 else None
            rows.append(_shape_factor({
                "validation_date": datetime.now().date().isoformat(),
                "factor": factor,
                "horizon": f"week{week}",
                "sample_count": len(pairs),
                "spearman_rho": rho,
            }))
    return _sort_by_horizon(rows)


def _build_local_summary(snapshots: list[dict], horizons: list[dict], thresholds: list[dict]) -> dict:
    latest = {
        "validation_date": datetime.now().date().isoformat(),
        "period_start": min((s.get("scored_at") for s in snapshots if s.get("scored_at")), default=None),
        "period_end": max((s.get("scored_at") for s in snapshots if s.get("scored_at")), default=None),
        "snapshot_count": len(snapshots),
        "passed_threshold_count": sum(1 for snapshot in snapshots if snapshot.get("passed_threshold")),
        "rejected_threshold_count": sum(1 for snapshot in snapshots if not snapshot.get("passed_threshold")),
    }
    return _shape_summary(latest, horizons, thresholds)


def _infer_conviction_from_score(score: Any) -> str:
    value = _to_float(score)
    if value is None:
        return ""
    if value >= 8.0:
        return "HIGH"
    if value >= 7.0:
        return "MEDIUM"
    return "LOW"


def _snapshot_conviction(snapshot: dict) -> tuple[str, str]:
    conviction = str(snapshot.get("conviction") or "").strip().upper()
    source = str(snapshot.get("conviction_source") or "").strip().lower()
    if conviction in CONVICTIONS:
        return conviction, source or "stored"
    inferred = _infer_conviction_from_score(snapshot.get("score"))
    if inferred:
        return inferred, "inferred_from_score"
    return "", "missing"


def _week_rows_for_conviction(snapshots: list[dict], week: int) -> list[dict]:
    rows = []
    for snapshot in snapshots:
        data = _week_data(snapshot, week)
        ret = _to_float(data.get("return_pct"))
        if data.get("fetched_at") is None or ret is None or abs(ret) > 100:
            continue
        conviction, source = _snapshot_conviction(snapshot)
        if conviction not in CONVICTIONS:
            continue
        alpha_spy = _to_float(data.get("alpha_vs_spy", data.get("alpha_pct")))
        alpha_sector = _to_float(data.get("alpha_vs_sector"))
        rows.append({
            "ticker": snapshot.get("ticker"),
            "scored_at": snapshot.get("scored_at"),
            "score": _to_float(snapshot.get("score")),
            "conviction": conviction,
            "conviction_source": source,
            "return_pct": ret,
            "alpha_spy_pct": alpha_spy,
            "alpha_sector_pct": alpha_sector,
        })
    return rows


def _conviction_stat(rows: list[dict]) -> dict:
    returns = [row["return_pct"] for row in rows]
    alpha_spy = [row["alpha_spy_pct"] for row in rows if row["alpha_spy_pct"] is not None]
    losses = [value for value in returns if value < 0]
    return {
        "sample_count": len(returns),
        "explicit_count": sum(1 for row in rows if row["conviction_source"] == "explicit"),
        "stored_count": sum(1 for row in rows if row["conviction_source"] == "stored"),
        "inferred_count": sum(1 for row in rows if row["conviction_source"] == "inferred_from_score"),
        "win_rate_pct": round(sum(1 for value in returns if value > 0) / len(returns) * 100, 1) if returns else None,
        "alpha_win_rate_pct": round(sum(1 for value in alpha_spy if value > 0) / len(alpha_spy) * 100, 1) if alpha_spy else None,
        "avg_return_pct": _mean(returns),
        "median_return_pct": _median(returns),
        "avg_alpha_spy_pct": _mean(alpha_spy),
        "loss_rate_pct": round(len(losses) / len(returns) * 100, 1) if returns else None,
        "avg_loss_pct": _mean(losses),
        "p10_return_pct": _percentile(returns, 0.10),
    }


def _conviction_order_label(stats_by_conviction: dict[str, dict]) -> str:
    values = {key: stats_by_conviction.get(key, {}).get("avg_alpha_spy_pct") for key in CONVICTIONS}
    if any(values[key] is None for key in CONVICTIONS):
        values = {key: stats_by_conviction.get(key, {}).get("avg_return_pct") for key in CONVICTIONS}
    if any(values[key] is None for key in CONVICTIONS):
        return "判断保留"
    if values["HIGH"] > values["MEDIUM"] > values["LOW"]:
        return "順序性あり"
    if values["HIGH"] >= values["MEDIUM"] >= values["LOW"]:
        return "弱い順序性あり"
    if values["HIGH"] < values["MEDIUM"]:
        return "HIGH過信の疑い"
    if values["MEDIUM"] < values["LOW"]:
        return "MEDIUM/LOW分類に歪み"
    return "順序性なし"


def _conviction_ic_label(sample_count: int, rho: float | None) -> str:
    if sample_count < 30:
        return "判断保留: N<30"
    if rho is not None and rho >= 0.30:
        return "強い: サイズ差に使える"
    if rho is not None and rho >= 0.15:
        return "有効: 補助判断に使える"
    if rho is not None and rho >= 0.05:
        return "弱い: 過信しない"
    return "効いていない"


def _build_conviction_horizon_rows(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    rows = []
    ordinal = {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 3.0}
    for week in range(1, 9):
        week_rows = _rows_for_aggregation_mode(_week_rows_for_conviction(snapshots, week), aggregation_mode)
        stats_by_conviction = {
            conviction: _conviction_stat([row for row in week_rows if row["conviction"] == conviction])
            for conviction in CONVICTIONS
        }
        pairs = [(ordinal[row["conviction"]], row["return_pct"]) for row in week_rows]
        rho = _spearman([pair[0] for pair in pairs], [pair[1] for pair in pairs]) if len(pairs) >= 3 else None
        rows.append({
            "horizon": f"week{week}",
            "horizon_weeks": week,
            "sample_count": len(week_rows),
            "explicit_count": sum(1 for row in week_rows if row["conviction_source"] == "explicit"),
            "stored_count": sum(1 for row in week_rows if row["conviction_source"] == "stored"),
            "inferred_count": sum(1 for row in week_rows if row["conviction_source"] == "inferred_from_score"),
            "conviction_ic": rho,
            "order_label": _conviction_order_label(stats_by_conviction),
            "judgement": _conviction_ic_label(len(week_rows), rho),
        })
    return rows


def _build_conviction_reliability_rows(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    rows = []
    for week in range(1, 9):
        week_rows = _rows_for_aggregation_mode(_week_rows_for_conviction(snapshots, week), aggregation_mode)
        for conviction in CONVICTIONS:
            stat = _conviction_stat([row for row in week_rows if row["conviction"] == conviction])
            rows.append({
                "horizon": f"week{week}",
                "horizon_weeks": week,
                "conviction": conviction,
                **stat,
            })
    return rows


def _score_in_bucket(score: float, lo: float | None, hi: float | None) -> bool:
    if lo is not None and score < lo:
        return False
    if hi is not None and score >= hi:
        return False
    return True


def _build_conviction_score_bucket_rows(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    rows = []
    week_rows = _rows_for_aggregation_mode(_week_rows_for_conviction(snapshots, 4), aggregation_mode)
    for bucket_label, lo, hi in SCORE_BUCKETS:
        bucket_rows = [
            row for row in week_rows
            if row.get("score") is not None and _score_in_bucket(float(row["score"]), lo, hi)
        ]
        for conviction in CONVICTIONS:
            stat = _conviction_stat([row for row in bucket_rows if row["conviction"] == conviction])
            rows.append({
                "score_bucket": bucket_label,
                "conviction": conviction,
                **stat,
            })
    return rows


def _score_bucket_for_score(score: Any) -> str:
    value = _to_float(score)
    if value is None:
        return ""
    for bucket_label, lo, hi in SCORE_BUCKETS:
        if _score_in_bucket(value, lo, hi):
            return bucket_label
    return ""


def _week_rows_for_score_bucket(snapshots: list[dict], week: int) -> list[dict]:
    rows = []
    for snapshot in snapshots:
        score = _to_float(snapshot.get("score"))
        bucket = _score_bucket_for_score(score)
        data = _week_data(snapshot, week)
        ret = _to_float(data.get("return_pct"))
        if not bucket or ret is None or abs(ret) > 100:
            continue
        alpha_spy = _to_float(data.get("alpha_vs_spy", data.get("alpha_pct", data.get("alpha_spy_pct"))))
        rows.append({
            "ticker": snapshot.get("ticker"),
            "scored_at": snapshot.get("scored_at"),
            "score": score,
            "score_bucket": bucket,
            "return_pct": ret,
            "alpha_spy_pct": alpha_spy,
        })
    return rows


def _score_bucket_stat(rows: list[dict]) -> dict:
    returns = [row["return_pct"] for row in rows]
    alpha_spy = [row["alpha_spy_pct"] for row in rows if row["alpha_spy_pct"] is not None]
    losses = [value for value in returns if value < 0]
    return {
        "sample_count": len(returns),
        "win_rate_pct": round(sum(1 for value in returns if value > 0) / len(returns) * 100, 1) if returns else None,
        "alpha_win_rate_pct": round(sum(1 for value in alpha_spy if value > 0) / len(alpha_spy) * 100, 1) if alpha_spy else None,
        "avg_return_pct": _mean(returns),
        "median_return_pct": _median(returns),
        "avg_alpha_spy_pct": _mean(alpha_spy),
        "loss_rate_pct": round(len(losses) / len(returns) * 100, 1) if returns else None,
        "avg_loss_pct": _mean(losses),
        "p10_return_pct": _percentile(returns, 0.10),
    }


def _build_score_bucket_reliability_rows(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    rows = []
    for week in range(1, 9):
        week_rows = _rows_for_aggregation_mode(_week_rows_for_score_bucket(snapshots, week), aggregation_mode)
        for bucket_label, _, _ in SCORE_BUCKETS:
            stat = _score_bucket_stat([row for row in week_rows if row["score_bucket"] == bucket_label])
            rows.append({
                "horizon": f"week{week}",
                "horizon_weeks": week,
                "score_bucket": bucket_label,
                **stat,
            })
    return rows


def _observation_week_values(snapshot: dict, week: int) -> dict:
    data = _week_data(snapshot, week)
    ret = _to_float(data.get("return_pct"))
    alpha_spy = _to_float(data.get("alpha_vs_spy", data.get("alpha_pct", data.get("alpha_spy_pct"))))
    return {
        "return_pct": ret,
        "alpha_spy_pct": alpha_spy,
        "win_rate_pct": 100.0 if ret is not None and ret > 0 else 0.0 if ret is not None else None,
        "alpha_win_rate_pct": 100.0 if alpha_spy is not None and alpha_spy > 0 else 0.0 if alpha_spy is not None else None,
        "loss_rate_pct": 100.0 if ret is not None and ret < 0 else 0.0 if ret is not None else None,
        "p10_return_pct": ret,
    }


def _build_score_bucket_observation_rows(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    bucket_rank = {bucket_label: index for index, (bucket_label, _, _) in enumerate(SCORE_BUCKETS)}
    rows = []
    for snapshot in snapshots:
        score = _to_float(snapshot.get("score"))
        bucket = _score_bucket_for_score(score)
        if not bucket:
            continue
        conviction, source = _snapshot_conviction(snapshot)
        weeks = {
            f"week{week}": _observation_week_values(snapshot, week)
            for week in range(1, 9)
        }
        if not any(payload["return_pct"] is not None for payload in weeks.values()):
            continue
        rows.append({
            "ticker": snapshot.get("ticker"),
            "company_name": snapshot.get("company_name"),
            "score_bucket": bucket,
            "conviction": conviction,
            "conviction_source": source,
            "scored_at": snapshot.get("scored_at"),
            "score": score,
            "weeks": weeks,
        })
    rows = _rows_for_aggregation_mode(rows, aggregation_mode)
    return sorted(
        rows,
        key=lambda row: (
            bucket_rank.get(row.get("score_bucket"), 99),
            str(row.get("scored_at") or ""),
            str(row.get("ticker") or ""),
        ),
    )


def _build_conviction_observation_rows(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    conviction_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    rows = []
    for snapshot in snapshots:
        conviction, source = _snapshot_conviction(snapshot)
        if conviction not in CONVICTIONS:
            continue
        weeks = {
            f"week{week}": _observation_week_values(snapshot, week)
            for week in range(1, 9)
        }
        if not any(payload["return_pct"] is not None for payload in weeks.values()):
            continue
        rows.append({
            "ticker": snapshot.get("ticker"),
            "company_name": snapshot.get("company_name"),
            "conviction": conviction,
            "conviction_source": source,
            "scored_at": snapshot.get("scored_at"),
            "score": _to_float(snapshot.get("score")),
            "weeks": weeks,
        })
    rows = _rows_for_aggregation_mode(rows, aggregation_mode)
    return sorted(
        rows,
        key=lambda row: (
            conviction_rank.get(row.get("conviction"), 99),
            str(row.get("scored_at") or ""),
            str(row.get("ticker") or ""),
        ),
    )


def _build_maturity(snapshots: list[dict]) -> list[dict]:
    today = datetime.now().date()
    rows = []
    for week in range(1, 9):
        total = matured = fetched = 0
        for snapshot in snapshots:
            data = _week_data(snapshot, week)
            if not data:
                continue
            total += 1
            target_date = str(data.get("target_date") or "")[:10]
            if target_date:
                try:
                    matured += datetime.fromisoformat(target_date).date() <= today
                except ValueError:
                    pass
            if data.get("return_pct") is not None:
                fetched += 1
        fetched_pct = round(fetched / total * 100, 1) if total else None
        rows.append({
            "horizon_weeks": week,
            "horizon": f"week{week}",
            "total_observations": total,
            "matured_count": matured,
            "fetched_count": fetched,
            "fetched_pct": fetched_pct,
            "judgement": "十分" if fetched >= 50 else "最低限OK" if fetched >= 30 else "判断保留",
        })
    return rows


def _build_return_distribution(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    rows = []
    for week in range(1, 9):
        week_snapshots = [
            snapshot
            for snapshot in snapshots
            if _to_float(_week_data(snapshot, week).get("return_pct")) is not None
        ]
        for snapshot in _snapshots_for_aggregation_mode(week_snapshots, aggregation_mode):
            value = _to_float(_week_data(snapshot, week).get("return_pct"))
            if value is None or abs(value) > 100:
                continue
            rows.append({"horizon_weeks": week, "horizon": f"week{week}", "return_pct": round(value, 2)})
    return sorted(rows, key=lambda row: (row["horizon_weeks"], row["return_pct"]))


def _build_score_scatter(snapshots: list[dict], aggregation_mode: str = "first") -> list[dict]:
    rows = []
    for snapshot in snapshots:
        score = _to_float(snapshot.get("score"))
        ret = _to_float(_week_data(snapshot, 4).get("return_pct"))
        if score is None or score <= 6 or ret is None or abs(ret) > 100:
            continue
        week4 = _week_data(snapshot, 4)
        rows.append({
            "ticker": snapshot.get("ticker"),
            "scored_at": snapshot.get("scored_at"),
            "score": round(score, 2),
            "passed_threshold": snapshot.get("passed_threshold"),
            "macro_regime": snapshot.get("macro_regime"),
            "sector_etf": snapshot.get("sector_etf"),
            "week4_return_pct": round(ret, 2),
            "week4_alpha_spy_pct": _to_float(week4.get("alpha_spy_pct")),
            "week4_alpha_qqq_pct": _to_float(week4.get("alpha_qqq_pct")),
            "week4_alpha_sector_pct": _to_float(week4.get("alpha_sector_pct")),
        })
    rows = _rows_for_aggregation_mode(rows, aggregation_mode)
    return sorted(rows, key=lambda row: (row["score"], row["week4_return_pct"]))[:500]


def _json_for_script(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).replace("</", "<\\/")


def _format_generated_at(data: dict[str, Any]) -> str:
    generated = str(data.get("generatedAt") or "")
    return html.escape(generated.replace("T", " "))


def build_html(data: dict[str, Any]) -> str:
    payload = _json_for_script(data)
    generated_at = _format_generated_at(data)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Score Reliability Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg:#fafafa; --surface:#fff; --line:#e8e8e8; --line2:#f3f3f3;
      --ink:#111; --muted:#666; --faint:#999; --pos:#15803d; --neg:#b91c1c; --warn:#b45309;
      --blue:#2563eb; --radius:8px; --mono:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
      --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }}
    *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:13px/1.55 var(--sans)}}
    .wrap{{max-width:1320px;margin:0 auto;padding:30px 42px 70px}}
    header{{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:22px}}
    h1{{font-size:18px;margin:0;font-weight:650;letter-spacing:0}} .meta{{font:12px var(--mono);color:var(--faint)}}
    .grid{{display:grid;gap:14px}} .kpis{{grid-template-columns:1.4fr repeat(4,1fr);margin-bottom:24px}}
    .two{{grid-template-columns:1fr 1fr}} .wide{{grid-template-columns:1.2fr .8fr}}
    .card{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;min-width:0}}
    .label{{font-size:11px;color:var(--faint);font-weight:650;letter-spacing:.04em;text-transform:uppercase;margin-bottom:6px}}
    .value{{font:600 24px/1.15 var(--mono);letter-spacing:0;overflow-wrap:anywhere}} .sub{{color:var(--muted);margin-top:7px}}
    .judgement{{font-size:18px;font-weight:650;line-height:1.35}} .action{{margin-top:10px;color:var(--muted)}}
    .conclusion{{margin-bottom:18px;border-color:#d7dfd9;background:#fbfdfb}}
    .conclusion-grid{{display:grid;grid-template-columns:1.4fr 1fr;gap:16px;align-items:start}}
    .conclusion-title{{font-size:20px;font-weight:700;line-height:1.35;margin:0 0 8px}}
    .conclusion-lead{{font-size:14px;color:var(--muted);margin:0}}
    .conclusion-list{{display:grid;gap:7px;margin:0;padding:0;list-style:none}}
    .conclusion-list li{{display:flex;gap:8px;align-items:flex-start;color:var(--muted)}}
    .dot{{width:7px;height:7px;border-radius:50%;background:var(--ink);margin-top:7px;flex:0 0 auto}}
    .dot.pos{{background:var(--pos)}} .dot.warn{{background:var(--warn)}} .dot.neg{{background:var(--neg)}}
    .pos{{color:var(--pos)}} .neg{{color:var(--neg)}} .warn{{color:var(--warn)}} .blue{{color:var(--blue)}} .muted{{color:var(--faint)}}
    .section{{margin-top:26px}} .section h2{{font-size:14px;margin:0 0 10px;border-bottom:1px solid var(--line);padding-bottom:8px}}
    table{{width:100%;border-collapse:collapse;font-size:12px}} th{{text-align:left;color:var(--faint);font-size:10px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--line);padding:7px 8px;white-space:nowrap}}
    td{{padding:8px;border-top:1px solid var(--line2);vertical-align:top}} tr:hover td{{background:#fcfcfc}}
    .num{{font-family:var(--mono);text-align:right}} .chip{{display:inline-flex;border:1px solid var(--line);border-radius:4px;padding:1px 6px;font:10px var(--mono);white-space:nowrap}}
    .chip.ok{{color:var(--pos);border-color:#b8e0c4}} .chip.bad{{color:var(--neg);border-color:#f0b8b8}} .chip.warn{{color:var(--warn);border-color:#e5c48a}}
	    .chart{{height:310px}} .chart-sm{{height:250px}} canvas{{width:100%!important;height:100%!important}}
	    .controls{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}}
	    .tabs{{display:flex;gap:8px;margin:0 0 18px}} .tab,.metric-tab{{border:1px solid var(--line);background:var(--surface);border-radius:6px;padding:7px 12px;font-weight:650;color:var(--muted);cursor:pointer}}
	    .tab.active,.metric-tab.active{{border-color:#b8c7f0;color:var(--blue);background:#f7f9ff}} .page{{display:none}} .page.active{{display:block}}
	    .mode-bar{{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:0 0 18px;padding:10px 12px;border:1px solid var(--line);border-radius:6px;background:var(--surface)}}
	    .mode-bar .sub{{margin-top:0}}
	    .metric-tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}}
	    .metric-info{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:14px}}
	    .metric-card{{border:1px solid var(--line2);border-radius:6px;padding:10px 12px;background:#fcfcfc}}
	    .metric-card{{cursor:pointer;text-align:left}} .metric-card:hover{{border-color:#cbd5e1;background:#f8fafc}}
	    .metric-card strong{{display:block;font-size:12px;margin-bottom:4px}} .metric-card span{{display:block;color:var(--muted);font-size:12px;line-height:1.45}}
	    .toggle-row{{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:16px;padding-top:14px;border-top:1px solid var(--line2)}}
	    .toggle-button{{border:1px solid var(--line);background:white;border-radius:6px;padding:7px 10px;font-weight:650;color:var(--ink);cursor:pointer}}
	    .detail-panel{{display:none;margin-top:12px;max-height:520px;overflow:auto;border:1px solid var(--line2);border-radius:6px}}
	    .detail-panel.open{{display:block}} .detail-panel table{{font-size:11px}} .sticky-head th{{position:sticky;top:0;background:white;z-index:1}}
	    select,input{{border:1px solid var(--line);border-radius:5px;background:white;padding:5px 8px;font:12px var(--mono);color:var(--ink)}}
    .suggestions{{display:flex;flex-direction:column;gap:8px}} .suggestion{{border-left:3px solid var(--warn);padding:8px 10px;background:#fffaf2;border-radius:4px;color:#5f3a05}}
    @media(max-width:900px){{.wrap{{padding:20px 16px 50px}} header{{align-items:flex-start;flex-direction:column}} .kpis,.two,.wide,.conclusion-grid{{grid-template-columns:1fr}} .value{{font-size:21px}}}}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>Score Reliability Dashboard</h1>
        <div class="meta">Generated: {generated_at}</div>
      </div>
      <div class="meta">Source: Supabase score reliability views</div>
    </header>

	    <nav class="tabs">
	      <button class="tab active" data-page="scorePage">Score</button>
	      <button class="tab" data-page="convictionPage">Conviction</button>
	    </nav>
	    <div class="mode-bar">
	      <div>
	        <div class="label">取得モード</div>
	        <div class="sub">全グラフ・表の集計単位を切り替え</div>
	      </div>
	      <select id="aggregationModeSelect">
	        <option value="first">初回のみ</option>
	        <option value="all">全シグナル</option>
	      </select>
	    </div>

	    <main id="scorePage" class="page active">
	      <section id="conclusionSummary" class="card conclusion"></section>

	      <div id="kpis" class="grid kpis"></div>

	      <section class="section grid wide">
	        <div class="card">
	          <h2>何週後にスコアが効いているか</h2>
	          <div id="horizonTable"></div>
	        </div>
	        <div class="card">
	          <h2>キャリブレーション提案</h2>
	          <div id="suggestions" class="suggestions"></div>
	        </div>
	      </section>

	      <section class="section card">
	        <h2>Score Bucket別 指標推移</h2>
	        <div class="metric-tabs" id="scoreMetricTabs">
	          <button class="metric-tab active" data-metric="avg_return_pct">平均リターン</button>
	          <button class="metric-tab" data-metric="avg_alpha_spy_pct">SPY alpha</button>
	          <button class="metric-tab" data-metric="win_rate_pct">勝率</button>
	          <button class="metric-tab" data-metric="alpha_win_rate_pct">Alpha勝率</button>
	          <button class="metric-tab" data-metric="loss_rate_pct">損失率</button>
	          <button class="metric-tab" data-metric="p10_return_pct">P10</button>
	        </div>
	        <div class="chart"><canvas id="scoreMetricChart"></canvas></div>
	        <div class="metric-info" id="scoreMetricInfo"></div>
	        <div class="toggle-row">
	          <div>
	            <div class="label">銘柄別 週次観測値</div>
	            <div class="sub">現在選択中の指標を、score bucket順・取得日順で表示</div>
	          </div>
	          <button class="toggle-button" id="scoreObservationToggle" type="button" aria-expanded="false">銘柄別テーブルを開く</button>
	        </div>
	        <div class="detail-panel" id="scoreObservationPanel">
	          <div class="controls" style="padding:10px 10px 0">
	            <label class="meta">Score bucket</label>
	            <select id="scoreObservationFilter">
	              <option value="ALL">ALL</option>
	              <option value="≥ 8.5">≥ 8.5</option>
	              <option value="8.0–8.4">8.0–8.4</option>
	              <option value="7.5–7.9">7.5–7.9</option>
	              <option value="7.0–7.4">7.0–7.4</option>
	              <option value="< 7.0">&lt; 7.0</option>
	            </select>
	          </div>
	          <div id="scoreObservationTable"></div>
	        </div>
	      </section>

	      <section class="section grid two">
	        <div class="card"><h2>Score IC 現状</h2><div class="chart"><canvas id="scoreIcNowChart"></canvas></div></div>
	        <div class="card"><h2>IC履歴</h2><div class="chart"><canvas id="icChart"></canvas></div></div>
	      </section>

	      <section class="section grid two">
	        <div class="card"><h2>7.0閾値差分</h2><div class="chart"><canvas id="thresholdChart"></canvas></div></div>
	        <div class="card"><h2>ファクター別IC 推移</h2><div class="chart"><canvas id="factorIcChart"></canvas></div></div>
	      </section>

	      <section class="section grid two">
	        <div class="card"><h2>ファクター別IC</h2><div id="factorTable"></div></div>
	        <div class="card"><h2>データ成熟度</h2><div id="maturityTable"></div></div>
	      </section>

	      <section class="section grid two">
	        <div class="card">
	          <h2>スコアと4週後リターン</h2>
	          <div class="controls">
	            <label class="meta">外れ値</label>
	            <select id="scatterLimit"><option value="100">±100%</option><option value="50">±50%</option><option value="25">±25%</option></select>
	            <input id="tickerSearch" placeholder="ticker filter">
	          </div>
	          <div class="chart"><canvas id="scatterChart"></canvas></div>
	        </div>
	        <div class="card">
	          <h2>ホライゾン別リターン分布</h2>
	          <div class="chart"><canvas id="distributionChart"></canvas></div>
	        </div>
	      </section>
	    </main>

	    <main id="convictionPage" class="page">
	      <section id="convictionConclusion" class="card conclusion"></section>
	      <div id="convictionKpis" class="grid kpis"></div>
	      <section class="section grid two">
	        <div class="card"><h2>Conviction IC</h2><div class="chart"><canvas id="convictionIcChart"></canvas></div></div>
	        <div class="card"><h2>4週後 Conviction別リターン</h2><div class="chart"><canvas id="convictionReturnChart"></canvas></div></div>
	      </section>
		      <section class="section card">
		        <h2>Conviction別 指標推移</h2>
		        <div class="metric-tabs" id="convictionMetricTabs">
		          <button class="metric-tab active" data-metric="avg_return_pct">平均リターン</button>
		          <button class="metric-tab" data-metric="avg_alpha_spy_pct">SPY alpha</button>
		          <button class="metric-tab" data-metric="win_rate_pct">勝率</button>
		          <button class="metric-tab" data-metric="alpha_win_rate_pct">Alpha勝率</button>
		          <button class="metric-tab" data-metric="loss_rate_pct">損失率</button>
		          <button class="metric-tab" data-metric="p10_return_pct">P10</button>
		        </div>
		        <div class="chart"><canvas id="convictionMetricChart"></canvas></div>
		        <div class="metric-info" id="convictionMetricInfo"></div>
		        <div class="toggle-row">
		          <div>
		            <div class="label">銘柄別 週次観測値</div>
		            <div class="sub">現在選択中の指標を、conviction順・取得日順で表示</div>
		          </div>
		          <button class="toggle-button" id="convictionObservationToggle" type="button" aria-expanded="false">銘柄別テーブルを開く</button>
		        </div>
		        <div class="detail-panel" id="convictionObservationPanel">
		          <div class="controls" style="padding:10px 10px 0">
		            <label class="meta">Conviction</label>
		            <select id="convictionObservationFilter">
		              <option value="ALL">ALL</option>
		              <option value="HIGH">HIGH</option>
		              <option value="MEDIUM">MEDIUM</option>
		              <option value="LOW">LOW</option>
		            </select>
		          </div>
		          <div id="convictionObservationTable"></div>
		        </div>
		      </section>
		      <section class="section card">
		        <h2>ホライゾン別 Conviction 信頼性</h2>
		        <div id="convictionHorizonTable"></div>
		      </section>
	      <section class="section card">
	        <h2>Score Bucket内 Conviction差分（4週後）</h2>
	        <div id="convictionBucketTable"></div>
	      </section>
	    </main>
	  </div>

  <script>
    const DASHBOARD_DATA = {payload};
    let activeAggregationMode = DASHBOARD_DATA.aggregationMode || "first";
    let VIEW_DATA = (DASHBOARD_DATA.aggregationModes || {{}})[activeAggregationMode] || DASHBOARD_DATA;

    const fmt = {{
      pct: v => v === null || v === undefined || Number.isNaN(Number(v)) ? "N/A" : `${{Number(v).toFixed(1)}}%`,
      rho: v => v === null || v === undefined || Number.isNaN(Number(v)) ? "N/A" : Number(v).toFixed(2),
      n: v => v === null || v === undefined ? "0" : String(v),
    }};
    const colorByNumber = v => Number(v) > 0 ? "pos" : Number(v) < 0 ? "neg" : "muted";
    const chipClass = text => /使える|十分|OK|有効|強い/.test(text || "") ? "ok" : /見直し|無効|逆効果|効いていない/.test(text || "") ? "bad" : "warn";

    function cell(value, cls="") {{
      return `<td class="${{cls}}">${{value ?? ""}}</td>`;
    }}
    function renderTable(targetId, columns, rows) {{
      const head = columns.map(c => `<th class="${{c.cls || ""}}">${{c.label}}</th>`).join("");
      const body = rows.map(row => `<tr>${{columns.map(c => cell(c.render ? c.render(row) : row[c.key], c.cls || "")).join("")}}</tr>`).join("");
      document.getElementById(targetId).innerHTML = `<table><thead><tr>${{head}}</tr></thead><tbody>${{body || `<tr><td colspan="${{columns.length}}" class="muted">No data</td></tr>`}}</tbody></table>`;
    }}

    function renderKpis() {{
      const s = (VIEW_DATA.summary || [])[0] || {{}};
      const kpis = [
        `<div class="card"><div class="label">総合判定</div><div class="judgement">${{s.overall_judgement || "No validation data"}}</div><div class="action">${{s.recommended_action || ""}}</div></div>`,
        `<div class="card"><div class="label">検証データ</div><div class="value">${{fmt.n(s.snapshot_count)}}</div><div class="sub">passed ${{fmt.n(s.passed_threshold_count)}} / rejected ${{fmt.n(s.rejected_threshold_count)}}</div></div>`,
        `<div class="card"><div class="label">4週IC</div><div class="value ${{colorByNumber(s.week4_ic)}}">${{fmt.rho(s.week4_ic)}}</div><div class="sub">n=${{fmt.n(s.week4_sample_count)}} / p=${{fmt.rho(s.week4_p_value)}}</div></div>`,
        `<div class="card"><div class="label">8週IC</div><div class="value ${{colorByNumber(s.week8_ic)}}">${{fmt.rho(s.week8_ic)}}</div><div class="sub">n=${{fmt.n(s.week8_sample_count)}} / p=${{fmt.rho(s.week8_p_value)}}</div></div>`,
        `<div class="card"><div class="label">4週閾値差分</div><div class="value ${{colorByNumber(s.week4_threshold_spread)}}">${{fmt.pct(s.week4_threshold_spread)}}</div><div class="sub">score>=7.0 - score&lt;7.0</div></div>`,
      ];
      document.getElementById("kpis").innerHTML = kpis.join("");
    }}

    function renderConclusionSummary() {{
      const s = (VIEW_DATA.summary || [])[0] || {{}};
      const horizons = VIEW_DATA.horizonLatest || [];
      const factors = VIEW_DATA.factorLatest || [];
      const week4 = horizons.find(r => r.horizon === "week4") || {{}};
      const week4Factors = factors.filter(r => r.horizon === "week4" && r.spearman_rho !== null && r.spearman_rho !== undefined);
      const bestFactor = week4Factors.length ? [...week4Factors].sort((a,b) => Number(b.spearman_rho) - Number(a.spearman_rho))[0] : null;
      const weakFactor = week4Factors.length ? [...week4Factors].sort((a,b) => Number(a.spearman_rho) - Number(b.spearman_rho))[0] : null;
      const shortTermWeak = horizons.filter(r => Number(r.sample_count) >= 30 && Number(r.spearman_rho) < 0.2).map(r => `${{r.horizon_weeks}}週`);
      const judgement = s.overall_judgement || "検証データなし";
      const action = s.recommended_action || "データを蓄積してから判断";
      const titleClass = /要見直し|無効|効いていない/.test(judgement) ? "neg" : /条件付き|足切り|保留/.test(judgement) ? "warn" : "pos";
      const bullets = [
        {{cls:"pos", text:`4週ICは ${{fmt.rho(s.week4_ic ?? week4.spearman_rho)}}、score>=7.0の4週差分は ${{fmt.pct(s.week4_threshold_spread)}}。現時点では4週目線の足切りと候補順位付けに使える。`}},
        {{cls:"pos", text: bestFactor ? `最も効いているファクターは ${{bestFactor.factor}}（4週ρ=${{fmt.rho(bestFactor.spearman_rho)}}）。BUY根拠として重視する。` : "ファクター別データは蓄積中。"}},
        {{cls:"warn", text: weakFactor ? `弱いファクターは ${{weakFactor.factor}}（4週ρ=${{fmt.rho(weakFactor.spearman_rho)}}）。単独の買い理由にしない。` : "弱いファクターはまだ判定保留。"}},
        {{cls:"warn", text: shortTermWeak.length ? `${{shortTermWeak.join("・")}}のICは0.20未満。短期トレードの根拠としてスコアを単独使用しない。` : "短期ホライゾンも最低限の予測力を維持。"}},
      ];
      document.getElementById("conclusionSummary").innerHTML = `
        <div class="conclusion-grid">
          <div>
            <div class="label">結論サマリー</div>
            <h2 class="conclusion-title ${{titleClass}}">${{judgement}}</h2>
            <p class="conclusion-lead">${{action}}</p>
          </div>
          <ul class="conclusion-list">
            ${{bullets.map(b => `<li><span class="dot ${{b.cls}}"></span><span>${{b.text}}</span></li>`).join("")}}
          </ul>
        </div>`;
    }}

    function renderTables() {{
      renderTable("horizonTable", [
        {{key:"horizon_weeks", label:"週", cls:"num"}},
        {{key:"sample_count", label:"n", cls:"num"}},
        {{key:"spearman_rho", label:"IC", cls:"num", render:r=>`<span class="${{colorByNumber(r.spearman_rho)}}">${{fmt.rho(r.spearman_rho)}}</span>`}},
        {{key:"p_value", label:"p", cls:"num", render:r=>fmt.rho(r.p_value)}},
        {{key:"spearman_rho", label:"判定", render:r=>`<span class="chip ${{chipClass(judgeHorizon(r))}}">${{judgeHorizon(r)}}</span>`}},
        {{key:"spearman_rho", label:"運用", render:r=>actionHorizon(r)}},
      ], VIEW_DATA.horizonLatest || []);
      renderTable("factorTable", [
        {{key:"factor", label:"factor"}},
        {{key:"horizon_weeks", label:"週", cls:"num"}},
        {{key:"sample_count", label:"n", cls:"num"}},
        {{key:"spearman_rho", label:"IC", cls:"num", render:r=>`<span class="${{colorByNumber(r.spearman_rho)}}">${{fmt.rho(r.spearman_rho)}}</span>`}},
        {{key:"judgement", label:"判定", render:r=>`<span class="chip ${{chipClass(r.judgement)}}">${{r.judgement}}</span>`}},
        {{key:"action", label:"運用"}},
      ], VIEW_DATA.factorLatest || []);
      renderTable("maturityTable", [
        {{key:"horizon_weeks", label:"週", cls:"num"}},
        {{key:"total_observations", label:"全観測", cls:"num"}},
        {{key:"matured_count", label:"満期", cls:"num"}},
        {{key:"fetched_count", label:"取得済", cls:"num"}},
        {{key:"fetched_pct", label:"取得率", cls:"num", render:r=>fmt.pct(r.fetched_pct)}},
        {{key:"judgement", label:"判定", render:r=>`<span class="chip ${{chipClass(r.judgement)}}">${{r.judgement}}</span>`}},
      ], VIEW_DATA.maturity || []);
      const suggestions = VIEW_DATA.suggestions || [];
      document.getElementById("suggestions").innerHTML = suggestions.length
        ? suggestions.map(s => `<div class="suggestion">${{s.suggestion}}</div>`).join("")
        : `<div class="muted">No suggestions</div>`;
    }}

    function judgeHorizon(r) {{
      if (Number(r.sample_count) < 30) return "判断保留: N<30";
      if (Number(r.spearman_rho) >= 0.40) return "強い: 主要判断に使える";
      if (Number(r.spearman_rho) >= 0.20) return "使える: 過信しない";
      if (Number(r.spearman_rho) >= 0.05) return "弱い: 補助材料";
      return "効いていない";
    }}
	    function actionHorizon(r) {{
	      if (Number(r.sample_count) < 30) return "データ蓄積を待つ";
	      return Number(r.spearman_rho) >= 0.20 ? "候補順位付けに使う" : "スコア単独判断を避ける";
	    }}

	    function renderConvictionSummary() {{
	      const horizons = VIEW_DATA.convictionHorizon || [];
	      const week4 = horizons.find(r => r.horizon === "week4") || {{}};
	      const details = VIEW_DATA.convictionReliability || [];
	      const week4Details = details.filter(r => r.horizon === "week4");
	      const high = week4Details.find(r => r.conviction === "HIGH") || {{}};
	      const medium = week4Details.find(r => r.conviction === "MEDIUM") || {{}};
	      const low = week4Details.find(r => r.conviction === "LOW") || {{}};
	      const judgement = week4.judgement || "判断保留";
	      const order = week4.order_label || "判断保留";
	      const titleClass = /強い|有効|順序性あり/.test(judgement + order) ? "pos" : /効いていない|過信|歪み|なし/.test(judgement + order) ? "neg" : "warn";
	      const action = /過信/.test(order)
	        ? "HIGHのサイズ上限を下げるか、HIGH条件をfundamentals/catalystで再ゲートする"
	        : /有効|強い|順序性/.test(judgement + order)
	          ? "convictionをサイズ調整とBUY優先順位に使う"
	          : "convictionは補助扱いにし、scoreとrisk gateを優先する";
	      const bullets = [
	        {{cls:titleClass, text:`4週Conviction ICは ${{fmt.rho(week4.conviction_ic)}}、判定は「${{judgement}}」。`}},
	        {{cls:titleClass, text:`4週の順序性は「${{order}}」。HIGH/MEDIUM/LOW が期待値順になっているかを見る。`}},
	        {{cls:"pos", text:`HIGH: n=${{fmt.n(high.sample_count)}} / avg ${{fmt.pct(high.avg_return_pct)}} / alpha ${{fmt.pct(high.avg_alpha_spy_pct)}} / win ${{fmt.pct(high.win_rate_pct)}}。`}},
	        {{cls:"warn", text:`MEDIUM: n=${{fmt.n(medium.sample_count)}} / avg ${{fmt.pct(medium.avg_return_pct)}}。LOW: n=${{fmt.n(low.sample_count)}} / avg ${{fmt.pct(low.avg_return_pct)}}。`}},
	      ];
	      document.getElementById("convictionConclusion").innerHTML = `
	        <div class="conclusion-grid">
	          <div>
	            <div class="label">Conviction 結論</div>
	            <h2 class="conclusion-title ${{titleClass}}">${{order}}</h2>
	            <p class="conclusion-lead">${{action}}</p>
	          </div>
	          <ul class="conclusion-list">
	            ${{bullets.map(b => `<li><span class="dot ${{b.cls}}"></span><span>${{b.text}}</span></li>`).join("")}}
	          </ul>
	        </div>`;
	    }}

	    function renderConvictionKpis() {{
	      const horizons = VIEW_DATA.convictionHorizon || [];
	      const week4 = horizons.find(r => r.horizon === "week4") || {{}};
	      const details = VIEW_DATA.convictionReliability || [];
	      const high = details.find(r => r.horizon === "week4" && r.conviction === "HIGH") || {{}};
	      const medium = details.find(r => r.horizon === "week4" && r.conviction === "MEDIUM") || {{}};
	      const low = details.find(r => r.horizon === "week4" && r.conviction === "LOW") || {{}};
	      const kpis = [
	        `<div class="card"><div class="label">4週 Conviction判定</div><div class="judgement">${{week4.judgement || "No data"}}</div><div class="action">${{week4.order_label || ""}}</div></div>`,
	        `<div class="card"><div class="label">4週 Conviction IC</div><div class="value ${{colorByNumber(week4.conviction_ic)}}">${{fmt.rho(week4.conviction_ic)}}</div><div class="sub">n=${{fmt.n(week4.sample_count)}} / explicit ${{fmt.n(week4.explicit_count)}}</div></div>`,
	        `<div class="card"><div class="label">HIGH 4週 alpha</div><div class="value ${{colorByNumber(high.avg_alpha_spy_pct)}}">${{fmt.pct(high.avg_alpha_spy_pct)}}</div><div class="sub">win ${{fmt.pct(high.win_rate_pct)}} / n=${{fmt.n(high.sample_count)}}</div></div>`,
	        `<div class="card"><div class="label">MEDIUM 4週 alpha</div><div class="value ${{colorByNumber(medium.avg_alpha_spy_pct)}}">${{fmt.pct(medium.avg_alpha_spy_pct)}}</div><div class="sub">win ${{fmt.pct(medium.win_rate_pct)}} / n=${{fmt.n(medium.sample_count)}}</div></div>`,
	        `<div class="card"><div class="label">LOW 4週 alpha</div><div class="value ${{colorByNumber(low.avg_alpha_spy_pct)}}">${{fmt.pct(low.avg_alpha_spy_pct)}}</div><div class="sub">loss ${{fmt.pct(low.loss_rate_pct)}} / n=${{fmt.n(low.sample_count)}}</div></div>`,
	      ];
	      document.getElementById("convictionKpis").innerHTML = kpis.join("");
	    }}

	    function renderConvictionTables() {{
	      renderTable("convictionHorizonTable", [
	        {{key:"horizon_weeks", label:"週", cls:"num"}},
	        {{key:"sample_count", label:"n", cls:"num"}},
	        {{key:"explicit_count", label:"明示", cls:"num"}},
	        {{key:"stored_count", label:"保存", cls:"num"}},
	        {{key:"inferred_count", label:"推定", cls:"num"}},
	        {{key:"conviction_ic", label:"IC", cls:"num", render:r=>`<span class="${{colorByNumber(r.conviction_ic)}}">${{fmt.rho(r.conviction_ic)}}</span>`}},
	        {{key:"judgement", label:"判定", render:r=>`<span class="chip ${{chipClass(r.judgement)}}">${{r.judgement}}</span>`}},
	        {{key:"order_label", label:"順序性", render:r=>`<span class="chip ${{chipClass(r.order_label)}}">${{r.order_label}}</span>`}},
	      ], VIEW_DATA.convictionHorizon || []);
	      renderTable("convictionBucketTable", [
	        {{key:"score_bucket", label:"score bucket"}},
	        {{key:"conviction", label:"conviction"}},
	        {{key:"sample_count", label:"n", cls:"num"}},
	        {{key:"win_rate_pct", label:"勝率", cls:"num", render:r=>fmt.pct(r.win_rate_pct)}},
	        {{key:"avg_return_pct", label:"平均", cls:"num", render:r=>`<span class="${{colorByNumber(r.avg_return_pct)}}">${{fmt.pct(r.avg_return_pct)}}</span>`}},
	        {{key:"avg_alpha_spy_pct", label:"SPY alpha", cls:"num", render:r=>`<span class="${{colorByNumber(r.avg_alpha_spy_pct)}}">${{fmt.pct(r.avg_alpha_spy_pct)}}</span>`}},
	        {{key:"p10_return_pct", label:"P10", cls:"num", render:r=>fmt.pct(r.p10_return_pct)}},
	      ], (VIEW_DATA.convictionScoreBuckets || []).filter(r => Number(r.sample_count) > 0));
	    }}

	    const convictionMetricLabels = {{
	      avg_return_pct: "平均リターン %",
	      avg_alpha_spy_pct: "SPY alpha %",
	      win_rate_pct: "勝率 %",
	      alpha_win_rate_pct: "Alpha勝率 %",
	      loss_rate_pct: "損失率 %",
	      p10_return_pct: "P10 return %",
	    }};
	    const scoreMetricLabels = convictionMetricLabels;
	    const scoreBucketOrder = ["≥ 8.5", "8.0–8.4", "7.5–7.9", "7.0–7.4", "< 7.0"];
	    const scoreBucketColors = {{
	      "≥ 8.5": "#15803d",
	      "8.0–8.4": "#2563eb",
	      "7.5–7.9": "#7c3aed",
	      "7.0–7.4": "#b45309",
	      "< 7.0": "#b91c1c",
	    }};
	    const scoreMetricDescriptions = {{
	      avg_return_pct: ["平均リターン", "score bucketごとの銘柄リターン平均。高スコアほど絶対成績が高いかを見る。"],
	      avg_alpha_spy_pct: ["SPY alpha", "同期間のSPYに対する超過リターン。スコアが市場超過に効いているかを見る。"],
	      win_rate_pct: ["勝率", "リターンが0%を上回った割合。高スコアほど勝ちやすいかを見る。"],
	      alpha_win_rate_pct: ["Alpha勝率", "SPY alphaが0%を上回った割合。市場に勝った観測頻度を見る。"],
	      loss_rate_pct: ["損失率", "リターンが0%未満だった割合。高スコアの下振れ頻度を見る。"],
	      p10_return_pct: ["P10", "下位10%地点のリターン。高スコアでも悪いケースが深すぎないかを見る。"],
	    }};
		    const convictionColors = {{
	      HIGH: "#15803d",
	      MEDIUM: "#2563eb",
	      LOW: "#b45309",
		    }};
	    const convictionMetricDescriptions = {{
	      avg_return_pct: ["平均リターン", "各convictionの銘柄リターン平均。絶対成績を見る。"],
	      avg_alpha_spy_pct: ["SPY alpha", "銘柄リターンから同期間のSPYリターンを引いた超過リターン。市場に勝ったかを見る。"],
	      win_rate_pct: ["勝率", "リターンが0%を上回った観測の割合。絶対勝率を見る。"],
	      alpha_win_rate_pct: ["Alpha勝率", "SPY alphaが0%を上回った観測の割合。市場超過の勝率を見る。"],
	      loss_rate_pct: ["損失率", "リターンが0%未満だった観測の割合。下振れ頻度を見る。"],
	      p10_return_pct: ["P10", "下位10%地点のリターン。悪いケースの損失深度を見る。"],
	    }};
	    const observationMetricKeys = {{
	      avg_return_pct: "return_pct",
	      avg_alpha_spy_pct: "alpha_spy_pct",
	      win_rate_pct: "win_rate_pct",
	      alpha_win_rate_pct: "alpha_win_rate_pct",
	      loss_rate_pct: "loss_rate_pct",
	      p10_return_pct: "p10_return_pct",
	    }};
			    let activeConvictionMetric = "avg_return_pct";
	    let convictionObservationOpen = false;
	    let activeConvictionFilter = "ALL";
	    let activeScoreMetric = "avg_return_pct";
	    let scoreObservationOpen = false;
	    let activeScoreFilter = "ALL";

	    function setViewDataForAggregationMode(mode) {{
	      activeAggregationMode = mode;
	      VIEW_DATA = (DASHBOARD_DATA.aggregationModes || {{}})[mode] || DASHBOARD_DATA;
	    }}

    function lineDatasets(rows, valueKey) {{
      const horizons = [...new Set(rows.map(r => r.horizon))].sort((a,b)=>Number(a.replace("week",""))-Number(b.replace("week","")));
      const dates = [...new Set(rows.map(r => r.validation_date))].sort();
      return {{
        labels: dates,
        datasets: horizons.map((h, i) => ({{
          label: h,
          data: dates.map(d => {{
            const row = rows.find(r => r.validation_date === d && r.horizon === h);
            return row ? Number(row[valueKey]) : null;
          }}),
          borderWidth: 2,
          tension: .25,
          spanGaps: true,
        }}))
      }};
    }}
	    const chartInstances = {{}};
	    function makeChart(id, config) {{
	      if (chartInstances[id]) chartInstances[id].destroy();
	      chartInstances[id] = new Chart(document.getElementById(id), config);
	      return chartInstances[id];
	    }}
	    function scoreIcTooltipLabel(context) {{
	      const row = (VIEW_DATA.horizonLatest || [])[context.dataIndex] || {{}};
	      return `Score IC: ${{fmt.rho(context.raw)}} / n=${{fmt.n(row.sample_count)}}`;
	    }}
	    function factorIcTooltipLabel(context, horizons, rows) {{
	      const week = horizons[context.dataIndex];
	      const row = rows.find(r => Number(r.horizon_weeks) === week && r.factor === context.dataset.label);
	      return `${{context.dataset.label}} IC: ${{fmt.rho(context.raw)}} / n=${{fmt.n(row?.sample_count)}}`;
	    }}
	    function renderCharts() {{
      makeChart("scoreIcNowChart", {{
        type: "line",
        data: {{
          labels: (VIEW_DATA.horizonLatest || []).map(r => `${{r.horizon_weeks}}w`),
          datasets: [{{label:"Score IC", data:(VIEW_DATA.horizonLatest || []).map(r => r.spearman_rho === null || r.spearman_rho === undefined ? null : Number(r.spearman_rho)), borderWidth:2, pointRadius:4, tension:.25, spanGaps:true}}]
        }},
        options: {{
          maintainAspectRatio:false,
	          plugins:{{legend:{{display:false}}, tooltip:{{callbacks:{{label:c=>scoreIcTooltipLabel(c)}}}}}},
          scales:{{y:{{title:{{display:true,text:"IC"}}}}, x:{{title:{{display:true,text:"週"}}}}}}
        }}
      }});
      makeChart("icChart", {{
        type: "line",
        data: lineDatasets((VIEW_DATA.horizonHistory || []).filter(r => Number(r.sample_count) >= 30), "spearman_rho"),
        options: {{maintainAspectRatio:false, plugins:{{legend:{{position:"bottom"}}}}, scales:{{y:{{title:{{display:true,text:"IC"}}}}}}}}
      }});
      makeChart("thresholdChart", {{
        type: "bar",
        data: {{
          labels: (VIEW_DATA.thresholdLatest || []).map(r => `${{r.horizon_weeks}}w`),
          datasets: [{{label:"spread %", data:(VIEW_DATA.thresholdLatest || []).map(r => Number(r.spread_return_pct)), borderWidth:1}}]
        }},
        options: {{maintainAspectRatio:false, plugins:{{legend:{{display:false}}}}, scales:{{y:{{title:{{display:true,text:"return spread %"}}}}}}}}
      }});
      renderFactorIcChart();
      const distRows = VIEW_DATA.returnDistribution || [];
      makeChart("distributionChart", {{
        type: "bar",
        data: {{
          labels: [...new Set(distRows.map(r => `${{r.horizon_weeks}}w`))],
          datasets: [{{label:"avg return %", data:[...new Set(distRows.map(r => r.horizon_weeks))].map(w => {{
            const vals = distRows.filter(r => r.horizon_weeks === w).map(r => Number(r.return_pct));
            return vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : null;
          }})}}]
        }},
        options: {{maintainAspectRatio:false, plugins:{{legend:{{display:false}}}}, scales:{{y:{{title:{{display:true,text:"avg return %"}}}}}}}}
	      }});
		      renderScoreMetricChart();
		      renderScatter();
		    }}

	    function renderFactorIcChart() {{
	      const rows = VIEW_DATA.factorLatest || [];
	      const horizons = [...new Set(rows.map(r => Number(r.horizon_weeks)))].sort((a,b) => a - b);
	      makeChart("factorIcChart", {{
	        type: "line",
	        data: {{
	          labels: horizons.map(w => `${{w}}w`),
	          datasets: ["momentum", "fundamentals", "catalyst", "technical", "sentiment"].map(factor => ({{
	            label: factor,
	            data: horizons.map(w => {{
	              const row = rows.find(r => Number(r.horizon_weeks) === w && r.factor === factor);
	              return row?.spearman_rho === null || row?.spearman_rho === undefined ? null : Number(row.spearman_rho);
	            }}),
	            borderWidth: 2,
	            pointRadius: 4,
	            tension: .25,
	            spanGaps: true,
	          }}))
	        }},
	        options: {{
	          maintainAspectRatio:false,
	          plugins:{{legend:{{position:"bottom"}}, tooltip:{{callbacks:{{label:c=>factorIcTooltipLabel(c, horizons, rows)}}}}}},
	          scales:{{y:{{title:{{display:true,text:"IC"}}}}, x:{{title:{{display:true,text:"週"}}}}}}
	        }}
	      }});
	    }}

	    function convictionReturnTooltipLabel(context, rows) {{
	      const row = rows.find(r => r.conviction === context.label);
	      return `${{context.dataset.label}} ${{context.label}}: ${{fmt.pct(context.raw)}} / n=${{fmt.n(row?.sample_count)}}`;
	    }}

	    function convictionMetricTooltipLabel(context, horizons, rows, metric) {{
	      const week = horizons[context.dataIndex];
	      const row = rows.find(r => Number(r.horizon_weeks) === week && r.conviction === context.dataset.label);
	      return `${{context.dataset.label}} ${{convictionMetricLabels[metric]}}: ${{fmt.pct(context.raw)}} / n=${{fmt.n(row?.sample_count)}}`;
	    }}

	    function scoreMetricTooltipLabel(context, horizons, rows, metric) {{
	      const week = horizons[context.dataIndex];
	      const row = rows.find(r => Number(r.horizon_weeks) === week && r.score_bucket === context.dataset.label);
	      return `${{context.dataset.label}} ${{scoreMetricLabels[metric]}}: ${{fmt.pct(context.raw)}} / n=${{fmt.n(row?.sample_count)}}`;
	    }}

	    function renderScoreMetricChart() {{
	      const rows = VIEW_DATA.scoreBucketReliability || [];
	      const horizons = [...new Set(rows.map(r => Number(r.horizon_weeks)))].sort((a,b) => a - b);
	      const metric = activeScoreMetric;
	      makeChart("scoreMetricChart", {{
	        type: "line",
	        data: {{
	          labels: horizons.map(w => `${{w}}w`),
	          datasets: scoreBucketOrder.map(bucket => ({{
	            label: bucket,
	            data: horizons.map(w => {{
	              const row = rows.find(r => Number(r.horizon_weeks) === w && r.score_bucket === bucket);
	              const value = row ? row[metric] : null;
	              return value === null || value === undefined ? null : Number(value);
	            }}),
	            borderColor: scoreBucketColors[bucket],
	            backgroundColor: scoreBucketColors[bucket],
	            borderWidth: 2,
	            pointRadius: 4,
	            tension: .25,
	            spanGaps: true,
	          }}))
	        }},
	        options: {{
	          maintainAspectRatio:false,
	          plugins:{{legend:{{position:"bottom"}}, tooltip:{{callbacks:{{label:c=>scoreMetricTooltipLabel(c, horizons, rows, metric)}}}}}},
	          scales:{{y:{{title:{{display:true,text:scoreMetricLabels[metric] || "%"}}}}, x:{{title:{{display:true,text:"週"}}}}}}
	        }}
	      }});
	      renderScoreMetricInfo();
	    }}

	    function renderScoreMetricInfo() {{
	      const items = Object.entries(scoreMetricDescriptions).map(([key, value]) => {{
	        const active = key === activeScoreMetric ? " style=\\"border-color:#b8c7f0;background:#f7f9ff\\"" : "";
	        return `<button class="metric-card" data-metric="${{key}}" type="button"${{active}}><strong>${{value[0]}}</strong><span>${{value[1]}}</span></button>`;
	      }});
	      document.getElementById("scoreMetricInfo").innerHTML = items.join("");
	    }}

	    function scoreObservationMetricValue(row, week) {{
	      const metricKey = observationMetricKeys[activeScoreMetric] || "return_pct";
	      const weekPayload = row.weeks?.[`week${{week}}`] || {{}};
	      return weekPayload[metricKey];
	    }}

	    function renderScoreObservationTable() {{
	      const rows = (VIEW_DATA.scoreBucketObservations || []).filter(row => (
	        activeScoreFilter === "ALL" || row.score_bucket === activeScoreFilter
	      ));
	      const metricLabel = scoreMetricLabels[activeScoreMetric] || "%";
	      const headers = [
	        {{label:"Bucket", cls:""}},
	        {{label:"取得日", cls:""}},
	        {{label:"銘柄", cls:""}},
	        {{label:"Score", cls:"num"}},
	        {{label:"Conviction", cls:""}},
	        ...Array.from({{length:8}}, (_, i) => ({{label:`${{i + 1}}w`, cls:"num"}})),
	      ];
	      const head = headers.map(h => `<th class="${{h.cls}}">${{h.label}}</th>`).join("");
	      const body = rows.map(row => {{
	        const cells = [
	          `<td><span class="chip">${{row.score_bucket || ""}}</span></td>`,
	          `<td>${{row.scored_at || ""}}</td>`,
	          `<td><strong>${{row.ticker || ""}}</strong></td>`,
	          `<td class="num">${{row.score === null || row.score === undefined ? "" : Number(row.score).toFixed(2)}}</td>`,
	          `<td><span class="chip">${{row.conviction || ""}}</span></td>`,
	          ...Array.from({{length:8}}, (_, i) => {{
	            const value = scoreObservationMetricValue(row, i + 1);
	            return `<td class="num ${{colorByNumber(value)}}">${{fmt.pct(value)}}</td>`;
	          }}),
	        ];
	        return `<tr>${{cells.join("")}}</tr>`;
	      }}).join("");
	      document.getElementById("scoreObservationTable").innerHTML = `
	        <table>
	          <thead class="sticky-head"><tr>${{head}}</tr></thead>
	          <tbody>${{body || `<tr><td colspan="13" class="muted">No observation data for ${{metricLabel}}</td></tr>`}}</tbody>
	        </table>`;
	    }}

	    function setScoreObservationOpen(open) {{
	      scoreObservationOpen = open;
	      const panel = document.getElementById("scoreObservationPanel");
	      const button = document.getElementById("scoreObservationToggle");
	      panel.classList.toggle("open", open);
	      button.setAttribute("aria-expanded", String(open));
	      button.textContent = open ? "銘柄別テーブルを閉じる" : "銘柄別テーブルを開く";
	      if (open) renderScoreObservationTable();
	    }}

	    function selectScoreMetric(metric) {{
	      activeScoreMetric = metric;
	      document.querySelectorAll("#scoreMetricTabs .metric-tab").forEach(tab => {{
	        tab.classList.toggle("active", tab.dataset.metric === metric);
	      }});
	      renderScoreMetricChart();
	      if (scoreObservationOpen) renderScoreObservationTable();
	    }}

		    function renderConvictionCharts() {{
	      const horizonRows = VIEW_DATA.convictionHorizon || [];
	      makeChart("convictionIcChart", {{
	        type: "line",
	        data: {{
	          labels: horizonRows.map(r => `${{r.horizon_weeks}}w`),
	          datasets: [{{label:"Conviction IC", data:horizonRows.map(r => r.conviction_ic === null || r.conviction_ic === undefined ? null : Number(r.conviction_ic)), borderWidth:2, tension:.25, spanGaps:true}}]
	        }},
	        options: {{maintainAspectRatio:false, plugins:{{legend:{{display:false}}}}, scales:{{y:{{title:{{display:true,text:"IC"}}}}}}}}
	      }});
	      const week4 = (VIEW_DATA.convictionReliability || []).filter(r => r.horizon === "week4");
	      makeChart("convictionReturnChart", {{
	        type: "bar",
	        data: {{
	          labels: week4.map(r => r.conviction),
	          datasets: [
	            {{label:"avg return %", data:week4.map(r => Number(r.avg_return_pct)), borderWidth:1}},
	            {{label:"SPY alpha %", data:week4.map(r => Number(r.avg_alpha_spy_pct)), borderWidth:1}}
	          ]
	        }},
	        options: {{
	          maintainAspectRatio:false,
	          plugins:{{legend:{{position:"bottom"}}, tooltip:{{callbacks:{{label:c=>convictionReturnTooltipLabel(c, week4)}}}}}},
	          scales:{{y:{{title:{{display:true,text:"%"}}}}}}
	        }}
	      }});
	      renderConvictionMetricChart();
	    }}

	    function renderConvictionMetricChart() {{
	      const rows = VIEW_DATA.convictionReliability || [];
	      const horizons = [...new Set(rows.map(r => Number(r.horizon_weeks)))].sort((a,b) => a - b);
	      const metric = activeConvictionMetric;
	      makeChart("convictionMetricChart", {{
	        type: "line",
	        data: {{
	          labels: horizons.map(w => `${{w}}w`),
	          datasets: ["HIGH", "MEDIUM", "LOW"].map(conviction => ({{
	            label: conviction,
	            data: horizons.map(w => {{
	              const row = rows.find(r => Number(r.horizon_weeks) === w && r.conviction === conviction);
	              const value = row ? row[metric] : null;
	              return value === null || value === undefined ? null : Number(value);
	            }}),
	            borderColor: convictionColors[conviction],
	            backgroundColor: convictionColors[conviction],
	            borderWidth: 2,
	            pointRadius: 4,
	            tension: .25,
	            spanGaps: true,
	          }}))
	        }},
	        options: {{
	          maintainAspectRatio:false,
	          plugins:{{legend:{{position:"bottom"}}, tooltip:{{callbacks:{{label:c=>convictionMetricTooltipLabel(c, horizons, rows, metric)}}}}}},
	          scales:{{y:{{title:{{display:true,text:convictionMetricLabels[metric] || "%"}}}}, x:{{title:{{display:true,text:"週"}}}}}}
	        }}
	      }});
	      renderConvictionMetricInfo();
	    }}

	    function renderConvictionMetricInfo() {{
	      const items = Object.entries(convictionMetricDescriptions).map(([key, value]) => {{
	        const active = key === activeConvictionMetric ? " style=\\"border-color:#b8c7f0;background:#f7f9ff\\"" : "";
	        return `<button class="metric-card" data-metric="${{key}}" type="button"${{active}}><strong>${{value[0]}}</strong><span>${{value[1]}}</span></button>`;
	      }});
	      document.getElementById("convictionMetricInfo").innerHTML = items.join("");
	    }}

	    function observationMetricValue(row, week) {{
	      const metricKey = observationMetricKeys[activeConvictionMetric] || "return_pct";
	      const weekPayload = row.weeks?.[`week${{week}}`] || {{}};
	      return weekPayload[metricKey];
	    }}

	    function renderConvictionObservationTable() {{
	      const rows = (VIEW_DATA.convictionObservations || []).filter(row => (
	        activeConvictionFilter === "ALL" || row.conviction === activeConvictionFilter
	      ));
	      const metricLabel = convictionMetricLabels[activeConvictionMetric] || "%";
	      const headers = [
	        {{label:"Conviction", cls:""}},
	        {{label:"取得日", cls:""}},
	        {{label:"銘柄", cls:""}},
	        {{label:"Score", cls:"num"}},
	        ...Array.from({{length:8}}, (_, i) => ({{label:`${{i + 1}}w`, cls:"num"}})),
	      ];
	      const head = headers.map(h => `<th class="${{h.cls}}">${{h.label}}</th>`).join("");
	      const body = rows.map(row => {{
	        const cells = [
	          `<td><span class="chip">${{row.conviction || ""}}</span></td>`,
	          `<td>${{row.scored_at || ""}}</td>`,
	          `<td><strong>${{row.ticker || ""}}</strong></td>`,
	          `<td class="num">${{row.score === null || row.score === undefined ? "" : Number(row.score).toFixed(2)}}</td>`,
	          ...Array.from({{length:8}}, (_, i) => {{
	            const value = observationMetricValue(row, i + 1);
	            return `<td class="num ${{colorByNumber(value)}}">${{fmt.pct(value)}}</td>`;
	          }}),
	        ];
	        return `<tr>${{cells.join("")}}</tr>`;
	      }}).join("");
	      document.getElementById("convictionObservationTable").innerHTML = `
	        <table>
	          <thead class="sticky-head"><tr>${{head}}</tr></thead>
	          <tbody>${{body || `<tr><td colspan="12" class="muted">No observation data for ${{metricLabel}}</td></tr>`}}</tbody>
	        </table>`;
	    }}

	    function setConvictionObservationOpen(open) {{
	      convictionObservationOpen = open;
	      const panel = document.getElementById("convictionObservationPanel");
	      const button = document.getElementById("convictionObservationToggle");
	      panel.classList.toggle("open", open);
	      button.setAttribute("aria-expanded", String(open));
	      button.textContent = open ? "銘柄別テーブルを閉じる" : "銘柄別テーブルを開く";
	      if (open) renderConvictionObservationTable();
	    }}

	    function selectConvictionMetric(metric) {{
	      activeConvictionMetric = metric;
	      document.querySelectorAll("#convictionMetricTabs .metric-tab").forEach(tab => {{
	        tab.classList.toggle("active", tab.dataset.metric === metric);
	      }});
	      renderConvictionMetricChart();
	      if (convictionObservationOpen) renderConvictionObservationTable();
	    }}

    let scatterChart;
    function renderScatter() {{
      const limit = Number(document.getElementById("scatterLimit").value);
      const query = document.getElementById("tickerSearch").value.trim().toUpperCase();
      const rows = (VIEW_DATA.scoreScatter || []).filter(r => Math.abs(Number(r.week4_return_pct)) <= limit && (!query || String(r.ticker).includes(query)));
      const points = rows.map(r => ({{x:Number(r.score), y:Number(r.week4_return_pct), ticker:r.ticker}}));
      if (scatterChart) scatterChart.destroy();
      scatterChart = makeChart("scatterChart", {{
        type: "scatter",
        data: {{datasets:[{{label:"ticker", data:points, pointRadius:4}}]}},
        options: {{
          maintainAspectRatio:false,
          plugins:{{tooltip:{{callbacks:{{label:c=>`${{c.raw.ticker}} score ${{c.raw.x}} / 4w ${{c.raw.y}}%`}}}}}},
          scales:{{x:{{title:{{display:true,text:"score"}}}}, y:{{title:{{display:true,text:"4w return %"}}}}}}
        }}
      }});
    }}

	    let convictionChartsRendered = false;
	    function setupTabs() {{
	      document.querySelectorAll(".tab").forEach(button => {{
	        button.addEventListener("click", () => {{
	          document.querySelectorAll(".tab").forEach(tab => tab.classList.remove("active"));
	          document.querySelectorAll(".page").forEach(page => page.classList.remove("active"));
	          button.classList.add("active");
	          document.getElementById(button.dataset.page).classList.add("active");
	          if (button.dataset.page === "convictionPage" && !convictionChartsRendered) {{
	            renderConvictionCharts();
	            convictionChartsRendered = true;
	          }}
	        }});
	      }});
	    }}

	    function setupConvictionMetricTabs() {{
	      document.querySelectorAll("#convictionMetricTabs .metric-tab").forEach(button => {{
	        button.addEventListener("click", () => {{
	          selectConvictionMetric(button.dataset.metric);
	        }});
	      }});
	      document.getElementById("convictionMetricInfo").addEventListener("click", event => {{
	        const card = event.target.closest(".metric-card");
	        if (card?.dataset.metric) selectConvictionMetric(card.dataset.metric);
	      }});
	    }}

	    function setupScoreMetricTabs() {{
	      document.querySelectorAll("#scoreMetricTabs .metric-tab").forEach(button => {{
	        button.addEventListener("click", () => {{
	          selectScoreMetric(button.dataset.metric);
	        }});
	      }});
	      document.getElementById("scoreMetricInfo").addEventListener("click", event => {{
	        const card = event.target.closest(".metric-card");
	        if (card?.dataset.metric) selectScoreMetric(card.dataset.metric);
	      }});
	    }}

	    function setupScoreObservationToggle() {{
	      const button = document.getElementById("scoreObservationToggle");
	      button.addEventListener("click", () => setScoreObservationOpen(!scoreObservationOpen));
	      document.getElementById("scoreObservationFilter").addEventListener("change", event => {{
	        activeScoreFilter = event.target.value;
	        if (scoreObservationOpen) renderScoreObservationTable();
	      }});
	    }}

	    function setupConvictionObservationToggle() {{
	      const button = document.getElementById("convictionObservationToggle");
	      button.addEventListener("click", () => setConvictionObservationOpen(!convictionObservationOpen));
	      document.getElementById("convictionObservationFilter").addEventListener("change", event => {{
	        activeConvictionFilter = event.target.value;
	        if (convictionObservationOpen) renderConvictionObservationTable();
	      }});
	    }}

	    function renderDashboardForCurrentMode() {{
	      renderConclusionSummary();
	      renderKpis();
	      renderTables();
	      renderConvictionSummary();
	      renderConvictionKpis();
	      renderConvictionTables();
	      renderScoreObservationTable();
	      renderConvictionObservationTable();
	      renderCharts();
	      if (document.getElementById("convictionPage").classList.contains("active")) {{
	        renderConvictionCharts();
	        convictionChartsRendered = true;
	      }} else {{
	        convictionChartsRendered = false;
	      }}
	    }}

	    function setupAggregationModeSelect() {{
	      const select = document.getElementById("aggregationModeSelect");
	      select.value = activeAggregationMode;
	      select.addEventListener("change", event => {{
	        setViewDataForAggregationMode(event.target.value);
	        renderDashboardForCurrentMode();
	      }});
	    }}

	    renderDashboardForCurrentMode();
	    setupTabs();
	    setupAggregationModeSelect();
	    setupScoreMetricTabs();
	    setupScoreObservationToggle();
	    setupConvictionMetricTabs();
	    setupConvictionObservationToggle();
    document.getElementById("scatterLimit").addEventListener("change", renderScatter);
    document.getElementById("tickerSearch").addEventListener("input", renderScatter);
  </script>
</body>
</html>
"""


def write_dashboard(data: dict[str, Any], output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_html(data), encoding="utf-8")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local score reliability dashboard HTML.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="HTML output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    store = get_store()
    if store is None:
        print("Supabase is not configured. Building dashboard from local score_snapshots.json.", file=sys.stderr)
        data = fetch_dashboard_data_from_local_files()
    else:
        try:
            data = fetch_dashboard_data(store)
        except RuntimeError as exc:
            print(f"Supabase dashboard fetch failed. Building from local score_snapshots.json: {exc}", file=sys.stderr)
            data = fetch_dashboard_data_from_local_files()
    output_path = write_dashboard(data, args.output)
    print(f"Dashboard written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

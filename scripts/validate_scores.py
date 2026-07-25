#!/usr/bin/env python3
"""
validate_scores.py — スコア検証レポート生成スクリプト

score_snapshots.json から週次 IC（Spearman ρ）、
スコアバケット別リターン、ファクター別相関を計算し、
reports/validation/validation_{date}.md に出力する。

実行: .venv/bin/python scripts/validate_scores.py
"""

import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investor.core.score_snapshots import WEEK_KEYS
from investor.config import settings
from investor.supabase_store import sync_validation_stats
from investor.supabase_sync import sync_local_to_supabase

SNAPSHOTS_PATH = Path(__file__).parent.parent / "data" / "score_snapshots.json"
REPORTS_DIR = Path(__file__).parent.parent / "reports" / "validation"
MIN_SAMPLES = 30
WEEK_LABELS = {wk: f"{wk.removeprefix('week')}週後" for wk in WEEK_KEYS}
PRIMARY_WEEK = f"week{settings.evaluation_horizon_weeks}"
FACTORS = ["momentum", "fundamentals", "catalyst", "technical", "sentiment"]
MOMENTUM_MODES = ["EARLY_MOMENTUM", "CHASE_MOMENTUM", "BALANCED", "NONE"]
QUALITY_GRADES = ["A", "B", "C", "D"]
SCORE_BUCKETS = [
    ("≥ 8.5（exceptional）", lambda s: s >= 8.5),
    ("8.0–8.4（high）", lambda s: 8.0 <= s < 8.5),
    ("7.5–7.9（medium-high）", lambda s: 7.5 <= s < 8.0),
    ("7.0–7.4（medium）", lambda s: 7.0 <= s < 7.5),
    ("< 7.0（below threshold）", lambda s: s < 7.0),
]
CONVICTIONS = ["HIGH", "MEDIUM", "LOW"]
SPY_BUCKET_WIDTH = 2


# ── 統計ユーティリティ ──────────────────────────────────────────────

def _rank(values: list[float]) -> list[float]:
    """昇順ランク（同値は平均ランク）"""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
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


def spearman(x: list[float], y: list[float]) -> tuple[float, float]:
    """Spearman ρ と p 値（t 近似）を返す。"""
    n = len(x)
    if n < 3:
        return float("nan"), float("nan")
    rx = _rank(x)
    ry = _rank(y)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = math.sqrt(sum((rx[i] - mean_rx) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((ry[i] - mean_ry) ** 2 for i in range(n)))
    if den_x == 0 or den_y == 0:
        return float("nan"), float("nan")
    rho = num / (den_x * den_y)

    # t 分布による p 値近似（两側）
    t_stat = rho * math.sqrt((n - 2) / max(1 - rho ** 2, 1e-12))
    # 正規近似（n >= 10 で十分）
    p_val = 2 * (1 - _normal_cdf(abs(t_stat)))
    return round(rho, 4), round(p_val, 6)


def _normal_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2))) / 2


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    ordered = sorted(vals)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 2)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 2)


def _infer_conviction(score: float | int | None) -> str:
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


def _snapshot_conviction(snapshot: dict) -> tuple[str, str]:
    conviction = str(snapshot.get("conviction") or "").strip().upper()
    source = str(snapshot.get("conviction_source") or "").strip().lower()
    if conviction in CONVICTIONS:
        return conviction, source or "stored"
    inferred = _infer_conviction(snapshot.get("score"))
    if inferred in CONVICTIONS:
        return inferred, "inferred_from_score"
    return "", "missing"


def _percentile(vals: list[float], pct: float) -> float | None:
    if not vals:
        return None
    ordered = sorted(vals)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    pos = (len(ordered) - 1) * pct
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return round(ordered[int(pos)], 2)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo), 2)


def _extract_mode(snapshot: dict) -> str:
    direct = str(snapshot.get("momentum_primary_mode") or "").strip().upper()
    if direct in MOMENTUM_MODES:
        return direct
    nested = str((snapshot.get("momentum_profile") or {}).get("primary_mode") or "").strip().upper()
    if nested in MOMENTUM_MODES:
        return nested
    breakdown = str((snapshot.get("score_breakdown") or {}).get("primary_mode") or "").strip().upper()
    if breakdown in MOMENTUM_MODES:
        return breakdown
    return ""


def _spy_bucket(value: float, width: int = SPY_BUCKET_WIDTH) -> tuple[int, int, str]:
    lo = math.floor(value / width) * width
    hi = lo + width
    return lo, hi, f"{lo:+.0f}%〜{hi:+.0f}%"


def _fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.1f}%"


def _significance_label(rho: float, p: float) -> str:
    if math.isnan(rho):
        return "データ不足"
    if p >= 0.05:
        return "⚠️ 有意差なし"
    if rho >= 0.4:
        return "✅ 強い正の相関"
    if rho >= 0.2:
        return "✅ 正の相関あり"
    if rho >= 0.05:
        return "⚠️ 弱い正の相関"
    return "❌ 相関なし"


# ── データ読み込み ────────────────────────────────────────────────

def load_snapshots() -> list[dict]:
    if not SNAPSHOTS_PATH.exists():
        print(f"ERROR: {SNAPSHOTS_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    with open(SNAPSHOTS_PATH) as f:
        return json.load(f).get("snapshots", [])


# ── 解析 ─────────────────────────────────────────────────────────

def analyze(snapshots: list[dict]) -> dict:
    result: dict = {}

    # ── 基本統計 ──
    counts = {wk: 0 for wk in WEEK_KEYS}
    for snap in snapshots:
        for wk in WEEK_KEYS:
            if snap.get(wk, {}).get("fetched_at") is not None:
                counts[wk] += 1
    result["total"] = len(snapshots)
    result["counts"] = counts

    # 検証期間
    dates = [s["scored_at"] for s in snapshots if s.get("scored_at")]
    result["period_start"] = min(dates) if dates else "N/A"
    result["period_end"] = max(dates) if dates else "N/A"

    # ── 週次 IC（Spearman ρ） ──
    ic: dict[str, dict] = {}
    for wk in WEEK_KEYS:
        pairs = [
            (s["score"], s[wk]["return_pct"])
            for s in snapshots
            if s.get("score") is not None
            and s.get(wk, {}).get("fetched_at") is not None
            and s[wk].get("return_pct") is not None
        ]
        n = len(pairs)
        if n < MIN_SAMPLES:
            ic[wk] = {"n": n, "rho": float("nan"), "p": float("nan"), "label": f"データ不足（N={n} < {MIN_SAMPLES}）"}
        else:
            scores, returns = zip(*pairs)
            rho, p = spearman(list(scores), list(returns))
            ic[wk] = {"n": n, "rho": rho, "p": p, "label": _significance_label(rho, p)}
    result["ic"] = ic
    result["run_ic"] = build_run_level_ic(snapshots)
    result["strategy_versions"] = {
        version: sum(
            1 for snapshot in snapshots
            if str(snapshot.get("strategy_version") or "legacy_unversioned") == version
        )
        for version in sorted({
            str(snapshot.get("strategy_version") or "legacy_unversioned")
            for snapshot in snapshots
        })
    }

    # ── スコアバケット別 × 週別平均リターン ──
    buckets: dict[str, dict] = {}
    for label, cond in SCORE_BUCKETS:
        bucket_snaps = [s for s in snapshots if s.get("score") is not None and cond(s["score"])]
        wk_avgs: dict[str, str] = {}
        for wk in WEEK_KEYS:
            rets = [
                s[wk]["return_pct"]
                for s in bucket_snaps
                if s.get(wk, {}).get("fetched_at") is not None
                and s[wk].get("return_pct") is not None
            ]
            wk_avgs[wk] = f"{_mean(rets):+.1f}%" if rets else "N/A"
        buckets[label] = {"n": len(bucket_snaps), "avgs": wk_avgs}
    result["buckets"] = buckets

    # ── ファクター別 Spearman ρ ──
    factor_ic: dict[str, dict[str, dict]] = defaultdict(dict)
    for factor in FACTORS:
        for wk in WEEK_KEYS:
            pairs = [
                (s["score_breakdown"][factor], s[wk]["return_pct"])
                for s in snapshots
                if s.get("score_breakdown", {}).get(factor) is not None
                and s.get(wk, {}).get("fetched_at") is not None
                and s[wk].get("return_pct") is not None
            ]
            n = len(pairs)
            if n < MIN_SAMPLES:
                factor_ic[factor][wk] = {"rho": float("nan"), "n": n}
            else:
                fscores, returns = zip(*pairs)
                rho, _ = spearman(list(fscores), list(returns))
                factor_ic[factor][wk] = {"rho": rho, "n": n}
    result["factor_ic"] = dict(factor_ic)

    # ── passed_threshold 比較 ──
    passed = [
        s for s in snapshots
        if s.get("score") is not None and float(s["score"]) >= 7.5
    ]
    rejected = [
        s for s in snapshots
        if s.get("score") is not None and float(s["score"]) < 7.5
    ]

    def avg_return_for_group(group: list[dict], wk: str) -> str:
        rets = [
            s[wk]["return_pct"]
            for s in group
            if s.get(wk, {}).get("fetched_at") is not None
            and s[wk].get("return_pct") is not None
        ]
        return f"{_mean(rets):+.1f}%" if rets else "N/A"

    threshold_comparison: dict[str, dict] = {}
    for wk in WEEK_KEYS:
        threshold_comparison[wk] = {
            "passed_avg": avg_return_for_group(passed, wk),
            "rejected_avg": avg_return_for_group(rejected, wk),
        }
    result["threshold_comparison"] = threshold_comparison
    result["passed_n"] = len(passed)
    result["rejected_n"] = len(rejected)

    # ── 確信度 × SPY変動率マトリクス ──
    result["conviction_spy_matrix"] = build_conviction_spy_matrix(snapshots)
    result["horizon_summary"] = build_horizon_summary(snapshots)
    result["conviction_reliability"] = build_conviction_reliability(snapshots)
    result["conviction_score_bucket"] = build_conviction_score_bucket(snapshots)
    result["regime_summary"] = build_regime_summary(snapshots)

    # ── キャリブレーション提案 ──
    result["mode_summary"] = build_mode_summary(snapshots)
    result["mode_factor_reliability"] = build_mode_factor_reliability(snapshots)
    result["factor_grade_reliability"] = build_factor_grade_reliability(snapshots)
    result["calibration"] = build_calibration(ic, factor_ic, result["run_ic"])
    return result


def build_run_level_ic(snapshots: list[dict]) -> dict:
    """Compute cross-sectional score IC inside each run using SPY alpha.

    Pooled rows repeatedly observe the same names and market dates. Run-level IC
    measures whether the score ranked contemporaneous candidates correctly,
    then summarizes those independent decision occasions.
    """
    result: dict[str, dict] = {}
    for wk in WEEK_KEYS:
        grouped: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
        for snapshot in snapshots:
            score = snapshot.get("score")
            week = snapshot.get(wk, {})
            alpha = week.get("alpha_vs_spy", week.get("alpha_pct"))
            run_id = str(snapshot.get("run_id") or "")
            ticker = str(snapshot.get("ticker") or "").upper()
            if (
                not run_id
                or not ticker
                or score is None
                or alpha is None
                or week.get("fetched_at") is None
            ):
                continue
            # The same ticker can be written more than once by retries/backfills.
            # Treat it as one observation inside a decision occasion.
            grouped[run_id][ticker] = (float(score), float(alpha))

        run_rows = []
        for run_id, ticker_pairs in grouped.items():
            pairs = list(ticker_pairs.values())
            if len(pairs) < 3:
                continue
            scores, alphas = zip(*pairs)
            rho, p = spearman(list(scores), list(alphas))
            if math.isnan(rho):
                continue
            first = next(
                (row for row in snapshots if str(row.get("run_id") or "") == run_id),
                {},
            )
            run_rows.append({
                "run_id": run_id,
                "scored_at": first.get("scored_at"),
                "strategy_version": first.get("strategy_version") or "legacy_unversioned",
                "n": len(pairs),
                "rho": rho,
                "p": p,
            })

        rhos = [row["rho"] for row in run_rows]
        result[wk] = {
            "n_runs": len(run_rows),
            "n_observations": sum(row["n"] for row in run_rows),
            "mean_rho": _mean(rhos),
            "median_rho": _median(rhos),
            "positive_run_pct": (
                round(sum(rho > 0 for rho in rhos) / len(rhos) * 100, 1)
                if rhos else None
            ),
            "runs": sorted(run_rows, key=lambda row: (str(row["scored_at"]), row["run_id"])),
        }
    return result


def _snapshot_factor_grade(snapshot: dict, factor: str) -> str:
    direct = str(snapshot.get(f"{factor}_grade") or "").strip().upper()
    if direct in QUALITY_GRADES:
        return direct
    nested = str((snapshot.get("factor_grades") or {}).get(factor) or "").strip().upper()
    if nested in QUALITY_GRADES:
        return nested
    evidence = snapshot.get("score_evidence") or {}
    evidence_grade = str(evidence.get(f"{factor}_grade") or "").strip().upper()
    if evidence_grade in QUALITY_GRADES:
        return evidence_grade
    factor_evidence = evidence.get(factor)
    if isinstance(factor_evidence, dict):
        nested_evidence_grade = str(
            factor_evidence.get(f"{factor}_grade") or factor_evidence.get("grade") or ""
        ).strip().upper()
        if nested_evidence_grade in QUALITY_GRADES:
            return nested_evidence_grade
    return ""


def build_factor_grade_reliability(snapshots: list[dict]) -> dict:
    result: dict[str, dict[str, dict[str, dict]]] = {}
    for factor in FACTORS:
        factor_rows: dict[str, dict[str, dict]] = {}
        for wk in WEEK_KEYS:
            grade_rows: dict[str, dict] = {}
            for grade in QUALITY_GRADES:
                returns = []
                alphas = []
                for snap in snapshots:
                    if _snapshot_factor_grade(snap, factor) != grade:
                        continue
                    week = snap.get(wk, {})
                    if week.get("fetched_at") is None or week.get("return_pct") is None:
                        continue
                    ret = float(week["return_pct"])
                    returns.append(ret)
                    if week.get("alpha_vs_spy") is not None:
                        alphas.append(float(week["alpha_vs_spy"]))
                    elif week.get("alpha_pct") is not None:
                        alphas.append(float(week["alpha_pct"]))
                grade_rows[grade] = {
                    "n": len(returns),
                    "win_rate": round(sum(r > 0 for r in returns) / len(returns) * 100, 1) if returns else None,
                    "avg_return": _mean(returns),
                    "avg_alpha": _mean(alphas),
                }
            factor_rows[wk] = grade_rows
        result[factor] = factor_rows
    return result


def build_conviction_spy_matrix(snapshots: list[dict]) -> dict:
    matrix: dict[str, dict] = {}
    for wk in WEEK_KEYS:
        rows = []
        for snap in snapshots:
            week = snap.get(wk, {})
            if week.get("fetched_at") is None:
                continue
            if week.get("return_pct") is None or week.get("spy_return_pct") is None:
                continue
            conviction, _source = _snapshot_conviction(snap)
            if conviction not in CONVICTIONS:
                continue
            rows.append({
                "conviction": conviction,
                "return_pct": float(week["return_pct"]),
                "spy_return_pct": float(week["spy_return_pct"]),
            })
        if not rows:
            matrix[wk] = {"n": 0, "buckets": [], "rows": {}}
            continue
        bucket_keys = sorted({_spy_bucket(row["spy_return_pct"]) for row in rows}, key=lambda item: item[0])
        table: dict[str, dict[str, dict]] = {}
        for conviction in CONVICTIONS:
            table[conviction] = {}
            for lo, hi, label in bucket_keys:
                values = [
                    row["return_pct"]
                    for row in rows
                    if row["conviction"] == conviction and lo <= row["spy_return_pct"] < hi
                ]
                table[conviction][label] = {
                    "n": len(values),
                    "avg_return": _mean(values),
                }
        matrix[wk] = {
            "n": len(rows),
            "spy_min": min(row["spy_return_pct"] for row in rows),
            "spy_max": max(row["spy_return_pct"] for row in rows),
            "buckets": [label for _, _, label in bucket_keys],
            "rows": table,
        }
    return matrix


def build_horizon_summary(snapshots: list[dict]) -> dict:
    summary: dict[str, dict] = {}
    for wk in WEEK_KEYS:
        summary[wk] = {}
        for conviction in CONVICTIONS:
            rows = []
            for snap in snapshots:
                snap_conviction, _source = _snapshot_conviction(snap)
                if snap_conviction != conviction:
                    continue
                week = snap.get(wk, {})
                if week.get("fetched_at") is None or week.get("return_pct") is None:
                    continue
                rows.append(week)

            returns = [float(row["return_pct"]) for row in rows]
            alpha_spy = [
                float(row.get("alpha_vs_spy", row.get("alpha_pct")))
                for row in rows
                if row.get("alpha_vs_spy", row.get("alpha_pct")) is not None
            ]
            alpha_qqq = [float(row["alpha_vs_qqq"]) for row in rows if row.get("alpha_vs_qqq") is not None]
            alpha_sector = [
                float(row["alpha_vs_sector"])
                for row in rows
                if row.get("alpha_vs_sector") is not None
            ]
            summary[wk][conviction] = {
                "n": len(returns),
                "avg_return": _mean(returns),
                "median_return": _median(returns),
                "avg_alpha_spy": _mean(alpha_spy),
                "avg_alpha_qqq": _mean(alpha_qqq),
                "avg_alpha_sector": _mean(alpha_sector),
            }
    return summary


def _rows_for_week(snapshots: list[dict], wk: str) -> list[dict]:
    rows = []
    for snap in snapshots:
        week = snap.get(wk, {})
        if week.get("fetched_at") is None or week.get("return_pct") is None:
            continue
        conviction, source = _snapshot_conviction(snap)
        if conviction not in CONVICTIONS:
            continue
        ret = float(week["return_pct"])
        spy_alpha = week.get("alpha_vs_spy", week.get("alpha_pct"))
        sector_alpha = week.get("alpha_vs_sector")
        rows.append({
            "ticker": snap.get("ticker"),
            "score": snap.get("score"),
            "conviction": conviction,
            "conviction_source": source,
            "return_pct": ret,
            "alpha_spy": float(spy_alpha) if spy_alpha is not None else None,
            "alpha_sector": float(sector_alpha) if sector_alpha is not None else None,
        })
    return rows


def _conviction_stats(rows: list[dict]) -> dict:
    returns = [row["return_pct"] for row in rows]
    alpha_spy = [row["alpha_spy"] for row in rows if row["alpha_spy"] is not None]
    alpha_sector = [row["alpha_sector"] for row in rows if row["alpha_sector"] is not None]
    losses = [value for value in returns if value < 0]
    return {
        "n": len(returns),
        "explicit_n": sum(1 for row in rows if row["conviction_source"] == "explicit"),
        "stored_n": sum(1 for row in rows if row["conviction_source"] == "stored"),
        "inferred_n": sum(1 for row in rows if row["conviction_source"] == "inferred_from_score"),
        "win_rate": round(sum(1 for value in returns if value > 0) / len(returns) * 100, 1) if returns else None,
        "alpha_win_rate": round(sum(1 for value in alpha_spy if value > 0) / len(alpha_spy) * 100, 1) if alpha_spy else None,
        "avg_return": _mean(returns),
        "median_return": _median(returns),
        "avg_alpha_spy": _mean(alpha_spy),
        "avg_alpha_sector": _mean(alpha_sector),
        "loss_rate": round(len(losses) / len(returns) * 100, 1) if returns else None,
        "avg_loss": _mean(losses),
        "p10_return": _percentile(returns, 0.10),
    }


def _conviction_order_label(by_conviction: dict[str, dict]) -> str:
    values = {
        conviction: by_conviction.get(conviction, {}).get("avg_alpha_spy")
        for conviction in CONVICTIONS
    }
    if any(values[c] is None for c in CONVICTIONS):
        values = {
            conviction: by_conviction.get(conviction, {}).get("avg_return")
            for conviction in CONVICTIONS
        }
    if any(values[c] is None for c in CONVICTIONS):
        return "データ不足"
    high, medium, low = values["HIGH"], values["MEDIUM"], values["LOW"]
    if high > medium > low:
        return "✅ 順序性あり"
    if high >= medium and medium >= low:
        return "✅ 弱い順序性あり"
    if high < medium:
        return "⚠️ HIGH過信の疑い"
    if medium < low:
        return "⚠️ MEDIUM/LOW分類に歪み"
    return "⚠️ 順序性なし"


def build_conviction_reliability(snapshots: list[dict]) -> dict:
    reliability: dict[str, dict] = {}
    ordinal = {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 3.0}
    for wk in WEEK_KEYS:
        rows = _rows_for_week(snapshots, wk)
        by_conviction = {
            conviction: _conviction_stats([row for row in rows if row["conviction"] == conviction])
            for conviction in CONVICTIONS
        }
        pairs = [(ordinal[row["conviction"]], row["return_pct"]) for row in rows]
        if len(pairs) < MIN_SAMPLES:
            rho = float("nan")
            p = float("nan")
            ic_label = f"データ不足（N={len(pairs)} < {MIN_SAMPLES}）"
        else:
            ranks, returns = zip(*pairs)
            rho, p = spearman(list(ranks), list(returns))
            ic_label = _significance_label(rho, p)
        reliability[wk] = {
            "n": len(rows),
            "explicit_n": sum(1 for row in rows if row["conviction_source"] == "explicit"),
            "stored_n": sum(1 for row in rows if row["conviction_source"] == "stored"),
            "inferred_n": sum(1 for row in rows if row["conviction_source"] == "inferred_from_score"),
            "rho": rho,
            "p": p,
            "ic_label": ic_label,
            "order_label": _conviction_order_label(by_conviction),
            "by_conviction": by_conviction,
        }
    return reliability


def build_conviction_score_bucket(snapshots: list[dict]) -> dict:
    rows = _rows_for_week(snapshots, PRIMARY_WEEK)
    result: dict[str, dict] = {}
    for label, cond in SCORE_BUCKETS:
        bucket_rows = []
        for row in rows:
            score = row.get("score")
            if score is None:
                continue
            try:
                if cond(float(score)):
                    bucket_rows.append(row)
            except (TypeError, ValueError):
                continue
        result[label] = {
            conviction: _conviction_stats([row for row in bucket_rows if row["conviction"] == conviction])
            for conviction in CONVICTIONS
        }
    return result


def build_regime_summary(snapshots: list[dict]) -> dict:
    rows_by_regime: dict[str, list[float]] = {}
    for snap in snapshots:
        week = snap.get(PRIMARY_WEEK, {})
        if week.get("fetched_at") is None or week.get("return_pct") is None:
            continue
        regime = week.get("market_regime") or "unknown"
        rows_by_regime.setdefault(regime, []).append(float(week["return_pct"]))

    return {
        regime: {"n": len(values), "avg_return": _mean(values)}
        for regime, values in sorted(rows_by_regime.items())
    }


def build_mode_summary(snapshots: list[dict]) -> dict:
    summary: dict[str, dict] = {}
    for wk in WEEK_KEYS:
        summary[wk] = {}
        for mode in MOMENTUM_MODES:
            returns = []
            alpha_spy = []
            alpha_sector = []
            wins = 0
            for snap in snapshots:
                if _extract_mode(snap) != mode:
                    continue
                week = snap.get(wk, {})
                if week.get("fetched_at") is None or week.get("return_pct") is None:
                    continue
                ret = float(week["return_pct"])
                returns.append(ret)
                if ret > 0:
                    wins += 1
                spy_alpha = week.get("alpha_vs_spy", week.get("alpha_pct"))
                if spy_alpha is not None:
                    alpha_spy.append(float(spy_alpha))
                sector_alpha = week.get("alpha_vs_sector")
                if sector_alpha is not None:
                    alpha_sector.append(float(sector_alpha))

            n = len(returns)
            summary[wk][mode] = {
                "n": n,
                "avg_return": _mean(returns),
                "win_rate": round(wins / n * 100, 1) if n else None,
                "avg_alpha_spy": _mean(alpha_spy),
                "avg_alpha_sector": _mean(alpha_sector),
            }
    return summary


def build_mode_factor_reliability(snapshots: list[dict]) -> dict:
    reliability: dict[str, dict] = {}
    for mode in MOMENTUM_MODES:
        reliability[mode] = {}
        for factor in FACTORS:
            reliability[mode][factor] = {}
            for wk in WEEK_KEYS:
                pairs = []
                high_returns = []
                low_returns = []
                high_alpha = []
                low_alpha = []
                for snap in snapshots:
                    if _extract_mode(snap) != mode:
                        continue
                    factor_score = (snap.get("score_breakdown") or {}).get(factor)
                    week = snap.get(wk, {})
                    if factor_score is None or week.get("fetched_at") is None or week.get("return_pct") is None:
                        continue
                    try:
                        score = float(factor_score)
                        ret = float(week["return_pct"])
                    except (TypeError, ValueError):
                        continue
                    pairs.append((score, ret))
                    spy_alpha = week.get("alpha_vs_spy", week.get("alpha_pct"))
                    alpha_value = float(spy_alpha) if spy_alpha is not None else None
                    if score >= 8.0:
                        high_returns.append(ret)
                        if alpha_value is not None:
                            high_alpha.append(alpha_value)
                    elif score <= 6.0:
                        low_returns.append(ret)
                        if alpha_value is not None:
                            low_alpha.append(alpha_value)

                n = len(pairs)
                if n < MIN_SAMPLES:
                    rho = float("nan")
                    p = float("nan")
                    label = f"データ不足（N={n} < {MIN_SAMPLES}）"
                else:
                    scores, returns = zip(*pairs)
                    rho, p = spearman(list(scores), list(returns))
                    label = _significance_label(rho, p)

                reliability[mode][factor][wk] = {
                    "n": n,
                    "rho": rho,
                    "p": p,
                    "label": label,
                    "high_score_avg_return": _mean(high_returns),
                    "low_score_avg_return": _mean(low_returns),
                    "high_score_avg_alpha": _mean(high_alpha),
                    "low_score_avg_alpha": _mean(low_alpha),
                }
    return reliability


def build_calibration(ic: dict, factor_ic: dict, run_ic: dict) -> list[str]:
    suggestions = []

    # Only independent run-level alpha IC may change live policy. Pooled
    # ticker/date rows remain diagnostic because retries and repeated names are
    # not independent observations.
    primary = run_ic.get(PRIMARY_WEEK, {})
    primary_rho = primary.get("median_rho")
    n_runs = int(primary.get("n_runs") or 0)
    if primary_rho is not None and n_runs >= 10:
        if primary_rho >= 0.4:
            suggestions.append(f"{WEEK_LABELS[PRIMARY_WEEK]}run別alpha IC中央値が高い（ρ≥0.4）：run内ランキングは良好")
        elif primary_rho >= 0.2:
            suggestions.append(f"{WEEK_LABELS[PRIMARY_WEEK]}run別alpha IC中央値（ρ≥0.2）：run内ランキングは中程度")
        else:
            suggestions.append(f"{WEEK_LABELS[PRIMARY_WEEK]}run別alpha IC中央値が低い（ρ<0.2）：独立した判断機会での予測力が不十分")
    else:
        suggestions.append(
            f"{WEEK_LABELS[PRIMARY_WEEK]}の独立run数は{n_runs}。10 run未満のため、スコアウェイトを再調整しない"
        )
    suggestions.append(
        "pool済みファクター相関は診断専用。次の固定12週間はStrategy V2のウェイトを凍結する"
    )

    return suggestions


# ── レポート生成 ──────────────────────────────────────────────────

def format_rho(rho: float) -> str:
    return "N/A" if math.isnan(rho) else f"{rho:+.2f}"


def format_p(p: float) -> str:
    return "N/A" if math.isnan(p) else f"{p:.4f}"


def generate_report(stats: dict) -> str:
    today = date.today().isoformat()
    lines = []
    lines.append(f"# スコア検証レポート — {today}")
    lines.append("")
    lines.append("## データサマリー")
    lines.append("")
    lines.append("| 項目 | 値 |")
    lines.append("|---|---|")
    lines.append(f"| 検証期間 | {stats['period_start']} 〜 {stats['period_end']} |")
    lines.append(f"| スナップショット総数 | {stats['total']} 件 |")
    versions = ", ".join(
        f"{version}: {count}"
        for version, count in stats.get("strategy_versions", {}).items()
    )
    lines.append(f"| Strategy version | {versions or 'legacy_unversioned'} |")
    for wk in WEEK_KEYS:
        lines.append(f"| {WEEK_LABELS[wk]} リターン取得済み | {stats['counts'][wk]} 件 |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Pool済み週次 IC（診断用）— スコア vs 累積リターン")
    lines.append("")
    lines.append("同一銘柄・同一runの重複を含み得るため、ライブ戦略変更の根拠には使わない。")
    lines.append("")
    lines.append("| ホライゾン | サンプル数 | Spearman ρ | p値 | 判定 |")
    lines.append("|---|---|---|---|---|")
    for wk in WEEK_KEYS:
        d = stats["ic"][wk]
        lines.append(
            f"| {WEEK_LABELS[wk]} | {d['n']} | {format_rho(d['rho'])} | {format_p(d['p'])} | {d['label']} |"
        )

    lines.append("")
    lines.append("## Run別クロスセクション Alpha IC（主指標）")
    lines.append("")
    lines.append("同一run・同一tickerを1観測に重複排除し、候補順位とSPY超過リターンの相関をrunごとに測る。")
    lines.append("")
    lines.append("| ホライゾン | 独立run数 | 重複排除後n | 平均ρ | 中央値ρ | 正のrun比率 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for wk in WEEK_KEYS:
        row = stats["run_ic"][wk]
        positive = (
            "N/A"
            if row["positive_run_pct"] is None
            else f"{row['positive_run_pct']:.1f}%"
        )
        mean_rho = "N/A" if row["mean_rho"] is None else f"{row['mean_rho']:+.2f}"
        median_rho = "N/A" if row["median_rho"] is None else f"{row['median_rho']:+.2f}"
        lines.append(
            f"| {WEEK_LABELS[wk]} | {row['n_runs']} | {row['n_observations']} | "
            f"{mean_rho} | {median_rho} | {positive} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## スコアバケット別 × 週別 平均リターン")
    lines.append("")
    horizon_headers = " | ".join(f"{wk.removeprefix('week')}w avg" for wk in WEEK_KEYS)
    lines.append(f"| スコアバケット | 件数 | {horizon_headers} |")
    lines.append("|---|---|" + "---|" * len(WEEK_KEYS))
    for label, data in stats["buckets"].items():
        avgs = data["avgs"]
        avg_cells = " | ".join(avgs[wk] for wk in WEEK_KEYS)
        lines.append(f"| {label} | {data['n']} | {avg_cells} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 確信度 × SPY変動率マトリクス")
    lines.append("")
    lines.append("値は銘柄リターン率の平均。括弧内はn数。購入有無は問わず、score_snapshotsの全観測銘柄を使う。")
    for wk in WEEK_KEYS:
        matrix = stats["conviction_spy_matrix"][wk]
        lines.append("")
        lines.append(f"### {WEEK_LABELS[wk]}")
        lines.append("")
        if matrix["n"] == 0:
            lines.append("データなし")
            continue
        lines.append(f"- n={matrix['n']}")
        lines.append(f"- SPY変動レンジ: {matrix['spy_min']:+.1f}%〜{matrix['spy_max']:+.1f}%")
        lines.append("")
        buckets = matrix["buckets"]
        lines.append("| 確信度 | " + " | ".join(buckets) + " |")
        lines.append("|---|" + "|".join(["---:"] * len(buckets)) + "|")
        for conviction in CONVICTIONS:
            cells = []
            for bucket in buckets:
                cell = matrix["rows"][conviction][bucket]
                cells.append(
                    f"{cell['avg_return']:+.1f}% (n={cell['n']})"
                    if cell["n"] else "—"
                )
            lines.append(f"| {conviction} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## ホライゾン別 確信度サマリー")
    lines.append("")
    lines.append("12週後をStrategy V2の主指標とし、途中経過は診断用に見る。QQQ/セクターalphaはデータがある場合のみ表示。")
    lines.append("")
    lines.append("| ホライゾン | 確信度 | n | 平均リターン | 中央値 | SPY alpha | QQQ alpha | Sector alpha |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for wk in WEEK_KEYS:
        for conviction in CONVICTIONS:
            row = stats["horizon_summary"][wk][conviction]
            if row["n"] == 0:
                continue
            lines.append(
                f"| {WEEK_LABELS[wk]} | {conviction} | {row['n']} | "
                f"{_fmt_pct(row['avg_return'])} | {_fmt_pct(row['median_return'])} | "
                f"{_fmt_pct(row['avg_alpha_spy'])} | {_fmt_pct(row['avg_alpha_qqq'])} | "
                f"{_fmt_pct(row['avg_alpha_sector'])} |"
            )

    lines.append("")
    lines.append("### 確信度別 ベスト保有期間")
    lines.append("")
    lines.append("| 確信度 | 平均リターン最大 | SPY alpha最大 | セクターalpha最大 |")
    lines.append("|---|---|---|---|")
    for conviction in CONVICTIONS:
        rows = [
            (wk, stats["horizon_summary"][wk][conviction])
            for wk in WEEK_KEYS
            if stats["horizon_summary"][wk][conviction]["n"] > 0
        ]
        if not rows:
            continue
        best_return = max(rows, key=lambda item: item[1]["avg_return"] if item[1]["avg_return"] is not None else -999)
        best_spy = max(rows, key=lambda item: item[1]["avg_alpha_spy"] if item[1]["avg_alpha_spy"] is not None else -999)
        sector_rows = [row for row in rows if row[1]["avg_alpha_sector"] is not None]
        best_sector = (
            max(sector_rows, key=lambda item: item[1]["avg_alpha_sector"])
            if sector_rows
            else None
        )
        sector_text = (
            f"{WEEK_LABELS[best_sector[0]]} {_fmt_pct(best_sector[1]['avg_alpha_sector'])} "
            f"(n={best_sector[1]['n']})"
            if best_sector
            else "N/A"
        )
        lines.append(
            f"| {conviction} | {WEEK_LABELS[best_return[0]]} {_fmt_pct(best_return[1]['avg_return'])} "
            f"(n={best_return[1]['n']}) | {WEEK_LABELS[best_spy[0]]} {_fmt_pct(best_spy[1]['avg_alpha_spy'])} "
            f"(n={best_spy[1]['n']}) | {sector_text} |"
        )

    lines.append("")
    lines.append("### Conviction Reliability — 確信度そのものの検証")
    lines.append("")
    lines.append("conviction は保存済みの明示/旧保存値を優先し、欠損した古い観測のみ score から推定する。")
    lines.append("Conviction IC は LOW=1 / MEDIUM=2 / HIGH=3 と累積リターンの Spearman ρ。")
    lines.append("")
    lines.append("| ホライゾン | n | 明示/保存/推定 | Conviction IC | 判定 | 順序性 |")
    lines.append("|---|---:|---:|---:|---|---|")
    for wk in WEEK_KEYS:
        row = stats["conviction_reliability"][wk]
        source_counts = f"{row['explicit_n']}/{row['stored_n']}/{row['inferred_n']}"
        lines.append(
            f"| {WEEK_LABELS[wk]} | {row['n']} | {source_counts} | {format_rho(row['rho'])} | "
            f"{row['ic_label']} | {row['order_label']} |"
        )

    lines.append("")
    lines.append("| ホライゾン | 確信度 | n | 勝率 | Alpha勝率 | 平均リターン | SPY alpha | 損失率 | 平均損失 | P10 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for wk in WEEK_KEYS:
        for conviction in CONVICTIONS:
            row = stats["conviction_reliability"][wk]["by_conviction"][conviction]
            if row["n"] == 0:
                continue
            win_rate = "N/A" if row["win_rate"] is None else f"{row['win_rate']:.1f}%"
            alpha_win_rate = "N/A" if row["alpha_win_rate"] is None else f"{row['alpha_win_rate']:.1f}%"
            loss_rate = "N/A" if row["loss_rate"] is None else f"{row['loss_rate']:.1f}%"
            lines.append(
                f"| {WEEK_LABELS[wk]} | {conviction} | {row['n']} | {win_rate} | {alpha_win_rate} | "
                f"{_fmt_pct(row['avg_return'])} | {_fmt_pct(row['avg_alpha_spy'])} | {loss_rate} | "
                f"{_fmt_pct(row['avg_loss'])} | {_fmt_pct(row['p10_return'])} |"
            )

    lines.append("")
    lines.append(f"### Score Bucket内 Conviction差分（{WEEK_LABELS[PRIMARY_WEEK]}）")
    lines.append("")
    lines.append("同じ score bucket 内で conviction が追加の予測力を持っているかを見る。")
    lines.append("")
    lines.append("| Score bucket | 確信度 | n | 勝率 | 平均リターン | SPY alpha | P10 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for bucket, by_conviction in stats["conviction_score_bucket"].items():
        for conviction in CONVICTIONS:
            row = by_conviction[conviction]
            if row["n"] == 0:
                continue
            win_rate = "N/A" if row["win_rate"] is None else f"{row['win_rate']:.1f}%"
            lines.append(
                f"| {bucket} | {conviction} | {row['n']} | {win_rate} | "
                f"{_fmt_pct(row['avg_return'])} | {_fmt_pct(row['avg_alpha_spy'])} | {_fmt_pct(row['p10_return'])} |"
            )

    if stats["regime_summary"]:
        lines.append("")
        lines.append(f"### {WEEK_LABELS[PRIMARY_WEEK]} 市場レジーム別リターン")
        lines.append("")
        lines.append("| Regime | n | 平均リターン |")
        lines.append("|---|---:|---:|")
        for regime, row in stats["regime_summary"].items():
            lines.append(f"| {regime} | {row['n']} | {_fmt_pct(row['avg_return'])} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## モメンタムモード別 ホライゾンサマリー")
    lines.append("")
    lines.append("| ホライゾン | モード | n | 平均リターン | 勝率 | SPY alpha | Sector alpha |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    mode_rows_written = 0
    for wk in WEEK_KEYS:
        for mode in MOMENTUM_MODES:
            row = stats["mode_summary"][wk][mode]
            if row["n"] == 0:
                continue
            mode_rows_written += 1
            lines.append(
                f"| {WEEK_LABELS[wk]} | {mode} | {row['n']} | {_fmt_pct(row['avg_return'])} | "
                f"{row['win_rate']:.1f}% | {_fmt_pct(row['avg_alpha_spy'])} | {_fmt_pct(row['avg_alpha_sector'])} |"
            )
    if mode_rows_written == 0:
        lines.append("| — | — | 0 | N/A | N/A | N/A | N/A |")
        lines.append("")
        lines.append("注: momentum mode を保存し始めた後の観測がまだ成熟していない場合、この表は空になる。")

    lines.append("")
    lines.append("## モード×ファクター 信頼性")
    lines.append("")
    lines.append("各セルは、同じモメンタムモード内での `factor score` と累積リターンの Spearman ρ。")
    lines.append("右端の alpha は `factor score ≥ 8` と `≤ 6` の平均SPY alpha を比較し、その観点の効き方をざっくり見る。")
    lines.append("")
    reliability_headers = " | ".join(f"{wk.removeprefix('week')}w ρ" for wk in WEEK_KEYS)
    lines.append(
        f"| モード | ファクター | Best | {reliability_headers} | High alpha | Low alpha |"
    )
    lines.append("|---|---|---|" + "---|" * len(WEEK_KEYS) + "---:|---:|")
    mode_factor_rows_with_signal = 0
    for mode in MOMENTUM_MODES:
        for factor in FACTORS:
            rows = stats["mode_factor_reliability"][mode][factor]
            valid = [
                (wk, row) for wk, row in rows.items()
                if not math.isnan(row["rho"])
            ]
            if valid:
                mode_factor_rows_with_signal += 1
                best_wk, best_row = max(valid, key=lambda item: item[1]["rho"])
                best_text = f"{WEEK_LABELS[best_wk]} {format_rho(best_row['rho'])}"
                high_alpha = _fmt_pct(best_row["high_score_avg_alpha"])
                low_alpha = _fmt_pct(best_row["low_score_avg_alpha"])
            else:
                best_text = "N/A"
                high_alpha = "N/A"
                low_alpha = "N/A"
            rho_cells = [format_rho(rows[wk]["rho"]) for wk in WEEK_KEYS]
            lines.append(
                f"| {mode} | {factor} | {best_text} | "
                + " | ".join(rho_cells)
                + f" | {high_alpha} | {low_alpha} |"
            )
    if mode_factor_rows_with_signal == 0:
        lines.append("")
        lines.append("注: mode別の因子信頼性は、mode付きスナップショットが十分に満期化すると出始める。")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## ファクター別 Spearman ρ（各週リターンとの相関）")
    lines.append("")
    factor_headers = " | ".join(f"{wk.removeprefix('week')}w ρ" for wk in WEEK_KEYS)
    lines.append(f"| ファクター | {factor_headers} |")
    lines.append("|---|" + "---|" * len(WEEK_KEYS))
    for factor in FACTORS:
        row = [factor]
        for wk in WEEK_KEYS:
            rho = stats["factor_ic"].get(factor, {}).get(wk, {}).get("rho", float("nan"))
            row.append(format_rho(rho))
        lines.append("| " + " | ".join(row) + " |")

    grade_stats = stats.get("factor_grade_reliability") or {}
    has_grade_rows = any(
        payload.get(PRIMARY_WEEK, {}).get(grade, {}).get("n", 0) > 0
        for payload in grade_stats.values()
        for grade in QUALITY_GRADES
    )
    lines.append("")
    lines.append(f"### Factor Grade Reliability（{WEEK_LABELS[PRIMARY_WEEK]}）")
    lines.append("")
    lines.append("新しい `factor_grades`（A/B/C/D）の検証。改善後のresearch結果が蓄積されるほど有効になる。")
    lines.append("")
    if has_grade_rows:
        lines.append("| ファクター | Grade | n | 勝率 | 平均リターン | SPY alpha |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for factor in FACTORS:
            week_rows = grade_stats.get(factor, {}).get(PRIMARY_WEEK, {})
            for grade in QUALITY_GRADES:
                row = week_rows.get(grade, {})
                n = row.get("n", 0)
                if n == 0:
                    continue
                win = row.get("win_rate")
                avg_ret = row.get("avg_return")
                avg_alpha = row.get("avg_alpha")
                lines.append(
                    f"| {factor} | {grade} | {n} | "
                    f"{win:.1f}% | {_fmt_pct(avg_ret)} | {_fmt_pct(avg_alpha)} |"
                )
    else:
        lines.append("grade付きスナップショットはまだ満期化していない。次回以降の `/research` で蓄積する。")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## スコア閾値（7.5）の妥当性検証")
    lines.append("")
    lines.append(f"- 閾値通過（≥7.5）: {stats['passed_n']} 件")
    lines.append(f"- 閾値未満（<7.5）: {stats['rejected_n']} 件")
    lines.append("")
    lines.append("| ホライゾン | 通過銘柄 avg | 除外銘柄 avg |")
    lines.append("|---|---|---|")
    for wk in WEEK_KEYS:
        tc = stats["threshold_comparison"][wk]
        lines.append(f"| {WEEK_LABELS[wk]} | {tc['passed_avg']} | {tc['rejected_avg']} |")

    if stats["calibration"]:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## キャリブレーション提案")
        lines.append("")
        for s in stats["calibration"]:
            lines.append(f"- {s}")

    lines.append("")
    return "\n".join(lines)


# ── エントリーポイント ────────────────────────────────────────────

def main() -> None:
    snapshots = load_snapshots()
    if not snapshots:
        print("score_snapshots.json にデータがありません。/research を実行してスナップショットを蓄積してください。")
        sys.exit(0)

    print(f"Analyzing {len(snapshots)} snapshots...")
    stats = analyze(snapshots)

    report = generate_report(stats)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"validation_{date.today().isoformat()}.md"
    out_path.write_text(report, encoding="utf-8")
    sync_local_to_supabase("report_artifacts")

    try:
        sync_validation_stats(
            stats=stats,
            report_markdown=report,
            report_path=str(out_path),
            validation_date=date.today().isoformat(),
        )
    except Exception as exc:
        print(f"WARNING: Supabase validation sync skipped: {exc}", file=sys.stderr)

    print(report)
    print(f"\n→ レポート保存先: {out_path}")


if __name__ == "__main__":
    main()

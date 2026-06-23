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

from investor.supabase_store import sync_validation_stats
from investor.supabase_sync import sync_local_to_supabase

SNAPSHOTS_PATH = Path(__file__).parent.parent / "data" / "score_snapshots.json"
REPORTS_DIR = Path(__file__).parent.parent / "reports" / "validation"
MIN_SAMPLES = 30
WEEK_KEYS = ["week1", "week2", "week3", "week4"]
WEEK_LABELS = {"week1": "1週後", "week2": "2週後", "week3": "3週後", "week4": "4週後"}
PRIMARY_WEEK = "week3"
FACTORS = ["momentum", "fundamentals", "catalyst", "technical", "sentiment"]
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
    passed = [s for s in snapshots if s.get("passed_threshold")]
    rejected = [s for s in snapshots if not s.get("passed_threshold")]

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
    result["regime_summary"] = build_regime_summary(snapshots)

    # ── キャリブレーション提案 ──
    result["calibration"] = build_calibration(ic, factor_ic)
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
            conviction = _infer_conviction(snap.get("score"))
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
                if _infer_conviction(snap.get("score")) != conviction:
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


def build_calibration(ic: dict, factor_ic: dict) -> list[str]:
    suggestions = []

    # IC に基づく総評。運用上は3週を主指標、4週を補助指標として見る。
    primary = ic.get(PRIMARY_WEEK, {})
    primary_rho = primary.get("rho", float("nan"))
    if not math.isnan(primary_rho):
        if primary_rho >= 0.4:
            suggestions.append("3週後ICが高い（ρ≥0.4）：スコアは良好な予測力を持っている")
        elif primary_rho >= 0.2:
            suggestions.append("3週後IC（ρ≥0.2）：スコアの予測力は中程度。3週後alphaを主指標として継続観測")
        else:
            suggestions.append("3週後ICが低い（ρ<0.2）：スコアの予測力が不十分。ウェイト見直しを検討")

    # ファクター別ウェイト提案（3週後ρ基準）
    factor_rhos = {}
    for factor in FACTORS:
        rho = factor_ic.get(factor, {}).get(PRIMARY_WEEK, {}).get("rho", float("nan"))
        if not math.isnan(rho):
            factor_rhos[factor] = rho

    if factor_rhos:
        best = max(factor_rhos, key=factor_rhos.get)
        worst = min(factor_rhos, key=factor_rhos.get)
        if factor_rhos[best] > 0.3:
            suggestions.append(f"{best}（ρ={factor_rhos[best]:.2f}）は最も予測力が高い → ウェイト引き上げを検討")
        if factor_rhos[worst] < 0.15:
            suggestions.append(f"{worst}（ρ={factor_rhos[worst]:.2f}）は予測力が弱い → ウェイト引き下げを検討")

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
    for wk in WEEK_KEYS:
        lines.append(f"| {WEEK_LABELS[wk]} リターン取得済み | {stats['counts'][wk]} 件 |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 週次 IC（Spearman ρ）— スコア vs 累積リターン")
    lines.append("")
    lines.append("| ホライゾン | サンプル数 | Spearman ρ | p値 | 判定 |")
    lines.append("|---|---|---|---|---|")
    for wk in WEEK_KEYS:
        d = stats["ic"][wk]
        lines.append(
            f"| {WEEK_LABELS[wk]} | {d['n']} | {format_rho(d['rho'])} | {format_p(d['p'])} | {d['label']} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## スコアバケット別 × 週別 平均リターン")
    lines.append("")
    lines.append("| スコアバケット | 件数 | 1w avg | 2w avg | 3w avg | 4w avg |")
    lines.append("|---|---|---|---|---|---|")
    for label, data in stats["buckets"].items():
        avgs = data["avgs"]
        lines.append(
            f"| {label} | {data['n']} | {avgs['week1']} | {avgs['week2']} | {avgs['week3']} | {avgs['week4']} |"
        )

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
    lines.append("3週後を主指標、4週後を補助指標として見る。QQQ/セクターalphaはデータがある場合のみ表示。")
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

    if stats["regime_summary"]:
        lines.append("")
        lines.append("### 3週後 市場レジーム別リターン")
        lines.append("")
        lines.append("| Regime | n | 平均リターン |")
        lines.append("|---|---:|---:|")
        for regime, row in stats["regime_summary"].items():
            lines.append(f"| {regime} | {row['n']} | {_fmt_pct(row['avg_return'])} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## ファクター別 Spearman ρ（各週リターンとの相関）")
    lines.append("")
    lines.append("| ファクター | 1w ρ | 2w ρ | 3w ρ | 4w ρ |")
    lines.append("|---|---|---|---|---|")
    for factor in FACTORS:
        row = [factor]
        for wk in WEEK_KEYS:
            rho = stats["factor_ic"].get(factor, {}).get(wk, {}).get("rho", float("nan"))
            row.append(format_rho(rho))
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## スコア閾値（7.0）の妥当性検証")
    lines.append("")
    lines.append(f"- 閾値通過（≥7.0）: {stats['passed_n']} 件")
    lines.append(f"- 閾値未満（<7.0）: {stats['rejected_n']} 件")
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

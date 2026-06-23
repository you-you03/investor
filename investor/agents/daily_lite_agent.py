"""
Daily Lite Agent.

Runs a single lightweight pass across:
  - open positions (monitor-lite)
  - active watchlist items (watchlist-lite)
  - broad market screen (research-lite)

Design goals:
  - no LLM calls
  - no writes to portfolio or research history
  - one report + one history file per run
  - conservative watchlist state updates only
"""

from __future__ import annotations

import csv
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from investor.agents.research_agent import collect_screen_data
from investor.config import settings
from investor.core.monitor import check_all_positions
from investor.data.yfinance_client import YFinanceClient
from investor.notifications.slack import SlackNotifier
from investor.supabase_sync import sync_local_to_supabase
from investor.tools.market_tools import get_earnings_calendar, get_technical_indicators
from investor.utils.logger import get_logger

logger = get_logger(__name__)

PORTFOLIO_PATH = Path(settings.default_portfolio_path)
WATCHLIST_PATH = Path("data/watchlist.json")
HISTORY_PATH = Path("data/daily_lite_history.json")
REPORTS_DIR = Path("reports/daily")

TERMINAL_PIPELINE_STATUSES = {"promoted", "exited"}
WATCHLIST_RSI_WAIT_KEYWORDS = ("wait", "押し目待ち", "rsi_wait_entry")


@dataclass
class DailyLiteResult:
    run_id: str
    date: str
    macro_context: dict[str, Any]
    positions: list[dict[str, Any]]
    position_alerts: list[dict[str, Any]]
    watchlist_results: list[dict[str, Any]]
    research_candidates: list[dict[str, Any]]
    pending_actions: list[dict[str, Any]]
    slack_sent: bool
    report_path: str


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            logger.warning("Failed to read %s", path)
    return default


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    if path == WATCHLIST_PATH:
        sync_local_to_supabase("watchlist")
    elif path == HISTORY_PATH:
        sync_local_to_supabase("daily_lite", "workflow_tasks")


def _load_open_positions() -> list[dict[str, Any]]:
    if not PORTFOLIO_PATH.exists():
        return []

    with PORTFOLIO_PATH.open() as f:
        reader = csv.DictReader(f)
        positions = []
        for row in reader:
            if row.get("status") != "open":
                continue
            shares = _safe_float(row.get("shares"))
            if not shares or shares <= 0:
                continue
            positions.append(row)
        return positions


def _load_watchlist() -> dict[str, Any]:
    return _read_json(WATCHLIST_PATH, {"items": []})


def _load_history() -> dict[str, Any]:
    return _read_json(HISTORY_PATH, {"runs": []})


def _append_reason_once(reason: str, marker: str, text: str) -> str:
    if marker in reason:
        return reason
    if not reason:
        return text
    return f"{reason} | {text}"


def _primary_flag(flags: list[str]) -> str | None:
    priority = [
        "RSI_COOLED",
        "WATCHLIST_BREAKOUT",
        "WATCHLIST_SETUP",
        "WATCHLIST_EARNINGS",
        "WATCHLIST_MOVED",
        "WATCHLIST_DROPPED",
    ]
    for item in priority:
        if item in flags:
            return item
    return None


def _format_macro_regime(macro_context: dict[str, Any]) -> str:
    return str(macro_context.get("regime") or "UNKNOWN")


def _format_number(value: Any, digits: int = 2) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _format_pct(value: Any, digits: int = 2) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    if abs(number) < 0.005:
        number = 0.0
    return f"{number:+.{digits}f}%"


def _format_money(value: Any, digits: int = 2) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    if abs(number) < 0.005:
        number = 0.0
    sign = "+" if number >= 0 else "-"
    return f"{sign}${abs(number):,.{digits}f}"


def _has_rsi_wait_context(reason: str) -> bool:
    lowered = reason.lower()
    return "rsi" in lowered and any(keyword in lowered for keyword in WATCHLIST_RSI_WAIT_KEYWORDS)


def _position_status(position: dict[str, Any], high_alert_tickers: set[str]) -> str:
    ticker = str(position.get("ticker", ""))
    if ticker in high_alert_tickers:
        return "要対応"
    pnl_pct = _safe_float(position.get("pnl_pct"))
    if pnl_pct is None:
        return "データ不足"
    if pnl_pct >= 5.0:
        return "含み益大"
    if pnl_pct >= 0:
        return "含み益"
    if pnl_pct <= -5.0:
        return "弱い"
    return "様子見"


def _pending_action_label(action: dict[str, Any]) -> str:
    action_type = str(action.get("type", ""))
    if action_type == "exit_decision":
        return "出口判断"
    if action_type == "entry_decision":
        return "買い判断"
    if action_type == "watchlist_seed":
        return "ウォッチ銘柄を深掘り"
    if action_type == "market_seed":
        return "新規候補を深掘り"
    return action_type


def _summarize_action_counts(pending_actions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "買い判断": 0,
        "ウォッチ銘柄を深掘り": 0,
        "新規候補を深掘り": 0,
        "出口判断": 0,
    }
    for action in pending_actions:
        label = _pending_action_label(action)
        if label in counts:
            counts[label] += 1
    return counts


def _pending_action_reason(
    action: dict[str, Any],
    watchlist_map: dict[str, dict[str, Any]],
    research_map: dict[str, dict[str, Any]],
) -> str:
    ticker = str(action.get("ticker", ""))
    if ticker in watchlist_map:
        item = watchlist_map[ticker]
        flag = item.get("primary_flag")
        price = _format_number(item.get("price"))
        ref_change = item.get("ref_change_pct")
        rsi = item.get("rsi")
        parts = []
        if flag:
            parts.append(str(flag))
        parts.append(f"現値 ${price}")
        if ref_change is not None:
            parts.append(f"参照比 {ref_change:+.1f}%")
        if rsi is not None:
            parts.append(f"RSI {rsi:.1f}")
        return " / ".join(parts)
    if ticker in research_map:
        item = research_map[ticker]
        score = item.get("score")
        price = _format_number(item.get("price"))
        day_change = _safe_float(item.get("change_pct"))
        reason = _humanize_research_reason(str(item.get("reason", "")))
        parts = [f"スコア {score:.2f}" if isinstance(score, (int, float)) else "スコア -", f"現値 ${price}"]
        if day_change is not None:
            parts.append(f"当日 {day_change:+.1f}%")
        if reason:
            parts.append(reason)
        return " / ".join(parts)
    detail = action.get("detail")
    return str(detail) if detail else ""


def _humanize_research_reason(reason: str) -> str:
    text = reason
    replacements = [
        ("day change", "当日騰落"),
        ("in trend zone", "がトレンド継続圏"),
        ("MACD positive", "MACDがプラス圏"),
        ("above EMA50", "EMA50より上"),
        ("near 52w high", "52週高値圏"),
        ("strong day move", "当日大幅上昇"),
    ]
    for src, dst in replacements:
        text = text.replace(src, dst)
    return text


class DailyLiteAgent:
    def __init__(self) -> None:
        self.yf = YFinanceClient()
        self.slack = SlackNotifier()

    def run(
        self,
        dry_run: bool = False,
        max_research_candidates: int = 5,
    ) -> DailyLiteResult:
        run_id = str(uuid.uuid4())
        today = date.today().isoformat()
        macro_context = self.yf.get_market_context()

        positions, position_alerts = self._run_monitor_lite()
        watchlist_data = self._run_watchlist_lite(
            today=today,
            open_position_tickers={p["ticker"] for p in positions},
            dry_run=dry_run,
        )
        research_candidates = self._run_research_lite(
            macro_context=macro_context,
            exclude_tickers={p["ticker"] for p in positions} | {r["ticker"] for r in watchlist_data},
            max_research_candidates=max_research_candidates,
        )
        pending_actions = self._build_pending_actions(
            position_alerts=position_alerts,
            watchlist_results=watchlist_data,
            research_candidates=research_candidates,
        )

        report_path = self._save_report(
            today=today,
            run_id=run_id,
            macro_context=macro_context,
            positions=positions,
            position_alerts=position_alerts,
            watchlist_results=watchlist_data,
            research_candidates=research_candidates,
            pending_actions=pending_actions,
        )

        history_payload = {
            "run_id": run_id,
            "date": today,
            "macro_context": macro_context,
            "positions": positions,
            "position_alerts": position_alerts,
            "watchlist_results": watchlist_data,
            "research_candidates": research_candidates,
            "pending_actions": pending_actions,
            "report_path": str(report_path),
        }
        if not dry_run:
            history = _load_history()
            history["runs"].append(history_payload)
            _write_json(HISTORY_PATH, history)

        slack_sent = False
        if not dry_run:
            slack_sent = self.slack.send_text(
                self._build_slack_text(
                    today=today,
                    macro_context=macro_context,
                    positions=positions,
                    position_alerts=position_alerts,
                    watchlist_results=watchlist_data,
                    research_candidates=research_candidates,
                    pending_actions=pending_actions,
                )
            )

        return DailyLiteResult(
            run_id=run_id,
            date=today,
            macro_context=macro_context,
            positions=positions,
            position_alerts=position_alerts,
            watchlist_results=watchlist_data,
            research_candidates=research_candidates,
            pending_actions=pending_actions,
            slack_sent=slack_sent,
            report_path=str(report_path),
        )

    def _run_monitor_lite(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        raw_positions = _load_open_positions()
        snapshots: dict[str, dict[str, Any]] = {}
        positions: list[dict[str, Any]] = []

        for row in raw_positions:
            ticker = str(row["ticker"]).upper()
            snapshot = self.yf.get_stock_snapshot(ticker) or {}
            snapshots[ticker] = snapshot
            entry_price = _safe_float(row.get("entry_price")) or 0.0
            shares = _safe_float(row.get("shares")) or 0.0
            current_price = _safe_float(snapshot.get("price"))
            pnl_pct = None
            if current_price and entry_price:
                pnl_pct = round((current_price - entry_price) / entry_price * 100, 2)
            positions.append(
                {
                    "ticker": ticker,
                    "shares": shares,
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "target_price": _safe_float(row.get("target_price")),
                    "stop_loss": _safe_float(row.get("stop_loss")),
                    "pnl_pct": pnl_pct,
                    "change_pct": _safe_float(snapshot.get("change_pct")),
                    "note": row.get("note", ""),
                }
            )

        alerts = [alert.to_dict() for alert in check_all_positions(raw_positions, snapshots)]
        return positions, alerts

    def _run_watchlist_lite(
        self,
        today: str,
        open_position_tickers: set[str],
        dry_run: bool,
    ) -> list[dict[str, Any]]:
        watchlist = _load_watchlist()
        items = watchlist.get("items", [])
        active_items = [item for item in items if item.get("status") == "active"]

        if not active_items:
            return []

        def _collect(item: dict[str, Any]) -> dict[str, Any]:
            ticker = str(item["ticker"]).upper()
            snapshot = self.yf.get_stock_snapshot(ticker) or {}
            technicals = json.loads(get_technical_indicators(ticker))
            earnings = json.loads(get_earnings_calendar(ticker))
            return {
                "item": item,
                "snapshot": snapshot,
                "technicals": technicals,
                "earnings": earnings,
            }

        collected: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(6, len(active_items))) as executor:
            futures = [executor.submit(_collect, item) for item in active_items]
            for future in as_completed(futures):
                try:
                    collected.append(future.result())
                except Exception as exc:
                    logger.warning("watchlist-lite collect failed: %s", exc)

        results: list[dict[str, Any]] = []
        item_map = {str(item["ticker"]).upper(): item for item in items if item.get("ticker")}

        for bundle in sorted(collected, key=lambda x: x["item"]["ticker"]):
            item = bundle["item"]
            ticker = str(item["ticker"]).upper()
            snapshot = bundle["snapshot"]
            technicals = bundle["technicals"]
            earnings = bundle["earnings"]

            price = _safe_float(snapshot.get("price"))
            change_pct = _safe_float(snapshot.get("change_pct")) or 0.0
            reference_price = _safe_float(item.get("reference_price"))
            ref_change_pct = round((price - reference_price) / reference_price * 100, 2) if price and reference_price else None
            rsi = _safe_float(technicals.get("rsi_14"))
            macd_hist = _safe_float((technicals.get("macd") or {}).get("histogram"))
            ema20 = _safe_float(technicals.get("ema_20"))
            last_score = _safe_float(item.get("last_score"))
            days_until_earnings = earnings.get("days_until_earnings")
            reason = str(item.get("reason", ""))
            last_monitor_flag = str(item.get("last_monitor_flag") or "")
            pipeline_status = str(item.get("pipeline_status") or "watching")

            flags: list[str] = []
            if rsi is not None and macd_hist is not None and ema20 is not None and price is not None:
                if change_pct >= 5.0 and price >= ema20 and macd_hist > 0:
                    flags.append("WATCHLIST_BREAKOUT")
                if 40.0 <= rsi <= 60.0 and macd_hist > 0 and price >= ema20:
                    flags.append("WATCHLIST_SETUP")
            if isinstance(days_until_earnings, int) and 0 <= days_until_earnings <= 14:
                flags.append("WATCHLIST_EARNINGS")
            if ref_change_pct is not None and ref_change_pct >= 15.0:
                flags.append("WATCHLIST_MOVED")
            if ref_change_pct is not None and ref_change_pct <= -10.0:
                flags.append("WATCHLIST_DROPPED")

            reason_has_rsi_wait = _has_rsi_wait_context(reason)
            if (
                last_score is not None
                and last_score >= 7.5
                and rsi is not None
                and rsi <= 65.0
                and (last_monitor_flag == "EXTREME_RSI" or reason_has_rsi_wait)
            ):
                flags.append("RSI_COOLED")

            primary_flag = _primary_flag(flags)
            action = "MAINTAIN"
            next_step = None
            if ticker in open_position_tickers:
                action = "IN_PORTFOLIO"
                next_step = None
            elif "RSI_COOLED" in flags or ("WATCHLIST_BREAKOUT" in flags and (last_score or 0) >= 7.5):
                action = "ESCALATE_TO_DECISION"
                next_step = "/decision"
            elif any(flag in flags for flag in ("WATCHLIST_BREAKOUT", "WATCHLIST_SETUP", "WATCHLIST_EARNINGS", "WATCHLIST_MOVED")):
                action = "RESEARCH_SEED"
                next_step = f"/research --seed {ticker}"
            elif "WATCHLIST_DROPPED" in flags:
                action = "REVIEW"
                next_step = f"manual review: {ticker}"

            mutable_item = item_map.get(ticker)
            if mutable_item is not None:
                mutable_item["last_monitor_date"] = today
                mutable_item["last_monitor_flag"] = primary_flag

                consecutive_drops = int(mutable_item.get("consecutive_drops") or 0)
                if "WATCHLIST_DROPPED" in flags:
                    consecutive_drops += 1
                else:
                    consecutive_drops = 0
                mutable_item["consecutive_drops"] = consecutive_drops

                if ticker in open_position_tickers:
                    mutable_item["pipeline_status"] = "promoted"
                elif mutable_item.get("pipeline_status") not in TERMINAL_PIPELINE_STATUSES:
                    if action == "ESCALATE_TO_DECISION":
                        mutable_item["pipeline_status"] = "decision_queued"
                    elif action == "RESEARCH_SEED":
                        mutable_item["pipeline_status"] = "research_queued"

                if "RSI_COOLED" in flags and rsi is not None:
                    marker = f"{today} RSI_COOLED"
                    note = f"{today} RSI_COOLED: RSI={rsi:.1f} <= 65. decision候補。"
                    mutable_item["reason"] = _append_reason_once(reason, marker, note)
                elif "WATCHLIST_MOVED" in flags and ref_change_pct is not None:
                    marker = f"{today} WATCHLIST_MOVED"
                    note = f"{today} WATCHLIST_MOVED: 参照比{ref_change_pct:+.1f}%。"
                    mutable_item["reason"] = _append_reason_once(reason, marker, note)
                elif "WATCHLIST_DROPPED" in flags and ref_change_pct is not None:
                    marker = f"{today} WATCHLIST_DROPPED"
                    note = f"{today} WATCHLIST_DROPPED: 参照比{ref_change_pct:+.1f}%。"
                    mutable_item["reason"] = _append_reason_once(reason, marker, note)

            results.append(
                {
                    "ticker": ticker,
                    "price": price,
                    "change_pct": round(change_pct, 2),
                    "reference_price": reference_price,
                    "ref_change_pct": ref_change_pct,
                    "rsi": rsi,
                    "days_until_earnings": days_until_earnings,
                    "flags": flags,
                    "primary_flag": primary_flag,
                    "action": action,
                    "pipeline_status": (mutable_item or item).get("pipeline_status"),
                    "next_step": next_step,
                    "last_score": last_score,
                }
            )

        if not dry_run:
            _write_json(WATCHLIST_PATH, watchlist)

        return results

    def _run_research_lite(
        self,
        macro_context: dict[str, Any],
        exclude_tickers: set[str],
        max_research_candidates: int,
    ) -> list[dict[str, Any]]:
        screen = collect_screen_data(parallel=True)
        regime = _format_macro_regime(macro_context)
        candidates: list[dict[str, Any]] = []

        for ticker, payload in screen.get("ticker_data", {}).items():
            if ticker in exclude_tickers:
                continue
            snapshot = payload.get("snapshot", {})
            technicals = payload.get("technicals", {})
            if snapshot.get("error") or technicals.get("error"):
                continue

            score, reasons = self._score_screen_candidate(snapshot, technicals, regime)
            if score < 3.5:
                continue

            candidates.append(
                {
                    "ticker": ticker,
                    "score": round(score, 2),
                    "price": _safe_float(snapshot.get("price")),
                    "change_pct": _safe_float(snapshot.get("change_pct")),
                    "rsi": _safe_float(technicals.get("rsi_14")),
                    "reason": "; ".join(reasons[:3]),
                    "next_step": f"/research --seed {ticker}",
                }
            )

        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates[:max_research_candidates]

    def _score_screen_candidate(
        self,
        snapshot: dict[str, Any],
        technicals: dict[str, Any],
        regime: str,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        price = _safe_float(snapshot.get("price"))
        change_pct = _safe_float(snapshot.get("change_pct")) or 0.0
        market_cap = _safe_float(snapshot.get("market_cap")) or 0.0
        high_52w = _safe_float(snapshot.get("fifty_two_week_high"))
        rsi = _safe_float(technicals.get("rsi_14"))
        ema20 = _safe_float(technicals.get("ema_20"))
        ema50 = _safe_float(technicals.get("ema_50"))
        macd_hist = _safe_float((technicals.get("macd") or {}).get("histogram"))

        if 1.0 <= change_pct <= 8.0:
            score += 1.5
            reasons.append(f"day change {change_pct:+.1f}%")
        elif change_pct > 8.0:
            score += 1.0
            reasons.append(f"strong day move {change_pct:+.1f}%")
        elif change_pct < -2.0:
            score -= 1.0

        if rsi is not None:
            if 45.0 <= rsi <= 68.0:
                score += 1.5
                reasons.append(f"RSI {rsi:.1f} in trend zone")
            elif 68.0 < rsi <= 75.0:
                score += 0.5
            elif rsi > 75.0:
                score -= 1.0
            elif rsi < 35.0:
                score -= 0.5

        if macd_hist is not None:
            if macd_hist > 0:
                score += 1.0
                reasons.append("MACD positive")
            else:
                score -= 0.5

        if price is not None and ema20 is not None and price >= ema20:
            score += 0.5
        if price is not None and ema50 is not None and price >= ema50:
            score += 0.5
            reasons.append("above EMA50")

        if price is not None and high_52w:
            distance_to_high = (high_52w - price) / high_52w * 100
            if 0 <= distance_to_high <= 10:
                score += 0.75
                reasons.append("near 52w high")

        if 500_000_000 <= market_cap <= 50_000_000_000:
            score += 0.75
        elif market_cap > 250_000_000_000:
            score -= 0.25

        if "HIGH_FEAR" in regime or "RISK_OFF" in regime:
            score -= 0.75
        elif "DOWNTREND" in regime:
            score -= 0.5

        return score, reasons

    def _build_pending_actions(
        self,
        position_alerts: list[dict[str, Any]],
        watchlist_results: list[dict[str, Any]],
        research_candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []

        for alert in position_alerts:
            if alert.get("severity") == "HIGH":
                actions.append(
                    {
                        "ticker": alert.get("ticker"),
                        "type": "exit_decision",
                        "detail": alert.get("alert_type"),
                        "command": f"/decision --mode exit --ticker {alert.get('ticker')}",
                    }
                )

        for item in watchlist_results:
            if item.get("action") == "ESCALATE_TO_DECISION":
                actions.append(
                    {
                        "ticker": item["ticker"],
                        "type": "entry_decision",
                        "detail": item.get("primary_flag"),
                        "command": "/decision",
                    }
                )
            elif item.get("action") == "RESEARCH_SEED":
                actions.append(
                    {
                        "ticker": item["ticker"],
                        "type": "watchlist_seed",
                        "detail": item.get("primary_flag"),
                        "command": item["next_step"],
                    }
                )

        for candidate in research_candidates:
            actions.append(
                {
                    "ticker": candidate["ticker"],
                    "type": "market_seed",
                    "detail": f"score={candidate['score']}",
                    "command": candidate["next_step"],
                }
            )

        return actions

    def _save_report(
        self,
        today: str,
        run_id: str,
        macro_context: dict[str, Any],
        positions: list[dict[str, Any]],
        position_alerts: list[dict[str, Any]],
        watchlist_results: list[dict[str, Any]],
        research_candidates: list[dict[str, Any]],
        pending_actions: list[dict[str, Any]],
    ) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORTS_DIR / f"daily_lite_{today}.md"

        regime = _format_macro_regime(macro_context)
        high_alerts = [a for a in position_alerts if a.get("severity") == "HIGH"]
        escalated = [w for w in watchlist_results if w.get("action") == "ESCALATE_TO_DECISION"]
        seeded = [w for w in watchlist_results if w.get("action") == "RESEARCH_SEED"]

        lines = [
            f"# Daily Lite Report - {today}",
            "",
            f"run_id: `{run_id}`",
            "",
            f"macro regime: **{regime}**",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Open positions | {len(positions)} |",
            f"| Position alerts | {len(position_alerts)} total / {len(high_alerts)} HIGH |",
            f"| Active watchlist reviewed | {len(watchlist_results)} |",
            f"| Watchlist escalations | {len(escalated)} |",
            f"| Watchlist seed candidates | {len(seeded)} |",
            f"| Market seed candidates | {len(research_candidates)} |",
            "",
            "## Position Alerts",
            "",
        ]

        if position_alerts:
            lines.extend([
                "| Ticker | Severity | Type | Current | PnL % | Message |",
                "|---|---|---|---:|---:|---|",
            ])
            for alert in position_alerts:
                lines.append(
                    f"| {alert.get('ticker')} | {alert.get('severity')} | {alert.get('alert_type')} | "
                    f"{_format_number(alert.get('current_price'))} | {_format_number(alert.get('unrealized_pnl_pct'))} | {alert.get('message')} |"
                )
        else:
            lines.append("No position alerts.")

        lines.extend(["", "## Watchlist Lite", ""])
        if watchlist_results:
            lines.extend([
                "| Ticker | Action | Flag | Price | Day % | Ref % | RSI | Next |",
                "|---|---|---|---:|---:|---:|---:|---|",
            ])
            for item in watchlist_results:
                ref_change = item.get("ref_change_pct")
                rsi = item.get("rsi")
                day_change = _safe_float(item.get("change_pct")) or 0.0
                ref_change_str = f"{ref_change:+.2f}" if ref_change is not None else "-"
                rsi_str = f"{rsi:.1f}" if rsi is not None else "-"
                lines.append(
                    f"| {item['ticker']} | {item['action']} | {item.get('primary_flag') or '-'} | "
                    f"{_format_number(item.get('price'))} | {day_change:+.2f} | {ref_change_str} | "
                    f"{rsi_str} | {item.get('next_step') or '-'} |"
                )
        else:
            lines.append("No active watchlist items.")

        lines.extend(["", "## Research Lite", ""])
        if research_candidates:
            lines.extend([
                "| Ticker | Score | Price | Day % | RSI | Reason | Next |",
                "|---|---:|---:|---:|---:|---|---|",
            ])
            for candidate in research_candidates:
                lines.append(
                    f"| {candidate['ticker']} | {candidate['score']:.2f} | {_format_number(candidate.get('price'))} | "
                    f"{(_safe_float(candidate.get('change_pct')) or 0):+.2f} | "
                    f"{_format_number(candidate.get('rsi'))} | "
                    f"{candidate['reason']} | {candidate['next_step']} |"
                )
        else:
            lines.append("No market seed candidates passed the lite threshold.")

        lines.extend(["", "## Pending Actions", ""])
        if pending_actions:
            lines.extend([
                "| Ticker | Type | Detail | Command |",
                "|---|---|---|---|",
            ])
            for action in pending_actions:
                lines.append(
                    f"| {action['ticker']} | {action['type']} | {action['detail']} | {action['command']} |"
                )
        else:
            lines.append("No pending actions.")

        lines.extend([
            "",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])

        report_path.write_text("\n".join(lines))
        sync_local_to_supabase("report_artifacts")
        return report_path

    def _build_slack_text(
        self,
        today: str,
        macro_context: dict[str, Any],
        positions: list[dict[str, Any]],
        position_alerts: list[dict[str, Any]],
        watchlist_results: list[dict[str, Any]],
        research_candidates: list[dict[str, Any]],
        pending_actions: list[dict[str, Any]],
    ) -> str:
        regime = _format_macro_regime(macro_context)
        high_alerts = [a for a in position_alerts if a.get("severity") == "HIGH"]
        high_alert_tickers = {str(a.get("ticker", "")) for a in high_alerts}
        action_counts = _summarize_action_counts(pending_actions)
        entry_candidates = [
            str(action.get("ticker"))
            for action in pending_actions
            if _pending_action_label(action) == "買い判断"
        ]

        lines = [
            f"{today.replace('-', '/')} 朝の投資メモ",
            "",
            "**【相場】**",
            f"- レジーム: {regime}",
            f"- 緊急アラート: {len(high_alerts)}件",
        ]

        lines.extend(["", "**【保有株】**"])
        if positions:
            for position in positions:
                ticker = str(position.get("ticker", ""))
                entry = _format_number(position.get("entry_price"))
                current = _format_number(position.get("current_price"))
                pnl_str = _format_pct(position.get("pnl_pct"))
                pnl_amount = "-"
                entry_price = _safe_float(position.get("entry_price"))
                current_price = _safe_float(position.get("current_price"))
                shares = _safe_float(position.get("shares"))
                if entry_price is not None and current_price is not None and shares is not None:
                    pnl_amount = f"（{_format_money((current_price - entry_price) * shares)}）"
                status = _position_status(position, high_alert_tickers)
                lines.append(
                    f"- **{ticker}**  ${entry} → ${current}  {pnl_str}  {pnl_amount}  {status}"
                )
        else:
            lines.append("- 保有株なし")

        lines.extend(["", "**【要対応】**"])
        lines.append(f"- 買い判断: {action_counts['買い判断']}件")
        lines.append(f"- ウォッチ銘柄を深掘り: {action_counts['ウォッチ銘柄を深掘り']}件")
        lines.append(f"- 新規候補を深掘り: {action_counts['新規候補を深掘り']}件")
        if action_counts["出口判断"]:
            lines.append(f"- 出口判断: {action_counts['出口判断']}件")
        lines.append(f"- 合計: {len(pending_actions)}件")

        lines.extend(["", "**【今日のひとこと】**"])
        if high_alerts:
            lines.append(f"- 緊急アラート {len(high_alerts)}件。最優先で確認")
        else:
            lines.append("- 保有株に緊急対応なし")
        if entry_candidates:
            lines.append(f"- {', '.join(entry_candidates)} が買い判断候補")
        elif pending_actions:
            lines.append("- 深掘り候補が多い日")
        else:
            lines.append("- 今日は大きな追加対応なし")

        return "\n".join(lines)

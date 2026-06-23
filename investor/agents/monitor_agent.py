"""
Monitor Agent — runs daily to check open positions and send alerts.

Flow:
  1. Load all open positions from the configured default portfolio
  2. Fetch current price/snapshot via yfinance for each position
  3. Rule-based threshold checks (investor/core/monitor.py) — Python only, no Claude
  4. Save alert records to data/monitor_alerts.json
  5. Send Slack daily summary + separate HIGH severity alerts

Design: No Anthropic SDK calls. Claude Code (the session) reads the alerts
and provides commentary via /monitor command in CLAUDE.md.
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import date, datetime
from pathlib import Path
from investor.config import settings
from investor.core.monitor import Alert, check_all_positions
from investor.core.market_news import collect_market_news
from investor.data.yfinance_client import YFinanceClient
from investor.notifications.slack import SlackNotifier
from investor.supabase_store import is_enabled as supabase_is_enabled
from investor.supabase_store import sync_monitor_run
from investor.supabase_store import sync_watchlist_monitor_run
from investor.supabase_sync import sync_local_to_supabase
from investor.tools.market_tools import get_earnings_calendar, get_technical_indicators
from investor.utils.logger import get_logger

logger = get_logger(__name__)

PORTFOLIO_PATH = Path(settings.default_portfolio_path)
WATCHLIST_PATH = Path("data/watchlist.json")
ALERTS_PATH = Path("data/monitor_alerts.json")
HISTORY_PATH = Path("data/monitor_history.json")
REPORTS_DIR = Path("reports/monitor")


def _load_open_positions() -> list[dict]:
    if not PORTFOLIO_PATH.exists():
        return []
    try:
        with open(PORTFOLIO_PATH) as f:
            reader = csv.DictReader(f)
            return [row for row in reader if row.get("status") == "open"]
    except Exception as e:
        logger.warning(f"Failed to read portfolio: {e}")
        return []


def _safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_active_watchlist_items() -> list[dict]:
    if not WATCHLIST_PATH.exists():
        return []
    try:
        data = json.loads(WATCHLIST_PATH.read_text())
        return [
            item for item in data.get("items", [])
            if item.get("status") == "active" and item.get("ticker")
        ]
    except Exception as e:
        logger.warning(f"Failed to read watchlist: {e}")
        return []


def _save_alerts(alerts: list[dict]) -> None:
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if ALERTS_PATH.exists():
        try:
            history = json.loads(ALERTS_PATH.read_text())
        except Exception:
            pass
    history.extend(alerts)
    ALERTS_PATH.write_text(json.dumps(history, indent=2))


def _save_daily_summary(positions: list[dict], alerts: list[dict], market_news: dict | None = None) -> dict:
    """Always save daily run record including price snapshots and alert count."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text())
        except Exception:
            pass
    record = {
        "date": date.today().isoformat(),
        "position_count": len(positions),
        "alert_count": len(alerts),
        "high_alert_count": sum(1 for a in alerts if a.get("severity") == "HIGH"),
        "positions": positions,
        "alerts": alerts,
        "market_news": market_news or {},
    }
    history.append(record)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))
    _save_markdown_report(positions, alerts, market_news=market_news)
    return record


def _save_watchlist_summary(items: list[dict], alerts: list[dict]) -> dict:
    record = {
        "run_id": str(uuid.uuid4()),
        "date": date.today().isoformat(),
        "item_count": len(items),
        "alert_count": len(alerts),
        "decision_needed_count": sum(1 for item in items if item.get("action") == "decision_needed"),
        "research_needed_count": sum(1 for item in items if item.get("action") == "research_needed"),
        "items": items,
        "alerts": alerts,
    }
    sync_watchlist_monitor_run(record)
    return record


def _save_markdown_report(positions: list[dict], alerts: list[dict], market_news: dict | None = None) -> None:
    """Generate and save a markdown report to reports/monitor/monitor_{date}.md."""
    today = date.today().isoformat()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"monitor_{today}.md"

    severity_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}

    total_pnl = 0.0
    position_rows: list[str] = []
    for p in positions:
        current = p.get("current_price")
        entry = p.get("entry_price", 0.0)
        shares = p.get("shares", 0.0)
        target = p.get("target_price", "—")
        stop = p.get("stop_loss", "—")
        ticker = p.get("ticker", "")

        if current and entry and shares:
            pnl = (current - entry) * shares
            pnl_pct = (current - entry) / entry * 100
            total_pnl += pnl
            state = "✅" if pnl >= 0 else "⚠️"
            position_rows.append(
                f"| {ticker} | ${current:.2f} | ${entry:.2f} | {shares:.0f} "
                f"| {pnl:+.2f} | {pnl_pct:+.1f}% | ${stop} | ${target} | {state} |"
            )
        else:
            position_rows.append(
                f"| {ticker} | — | ${entry:.2f} | {shares:.0f} | — | — | ${stop} | ${target} | — |"
            )

    high_count = sum(1 for a in alerts if a.get("severity") == "HIGH")
    med_count = sum(1 for a in alerts if a.get("severity") == "MEDIUM")
    low_count = sum(1 for a in alerts if a.get("severity") == "LOW")

    alert_rows: list[str] = []
    for a in alerts:
        icon = severity_icon.get(a.get("severity", "LOW"), "🔵")
        alert_rows.append(
            f"| {icon} {a.get('severity', '—')} | {a.get('ticker', '—')} "
            f"| {a.get('alert_type', '—')} | {a.get('message', '—')} |"
        )

    lines: list[str] = [
        f"# Monitor Report — {today}",
        "",
        "## サマリー",
        "",
        "| 指標 | 値 |",
        "|---|---|",
        f"| オープンポジション | {len(positions)} 銘柄 |",
        f"| 合計未実現損益 | **{total_pnl:+.2f}** |",
        f"| 🔴 HIGH アラート | {high_count} 件 |",
        f"| 🟡 MEDIUM アラート | {med_count} 件 |",
        f"| 🔵 LOW アラート | {low_count} 件 |",
        "",
        "---",
        "",
        "## ポジション損益",
        "",
        "| Ticker | 現在値 | 買値 | 株数 | 損益 | 損益% | ストップ | 目標 | 状態 |",
        "|--------|-------|------|------|------|------|---------|------|------|",
    ]
    lines.extend(position_rows)
    lines += [
        "",
        "---",
        "",
        "## アラート",
        "",
    ]
    if alert_rows:
        lines += [
            "| 重要度 | Ticker | タイプ | メッセージ |",
            "|--------|--------|--------|-----------|",
        ]
        lines.extend(alert_rows)
    else:
        lines.append("アラートなし — 全ポジション正常範囲内。")

    news_items = (market_news or {}).get("items") or []
    lines += [
        "",
        "---",
        "",
        "## 関連テーマニュース（参考）",
        "",
        "> 未検証の参考情報。research / decision の補助材料として扱い、売買判断のファクトにはしない。",
        "",
    ]
    if news_items:
        for item in news_items:
            source = item.get("source_label") or item.get("theme") or item.get("source") or "関連テーマ"
            title = str(item.get("title") or "")
            key_point = str(item.get("key_point") or item.get("summary") or "").strip()
            url = item.get("url")
            title_line = f"### {source}"
            if str(url).startswith(("http://", "https://")):
                title_line += f" — [{title}]({url})"
            else:
                title_line += f" — {title}"
            lines += ["", title_line, ""]
            if key_point:
                lines.extend(key_point.splitlines())
            articles = item.get("source_articles") or []
            if articles:
                lines += ["", "参照記事:"]
                for article in articles[:3]:
                    article_title = str(article.get("title") or "")
                    article_url = article.get("url")
                    article_source = article.get("source") or "-"
                    if str(article_url).startswith(("http://", "https://")):
                        lines.append(f"- [{article_title}]({article_url}) ({article_source})")
                    else:
                        lines.append(f"- {article_title} ({article_source})")
    else:
        lines.append("参考ニュースなし。")

    if market_news:
        limits = market_news.get("collection_limits") or {}
        lines += [
            "",
            f"_DB: {market_news.get('db_path')} | "
            f"active={limits.get('active_sources')} / candidate_probe={limits.get('candidate_probe_sources')} / "
            f"items_per_source={limits.get('items_per_source')} / report_items={limits.get('report_items')}_",
        ]

    lines += [
        "",
        "---",
        "",
        f"*生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {HISTORY_PATH}*",
    ]

    report_path.write_text("\n".join(lines))
    logger.info(f"Saved markdown report to {report_path}")
    sync_local_to_supabase("report_artifacts")


class MonitorAgent:
    def __init__(self) -> None:
        self.yf = YFinanceClient()
        self.slack = SlackNotifier()
        self.last_portfolio_record: dict | None = None
        self.last_watchlist_record: dict | None = None

    def run(self, dry_run: bool = False) -> list[dict]:
        """Execute daily monitoring for all open positions."""
        logger.info("Monitor Agent started")

        positions = _load_open_positions()
        if not positions:
            logger.info("No open positions to monitor")
            if not dry_run:
                market_news = collect_market_news(yf_client=self.yf)
                record = _save_daily_summary([], [], market_news=market_news)
                self.last_portfolio_record = record
                sync_monitor_run(record)
                if not supabase_is_enabled():
                    self.slack.send_portfolio_summary([], [], market_news=market_news)
            return []

        logger.info(f"Monitoring {len(positions)} open position(s)")

        # Step 1: Fetch snapshots for all positions
        snapshots: dict[str, dict] = {}
        for p in positions:
            ticker = p["ticker"].upper()
            logger.info(f"  Fetching snapshot for {ticker}")
            snapshot = self.yf.get_stock_snapshot(ticker)
            if snapshot:
                snapshots[ticker] = snapshot

        # Step 2: Rule-based threshold checks (no Claude)
        rule_alerts = check_all_positions(positions, snapshots)
        high_alerts = [a for a in rule_alerts if a.severity == "HIGH"]
        logger.info(
            f"Threshold checks complete: {len(rule_alerts)} alert(s), "
            f"{len(high_alerts)} HIGH"
        )

        # Step 3: Build alert records (rule-based only; Claude commentary via /monitor skill)
        today = date.today().isoformat()
        alert_records = []
        for alert in rule_alerts:
            record = {
                "date": today,
                **alert.to_dict(),
            }
            alert_records.append(record)

        # Step 4: Build enriched positions for Slack and GitHub summary.
        enriched_positions = []
        for p in positions:
            ticker = p["ticker"].upper()
            snap = snapshots.get(ticker, {})
            entry_price = float(p.get("entry_price") or 0)
            shares = float(p.get("shares") or 0)
            current_price = snap.get("price")
            pnl_pct = None
            if current_price and entry_price:
                pnl_pct = round((float(current_price) - entry_price) / entry_price * 100, 2)
            enriched_positions.append({
                "ticker": ticker,
                "shares": shares,
                "entry_price": entry_price,
                "current_price": current_price,
                "target_price": p.get("target_price") or None,
                "stop_loss": p.get("stop_loss") or None,
                "pnl_pct": pnl_pct,
                "change_pct": snap.get("change_pct"),
                "note": p.get("note") or "",
            })

        if dry_run:
            self.last_portfolio_record = {
                "date": today,
                "position_count": len(enriched_positions),
                "alert_count": len(alert_records),
                "high_alert_count": sum(1 for a in alert_records if a.get("severity") == "HIGH"),
                "positions": enriched_positions,
                "alerts": alert_records,
                "market_news": {},
            }
            logger.info("[DRY RUN] Alerts:\n" + json.dumps(alert_records, indent=2))
            return alert_records

        if alert_records:
            _save_alerts(alert_records)
            logger.info(f"Saved {len(alert_records)} alert(s)")

        # Step 5: Lightweight market/sector news context. This is never used as
        # alert evidence; it is saved as weak reference material for later review.
        market_news = collect_market_news(yf_client=self.yf)
        logger.info(
            "Collected %d market/sector news reference(s)",
            len(market_news.get("items") or []),
        )

        # Always save daily summary (even with 0 alerts)
        record = _save_daily_summary(enriched_positions, alert_records, market_news=market_news)
        self.last_portfolio_record = record
        sync_monitor_run(record)
        logger.info(f"Saved daily summary to {HISTORY_PATH}")

        # Daily summary. Alerts may also be enqueued through Supabase, but this
        # position table is the only Slack message that shows the full book.
        self.slack.send_portfolio_summary(enriched_positions, alert_records, market_news=market_news)

        # Separate HIGH alerts only on the legacy path. With Supabase enabled,
        # scripts/send_pending_notifications.py sends the queued alert rows.
        if not supabase_is_enabled():
            position_map = {p["ticker"]: p for p in enriched_positions}
            for record in alert_records:
                if record.get("severity") == "HIGH":
                    position = position_map.get(record["ticker"])
                    if position:
                        self.slack.send_sell_alert(record, position)

        return alert_records

    def run_watchlist_monitor(self, dry_run: bool = False) -> dict:
        """Mechanically monitor active watchlist tickers. No AI calls."""
        items = _load_active_watchlist_items()
        if not items:
            return _save_watchlist_summary([], []) if not dry_run else {"items": [], "alerts": []}

        results: list[dict] = []
        alerts: list[dict] = []
        today = date.today().isoformat()

        for item in sorted(items, key=lambda row: str(row.get("ticker", ""))):
            ticker = str(item["ticker"]).upper()
            snapshot = self.yf.get_stock_snapshot(ticker) or {}
            try:
                technicals = json.loads(get_technical_indicators(ticker))
            except Exception:
                technicals = {}
            try:
                earnings = json.loads(get_earnings_calendar(ticker))
            except Exception:
                earnings = {}

            price = _safe_float(snapshot.get("price"))
            change_pct = _safe_float(snapshot.get("change_pct")) or 0.0
            reference_price = _safe_float(item.get("reference_price"))
            ref_change_pct = round((price - reference_price) / reference_price * 100, 2) if price and reference_price else None
            rsi = _safe_float(technicals.get("rsi_14"))
            macd_hist = _safe_float((technicals.get("macd") or {}).get("histogram"))
            ema20 = _safe_float(technicals.get("ema_20"))
            last_score = _safe_float(item.get("last_score"))
            days_until_earnings = earnings.get("days_until_earnings")

            flags: list[str] = []
            if rsi is not None and macd_hist is not None and ema20 is not None and price is not None:
                if change_pct >= 5.0 and price >= ema20 and macd_hist > 0:
                    flags.append("breakout")
                if 40.0 <= rsi <= 60.0 and macd_hist > 0 and price >= ema20:
                    flags.append("setup")
            if isinstance(days_until_earnings, int) and 0 <= days_until_earnings <= 14:
                flags.append("earnings_soon")
            if ref_change_pct is not None and ref_change_pct >= 15.0:
                flags.append("moved_up")
            if ref_change_pct is not None and ref_change_pct <= -10.0:
                flags.append("dropped")
            if last_score is not None and last_score >= 7.5 and rsi is not None and rsi <= 65.0:
                flags.append("high_score_rsi_cooled")

            action = "watch"
            next_step = None
            severity = None
            alert_type = None
            if "high_score_rsi_cooled" in flags or ("breakout" in flags and (last_score or 0) >= 7.5):
                action = "decision_needed"
                next_step = "/decision"
                severity = "HIGH"
                alert_type = "WATCHLIST_DECISION_NEEDED"
            elif any(flag in flags for flag in ("breakout", "setup", "earnings_soon", "moved_up")):
                action = "research_needed"
                next_step = f"/research --seed {ticker}"
                severity = "MEDIUM"
                alert_type = "WATCHLIST_RESEARCH_NEEDED"
            elif "dropped" in flags:
                action = "review_needed"
                next_step = f"manual review: {ticker}"
                severity = "LOW"
                alert_type = "WATCHLIST_REVIEW_NEEDED"

            result = {
                "ticker": ticker,
                "price": price,
                "change_pct": round(change_pct, 2),
                "reference_price": reference_price,
                "ref_change_pct": ref_change_pct,
                "rsi": rsi,
                "macd_hist": macd_hist,
                "ema20": ema20,
                "days_until_earnings": days_until_earnings,
                "last_score": last_score,
                "flags": flags,
                "action": action,
                "next_step": next_step,
            }
            results.append(result)

            if alert_type and severity:
                alerts.append({
                    "date": today,
                    "ticker": ticker,
                    "alert_type": alert_type,
                    "severity": severity,
                    "message": f"{ticker}: {action} ({', '.join(flags)})",
                    "next_step": next_step,
                    **result,
                })

        if dry_run:
            self.last_watchlist_record = {
                "run_id": str(uuid.uuid4()),
                "date": today,
                "item_count": len(results),
                "alert_count": len(alerts),
                "decision_needed_count": sum(1 for item in results if item.get("action") == "decision_needed"),
                "research_needed_count": sum(1 for item in results if item.get("action") == "research_needed"),
                "items": results,
                "alerts": alerts,
            }
            logger.info("[DRY RUN] Watchlist monitor:\n" + json.dumps({"items": results, "alerts": alerts}, indent=2))
            return self.last_watchlist_record

        self.last_watchlist_record = _save_watchlist_summary(results, alerts)
        return self.last_watchlist_record

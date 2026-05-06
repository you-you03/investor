"""
Slack Incoming Webhook client + Block Kit formatters.
Uses plain dicts throughout — no DB model dependency.
"""

from __future__ import annotations

from datetime import date

import httpx

from investor.config import settings
from investor.utils.logger import get_logger

logger = get_logger(__name__)


class SlackNotifier:
    def send_message(self, blocks: list[dict], text: str = "") -> bool:
        payload: dict = {"blocks": blocks}
        if text:
            payload["text"] = text
        try:
            response = httpx.post(
                settings.slack_webhook_url,
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("Slack message sent")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Slack send failed: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Slack send error: {e}")
            return False

    def send_text(self, message: str) -> bool:
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": message}}]
        return self.send_message(blocks, text=message)

    def send_proposals(self, proposals: list[dict]) -> bool:
        blocks, fallback = _format_proposals(proposals)
        return self.send_message(blocks, text=fallback)

    def send_portfolio_summary(self, positions: list[dict], alerts: list[dict]) -> bool:
        blocks, fallback = _format_portfolio_summary(positions, alerts)
        return self.send_message(blocks, text=fallback)

    def send_sell_alert(self, alert: dict, position: dict) -> bool:
        blocks, fallback = _format_sell_alert(alert, position)
        return self.send_message(blocks, text=fallback)


# --------------------------------------------------------------------------- #
#  Block Kit formatters
# --------------------------------------------------------------------------- #

def _format_proposals(proposals: list[dict]) -> tuple[list[dict], str]:
    today = date.today().strftime("%Y-%m-%d")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":brain: Investment Proposals — {today}"},
        },
        {"type": "divider"},
    ]

    for p in proposals:
        conviction_emoji = {"HIGH": ":large_green_circle:", "MEDIUM": ":large_yellow_circle:", "LOW": ":red_circle:"}.get(
            p.get("conviction", ""), ":white_circle:"
        )
        action_emoji = {"BUY": ":chart_with_upwards_trend:", "SELL": ":chart_with_downwards_trend:", "HOLD": ":pause_button:"}.get(
            p.get("action", ""), ""
        )

        header_text = (
            f"{action_emoji} *{p['ticker']}* — {p.get('action')} | {conviction_emoji} {p.get('conviction')} Conviction"
        )

        price_parts = []
        if p.get("entry_price_range"):
            price_parts.append(f"Entry: ${p['entry_price_range']}")
        if p.get("target_price"):
            try:
                price_parts.append(f"Target: ${float(p['target_price']):,.2f}")
            except (ValueError, TypeError):
                price_parts.append(f"Target: ${p['target_price']}")
        if p.get("stop_loss"):
            try:
                price_parts.append(f"Stop: ${float(p['stop_loss']):,.2f}")
            except (ValueError, TypeError):
                price_parts.append(f"Stop: ${p['stop_loss']}")
        if p.get("shares_suggested") and p.get("position_size_usd"):
            price_parts.append(f"Size: {p['shares_suggested']:.0f} shares (~${p['position_size_usd']:,.0f})")
        elif p.get("position_size_usd"):
            price_parts.append(f"Size: ~${p['position_size_usd']:,.0f}")

        section_text = header_text
        if price_parts:
            section_text += "\n" + " | ".join(price_parts)
        if p.get("rationale"):
            section_text += f"\n\n> {p['rationale']}"
        if p.get("key_catalysts"):
            section_text += "\n\n*Catalysts:* " + ", ".join(p["key_catalysts"])
        if p.get("risk_factors"):
            section_text += "\n*Risks:* " + ", ".join(p["risk_factors"])
        if p.get("time_horizon"):
            section_text += f"\n_Horizon: {p['time_horizon']}_"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": section_text}})
        blocks.append({"type": "divider"})

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "_Human approval required before executing any trade._"}],
    })

    fallback = f"New investment proposals: {', '.join(p['ticker'] for p in proposals)}"
    return blocks, fallback


def _format_portfolio_summary(positions: list[dict], alerts: list[dict]) -> tuple[list[dict], str]:
    today = date.today().strftime("%Y-%m-%d")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":chart_with_upwards_trend: Daily Portfolio Monitor — {today}"},
        },
        {"type": "divider"},
    ]

    high_alerts = [a for a in alerts if a.get("severity") == "HIGH"]
    alert_tickers = {a.get("ticker") for a in high_alerts}

    total_pnl = 0.0
    if not positions:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No open positions._"}})
    else:
        for p in positions:
            ticker = p.get("ticker", "")
            entry = float(p.get("entry_price") or 0)
            current = float(p.get("current_price") or entry)
            target = float(p.get("target_price") or 0) or None
            stop = float(p.get("stop_loss") or 0) or None
            shares = float(p.get("shares") or 0)
            pnl = (current - entry) * shares
            pnl_pct = (current - entry) / entry * 100 if entry else 0
            total_pnl += pnl

            # Status emoji
            if ticker in alert_tickers:
                status = ":rotating_light:"
            elif pnl_pct >= 5:
                status = ":rocket:"
            elif pnl_pct >= 0:
                status = ":white_check_mark:"
            else:
                status = ":small_red_triangle_down:"

            # Progress toward target
            progress_text = ""
            if target and stop and entry:
                total_range = target - stop
                current_pos = current - stop
                pct_to_target = max(0, min(100, current_pos / total_range * 100)) if total_range > 0 else 0
                filled = int(pct_to_target / 10)
                bar = "█" * filled + "░" * (10 - filled)
                progress_text = f"\n`Stop {bar} Target`  _{pct_to_target:.0f}% of range_"

            pnl_sign = "+" if pnl >= 0 else ""
            pnl_pct_sign = "+" if pnl_pct >= 0 else ""

            target_str = f"${target:,.2f}" if target is not None else "—"
            stop_str = f"${stop:,.2f}" if stop is not None else "—"
            line = (
                f"{status} *{ticker}*\n"
                f"買値: *${entry:,.2f}*  →  現値: *${current:,.2f}*  →  目標: *{target_str}*\n"
                f"損益: *{pnl_pct_sign}{pnl_pct:.1f}%* ({pnl_sign}${pnl:,.0f})  |  ストップ: {stop_str}  |  {shares:.0f}株"
            )
            if progress_text:
                line += progress_text

            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line}})
            blocks.append({"type": "divider"})

        total_sign = "+" if total_pnl >= 0 else ""
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"合計未実現損益: *{total_sign}${total_pnl:,.0f}*"}],
        })

    if not high_alerts:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":white_check_mark: 重大アラートなし"}],
        })
    else:
        alert_lines = [f":rotating_light: *{a['ticker']}* — {a.get('message', '')}" for a in high_alerts]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(alert_lines)},
        })
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": (
                ":warning: このアラートは市場クローズ後の確認です。"
                " イントラデイに大きく動いた場合、現在値はストップ価格と乖離している可能性があります。"
                " 証券口座で現在の約定可能価格を確認してください。"
            )}],
        })

    fallback = f"Daily monitor: {len(positions)} position(s) | Total P&L: {'+' if total_pnl >= 0 else ''}${total_pnl:,.0f}"
    return blocks, fallback


def _format_sell_alert(alert: dict, position: dict) -> tuple[list[dict], str]:
    ticker = alert.get("ticker", "")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":rotating_light: SELL ALERT — {ticker}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Action Required: Consider Selling*"},
        },
    ]

    price_parts = []
    current = alert.get("current_price")
    if current:
        price_parts.append(f"Current: ${float(current):,.2f}")
    entry = position.get("entry_price")
    if entry:
        price_parts.append(f"Entry: ${float(entry):,.2f}")
    pnl_pct = alert.get("unrealized_pnl_pct")
    if pnl_pct is not None:
        sign = "+" if float(pnl_pct) >= 0 else ""
        price_parts.append(f"P&L: {sign}{float(pnl_pct):.1f}%")
    stop = position.get("stop_loss")
    if stop:
        price_parts.append(f"Stop Loss: ${float(stop):,.2f}")

    if price_parts:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": " | ".join(price_parts)},
        })

    reasoning = alert.get("reasoning", "")
    if reasoning:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"> {reasoning}"},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"Alert type: {alert.get('alert_type')} | Severity: {alert.get('severity')}"}
        ],
    })

    fallback = f"SELL ALERT: {ticker} — {reasoning[:100]}"
    return blocks, fallback

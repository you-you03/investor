"""
Slack Block Kit message formatters.
All price data carries a "(15-min delay)" notice per policy.
"""

import json
from datetime import date

from investor.db.models import InvestmentProposal, MonitorAlert, Position


def format_proposal_message(
    proposals: list[InvestmentProposal],
) -> tuple[list[dict], str]:
    """
    Format a list of InvestmentProposal rows as Slack Block Kit blocks.
    Returns (blocks, fallback_text).
    """
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
            p.conviction, ":white_circle:"
        )
        action_emoji = {"BUY": ":chart_with_upwards_trend:", "SELL": ":chart_with_downwards_trend:", "HOLD": ":pause_button:"}.get(
            p.action, ""
        )

        header_text = (
            f"{action_emoji} *{p.ticker}* — {p.action} | {conviction_emoji} {p.conviction} Conviction"
        )
        price_line_parts = []
        if p.entry_price_range:
            price_line_parts.append(f"Entry: ${p.entry_price_range}")
        if p.target_price:
            price_line_parts.append(f"Target: ${p.target_price:,.2f}")
        if p.stop_loss:
            price_line_parts.append(f"Stop: ${p.stop_loss:,.2f}")
        if p.shares_suggested and p.position_size_usd:
            price_line_parts.append(
                f"Size: {p.shares_suggested:.0f} shares (~${p.position_size_usd:,.0f})"
            )

        catalysts = json.loads(p.key_catalysts or "[]")
        risks = json.loads(p.risk_factors or "[]")

        section_text = header_text
        if price_line_parts:
            section_text += "\n" + " | ".join(price_line_parts)
        if p.rationale:
            section_text += f"\n\n> {p.rationale}"
        if catalysts:
            section_text += "\n\n*Catalysts:* " + ", ".join(catalysts)
        if risks:
            section_text += "\n*Risks:* " + ", ".join(risks)
        if p.time_horizon:
            section_text += f"\n_Horizon: {p.time_horizon}_"

        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": section_text}}
        )
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_Price data has 15-min delay. Human approval required before executing any trade._",
                }
            ],
        }
    )

    fallback = f"New investment proposals: {', '.join(p.ticker for p in proposals)}"
    return blocks, fallback


def format_daily_summary(
    positions: list[Position],
    alerts: list[MonitorAlert],
    current_prices: dict[str, float],
) -> tuple[list[dict], str]:
    """
    Format the daily portfolio summary message.
    current_prices: {ticker: current_price}
    """
    today = date.today().strftime("%Y-%m-%d")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":chart_with_upwards_trend: Daily Portfolio Summary — {today}",
            },
        },
        {"type": "divider"},
    ]

    if not positions:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_No open positions._"},
            }
        )
    else:
        total_pnl = 0.0
        total_invested = 0.0
        lines = []
        for p in positions:
            price = current_prices.get(p.ticker, p.entry_price)
            pnl = (price - p.entry_price) * p.shares
            pnl_pct = (price - p.entry_price) / p.entry_price * 100
            total_pnl += pnl
            total_invested += p.entry_price * p.shares
            emoji = ":white_check_mark:" if pnl >= 0 else ":warning:"
            lines.append(
                f"{emoji} *{p.ticker}*  ${price:,.2f}  "
                f"{'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%  "
                f"(Entry: ${p.entry_price:,.2f}  P&L: {'+' if pnl >= 0 else ''}${pnl:,.0f})"
            )

        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0
        summary_line = (
            f"*Portfolio P&L: {'+' if total_pnl >= 0 else ''}${total_pnl:,.0f} "
            f"({'+' if total_pnl_pct >= 0 else ''}{total_pnl_pct:.1f}%)*"
        )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": summary_line + "\n\n" + "\n".join(lines)},
            }
        )

    high_alerts = [a for a in alerts if a.severity == "HIGH"]
    if not high_alerts:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "_No critical alerts today. All positions within normal range._"}
                ],
            }
        )
    else:
        alert_text = f":rotating_light: *{len(high_alerts)} HIGH severity alert(s)* — see separate messages."
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": alert_text}}
        )

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "_Price data has 15-min delay._"}],
        }
    )

    fallback = f"Daily summary: {len(positions)} position(s), {len(high_alerts)} alert(s)"
    return blocks, fallback


def format_sell_alert(
    alert: MonitorAlert, position: Position
) -> tuple[list[dict], str]:
    """Format a HIGH severity sell alert."""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":rotating_light: SELL ALERT — {alert.ticker}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Action Required: Consider Selling*",
            },
        },
    ]

    price_text_parts = []
    if alert.current_price:
        price_text_parts.append(f"Current: ${alert.current_price:,.2f} _(15-min delay)_")
    price_text_parts.append(f"Entry: ${position.entry_price:,.2f}")
    if alert.unrealized_pnl_pct is not None:
        sign = "+" if alert.unrealized_pnl_pct >= 0 else ""
        price_text_parts.append(f"P&L: {sign}{alert.unrealized_pnl_pct:.1f}%")
    if position.stop_loss:
        price_text_parts.append(f"Stop Loss: ${position.stop_loss:,.2f}")

    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": " | ".join(price_text_parts)},
        }
    )

    if alert.reasoning:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"> {alert.reasoning}"},
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Alert type: {alert.alert_type} | Severity: {alert.severity}"}
            ],
        }
    )

    fallback = f"SELL ALERT: {alert.ticker} — {alert.message}"
    return blocks, fallback

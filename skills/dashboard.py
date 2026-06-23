#!/usr/bin/env python3
"""
Dashboard Skill — generates reports/dashboard.html

Usage:
  python skills/dashboard.py
"""
from __future__ import annotations

import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investor.data.yfinance_client import YFinanceClient
from investor.config import settings
from investor.supabase_sync import sync_local_to_supabase

PORTFOLIO_PATH = Path(settings.default_portfolio_path)
WATCHLIST_PATH = Path("data/watchlist.json")
OUTPUT_PATH = Path("reports/dashboard.html")
BUDGET = settings.available_capital_usd


# ─── Data readers ─────────────────────────────────────────────────────────────

def _read_portfolio() -> list[dict]:
    if not PORTFOLIO_PATH.exists():
        return []
    with open(PORTFOLIO_PATH) as f:
        return list(csv.DictReader(f))


def _read_watchlist() -> list[dict]:
    if not WATCHLIST_PATH.exists():
        return []
    return json.loads(WATCHLIST_PATH.read_text()).get("items", [])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_conviction(note: str) -> str:
    for level in ("HIGH", "MEDIUM", "LOW"):
        if f"{level}確信" in note:
            return level
    return ""


def _days_held(entry_date: str, exit_date: str = "") -> int:
    try:
        end = date.fromisoformat(exit_date) if exit_date else date.today()
        return (end - date.fromisoformat(entry_date)).days
    except Exception:
        return 0


def _get_snapshot(yf_client: YFinanceClient, ticker: str) -> dict | None:
    snap = yf_client.get_stock_snapshot(ticker)
    if snap and snap.get("price"):
        return snap
    try:
        import yfinance as _yf
        hist = _yf.Ticker(ticker).history(period="2d")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else None
            chg = round((price - prev) / prev * 100, 2) if prev else None
            return {
                "ticker": ticker, "price": price, "prev_close": prev,
                "change_pct": chg, "fifty_two_week_high": None, "fifty_two_week_low": None,
            }
    except Exception:
        pass
    return None


def _get_index_all_periods(ticker: str, name: str) -> dict:
    """Fetch data for 5 periods for a given index ticker."""
    import yfinance as _yf

    periods = [
        ("30d",  "1d",  "30日"),
        ("3mo",  "1wk", "3ヶ月"),
        ("6mo",  "1wk", "6ヶ月"),
        ("1y",   "1mo", "1年"),
        ("5y",   "1mo", "5年"),
    ]

    result = {}
    obj = _yf.Ticker(ticker)

    for period_id, interval, period_label in periods:
        try:
            hist = obj.history(period=period_id, interval=interval)
            if hist.empty:
                result[period_id] = []
                continue
            closes = [float(c) for c in hist["Close"]]
            dates  = [str(idx.date()) for idx in hist.index]
            data   = []
            for i, (d, c) in enumerate(zip(dates, closes)):
                prev_c = closes[i - 1] if i > 0 else c
                chg = (c - prev_c) / prev_c * 100
                data.append({"date": d, "close": round(c, 2), "change_pct": round(chg, 2)})
            result[period_id] = data
            print(f"  {name} {period_label}: {len(data)} bars ({interval})")
        except Exception as e:
            print(f"  {name} {period_id} error: {e}")
            result[period_id] = []

    return result


def _fp(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return "—"


def _fpct(v, sign: bool = True) -> str:
    try:
        f = float(v)
        s = "+" if sign and f >= 0 else ""
        return f"{s}{f:.1f}%"
    except Exception:
        return "—"


def _pcc(v) -> str:
    try:
        return "c-pos" if float(v) >= 0 else "c-neg"
    except Exception:
        return "c-muted"


def _badge(text: str, cls: str, title: str = "") -> str:
    t = f' title="{title}"' if title else ""
    return f'<span class="badge {cls}"{t}>{text}</span>'


# ─── Price bar ────────────────────────────────────────────────────────────────

def _price_bar(stop, entry, current, target) -> str:
    try:
        stop = float(stop); entry = float(entry)
        current = float(current); target = float(target)
    except Exception:
        return ""

    lo = min(stop, entry, current) * 0.96
    hi = max(target, current) * 1.04
    span = hi - lo
    if span <= 0:
        return ""

    def p(price: float) -> float:
        return max(0.5, min(99.0, (price - lo) / span * 100))

    sp = p(stop); ep = p(entry); cp = p(current); tp = p(target)
    fl = min(ep, cp)
    fw = abs(cp - ep)
    fill_cls = "bar-fill-pos" if current >= entry else "bar-fill-neg"

    return (
        '<div class="price-bar-wrap">'
        '<div class="price-bar-track"></div>'
        f'<div class="{fill_cls}" style="left:{fl:.1f}%;width:{fw:.1f}%"></div>'
        f'<div class="bm bm-stop"   style="left:{sp:.1f}%" title="損切 {_fp(stop)}"></div>'
        f'<div class="bm bm-entry"  style="left:{ep:.1f}%" title="買値 {_fp(entry)}"></div>'
        f'<div class="bm bm-target" style="left:{tp:.1f}%" title="目標 {_fp(target)}"></div>'
        f'<div class="bar-dot" style="left:{cp:.1f}%" title="現値 {_fp(current)}"></div>'
        f'<div class="bl bl-stop"   style="left:{sp:.1f}%">損切<br>{_fp(stop)}</div>'
        f'<div class="bl bl-entry"  style="left:{ep:.1f}%">買値<br>{_fp(entry)}</div>'
        f'<div class="bl bl-target" style="left:{tp:.1f}%">目標<br>{_fp(target)}</div>'
        '</div>'
    )


# ─── Section: KPI Cards (3-col, no market card) ───────────────────────────────

def render_kpi(open_rows, closed_rows, snapshots) -> str:
    # Capital allocation
    deployed = 0.0
    for r in open_rows:
        try:
            deployed += float(r["shares"]) * float(r["entry_price"])
        except Exception:
            pass
    deploy_pct = deployed / BUDGET * 100
    available = BUDGET - deployed

    # Unrealized P&L
    unrealized = 0.0
    ur_lines = []
    for r in open_rows:
        snap = snapshots.get(r["ticker"])
        if not snap or not snap.get("price"):
            continue
        try:
            pnl = (float(snap["price"]) - float(r["entry_price"])) * float(r["shares"])
            pct = (float(snap["price"]) - float(r["entry_price"])) / float(r["entry_price"]) * 100
            unrealized += pnl
            ur_lines.append(
                f'<div class="kpi-row"><span class="c-muted">{r["ticker"]}</span>'
                f'<span class="{_pcc(pct)}">{_fpct(pct)}</span></div>'
            )
        except Exception:
            pass

    # Realized P&L
    realized = 0.0
    re_lines = []
    for r in sorted(closed_rows, key=lambda x: x.get("exit_date", ""), reverse=True):
        if not r.get("exit_price") or not r.get("entry_price"):
            continue
        try:
            pnl = (float(r["exit_price"]) - float(r["entry_price"])) * float(r["shares"])
            pct = (float(r["exit_price"]) - float(r["entry_price"])) / float(r["entry_price"]) * 100
            realized += pnl
            re_lines.append(
                f'<div class="kpi-row"><span class="c-muted">{r["ticker"]}</span>'
                f'<span class="{_pcc(pct)}">{_fpct(pct)}</span></div>'
            )
        except Exception:
            pass

    ur_sign = "+" if unrealized >= 0 else ""
    re_sign = "+" if realized >= 0 else ""

    return (
        '<div class="kpi-grid">'

        # Card 1: Capital
        '<div class="card">'
        '<div class="card-lbl">資金配分</div>'
        f'<div class="kpi-val">{deploy_pct:.0f}%</div>'
        f'<div class="kpi-sub c-muted">{_fp(deployed)} / {_fp(BUDGET)}</div>'
        '<div class="prog-bg"><div class="prog-fill" style="width:' + f'{min(deploy_pct,100):.1f}%' + '"></div></div>'
        f'<div class="kpi-sub c-muted" style="margin-top:6px">空き資金 {_fp(available)}</div>'
        '</div>'

        # Card 2: Unrealized
        '<div class="card">'
        '<div class="card-lbl">含み損益</div>'
        f'<div class="kpi-val {_pcc(unrealized)}">{ur_sign}${abs(unrealized):,.0f}</div>'
        '<div class="kpi-sub c-muted">オープンポジション</div>'
        '<div style="margin-top:8px">' + "".join(ur_lines) + '</div>'
        '</div>'

        # Card 3: Realized
        '<div class="card">'
        '<div class="card-lbl">確定損益</div>'
        f'<div class="kpi-val {_pcc(realized)}">{re_sign}${abs(realized):,.0f}</div>'
        '<div class="kpi-sub c-muted">全クローズ累計</div>'
        '<div style="margin-top:8px">' + "".join(re_lines[:5]) + '</div>'
        '</div>'

        '</div>'
    )


# ─── Section: Open Positions (Card layout) ────────────────────────────────────

CONVICTION_META = {
    "HIGH":   ("◎ 高確信", "badge-high",   "エントリー・ホールドに強い確信。ファンダ・テクニカル・モメンタム全て揃い"),
    "MEDIUM": ("△ 中確信", "badge-medium", "条件付きで有望。一部リスクあり、注意深くホールド"),
    "LOW":    ("▽ 低確信", "badge-low",    "ハイリスク・実験的ポジション。最小ロットで打診"),
}


def render_open_positions(open_rows, snapshots) -> str:
    if not open_rows:
        return '<div class="card c-muted" style="text-align:center;padding:32px">オープンポジションなし</div>'

    cards_html = []
    for r in open_rows:
        ticker = r["ticker"]
        snap = snapshots.get(ticker)
        current  = snap.get("price") if snap else None
        day_chg  = snap.get("change_pct") if snap else None

        try:
            entry  = float(r.get("entry_price") or 0)
            shares = float(r.get("shares") or 0)
            target = float(r["target_price"]) if r.get("target_price") else None
            stop   = float(r["stop_loss"])    if r.get("stop_loss")    else None
        except Exception:
            entry = shares = 0; target = stop = None

        entry_date = r.get("entry_date", "")
        days = _days_held(entry_date)
        conviction = _get_conviction(r.get("note", ""))

        pnl = pnl_pct = None
        if current and entry:
            pnl     = (current - entry) * shares
            pnl_pct = (current - entry) / entry * 100

        to_target = to_stop = rr = None
        if current and target:
            to_target = (target - current) / current * 100
        if current and stop:
            to_stop = (stop - current) / current * 100
        if to_target is not None and to_stop is not None and to_stop != 0:
            rr = abs(to_target / to_stop)

        bar = ""
        if all(v is not None for v in [stop, entry, current, target]):
            bar = _price_bar(stop, entry, current, target)

        pnl_str     = ("+" if (pnl or 0) >= 0 else "") + f"${abs(pnl):,.0f}" if pnl is not None else "—"
        pnl_pct_str = _fpct(pnl_pct) if pnl_pct is not None else "—"

        conv_label, conv_cls, conv_title = CONVICTION_META.get(conviction, ("", "badge-low", ""))
        conv_b = _badge(conv_label, conv_cls, conv_title) if conviction else ""

        target_c = "c-pos" if (to_target or 0) > 0 else "c-neg"
        day_sign  = "▲" if (day_chg or 0) >= 0 else "▼"
        day_cls   = _pcc(day_chg)

        per_share = f"({_fp(current - entry)} / 株)" if current and entry else ""

        # R/R description: color-coded interpretation
        rr_interp = ""
        if rr is not None:
            if rr >= 2.0:
                rr_interp = '<span class="c-pos" style="font-size:10px">良好</span>'
            elif rr >= 1.0:
                rr_interp = '<span class="c-warn" style="font-size:10px">普通</span>'
            else:
                rr_interp = '<span class="c-neg" style="font-size:10px">要注意</span>'

        cards_html.append(
            '<div class="pos-card">'

            # ── Header ──
            '<div class="pos-hdr">'
            f'<div class="pos-tk">{ticker}</div>'
            f'<div class="pos-hdr-right">{conv_b}'
            f'<span class="pos-days">{days}日保有</span></div>'
            '</div>'

            # ── 3-column metrics ──
            '<div class="pos-metrics">'

            '<div class="pos-metric pos-metric-entry">'
            '<div class="pos-metric-lbl">エントリー価格</div>'
            f'<div class="pos-metric-val-lg">{_fp(entry)}</div>'
            f'<div class="pos-metric-sub">{entry_date}</div>'
            f'<div class="pos-metric-sub">{shares:.0f}株</div>'
            '</div>'

            '<div class="pos-metric">'
            '<div class="pos-metric-lbl">現在値</div>'
            f'<div class="pos-metric-val-lg">{_fp(current) if current else "—"}</div>'
            f'<div class="pos-metric-sub {day_cls}">{day_sign}{abs(day_chg):.1f}% 本日</div>'
            '</div>'

            '<div class="pos-metric">'
            '<div class="pos-metric-lbl">含み損益</div>'
            f'<div class="pos-metric-val-lg {_pcc(pnl_pct)}">{pnl_str}</div>'
            f'<div class="pos-metric-sub {_pcc(pnl_pct)}">{pnl_pct_str}</div>'
            f'<div class="pos-metric-sub c-muted">{per_share}</div>'
            '</div>'

            '</div>'  # /pos-metrics

            # ── Risk row ──
            '<div class="pos-risk-row">'

            f'<div class="pos-risk-item">'
            f'<span class="pos-risk-lbl">目標価格</span>'
            f'<span class="pos-risk-val {target_c}">{_fp(target)}</span>'
            f'<span class="pos-risk-pct {target_c}">{_fpct(to_target) if to_target is not None else "—"}</span>'
            '</div>'

            '<div class="pos-risk-sep"></div>'

            f'<div class="pos-risk-item">'
            f'<span class="pos-risk-lbl">損切ライン</span>'
            f'<span class="pos-risk-val c-neg">{_fp(stop)}</span>'
            f'<span class="pos-risk-pct c-neg">{_fpct(to_stop) if to_stop is not None else "—"}</span>'
            '</div>'

            '<div class="pos-risk-sep"></div>'

            # R/R
            '<div class="pos-risk-item">'
            '<span class="pos-risk-lbl">R/R比率</span>'
            f'<span class="pos-risk-val">{f"{rr:.1f}x" if rr is not None else "—"}</span>'
            f'<span class="pos-risk-pct">{rr_interp}</span>'
            '</div>'

            '</div>'  # /pos-risk-row

            # ── Price bar ──
            + (f'<div class="pos-bar-wrap">{bar}</div>' if bar else '')

            + '</div>'  # /pos-card
        )

    # One-time R/R note above the grid
    rr_note = (
        '<div class="rr-note">'
        '<span class="rr-note-icon">ℹ</span>'
        'R/R比率 = 目標までの上昇幅 ÷ 損切までの下落幅。'
        '例: 目標+10%・損切-5% → R/R 2.0x。<strong>2.0x以上が理想</strong>、1.0x未満は損益が見合わない。'
        '</div>'
    )
    return rr_note + '<div class="pos-grid">' + "".join(cards_html) + '</div>'


# ─── Section: Index Multi-period Chart ───────────────────────────────────────

CHART_PERIODS = [
    ("30d", "30日"),
    ("3mo", "3ヶ月"),
    ("6mo", "6ヶ月"),
    ("1y",  "1年"),
    ("5y",  "5年"),
]

CHART_INDICES = [
    ("SPY",   "S&P 500"),
    ("N225",  "日経平均"),
]


def _build_js_dataset(period_data: dict) -> dict:
    """Convert raw bars dict to Chart.js-ready format per period."""
    js = {}
    for period_id, _ in CHART_PERIODS:
        bars = period_data.get(period_id, [])
        if not bars:
            js[period_id] = {"dates": [], "closes": [], "colors": [], "changes": []}
            continue
        js[period_id] = {
            "dates":   [b["date"]   for b in bars],
            "closes":  [b["close"]  for b in bars],
            "colors":  ["rgba(21,128,61,0.75)" if b["change_pct"] >= 0 else "rgba(185,28,28,0.75)"
                        for b in bars],
            "changes": [b["change_pct"] for b in bars],
        }
    return js


def _default_summary(period_data: dict, period_id: str = "30d"):
    bars = period_data.get(period_id, [])
    if not bars:
        return {}
    first_c = bars[0]["close"]
    last_c  = bars[-1]["close"]
    return {
        "last": last_c,
        "chg":  round((last_c - first_c) / first_c * 100, 2),
        "high": max(b["close"] for b in bars),
        "low":  min(b["close"] for b in bars),
    }


def render_index_chart(index_data: dict) -> str:
    """index_data = {'SPY': {period: [bars]}, 'N225': {period: [bars]}}"""
    import json as _json

    js_all = {idx_id: _build_js_dataset(index_data.get(idx_id, {})) for idx_id, _ in CHART_INDICES}
    data_json = _json.dumps(js_all)

    # Initial summary (SPY, 30d)
    s = _default_summary(index_data.get("SPY", {}))
    period_chg = s.get("chg") or 0
    period_cls = "c-pos" if period_chg >= 0 else "c-neg"
    period_str = ("+" if period_chg >= 0 else "") + f"{period_chg:.1f}%"

    # Index selector tabs
    idx_tabs = "".join(
        f'<button class="spy-tab{"  spy-tab-active" if idx_id == "SPY" else ""}" '
        f'data-idx="{idx_id}">{idx_label}</button>'
        for idx_id, idx_label in CHART_INDICES
    )
    # Period selector tabs
    period_tabs = "".join(
        f'<button class="spy-tab{"  spy-tab-active" if pid == "30d" else ""}" '
        f'data-period="{pid}">{lbl}</button>'
        for pid, lbl in CHART_PERIODS
    )

    def _fmts(key, cls=""):
        v = s.get(key)
        return f'<span class="spy-val{" " + cls if cls else ""}" id="spy-{key}">{_fp(v) if v else "—"}</span>'

    return (
        '<div class="sec">'
        '<div class="sec-ttl">マーケットチャート</div>'
        '<div class="card">'

        # Index selector
        f'<div class="spy-idx-tabs" id="spy-idx-tabs">{idx_tabs}</div>'

        # Summary row
        '<div class="spy-summary">'
        f'<div><span class="spy-label">現値</span>{_fmts("last")}</div>'
        f'<div><span class="spy-label">期間騰落</span>'
        f'<span class="spy-val {period_cls}" id="spy-chg">{period_str}</span></div>'
        f'<div><span class="spy-label">期間高値</span>{_fmts("high")}</div>'
        f'<div><span class="spy-label">期間安値</span>{_fmts("low")}</div>'
        '</div>'

        # Period selector
        f'<div class="spy-tabs" id="spy-tabs">{period_tabs}</div>'

        # Chart canvas
        '<div style="position:relative;height:260px">'
        '<canvas id="spyChart"></canvas>'
        '</div>'
        '</div>'
        '</div>'

        f'<script>window._indexData = {data_json};</script>'
    )


# ─── Section: Watchlist ───────────────────────────────────────────────────────

def _extract_entry_zone(reason: str) -> tuple:
    """Extract (lo, hi) entry zone from reason text. Returns (None, None) if not found."""
    import re
    # Pattern 1: エントリーゾーン $XXX[–-]$?XXX
    m = re.search(r'エントリーゾーン\s*\$?([\d,]+(?:\.\d+)?)\s*[–\-~]\s*\$?([\d,]+(?:\.\d+)?)', reason)
    if m:
        try:
            return float(m.group(1).replace(',', '')), float(m.group(2).replace(',', ''))
        except Exception:
            pass
    # Pattern 2: 押し目 $XXX[–-]XXX or 押し目$XXX-XXX
    m = re.search(r'押し目\s*\$?([\d,]+(?:\.\d+)?)\s*[–\-~]\s*\$?([\d,]+(?:\.\d+)?)', reason)
    if m:
        try:
            return float(m.group(1).replace(',', '')), float(m.group(2).replace(',', ''))
        except Exception:
            pass
    return None, None


def _extract_target_from_reason(reason: str) -> float | None:
    """Extract target price from reason text."""
    import re
    m = re.search(r'目標\s*\$?([\d,]+(?:\.\d+)?)', reason)
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except Exception:
            pass
    return None


def _sparkline_svg(prices: list[float], width: int = 80, height: int = 28) -> str:
    """Generate a lightweight SVG sparkline from closing prices."""
    if len(prices) < 2:
        return ""
    mn, mx = min(prices), max(prices)
    span = mx - mn
    n = len(prices)
    pad = 2

    def px(i: int, p: float) -> str:
        x = i / (n - 1) * width
        y = (height - pad) - ((p - mn) / span * (height - pad * 2)) if span > 0 else height / 2
        return f"{x:.1f},{y:.1f}"

    points = " ".join(px(i, p) for i, p in enumerate(prices))
    color = "#15803d" if prices[-1] >= prices[0] else "#b91c1c"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="display:block;overflow:visible">'
        f'<polyline points="{points}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )


def _fetch_ticker_data(yf_client, ticker: str) -> tuple[dict | None, list[float]]:
    """Fetch snapshot + sparkline for one ticker using a single yfinance Ticker object.

    Returns (snapshot_dict | None, sparkline_prices).
    The 5-day history covers both sparkline data and the 2-day snapshot fallback,
    so only one Ticker.history() call is made per ticker.
    """
    import yfinance as _yf

    snap = yf_client.get_stock_snapshot(ticker)

    hist5: object = None
    try:
        hist5 = _yf.Ticker(ticker).history(period="5d")
    except Exception:
        pass

    # Sparkline from 5d history
    sparkline: list[float] = []
    if hist5 is not None and not hist5.empty:
        sparkline = [float(c) for c in hist5["Close"]]

    # Snapshot fallback: derive from 5d history if cache missed
    if not (snap and snap.get("price")) and sparkline:
        price = sparkline[-1]
        prev  = sparkline[-2] if len(sparkline) >= 2 else None
        chg   = round((price - prev) / prev * 100, 2) if prev else None
        snap  = {
            "ticker": ticker, "price": price, "prev_close": prev,
            "change_pct": chg, "fifty_two_week_high": None, "fifty_two_week_low": None,
        }

    return snap, sparkline


def _fp_zone(v) -> str:
    """Price label for zone bar — integers shown without decimal."""
    try:
        f = float(v)
        return f"${int(f):,}" if f == int(f) else f"${f:,.2f}"
    except Exception:
        return "—"


def _wl_price_bar(entry_lo: float, entry_hi: float, current: float, target: float | None) -> str:
    """Mini horizontal price bar for watchlist cards showing entry zone vs current price."""
    try:
        all_vals = [entry_lo, entry_hi, current]
        if target:
            all_vals.append(target)
        lo = min(all_vals) * 0.96
        hi = max(all_vals) * 1.04
        span = hi - lo
        if span <= 0:
            return ""
    except Exception:
        return ""

    def p(v: float) -> float:
        return max(0.5, min(99.0, (v - lo) / span * 100))

    zone_l   = p(entry_lo)
    zone_r   = p(entry_hi)
    zone_w   = zone_r - zone_l
    zone_mid = zone_l + zone_w / 2
    cp       = p(current)

    in_zone = entry_lo <= current <= entry_hi
    dot_cls = "wl-dot-in" if in_zone else "wl-dot-out"

    # Single centered zone label to avoid overlap
    zone_label = f"{_fp_zone(entry_lo)}–{_fp_zone(entry_hi)}"

    html = (
        '<div class="wl-bar-wrap">'
        '<div class="wl-bar-track"></div>'
        f'<div class="wl-bar-zone" style="left:{zone_l:.1f}%;width:{zone_w:.1f}%"></div>'
        f'<div class="{dot_cls}" style="left:{cp:.1f}%" title="現値 {_fp_zone(current)}"></div>'
    )
    if target:
        html += f'<div class="wl-bar-tgt" style="left:{p(target):.1f}%" title="目標 {_fp_zone(target)}"></div>'

    # One centered label under the zone
    html += (
        f'<div class="wl-bl" style="left:{zone_mid:.1f}%">{zone_label}</div>'
        '</div>'
    )

    # Status line
    if in_zone:
        status = '<div class="wl-zone-st wl-zone-in">● エントリーゾーン内</div>'
    elif current < entry_lo:
        diff = (entry_lo - current) / current * 100
        status = f'<div class="wl-zone-st wl-zone-below">▲ +{diff:.1f}% でゾーン到達</div>'
    else:
        diff = (current - entry_hi) / entry_hi * 100
        status = f'<div class="wl-zone-st wl-zone-above">ゾーン上抜け +{diff:.1f}%</div>'

    return html + status


FLAG_LABEL = {
    "BREAKOUT_PENDING":   "⚡ ブレイクアウト待ち",
    "WATCHLIST_BREAKOUT": "📈 急騰シグナル",
    "WATCHLIST_MOVED":    "⬆ 大幅上昇",
    "WATCHLIST_DROPPED":  "⬇ 下落注意",
    "TARGET_REACHED":     "✓ 目標到達",
}
FLAG_TITLE = {
    "BREAKOUT_PENDING":   "条件成立でBUYシグナル発動予定（上値ブレイクを待機中）",
    "WATCHLIST_BREAKOUT": "参照価格比で+10%以上の急騰を検出",
    "WATCHLIST_MOVED":    "参照比で+15%以上の上昇（勢い強め）",
    "WATCHLIST_DROPPED":  "参照比で-10%以上の下落（要注意）",
    "TARGET_REACHED":     "設定した目標価格に到達",
}
FLAG_CLS = {
    "BREAKOUT_PENDING":   "badge-warn",
    "WATCHLIST_BREAKOUT": "badge-warn",
    "WATCHLIST_MOVED":    "badge-info",
    "WATCHLIST_DROPPED":  "badge-danger",
    "TARGET_REACHED":     "badge-ok",
}


def _score_widget(score) -> str:
    """スコア表示＋プログレスバー。スコアなしは未リサーチバッジ。"""
    if score is None:
        return '<span class="badge badge-warn wl-unresearched">🔍 未リサーチ</span>'
    pct = min(100, score / 10 * 100)
    bar_cls = "score-bar-hi" if score >= 8.0 else ("score-bar-mid" if score >= 6.0 else "score-bar-lo")
    return (
        f'<div class="wl-score-wrap">'
        f'<span class="wl-score">★ {score:.1f}</span>'
        f'<div class="wl-score-bg"><div class="wl-score-fill {bar_cls}" style="width:{pct:.0f}%"></div></div>'
        f'</div>'
    )


def _days_since(added_at: str) -> int:
    try:
        d = date.fromisoformat(added_at[:10])
        return (date.today() - d).days
    except Exception:
        return 0


def _added_html(added_at: str) -> str:
    """追加日＋長期監視バッジ。"""
    if not added_at:
        return ""
    days = _days_since(added_at)
    long_badge = ' <span class="badge badge-warn" style="font-size:9px">⏰ 長期監視</span>' if days >= 30 else ""
    return f'<div class="wl-added">追加 {added_at[:10]} ({days}日前){long_badge}</div>'


def render_watchlist(watchlist_items, snapshots, sparklines: dict | None = None) -> str:
    if sparklines is None:
        sparklines = {}
    if not watchlist_items:
        return '<div class="card c-muted" style="text-align:center;padding:32px">ウォッチリストなし</div>'

    alert_cards = []; active_cards = []; promoted_cards = []
    table_rows = []

    for w in watchlist_items:
        ticker   = w.get("ticker", "")
        status   = w.get("status", "active")
        flag     = w.get("last_monitor_flag") or ""
        ref_p    = w.get("reference_price")
        score    = w.get("last_score")
        reason   = w.get("reason", "")
        short    = reason[:40] + ("…" if len(reason) > 40 else "")
        added_at = w.get("added_at", "")
        reason_date_line = f'<div class="wl-reason-date">追加日: {added_at}</div>' if added_at else ""
        reason_html = (
            f'<details class="wl-reason-detail">'
            f'<summary class="wl-reason-short">{short}'
            + (' <span class="wl-reason-toggle">▼ 詳細</span>' if len(reason) > 40 else '')
            + '</summary>'
            f'<div class="wl-reason-full">{reason}</div>'
            + reason_date_line
            + '</details>'
        )

        snap    = snapshots.get(ticker)
        current = snap.get("price") if snap else None
        day_chg = snap.get("change_pct") if snap else None

        ref_chg = None
        if current and ref_p:
            try:
                ref_chg = (current - float(ref_p)) / float(ref_p) * 100
            except Exception:
                pass

        flag_title = FLAG_TITLE.get(flag, "")
        flag_b  = _badge(FLAG_LABEL.get(flag, flag), FLAG_CLS.get(flag, "badge-info"), flag_title) if flag else ""
        promo_b = _badge("✓ Portfolio入り", "badge-ok", "すでにBUY済み・ポートフォリオ内") if status == "promoted" else ""
        score_h    = _score_widget(score)
        added_line = _added_html(added_at)

        # Entry zone extraction
        ez_lo, ez_hi = _extract_entry_zone(reason)
        ez_target    = _extract_target_from_reason(reason)
        ez_bar = ""
        if ez_lo and ez_hi and current:
            ez_bar = _wl_price_bar(ez_lo, ez_hi, current, ez_target)

        spark_html = ""
        tbl_spark  = ""
        if ticker in sparklines:
            svg = _sparkline_svg(sparklines[ticker])
            if svg:
                spark_html = f'<div class="wl-sparkline">{svg}</div>'
            svg_sm = _sparkline_svg(sparklines[ticker], width=60, height=20)
            if svg_sm:
                tbl_spark = svg_sm

        is_alert = flag in ("BREAKOUT_PENDING", "WATCHLIST_BREAKOUT", "WATCHLIST_MOVED")
        card_cls = "wl-card"
        if is_alert:
            card_cls += " wl-alert"
        if status == "promoted":
            card_cls += " wl-promoted"

        # Sortable data attributes
        d_score  = f"{score:.2f}"   if score   is not None else "0"
        d_refchg = f"{ref_chg:.2f}" if ref_chg is not None else "-999"
        d_daychg = f"{day_chg:.2f}" if day_chg is not None else "-999"
        d_added  = w.get("added_at", "")
        d_alert  = "1" if is_alert else "0"
        d_ticker = ticker.lower()
        d_reason = reason.replace('&', '&amp;').replace('"', '&quot;').replace('\n', ' ')[:300]

        data_attrs = (
            f' data-status="{status}" data-flag="{flag}"'
            f' data-score="{d_score}" data-refchg="{d_refchg}"'
            f' data-daychg="{d_daychg}" data-added="{d_added}" data-alert="{d_alert}"'
            f' data-ticker="{d_ticker}" data-reason="{d_reason}"'
        )

        if is_alert:
            card = (
                f'<div class="{card_cls}"{data_attrs}>'

                # バナーヘッダー行
                f'<div class="wl-alert-hdr">'
                f'<div class="wl-alert-left">'
                f'<span class="wl-alert-icon">⚡</span>'
                f'<span class="wl-tk">{ticker}</span>'
                f'<div class="wl-bgs">{flag_b}{promo_b}</div>'
                f'</div>'
                f'<span class="wl-action-badge">要アクション</span>'
                f'</div>'

                # ボディ: 価格情報 + エントリーゾーンバー
                f'<div class="wl-alert-body">'

                f'<div class="wl-alert-prices">'
                + (score_h if score_h else '')
                + f'<div class="wl-prices">'
                f'<span class="c-muted" style="font-size:11px">参照 {_fp(ref_p)}</span>'
                f'<span class="wl-cur">{_fp(current) if current else "—"}</span></div>'
                f'<div class="wl-chgs">'
                f'<span class="{_pcc(ref_chg)}" style="font-size:13px;font-weight:700">{_fpct(ref_chg)} vs参照</span>'
                f'<span class="{_pcc(day_chg)}" style="font-size:11px">{_fpct(day_chg)} 本日</span>'
                f'</div>'
                + spark_html
                + f'</div>'

                + (f'<div class="wl-alert-zone"><div class="wl-ezbar">{ez_bar}</div></div>' if ez_bar else '')
                + f'</div>'  # /wl-alert-body

                + f'<div class="wl-reason-wrap">{reason_html}</div>'
                + added_line
                + '</div>'
            )
        else:
            # ── 通常カード ──
            card = (
                f'<div class="{card_cls}"{data_attrs}>'
                f'<div class="wl-head"><span class="wl-tk">{ticker}</span>'
                f'<div class="wl-bgs">{flag_b}{promo_b}</div></div>'
                f'{score_h}'
                f'<div class="wl-prices">'
                f'<span class="c-muted" style="font-size:11px">参照価格 {_fp(ref_p)}</span>'
                f'<span class="wl-cur">{_fp(current) if current else "—"}</span></div>'
                f'<div class="wl-chgs">'
                f'<span class="{_pcc(ref_chg)}" style="font-size:13px;font-weight:700">{_fpct(ref_chg)} vs参照</span>'
                f'<span class="{_pcc(day_chg)}" style="font-size:11px">{_fpct(day_chg)} 本日</span>'
                f'</div>'
                + spark_html
                + (f'<div class="wl-ezbar">{ez_bar}</div>' if ez_bar else '')
                + reason_html
                + added_line
                + '</div>'
            )

        score_td = f"★ {score:.1f}" if score is not None else '<span class="badge badge-warn" style="font-size:9px">未</span>'
        table_rows.append(
            f'<tr class="wl-tbl-row" data-status="{status}" data-alert="{d_alert}"'
            f' data-score="{d_score}" data-refchg="{d_refchg}" data-daychg="{d_daychg}"'
            f' data-added="{d_added}" data-ticker="{d_ticker}" data-reason="{d_reason}">'
            f'<td class="wl-tbl-tk">{"⚡ " if is_alert else ""}{ticker}</td>'
            f'<td>{tbl_spark}</td>'
            f'<td>{score_td}</td>'
            f'<td class="c-muted">{_fp(current) if current else "—"}</td>'
            f'<td class="{_pcc(ref_chg)}" style="font-weight:600">{_fpct(ref_chg)}</td>'
            f'<td class="{_pcc(day_chg)}">{_fpct(day_chg)}</td>'
            f'<td>{flag_b}</td>'
            f'<td class="c-muted">{added_at[:10] if added_at else ""}</td>'
            f'</tr>'
        )

        if is_alert:
            alert_cards.append(card)
        elif status == "promoted":
            promoted_cards.append(card)
        else:
            active_cards.append(card)

    n_alert = len(alert_cards); n_active = len(active_cards); n_promo = len(promoted_cards)
    n_total = n_alert + n_active + n_promo

    legend = (
        '<div class="wl-legend">'
        '<div class="wl-legend-title">タブの見方</div>'
        '<div class="wl-legend-items">'
        f'<span class="wl-legend-item">{_badge("🚨 アラート", "badge-warn")} 急騰・ブレイクアウト等のシグナルあり（要確認）</span>'
        f'<span class="wl-legend-item">{_badge("監視中", "badge-muted")} 通常の観察対象（まだBUY判断待ち）</span>'
        f'<span class="wl-legend-item">{_badge("✓ Portfolio入り", "badge-ok")} すでにBUY済み（折りたたみ表示）</span>'
        '</div>'
        '</div>'
    )

    controls = (
        '<div class="wl-controls">'
        '<div class="wl-tabs" id="wl-tabs">'
        f'<button class="wl-tab active" data-f="all">全て ({n_total})</button>'
        f'<button class="wl-tab" data-f="alert" title="急騰・ブレイクアウト等の注目シグナルあり">🚨 アラート ({n_alert})</button>'
        f'<button class="wl-tab" data-f="active" title="通常の観察対象（まだBUY判断待ち）">監視中 ({n_active})</button>'
        f'<button class="wl-tab" data-f="promoted" title="すでにBUY済みの銘柄">Portfolio入り ({n_promo})</button>'
        '</div>'
        '<div class="wl-controls-right">'
        '<input type="text" id="wl-search" class="wl-search" placeholder="🔍 Ticker / 理由を検索…" />'
        '<select class="wl-sort" id="wl-sort" title="並び替え">'
        '<option value="default">並び順: デフォルト</option>'
        '<option value="score">並び順: スコア高い順</option>'
        '<option value="refchg">並び順: vs参照 騰落率</option>'
        '<option value="daychg">並び順: 本日騰落率</option>'
        '<option value="added">並び順: 追加日 (新しい順)</option>'
        '</select>'
        '<button id="wl-view-btn" class="wl-view-btn" title="カード ↔ リスト表示切り替え">☰</button>'
        '</div>'
        '</div>'
    )

    # ── アラート: 2列グリッド ──
    alert_section = (
        '<div class="wl-alert-grid" id="wl-alert-grid">' + "".join(alert_cards) + '</div>'
    ) if alert_cards else '<div id="wl-alert-grid" style="display:none"></div>'

    # ── 監視中: 通常グリッド ──
    active_section = '<div class="wl-grid" id="wl-grid">' + "".join(active_cards) + '</div>'

    promoted_section = (
        '<details class="wl-promoted-section" id="wl-promoted-section">'
        f'<summary class="wl-promoted-summary">✓ Portfolio入り ({n_promo})</summary>'
        '<div class="wl-grid wl-promoted-grid" id="wl-promoted-grid">' + "".join(promoted_cards) + '</div>'
        '</details>'
    ) if promoted_cards else ''

    table_view = (
        '<div id="wl-table-view" class="wl-table-view">'
        '<table class="wl-tbl">'
        '<thead><tr>'
        '<th data-sort-col="ticker">Ticker ↕</th>'
        '<th>5日</th>'
        '<th data-sort-col="score">スコア ↕</th>'
        '<th>現値</th>'
        '<th data-sort-col="refchg">vs参照 ↕</th>'
        '<th data-sort-col="daychg">本日 ↕</th>'
        '<th>フラグ</th>'
        '<th data-sort-col="added">追加日 ↕</th>'
        '</tr></thead>'
        '<tbody id="wl-tbl-body">' + "".join(table_rows) + '</tbody>'
        '</table>'
        '</div>'
    )

    return '<div class="card">' + legend + controls + alert_section + active_section + promoted_section + table_view + '</div>'


# ─── Section: Closed Positions ────────────────────────────────────────────────

def render_closed_positions(closed_rows) -> str:
    valid = [r for r in closed_rows if r.get("exit_price") and r.get("entry_price")]
    if not valid:
        return ""

    rows_html = []
    total_pnl = 0.0
    for r in sorted(valid, key=lambda x: x.get("exit_date", ""), reverse=True):
        try:
            entry  = float(r["entry_price"])
            exit_p = float(r["exit_price"])
            shares = float(r["shares"])
            pnl    = (exit_p - entry) * shares
            pct    = (exit_p - entry) / entry * 100
            days   = _days_held(r.get("entry_date", ""), r.get("exit_date", ""))
            total_pnl += pnl

            note = r.get("note", "")
            tag = note
            for t in ("TARGET_HIT", "STOPPED_OUT", "TIME_EXIT", "部分利確", "TARGET_REACHED"):
                if t in note:
                    tag = t; break
            else:
                tag = note[:28] + ("…" if len(note) > 28 else "")

            pnl_str = ("+" if pnl >= 0 else "") + f"${abs(pnl):,.0f}"
            rows_html.append(
                '<tr>'
                f'<td class="cl-tk">{r["ticker"]}</td>'
                f'<td class="c-muted">{shares:.0f}株</td>'
                f'<td class="c-muted">{_fp(entry)} → {_fp(exit_p)}</td>'
                f'<td class="{_pcc(pct)}">{_fpct(pct)}</td>'
                f'<td class="{_pcc(pnl)}" style="font-weight:600">{pnl_str}</td>'
                f'<td class="c-muted">{days}d</td>'
                f'<td class="c-muted">{r.get("exit_date","")[:10]}</td>'
                f'<td class="c-muted" style="font-size:11px">{tag}</td>'
                '</tr>'
            )
        except Exception:
            pass

    total_str = ("+" if total_pnl >= 0 else "") + f"${abs(total_pnl):,.0f}"
    return (
        f'<details class="card">'
        f'<summary class="closed-summary">クローズポジション ({len(rows_html)}) '
        f'<span class="{_pcc(total_pnl)}" style="font-weight:700">{total_str}</span>'
        f'<span class="c-muted" style="font-size:12px;margin-left:6px">▼</span></summary>'
        '<div style="overflow-x:auto;margin-top:16px">'
        '<table class="closed-tbl">'
        '<thead><tr>'
        '<th>Ticker</th><th>株数</th><th>Entry → Exit</th>'
        '<th>P&L%</th><th>P&L$</th><th>保有</th><th>決済日</th><th>備考</th>'
        '</tr></thead>'
        '<tbody>' + "".join(rows_html) + '</tbody>'
        '</table></div>'
        '</details>'
    )


# ─── CSS (Edge design — matches Dashboard_Design/index.html) ──────────────────

_CSS = """
:root {
  --bg:#fafafa; --surface:#ffffff;
  --line:#ececec; --line-2:#f4f4f4;
  --ink-1:#0a0a0a; --ink-2:#525252; --ink-3:#a1a1a1; --ink-4:#d4d4d4;
  --pos:#15803d; --neg:#b91c1c; --warn:#b45309;
  --radius:8px;
  --mono:"Geist Mono",ui-monospace,"SF Mono",Menlo,monospace;
  --sans:"Geist",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink-1);font-family:var(--sans);font-size:13px;line-height:1.55;-webkit-font-smoothing:antialiased;font-feature-settings:"ss01","cv11";min-height:100vh}
.wrap{max-width:1280px;margin:0 auto;padding:32px 48px 80px}
.sec{margin-bottom:48px}
.sec-ttl{font-size:14px;font-weight:600;letter-spacing:-.01em;color:var(--ink-1);display:flex;align-items:baseline;justify-content:space-between;padding-bottom:10px;border-bottom:1px solid var(--line);margin-bottom:14px}
.sec-ttl span{font-size:11px;font-family:var(--mono);color:var(--ink-3);font-weight:400;letter-spacing:0}

/* Card — flat, no shadow */
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:18px 22px}
.card-lbl{font-size:11px;font-weight:500;letter-spacing:.02em;color:var(--ink-3);margin-bottom:6px}

/* KPI grid — strip layout with dividers */
.kpi-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:0;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;margin-bottom:32px}
@media(max-width:700px){.kpi-grid{grid-template-columns:1fr}}
.kpi-grid>.card{border:none;border-right:1px solid var(--line);border-radius:0;min-height:110px;display:flex;flex-direction:column;gap:6px}
.kpi-grid>.card:last-child{border-right:none}
.kpi-val{font-family:var(--mono);font-size:26px;font-weight:500;letter-spacing:-.025em;color:var(--ink-1);line-height:1.05}
.kpi-sub{font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-top:auto}
.kpi-row{display:flex;justify-content:space-between;font-size:12px;margin-top:4px;font-family:var(--mono)}
.prog-bg{height:2px;background:var(--line);border-radius:2px;overflow:hidden;margin-top:4px}
.prog-fill{height:100%;background:var(--ink-1);border-radius:2px;transition:width .3s}

/* Colors */
.c-pos{color:var(--pos)}.c-neg{color:var(--neg)}.c-warn{color:var(--warn)}
.c-text{color:var(--ink-1)}.c-muted{color:var(--ink-3)}.c-sub{color:var(--ink-2)}

/* Badges — rectangular, mono, small */
.badge{display:inline-flex;align-items:center;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;font-family:var(--mono);letter-spacing:.04em;border:1px solid transparent;white-space:nowrap}
.badge-high  {color:var(--pos);border-color:#b8e0c4}
.badge-medium{color:#1d4ed8;border-color:#c8d8f6}
.badge-low   {color:var(--ink-3);border-color:var(--ink-4)}
.badge-warn  {color:var(--warn);border-color:#e5c48a}
.badge-info  {color:#0369a1;border-color:#bae0f5}
.badge-danger{color:var(--neg);border-color:#f5bcbc}
.badge-ok    {color:var(--pos);border-color:#b8e0c4}
.badge-muted {color:var(--ink-3);border-color:var(--ink-4)}

/* ── Open Position cards ── */
.pos-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px}
.pos-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px}
.pos-hdr{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:14px}
.pos-tk{font-family:var(--mono);font-size:22px;font-weight:600;color:var(--ink-1);letter-spacing:-.015em}
.pos-hdr-right{display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.pos-days{font-size:11px;color:var(--ink-3);font-family:var(--mono)}

.pos-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-bottom:10px}
.pos-metric{padding:10px 12px;border-right:1px solid var(--line)}
.pos-metric:last-child{border-right:none}
.pos-metric-entry{background:var(--line-2)}
.pos-metric-lbl{font-size:10px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);margin-bottom:4px}
.pos-metric-val-lg{font-family:var(--mono);font-size:18px;font-weight:500;color:var(--ink-1);line-height:1.2}
.pos-metric-sub{font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-top:2px}

.pos-risk-row{display:flex;align-items:stretch;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-bottom:10px}
.pos-risk-item{flex:1;padding:8px 10px;display:flex;flex-direction:column;gap:2px}
.pos-risk-sep{width:1px;background:var(--line);flex-shrink:0}
.pos-risk-lbl{font-size:10px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}
.pos-risk-val{font-family:var(--mono);font-size:14px;font-weight:500;color:var(--ink-1)}
.pos-risk-pct{font-family:var(--mono);font-size:11px;font-weight:500}

/* R/R note */
.rr-note{font-size:12px;color:var(--ink-2);margin-bottom:10px;padding:7px 12px;background:var(--line-2);border-radius:6px;border:1px solid var(--line);display:flex;align-items:baseline;gap:6px}
.rr-note-icon{font-size:13px;color:var(--ink-3);flex-shrink:0}

/* Price bar */
.pos-bar-wrap{margin-top:4px}
.price-bar-wrap{position:relative;height:54px;width:100%;margin-top:2px}
.price-bar-track{position:absolute;top:12px;left:0;right:0;height:2px;background:var(--line);border-radius:2px}
.bar-fill-pos{position:absolute;top:12px;height:2px;background:rgba(21,128,61,.35);border-radius:2px}
.bar-fill-neg{position:absolute;top:12px;height:2px;background:rgba(185,28,28,.35);border-radius:2px}
.bm{position:absolute;top:7px;width:1px;height:10px;border-radius:1px;transform:translateX(-50%)}
.bm-stop  {background:var(--neg)}
.bm-entry {background:var(--ink-3)}
.bm-target{background:var(--pos)}
.bar-dot{position:absolute;top:7px;width:12px;height:12px;background:var(--ink-1);border-radius:50%;transform:translateX(-50%);border:2px solid var(--surface);box-shadow:0 0 0 1px var(--ink-1)}
.bl{position:absolute;top:26px;font-size:9.5px;font-family:var(--mono);transform:translateX(-50%);white-space:nowrap;text-align:center;line-height:1.3}
.bl-stop  {color:var(--neg)}
.bl-entry {color:var(--ink-3)}
.bl-target{color:var(--pos)}

/* Index/Period Chart */
.spy-idx-tabs{display:flex;gap:1px;margin-bottom:12px;background:var(--line-2);padding:2px;border-radius:6px;width:fit-content}
.spy-summary{display:flex;gap:28px;flex-wrap:wrap;margin-bottom:12px}
.spy-label{font-size:10px;font-weight:500;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);display:block;margin-bottom:2px}
.spy-val{font-family:var(--mono);font-size:17px;font-weight:500;color:var(--ink-1)}
.spy-tabs{display:flex;gap:1px;margin-bottom:14px;flex-wrap:wrap;background:var(--line-2);padding:2px;border-radius:6px;width:fit-content}
.spy-tab{padding:4px 12px;border-radius:4px;font-size:11px;font-family:var(--mono);cursor:pointer;border:none;background:transparent;color:var(--ink-3);transition:background .12s,color .12s}
.spy-tab:hover{color:var(--ink-1)}
.spy-tab-active{background:var(--surface)!important;color:var(--ink-1)!important;box-shadow:0 1px 2px rgba(0,0,0,.04),0 0 0 1px var(--line)!important}

/* Watchlist */
.wl-legend{background:var(--line-2);border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin-bottom:14px}
.wl-legend-title{font-size:10px;font-weight:500;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin-bottom:7px}
.wl-legend-items{display:flex;flex-direction:column;gap:5px}
.wl-legend-item{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--ink-2)}
.wl-controls{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.wl-tabs{display:flex;gap:1px;flex-wrap:wrap;background:var(--line-2);padding:2px;border-radius:6px}
.wl-tab{padding:4px 12px;border-radius:4px;font-size:11px;font-family:var(--mono);cursor:pointer;border:none;background:transparent;color:var(--ink-3);transition:background .12s,color .12s}
.wl-tab:hover{color:var(--ink-1)}
.wl-tab.active{background:var(--surface);color:var(--ink-1);box-shadow:0 1px 2px rgba(0,0,0,.04),0 0 0 1px var(--line)}
.wl-sort{padding:4px 10px;border-radius:4px;font-size:11px;font-family:var(--mono);border:1px solid var(--line);background:var(--surface);color:var(--ink-2);cursor:pointer;outline:none}
.wl-sort:hover{border-color:var(--ink-4)}.wl-sort:focus{border-color:var(--ink-2)}
.wl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
.wl-card{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px;transition:border-color .12s}
.wl-card:hover{border-color:var(--ink-4)}
/* Alert 2-column grid */
.wl-alert-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:12px}
@media(max-width:700px){.wl-alert-grid{grid-template-columns:1fr}}
.wl-alert{border-left:3px solid var(--warn)!important}
.wl-alert-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.wl-alert-left{display:flex;align-items:center;gap:8px}
.wl-alert-icon{font-size:15px;line-height:1}
.wl-action-badge{font-size:10px;font-weight:600;font-family:var(--mono);color:var(--warn);padding:2px 8px;border:1px solid var(--warn);border-radius:3px;white-space:nowrap}
.wl-alert-body{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}
.wl-alert-prices{flex:0 0 auto;min-width:150px}
.wl-alert-zone{flex:1;min-width:200px}
.wl-reason-wrap{margin-top:8px}
.wl-score-wrap{margin-bottom:4px}
.wl-score-bg{height:2px;background:var(--line);border-radius:2px;overflow:hidden;margin-top:4px}
.wl-score-fill{height:100%;border-radius:2px}
.score-bar-hi{background:var(--pos)}.score-bar-mid{background:var(--warn)}.score-bar-lo{background:var(--ink-4)}
.wl-unresearched{font-size:10px;margin-bottom:4px;display:inline-flex}
.wl-added{font-size:10px;color:var(--ink-3);margin-top:6px;border-top:1px solid var(--line-2);padding-top:6px;line-height:1.4}
.wl-promoted-section{margin-top:16px;border-top:1px solid var(--line);padding-top:12px}
.wl-promoted-summary{font-size:12px;font-weight:500;color:var(--ink-2);cursor:pointer;padding:4px 0 8px;user-select:none;list-style:none}
.wl-promoted-summary::-webkit-details-marker{display:none}
.wl-promoted-grid{margin-top:10px;opacity:.55}
.wl-promoted{opacity:.45}
.wl-head{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:6px}
.wl-tk{font-family:var(--mono);font-size:15px;font-weight:600;color:var(--ink-1)}
.wl-bgs{display:flex;flex-direction:column;gap:3px;align-items:flex-end}
.wl-score{font-size:11px;color:var(--warn);font-weight:600;font-family:var(--mono);margin-bottom:4px}
.wl-prices{display:flex;justify-content:space-between;align-items:baseline;margin:6px 0 2px}
.wl-cur{font-family:var(--mono);font-size:14px;font-weight:500;color:var(--ink-1)}
.wl-chgs{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
.wl-reason{font-size:11px;color:var(--ink-2);line-height:1.45;border-top:1px solid var(--line-2);padding-top:8px;margin-top:4px}
.wl-reason-detail{border-top:1px solid var(--line-2);padding-top:8px;margin-top:4px}
.wl-reason-short{font-size:11px;color:var(--ink-2);line-height:1.45;cursor:pointer;list-style:none;display:flex;align-items:baseline;gap:6px}
.wl-reason-short::-webkit-details-marker{display:none}
.wl-reason-toggle{font-size:10px;color:var(--ink-3);white-space:nowrap;flex-shrink:0}
.wl-reason-full{font-size:11px;color:var(--ink-2);line-height:1.55;margin-top:6px;padding:8px;background:var(--line-2);border-radius:4px}
.wl-reason-date{font-size:10px;color:var(--ink-3);margin-top:4px}

/* Entry zone mini bar */
.wl-ezbar{margin:8px 0 4px;border-top:1px solid var(--line-2);padding-top:8px}
.wl-bar-wrap{position:relative;height:38px;width:100%}
.wl-bar-track{position:absolute;top:10px;left:0;right:0;height:2px;background:var(--line);border-radius:2px}
.wl-bar-zone{position:absolute;top:8px;height:6px;background:rgba(0,0,0,.06);border:1px solid var(--ink-4);border-radius:3px}
.wl-dot-in{position:absolute;top:6px;width:10px;height:10px;border-radius:50%;background:var(--pos);border:2px solid var(--surface);box-shadow:0 0 0 1px var(--pos);transform:translateX(-50%)}
.wl-dot-out{position:absolute;top:6px;width:10px;height:10px;border-radius:50%;background:var(--ink-1);border:2px solid var(--surface);transform:translateX(-50%)}
.wl-bar-tgt{position:absolute;top:6px;width:1px;height:10px;background:var(--pos);opacity:.7;transform:translateX(-50%);border-radius:1px}
.wl-bl{position:absolute;top:20px;font-size:9px;font-family:var(--mono);color:var(--ink-3);transform:translateX(-50%);white-space:nowrap}
.wl-zone-st{font-size:10px;font-family:var(--mono);font-weight:500;text-align:center;margin-top:1px}
.wl-zone-in{color:var(--pos)}
.wl-zone-below{color:var(--ink-2)}
.wl-zone-above{color:var(--warn)}

/* Closed */
details summary{cursor:pointer;user-select:none}
details[open] summary{margin-bottom:16px}
.closed-summary{font-size:14px;font-weight:600;color:var(--ink-1);list-style:none}
.closed-tbl{width:100%;border-collapse:collapse;font-size:12px}
.closed-tbl th{text-align:left;padding:7px 10px;font-size:10px;font-weight:500;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);border-bottom:1px solid var(--line)}
.closed-tbl td{padding:10px;border-top:1px solid var(--line-2)}
.cl-tk{font-family:var(--mono);font-weight:600;color:var(--ink-1)}

/* Header */
.hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:40px;flex-wrap:wrap;gap:12px;padding-bottom:18px;border-bottom:1px solid var(--line)}
.hdr-title{font-size:15px;font-weight:600;letter-spacing:-.01em;color:var(--ink-1)}
.hdr-meta{font-family:var(--mono);font-size:12px;color:var(--ink-3)}

.wl-sparkline{margin:6px 0 2px}

.wl-controls-right{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.wl-search{padding:4px 10px;border-radius:4px;font-size:12px;font-family:var(--mono);border:1px solid var(--line);background:var(--surface);color:var(--ink-1);outline:none;width:180px}
.wl-search:focus{border-color:var(--ink-3)}
.wl-search::placeholder{color:var(--ink-4)}

.wl-view-btn{padding:4px 10px;border-radius:4px;font-size:12px;font-family:var(--mono);font-weight:500;cursor:pointer;border:1px solid var(--line);background:transparent;color:var(--ink-3);transition:all .12s;line-height:1}
.wl-view-btn:hover{color:var(--ink-1)}
.wl-view-btn.active{background:var(--ink-1);color:var(--surface);border-color:var(--ink-1)}
.wl-table-view{display:none;overflow-x:auto;margin-top:4px}
.wl-tbl{width:100%;border-collapse:collapse;font-size:12px}
.wl-tbl th{text-align:left;padding:7px 10px;font-size:10px;font-weight:500;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);border-bottom:1px solid var(--line);white-space:nowrap;user-select:none}
.wl-tbl th[data-sort-col]{cursor:pointer}
.wl-tbl th[data-sort-col]:hover{color:var(--ink-1)}
.wl-tbl td{padding:8px 10px;border-top:1px solid var(--line-2);vertical-align:middle}
.wl-tbl tr:hover td{background:var(--line-2)}
.wl-tbl-tk{font-family:var(--mono);font-weight:600;color:var(--ink-1);font-size:13px}
"""

# ─── JavaScript ───────────────────────────────────────────────────────────────

_JS = """
// ── Reason accordion toggle text ──
document.querySelectorAll('.wl-reason-detail').forEach(function(d) {
  d.addEventListener('toggle', function() {
    var t = d.querySelector('.wl-reason-toggle');
    if (t) t.textContent = d.open ? '▲ 閉じる' : '▼ 詳細';
  });
});

// ── Watchlist: tab filter, sort, search, view toggle ──
(function() {
  const alertGrid    = document.getElementById('wl-alert-grid');
  const mainGrid     = document.getElementById('wl-grid');
  const promoSection = document.getElementById('wl-promoted-section');
  const promoGrid    = document.getElementById('wl-promoted-grid');
  const wlTabs       = document.querySelectorAll('.wl-tab');
  const sortSel      = document.getElementById('wl-sort');
  const searchInput  = document.getElementById('wl-search');
  const viewBtn      = document.getElementById('wl-view-btn');
  const tblView      = document.getElementById('wl-table-view');
  const tblBody      = document.getElementById('wl-tbl-body');
  let currentFilter  = 'all';
  let isTableView    = false;

  function cards(el) { return el ? [...el.querySelectorAll('.wl-card')] : []; }
  function tblRows()  { return tblBody ? [...tblBody.querySelectorAll('.wl-tbl-row')] : []; }

  function getQ() {
    return searchInput ? searchInput.value.toLowerCase().trim() : '';
  }
  function matchesSearch(el, q) {
    if (!q) return true;
    return (el.dataset.ticker || '').includes(q) || (el.dataset.reason || '').toLowerCase().includes(q);
  }

  // ── Filter (cards) ──
  function applyFilter(f) {
    currentFilter = f;
    if (isTableView) { applyTableFilter(); return; }

    var q = getQ();
    var showCard = function(c) { c.style.display = matchesSearch(c, q) ? '' : 'none'; };

    if (f === 'all') {
      if (alertGrid)    { alertGrid.style.display = ''; cards(alertGrid).forEach(showCard); }
      if (mainGrid)     { mainGrid.style.display  = ''; cards(mainGrid).forEach(showCard); }
      if (promoSection) promoSection.style.display = '';
      if (promoGrid)    cards(promoGrid).forEach(showCard);
    } else if (f === 'alert') {
      if (alertGrid)    { alertGrid.style.display = ''; cards(alertGrid).forEach(showCard); }
      if (mainGrid)     mainGrid.style.display    = 'none';
      if (promoSection) promoSection.style.display = 'none';
    } else if (f === 'active') {
      if (alertGrid)    alertGrid.style.display   = 'none';
      if (mainGrid) {
        mainGrid.style.display = '';
        cards(mainGrid).forEach(function(c) {
          c.style.display = (c.dataset.status === 'active' && matchesSearch(c, q)) ? '' : 'none';
        });
      }
      if (promoSection) promoSection.style.display = 'none';
    } else if (f === 'promoted') {
      if (alertGrid)    alertGrid.style.display   = 'none';
      if (mainGrid)     mainGrid.style.display    = 'none';
      if (promoSection) { promoSection.style.display = ''; promoSection.open = true; }
      if (promoGrid)    cards(promoGrid).forEach(showCard);
    }
  }

  // ── Filter (table rows) ──
  function applyTableFilter() {
    var q = getQ(), f = currentFilter;
    tblRows().forEach(function(r) {
      var ok = matchesSearch(r, q);
      if (ok) {
        if      (f === 'alert')    ok = r.dataset.alert  === '1';
        else if (f === 'active')   ok = r.dataset.status === 'active';
        else if (f === 'promoted') ok = r.dataset.status === 'promoted';
      }
      r.style.display = ok ? '' : 'none';
    });
  }

  // ── Sort ──
  function makeSortFn(key) {
    return function(a, b) {
      if (key === 'default') {
        var ad = Number(b.dataset.alert) - Number(a.dataset.alert);
        if (ad !== 0) return ad;
        return Number(b.dataset.score) - Number(a.dataset.score);
      }
      if (key === 'score')  return Number(b.dataset.score)  - Number(a.dataset.score);
      if (key === 'refchg') return Number(b.dataset.refchg) - Number(a.dataset.refchg);
      if (key === 'daychg') return Number(b.dataset.daychg) - Number(a.dataset.daychg);
      if (key === 'added')  return (b.dataset.added || '').localeCompare(a.dataset.added || '');
      if (key === 'ticker') return (a.dataset.ticker || '').localeCompare(b.dataset.ticker || '');
      return 0;
    };
  }

  function applySort(key) {
    var fn = makeSortFn(key);
    [alertGrid, mainGrid, promoGrid].forEach(function(g) {
      if (!g) return;
      cards(g).sort(fn).forEach(function(c) { g.appendChild(c); });
    });
    if (tblBody) tblRows().sort(fn).forEach(function(r) { tblBody.appendChild(r); });
  }

  // ── Tab click ──
  wlTabs.forEach(function(tab) {
    tab.addEventListener('click', function() {
      wlTabs.forEach(function(t) { t.classList.remove('active'); });
      tab.classList.add('active');
      applyFilter(tab.dataset.f);
    });
  });

  // ── Sort change ──
  if (sortSel) {
    sortSel.addEventListener('change', function() {
      applySort(sortSel.value);
      applyFilter(currentFilter);
    });
  }

  if (searchInput) {
    searchInput.addEventListener('input', function() {
      if (isTableView) applyTableFilter();
      else applyFilter(currentFilter);
    });
  }

  if (viewBtn && tblView) {
    viewBtn.addEventListener('click', function() {
      isTableView = !isTableView;
      if (isTableView) {
        [alertGrid, mainGrid, promoSection].forEach(function(el) { if (el) el.style.display = 'none'; });
        tblView.style.display = '';
        viewBtn.textContent = '⊞';
        viewBtn.title = 'カード表示に戻す';
        viewBtn.classList.add('active');
        applyTableFilter();
      } else {
        tblView.style.display = 'none';
        viewBtn.textContent = '☰';
        viewBtn.title = 'カード ↔ リスト表示切り替え';
        viewBtn.classList.remove('active');
        applyFilter(currentFilter);
      }
    });
  }

  document.querySelectorAll('.wl-tbl th[data-sort-col]').forEach(function(th) {
    th.addEventListener('click', function() {
      var key = th.dataset.sortCol;
      if (sortSel) sortSel.value = key === 'ticker' ? 'default' : key;
      applySort(key);
      applyTableFilter();
    });
  });

})();

// ── Index Multi-period Chart ──
(function() {
  if (!window._indexData || !document.getElementById('spyChart')) return;

  const ctx = document.getElementById('spyChart').getContext('2d');
  let currentIdx    = 'SPY';
  let currentPeriod = '30d';

  // For N225 (JPY) we don't prefix with '$'
  function fmtPrice(v, idx) {
    const n = Number(v);
    if (isNaN(n)) return '—';
    if (idx === 'N225') return n.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return '$' + n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }
  function fmtPct(v) { return (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%'; }

  function getD() {
    return (window._indexData[currentIdx] || {})[currentPeriod] || {};
  }

  function updateChart() {
    const d = getD();
    const closes  = d.closes  || [];
    const dates   = d.dates   || [];
    const colors  = d.colors  || [];
    chart.data.labels = dates;
    chart.data.datasets[0].data = closes;
    chart.data.datasets[0].pointBackgroundColor = colors;
    chart.update('active');
    updateSummary();
  }

  function updateSummary() {
    const d = getD();
    const closes = d.closes || [];
    if (!closes.length) return;
    const last  = closes[closes.length - 1];
    const first = closes[0];
    const chg   = (last - first) / first * 100;
    const high  = Math.max(...closes);
    const low   = Math.min(...closes);

    document.getElementById('spy-last').textContent = fmtPrice(last, currentIdx);
    document.getElementById('spy-high').textContent = fmtPrice(high, currentIdx);
    document.getElementById('spy-low').textContent  = fmtPrice(low,  currentIdx);
    const chgEl = document.getElementById('spy-chg');
    chgEl.textContent = fmtPct(chg);
    chgEl.className   = 'spy-val ' + (chg >= 0 ? 'c-pos' : 'c-neg');
  }

  // Init chart
  const initD = (window._indexData['SPY'] || {})['30d'] || {};
  const chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: initD.dates || [],
      datasets: [{
        label: 'Index',
        data: initD.closes || [],
        borderColor: '#0a0a0a',
        backgroundColor: 'rgba(10,10,10,0.05)',
        borderWidth: 1.5,
        pointRadius: 3,
        pointBackgroundColor: initD.colors || [],
        pointBorderColor: '#fff',
        pointBorderWidth: 1.5,
        pointHoverRadius: 5,
        fill: true,
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#0a0a0a',
          titleColor: '#a1a1a1',
          bodyColor: '#ffffff',
          padding: 10,
          callbacks: {
            label: function(item) {
              const i = item.dataIndex;
              const d = getD();
              const chg = (d.changes || [])[i] || 0;
              const sign = chg >= 0 ? '+' : '';
              return [
                ' ' + fmtPrice(item.parsed.y, currentIdx),
                ' ' + sign + chg.toFixed(2) + '%'
              ];
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: '#f4f4f4' },
          ticks: { color: '#a1a1a1', font: { size: 10 }, maxRotation: 45, maxTicksLimit: 12 }
        },
        y: {
          grid: { color: '#f4f4f4' },
          ticks: {
            color: '#a1a1a1', font: { size: 10 },
            callback: v => currentIdx === 'N225'
              ? Number(v).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
              : '$' + Number(v).toFixed(0)
          }
        }
      }
    }
  });

  // Index tab switching
  document.querySelectorAll('[data-idx]').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('[data-idx]').forEach(t => t.classList.remove('spy-tab-active'));
      tab.classList.add('spy-tab-active');
      currentIdx = tab.dataset.idx;
      updateChart();
    });
  });

  // Period tab switching
  document.querySelectorAll('[data-period]').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('[data-period]').forEach(t => t.classList.remove('spy-tab-active'));
      tab.classList.add('spy-tab-active');
      currentPeriod = tab.dataset.period;
      updateChart();
    });
  });

  updateSummary();
})();
"""


# ─── HTML assembly ────────────────────────────────────────────────────────────

def generate_html(open_rows, closed_rows, watchlist, snapshots, index_data, sparklines: dict | None = None) -> str:
    if sparklines is None:
        sparklines = {}
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    gen_at  = now_jst.strftime("%Y-%m-%d %H:%M JST")

    kpi      = render_kpi(open_rows, closed_rows, snapshots)
    open_s   = render_open_positions(open_rows, snapshots)
    spy_s    = render_index_chart(index_data)
    wl_s     = render_watchlist(watchlist, snapshots, sparklines)
    closed_s = render_closed_positions(closed_rows)

    return (
        '<!DOCTYPE html><html lang="ja"><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<title>Investor Dashboard</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">'
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'
        f'<style>{_CSS}</style>'
        '</head><body><div class="wrap">'

        # Header
        '<div class="hdr">'
        '<div>'
        '<div class="hdr-title">Investor Dashboard</div>'
        f'<div class="hdr-meta">Generated: {gen_at}</div>'
        '</div>'
        f'<div class="hdr-meta">Budget ¥1,000,000 ≈ ${BUDGET:,.0f}</div>'
        '</div>'

        + kpi

        # Open Positions
        + '<div class="sec">'
        f'<div class="sec-ttl">Open Positions <span>{len(open_rows)} 件</span></div>'
        + open_s
        + '</div>'

        # S&P 500 Chart
        + spy_s

        # Watchlist
        + '<div class="sec">'
        '<div class="sec-ttl">Watchlist <span></span></div>'
        + wl_s
        + '</div>'

        # Closed Positions
        + '<div class="sec">'
        '<div class="sec-ttl">Closed Positions <span></span></div>'
        + closed_s
        + '</div>'

        f'</div><script>{_JS}</script></body></html>'
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Fetching market data…")
    yf_client = YFinanceClient()

    all_rows    = _read_portfolio()
    open_rows   = [r for r in all_rows if r.get("status") == "open"]
    closed_rows = [r for r in all_rows if r.get("status") == "closed"]
    watchlist   = _read_watchlist()

    tickers = list({r["ticker"] for r in open_rows} | {
        w["ticker"] for w in watchlist if w.get("status") in ("active", "promoted")
    })

    print(f"Fetching snapshots + sparklines for {len(tickers)} tickers…")
    snapshots: dict = {}
    sparklines: dict = {}
    with ThreadPoolExecutor(max_workers=min(8, len(tickers) or 1)) as exe:
        results = exe.map(lambda t: (t, *_fetch_ticker_data(yf_client, t)), tickers)
    for ticker, snap, sl in results:
        if snap:
            snapshots[ticker] = snap
        if sl:
            sparklines[ticker] = sl

    print("Fetching SPY multi-period history…")
    spy_periods = _get_index_all_periods("SPY", "SPY")

    print("Fetching 日経平均 multi-period history…")
    n225_periods = _get_index_all_periods("^N225", "日経平均")

    index_data = {"SPY": spy_periods, "N225": n225_periods}

    print("Generating HTML…")
    html = generate_html(open_rows, closed_rows, watchlist, snapshots, index_data, sparklines)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    sync_local_to_supabase("report_artifacts")
    print(f"✓ Dashboard saved → {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()

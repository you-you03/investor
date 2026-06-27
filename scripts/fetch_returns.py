#!/usr/bin/env python3
"""
fetch_returns.py — 週次リターン取得スクリプト

score_snapshots.json の各マイルストーンのうち、
target_date <= today かつ fetched_at is None のものを一括更新する。

実行: .venv/bin/python scripts/fetch_returns.py
cron:  0 8 * * 1  cd "/Users/yutaobayashi/PERSONAL DEV/1_now/investor" && .venv/bin/python scripts/fetch_returns.py >> logs/cron.log 2>&1
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

from investor.core.score_snapshots import (
    WEEK_KEYS,
    classify_market_regime,
    ensure_tracking_horizons,
    sector_etf_for_ticker,
)

SNAPSHOTS_PATH = Path(__file__).parent.parent / "data" / "score_snapshots.json"


def fetch_close_on_or_before(ticker: str, target: date) -> float | None:
    """target_date の終値を取得。週末・祝日は直前営業日を使う。"""
    t = yf.Ticker(ticker)
    # target から最大7営業日前まで遡って取得
    start = target - timedelta(days=7)
    end = target + timedelta(days=1)
    hist = t.history(start=start.isoformat(), end=end.isoformat())
    if hist.empty:
        return None
    # target 以前の最新の終値
    hist = hist[hist.index.date <= target]
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])


def fetch_symbol_return(symbol: str, scored_at: date, target: date) -> float | None:
    """scored_at → target 間の symbol 累積リターン（%）を返す。"""
    ticker = yf.Ticker(symbol)
    start = scored_at - timedelta(days=7)
    end = target + timedelta(days=1)
    hist = ticker.history(start=start.isoformat(), end=end.isoformat())
    if hist.empty:
        return None

    # scored_at 以前の最新終値
    before = hist[hist.index.date <= scored_at]
    after = hist[hist.index.date <= target]
    if before.empty or after.empty:
        return None

    price_start = float(before["Close"].iloc[-1])
    price_end = float(after["Close"].iloc[-1])
    if price_start == 0:
        return None
    return round((price_end - price_start) / price_start * 100, 4)


def fetch_tnx_change_bps(scored_at: date, target: date) -> float | None:
    """
    ^TNX is quoted as 10x the 10-year yield.
    A 1.0 move in ^TNX is roughly 10 bps.
    """
    tnx = yf.Ticker("^TNX")
    start = scored_at - timedelta(days=7)
    end = target + timedelta(days=1)
    hist = tnx.history(start=start.isoformat(), end=end.isoformat())
    if hist.empty:
        return None
    before = hist[hist.index.date <= scored_at]
    after = hist[hist.index.date <= target]
    if before.empty or after.empty:
        return None
    start_value = float(before["Close"].iloc[-1])
    end_value = float(after["Close"].iloc[-1])
    return round((end_value - start_value) * 10, 2)


def _needs_backfill(wk: dict) -> bool:
    return any(
        wk.get(key) is None
        for key in (
            "qqq_return_pct",
            "sector_return_pct",
            "alpha_vs_spy",
            "alpha_vs_qqq",
            "alpha_vs_sector",
            "vix_change_pct",
            "ten_year_yield_change_bps",
            "market_regime",
        )
    )


def process_snapshots() -> None:
    if not SNAPSHOTS_PATH.exists():
        print(f"ERROR: {SNAPSHOTS_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    with open(SNAPSHOTS_PATH) as f:
        data = json.load(f)

    snapshots = data.get("snapshots", [])
    today = date.today()
    updated = 0
    normalized = 0

    # Benchmark caches. Keyed by symbol + scored_at + target.
    return_cache: dict[tuple[str, str, str], float | None] = {}
    tnx_cache: dict[tuple[str, str], float | None] = {}

    print(f"Checking score_snapshots for matured milestones... (today={today})")

    for snap in snapshots:
        if ensure_tracking_horizons(snap):
            normalized += 1
        ticker = snap.get("ticker", "?")
        scored_at_str = snap.get("scored_at", "")
        price_at_score = snap.get("price_at_score")

        if not scored_at_str or price_at_score is None:
            continue
        scored_at = date.fromisoformat(scored_at_str)

        for wk_key in WEEK_KEYS:
            wk = snap.get(wk_key)
            if wk is None:
                continue
            target_str = wk.get("target_date")
            if not target_str:
                continue
            target = date.fromisoformat(target_str)

            if target > today:
                print(f"  {ticker:6s} {wk_key} ({target}) → future, skip")
                continue

            if wk.get("fetched_at") is not None and not _needs_backfill(wk):
                continue

            if wk.get("return_pct") is None or wk.get("price") is None:
                price = fetch_close_on_or_before(ticker, target)
                if price is None:
                    print(f"  {ticker:6s} {wk_key} ({target}) → price fetch failed, skip")
                    continue
                ret_pct = round((price - price_at_score) / price_at_score * 100, 4)
                wk["price"] = round(price, 2)
                wk["return_pct"] = ret_pct
            else:
                price = wk.get("price")
                ret_pct = wk.get("return_pct")

            sector_etf = wk.get("sector_etf") or snap.get("sector_etf") or sector_etf_for_ticker(ticker)
            wk["sector_etf"] = sector_etf
            snap["sector_etf"] = snap.get("sector_etf") or sector_etf

            def cached_return(symbol: str) -> float | None:
                key = (symbol, scored_at_str, target_str)
                if key not in return_cache:
                    return_cache[key] = fetch_symbol_return(symbol, scored_at, target)
                return return_cache[key]

            spy_ret = wk.get("spy_return_pct")
            if spy_ret is None:
                spy_ret = cached_return("SPY")
                wk["spy_return_pct"] = spy_ret

            qqq_ret = wk.get("qqq_return_pct")
            if qqq_ret is None:
                qqq_ret = cached_return("QQQ")
                wk["qqq_return_pct"] = qqq_ret

            sector_ret = wk.get("sector_return_pct")
            if sector_ret is None:
                sector_ret = cached_return(sector_etf)
                wk["sector_return_pct"] = sector_ret

            vix_change = wk.get("vix_change_pct")
            if vix_change is None:
                vix_change = cached_return("^VIX")
                wk["vix_change_pct"] = vix_change

            tnx_key = (scored_at_str, target_str)
            yield_change = wk.get("ten_year_yield_change_bps")
            if yield_change is None:
                if tnx_key not in tnx_cache:
                    tnx_cache[tnx_key] = fetch_tnx_change_bps(scored_at, target)
                yield_change = tnx_cache[tnx_key]
                wk["ten_year_yield_change_bps"] = yield_change

            alpha_spy = round(ret_pct - spy_ret, 4) if spy_ret is not None else None
            alpha_qqq = round(ret_pct - qqq_ret, 4) if qqq_ret is not None else None
            alpha_sector = round(ret_pct - sector_ret, 4) if sector_ret is not None else None
            wk["alpha_pct"] = alpha_spy
            wk["alpha_vs_spy"] = alpha_spy
            wk["alpha_vs_qqq"] = alpha_qqq
            wk["alpha_vs_sector"] = alpha_sector
            wk["market_regime"] = classify_market_regime(
                spy_return_pct=spy_ret,
                qqq_return_pct=qqq_ret,
                sector_return_pct=sector_ret,
                vix_change_pct=vix_change,
                ten_year_yield_change_bps=yield_change,
            )
            wk["spy_return_pct"] = spy_ret
            wk["fetched_at"] = datetime.now().isoformat(timespec="seconds")
            updated += 1

            spy_str = f"SPY: {spy_ret:+.1f}%" if spy_ret is not None else "SPY: N/A"
            sector_str = f"{sector_etf}: {sector_ret:+.1f}%" if sector_ret is not None else f"{sector_etf}: N/A"
            alpha_str = f"sector alpha: {alpha_sector:+.1f}%" if alpha_sector is not None else "sector alpha: N/A"
            print(
                f"  {ticker:6s} {wk_key} ({target}) → ${float(price):.2f} | {ret_pct:+.1f}% | "
                f"{spy_str} | {sector_str} | {alpha_str}  ✅"
            )

    with open(SNAPSHOTS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nUpdated {updated} milestone(s) across score_snapshots.json")
    if normalized:
        print(f"Normalized {normalized} existing snapshot(s) with new horizon checkpoints")
    sync_score_snapshots_to_supabase()


def sync_score_snapshots_to_supabase() -> None:
    """Keep Supabase row data aligned after local milestone updates."""
    try:
        from investor.supabase_store import get_store
        from scripts.backfill_supabase import backfill_score_snapshots

        store = get_store()
        if not store:
            return
        synced = backfill_score_snapshots(store)
        print(f"Synced {synced} score snapshot row(s) to Supabase")
    except Exception as exc:
        print(f"WARNING: Supabase score_snapshots sync skipped: {exc}", file=sys.stderr)


if __name__ == "__main__":
    process_snapshots()

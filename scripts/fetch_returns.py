#!/usr/bin/env python3
"""
fetch_returns.py — 週次リターン取得スクリプト

score_snapshots.json の week1〜week4 マイルストーンのうち、
target_date <= today かつ fetched_at is None のものを一括更新する。

実行: .venv/bin/python scripts/fetch_returns.py
cron:  0 8 * * 1  cd "/Users/yutaobayashi/PERSONAL DEV/investor" && .venv/bin/python scripts/fetch_returns.py >> logs/cron.log 2>&1
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yfinance as yf

SNAPSHOTS_PATH = Path(__file__).parent.parent / "data" / "score_snapshots.json"
WEEK_KEYS = ["week1", "week2", "week3", "week4"]


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


def fetch_spy_return(scored_at: date, target: date) -> float | None:
    """scored_at → target 間の SPY 累積リターン（%）を返す。"""
    spy = yf.Ticker("SPY")
    start = scored_at - timedelta(days=7)
    end = target + timedelta(days=1)
    hist = spy.history(start=start.isoformat(), end=end.isoformat())
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


def process_snapshots() -> None:
    if not SNAPSHOTS_PATH.exists():
        print(f"ERROR: {SNAPSHOTS_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    with open(SNAPSHOTS_PATH) as f:
        data = json.load(f)

    snapshots = data.get("snapshots", [])
    today = date.today()
    updated = 0

    # SPY キャッシュ（scored_at ごとに1回だけ取得）
    spy_cache: dict[tuple[str, str], float | None] = {}

    print(f"Checking score_snapshots for matured milestones... (today={today})")

    for snap in snapshots:
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
            if wk.get("fetched_at") is not None:
                continue  # 取得済み

            target_str = wk.get("target_date")
            if not target_str:
                continue
            target = date.fromisoformat(target_str)

            if target > today:
                print(f"  {ticker:6s} {wk_key} ({target}) → future, skip")
                continue

            # 株価取得
            price = fetch_close_on_or_before(ticker, target)
            if price is None:
                print(f"  {ticker:6s} {wk_key} ({target}) → price fetch failed, skip")
                continue

            # リターン計算
            ret_pct = round((price - price_at_score) / price_at_score * 100, 4)

            # SPY リターン（キャッシュ利用）
            spy_key = (scored_at_str, target_str)
            if spy_key not in spy_cache:
                spy_cache[spy_key] = fetch_spy_return(scored_at, target)
            spy_ret = spy_cache[spy_key]

            alpha = None
            if spy_ret is not None:
                alpha = round(ret_pct - spy_ret, 4)

            wk["price"] = round(price, 2)
            wk["return_pct"] = ret_pct
            wk["spy_return_pct"] = spy_ret
            wk["alpha_pct"] = alpha
            wk["fetched_at"] = datetime.now().isoformat(timespec="seconds")
            updated += 1

            spy_str = f"SPY: {spy_ret:+.1f}%" if spy_ret is not None else "SPY: N/A"
            alpha_str = f"alpha: {alpha:+.1f}%" if alpha is not None else "alpha: N/A"
            print(
                f"  {ticker:6s} {wk_key} ({target}) → ${price:.2f} | {ret_pct:+.1f}% | {spy_str} | {alpha_str}  ✅"
            )

    with open(SNAPSHOTS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nUpdated {updated} milestone(s) across score_snapshots.json")


if __name__ == "__main__":
    process_snapshots()

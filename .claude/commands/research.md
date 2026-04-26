Run a full market research scan for today's best US stock investment opportunities, then save results to `data/research_history.json`.

All Bash commands must be run from the `investor/` subdirectory:
```
cd "/Users/yutaobayashi/PERSONAL DEV/investor"
```

---

## Invocation modes

Check the argument **before** proceeding:

| Invocation | Behavior |
|---|---|
| `/research` | **Standard mode** — full market scan. Follow Steps 1–7 below. |
| `/research --seed {TICKER}` | **Seed mode** — fast-track deep research on a single watchlist ticker. Skip to [Seed Mode section](#seed-mode) below. |

---

## Seed Mode

**Trigger**: `/research --seed {TICKER}`

Use when Monitor raises `WATCHLIST_BREAKOUT`, `WATCHLIST_SETUP`, or `WATCHLIST_EARNINGS` for a ticker.
Skips market scan (Steps 2–3). Delivers deep research on the single ticker within minutes.

### Seed Step 1: Load watchlist context

```bash
cat data/watchlist.json
cat data/research_history.json
```

From `watchlist.json`, extract for `{TICKER}`:
- `last_research_run_id`, `last_score`, `reference_price`, `added_at`, `reason`

If `last_research_run_id` is set, find that run in `research_history.json` and extract the previous candidate data for `{TICKER}`.

### Seed Step 2: Macro context (required even in seed mode)

```bash
.venv/bin/python scripts/tool.py get_market_context
```

State the current regime. Apply same scoring adjustments as standard mode.

### Seed Step 3: Deep research (same as standard Step 4)

Run all 9 tools for `{TICKER}`:

```bash
.venv/bin/python scripts/tool.py get_stock_snapshot --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
.venv/bin/python scripts/tool.py get_financials --ticker {TICKER}
.venv/bin/python scripts/tool.py get_ticker_details --ticker {TICKER}
.venv/bin/python scripts/tool.py get_relative_strength --ticker {TICKER}
.venv/bin/python scripts/tool.py get_earnings_calendar --ticker {TICKER}
.venv/bin/python scripts/tool.py get_news --ticker {TICKER}
.venv/bin/python scripts/tool.py get_analyst_ratings --ticker {TICKER}
.venv/bin/python scripts/tool.py get_atr_targets --ticker {TICKER} --entry_price {current_price}
```

### Seed Step 4: Score (same rubric as standard Step 5)

Use the same 5-axis scoring. Compute weighted total. Note: seed mode always proceeds regardless of score (user already flagged this ticker).

### Seed Step 5: Show diff vs previous research

If previous research exists for this ticker:

```
## スコア差分（前回 vs 今回）

前回リサーチ ({prev_date}, run: {prev_run_id[:8]}):
  スコア: {prev_score} / エントリーゾーン: {prev_entry_zone} / 目標: ${prev_target}

今回 ({today}):
  スコア: {new_score} ({score_delta:+.1f}) / 現在値: ${current_price}
  変化点:
  - RSI: {prev_rsi} → {new_rsi}
  - MACD: {prev_macd_signal} → {new_macd_signal}
  - Revenue YoY: {prev_revenue_growth} → {new_revenue_growth}
  → エントリーゾーン: {new_entry_zone} / 目標値: ${new_target}（ATR {multiplier}×）
```

If no previous research exists, output: "初回リサーチ — 前回比較なし"

### Seed Step 6: Save and update watchlist

Save to `data/research_history.json` as a new run (same format as standard Step 6). Use a new UUID4 as `run_id`.

Then update `data/watchlist.json` for `{TICKER}`:
- Set `last_score` = new score
- Set `last_research_run_id` = new run_id
- Set `reference_price` = current_price (reset reference to today's price)

```bash
cat data/watchlist.json
```

Write back the updated file.

### Seed Step 7: Report

```markdown
# Research Report (Seed) — {TICKER} — {YYYY-MM-DD}

**モード**: シードリサーチ（ウォッチリスト優先） | **run_id**: `{run_id}`
**トリガー**: {watchlist_flag that caused this run, e.g. WATCHLIST_BREAKOUT}
**マクロ**: {regime}

{diff block from Seed Step 5}

---

## {TICKER} — {company_name}  スコア: **{score}**

{same format as standard Step 7 individual ticker section}
```

End with:
```
> **Next step**: `/decision` を実行して投資判断フェーズへ（最新 run が自動選択される）
```

---

## Step 1: Get macro context (MANDATORY FIRST)

```bash
.venv/bin/python scripts/tool.py get_market_context
```

Classify the regime from the output:
- `HIGH_FEAR` (VIX > 30): cap all conviction scores at MEDIUM; reduce suggested position sizes by 50%
- `DOWNTREND` (SPY < EMA50): add "market headwind" to every candidate's risk_factors; raise the bar for BUY recommendations
- `NORMAL`: proceed with standard criteria

State the regime before moving on.

## Step 2: Get market movers + screeners

```bash
.venv/bin/python scripts/tool.py get_market_movers
.venv/bin/python scripts/tool.py get_market_movers --direction actives
.venv/bin/python scripts/tool.py get_52w_breakouts
.venv/bin/python scripts/tool.py get_earnings_surprises
```

Also load `data/watchlist.json` and treat active watchlist tickers as priority candidates.

## Step 3: Select 15–20 candidates

From movers + screeners + watchlist, select promising tickers using this priority order:

1. **ウォッチリスト（最大10件を優先スロット）** — 既に調査済みで追跡中の銘柄を必ず含める
2. **52週高値ブレイクアウト銘柄** — `get_52w_breakouts` の出力から有望株を追加
3. **決算サプライズ銘柄** — `get_earnings_surprises` の出力から追加
4. **gainers + actives** — 残りスロットをモメンタム銘柄で埋める

各候補の選別基準（以下を満たすものを優先）:
- Price up >3% intraday with volume spike >1.5x average
- Small/mid-cap ($500M–$20B market cap)
- Clear momentum or catalyst story
- Exclude ETFs, inverse funds, and tickers with <$1M daily volume

**上限: 20銘柄。全銘柄をStep 4で深研究する。**

## Step 4: Deep research per ticker

For **each selected ticker**, call ALL of these (replace `{TICKER}` and `{PRICE}`):

```bash
.venv/bin/python scripts/tool.py get_stock_snapshot --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
.venv/bin/python scripts/tool.py get_financials --ticker {TICKER}
.venv/bin/python scripts/tool.py get_ticker_details --ticker {TICKER}
.venv/bin/python scripts/tool.py get_relative_strength --ticker {TICKER}
.venv/bin/python scripts/tool.py get_earnings_calendar --ticker {TICKER}
.venv/bin/python scripts/tool.py get_news --ticker {TICKER}
.venv/bin/python scripts/tool.py get_analyst_ratings --ticker {TICKER}
.venv/bin/python scripts/tool.py get_atr_targets --ticker {TICKER} --entry_price {PRICE}
```

If `PERPLEXITY_API_KEY` or `XAI_API_KEY` are set in `.env`, also call:
```bash
.venv/bin/python scripts/tool.py get_web_search --query "{TICKER} stock analyst catalysts 2026"
.venv/bin/python scripts/tool.py get_x_search --query "{TICKER} stock sentiment"
```

## Step 5: Score each ticker

Use only data returned by the tools. Do not fabricate numbers. For each score, record the specific data point that justifies it in `score_evidence`.

| Factor | Weight | What to look for |
|--------|--------|-----------------|
| Momentum | 25% | RSI, MACD, % change, volume vs avg; rs_signal from get_relative_strength (STRONG_OUTPERFORM = +1pt bonus, STRONG_UNDERPERFORM = -2pt penalty) |
| Fundamentals | 20% | revenue_growth_yoy + earnings_growth_yoy + forward_pe from get_ticker_details; forward_pe > 50 → add "高バリュエーションリスク"; peg_ratio > 3 → add "成長織り込み済みリスク" |
| Catalyst | 25% | Upcoming events, analyst upside % from get_ticker_details; days_until_earnings ≤ 14 → +1pt and add "決算前カタリスト" to key_catalysts + "決算ギャップリスク" to risk_factors; no catalyst → cap at 6; downgrade 1-2pts if DOWNTREND or HIGH_FEAR |
| Technical | 15% | RSI positioning, MACD crossovers, BB squeeze, EMA20/50 alignment |
| Sentiment | 15% | News tone, X posts, analyst_recommendation + analyst_count from get_ticker_details; strong_buy with ≥10 analysts = score 8+ |

Score 1–10 per factor. Compute weighted total: (momentum×0.25 + fundamentals×0.20 + catalyst×0.25 + technical×0.15 + sentiment×0.15).

**スコアに関わらず全銘柄をスコアリングする。** スコア < 7.0 の銘柄はStep 6bのscore_snapshots.jsonに記録し、Step 6a（research_history.json）には含めない。

### ATR target selection
Use `get_atr_targets` output as the base, then adjust multiplier:
- Imminent earnings (≤14 days) AND strong fundamentals: target = entry + 3.0×ATR
- No near-term catalyst, pure technical setup: target = entry + 1.5×ATR
- Default: target = entry + 2.0×ATR; stop = entry − 1.0×ATR
- If a clear support level is closer than 1×ATR, use that as stop_loss instead
Record `atr_multiplier_used` and `atr_multiplier_reason` in output.

## Step 6a: Save to research_history.json（スコア ≥ 7.0 のみ）

Generate a UUID4 as `run_id`. Read `data/research_history.json` if it exists (preserve prior runs), then append this run and write back.

**このステップには score ≥ 7.0 の銘柄のみ含める。** decision agent のインプットとして使用する。

Output format for each candidate:
```json
{
  "ticker": "NVDA",
  "company_name": "NVIDIA Corporation",
  "score": 8.2,
  "current_price": 875.00,
  "score_breakdown": {
    "momentum": 9, "fundamentals": 8, "catalyst": 9, "technical": 7, "sentiment": 8
  },
  "score_evidence": {
    "momentum": "RSI=71, +8% today on 2.4x avg volume, rs_signal=STRONG_OUTPERFORM",
    "fundamentals": "Revenue +122% YoY, forward_pe=24, peg_ratio=1.8",
    "catalyst": "GTC conference in 2 weeks, analyst upside +34%, 56 strong_buy analysts",
    "technical": "Above EMA20/EMA50, MACD bullish crossover, BB squeeze",
    "sentiment": "Analyst consensus strong_buy (56 analysts), X posts 80% bullish"
  },
  "thesis": "2–3 sentence thesis explaining why this is compelling right now.",
  "key_catalysts": ["GTC conference", "H200 ramp"],
  "key_risks": ["Stretched valuation", "China export risk"],
  "entry_zone": "860–880",
  "target_price": 1000,
  "stop_loss": 820,
  "time_horizon": "4–6 weeks",
  "rs_signal": "STRONG_OUTPERFORM",
  "rs_1m": 12.4,
  "rs_3m": 28.1,
  "days_until_earnings": 18,
  "atr_multiplier_used": 2.0,
  "atr_multiplier_reason": "デフォルト2×ATR採用（決算18日前だが純技術セットアップ）",
  "analyst_upside_pct": 34.2,
  "macro_regime": "ELEVATED_RISK_DOWNTREND",
  "data_notes": "Financial data as of Q4 2025."
}
```

Full file structure:
```json
{
  "runs": [
    {
      "run_id": "<uuid4>",
      "date": "<YYYY-MM-DD>",
      "macro_regime": "<regime string>",
      "candidates": [ ... ]
    }
  ]
}
```

## Step 6b: Save ALL scored tickers to score_snapshots.json（検証用）

Read `data/score_snapshots.json` (if not exists, start with `{"snapshots": []}`).

**スコアに関わらず全銘柄**（スコア < 7.0 含む）を追記する。各エントリーのフォーマット:

```json
{
  "run_id": "<same uuid4 as Step 6a>",
  "scored_at": "<YYYY-MM-DD>",
  "ticker": "NVDA",
  "company_name": "NVIDIA Corporation",
  "score": 8.2,
  "score_breakdown": {
    "momentum": 9,
    "fundamentals": 8,
    "catalyst": 9,
    "technical": 7,
    "sentiment": 8
  },
  "rank_in_run": 1,
  "total_scored_in_run": 18,
  "price_at_score": 880.00,
  "passed_threshold": true,
  "macro_regime": "NORMAL",
  "week1": {
    "target_date": "<scored_at + 7日>",
    "price": null,
    "return_pct": null,
    "spy_return_pct": null,
    "alpha_pct": null,
    "fetched_at": null
  },
  "week2": {
    "target_date": "<scored_at + 14日>",
    "price": null,
    "return_pct": null,
    "spy_return_pct": null,
    "alpha_pct": null,
    "fetched_at": null
  },
  "week3": {
    "target_date": "<scored_at + 21日>",
    "price": null,
    "return_pct": null,
    "spy_return_pct": null,
    "alpha_pct": null,
    "fetched_at": null
  },
  "week4": {
    "target_date": "<scored_at + 28日>",
    "price": null,
    "return_pct": null,
    "spy_return_pct": null,
    "alpha_pct": null,
    "fetched_at": null
  }
}
```

フィールド計算ルール:
- `run_id` = Step 6a と同じ UUID4
- `scored_at` = 今日の日付 (YYYY-MM-DD)
- `rank_in_run` = このrun内でスコア降順の順位 (1=最高)
- `total_scored_in_run` = このrunで評価した銘柄総数
- `price_at_score` = Step 4で取得した `current_price`
- `passed_threshold` = `score >= 7.0`
- `week{N}.target_date` = `scored_at + N×7日` を YYYY-MM-DD 形式で

書き込み後にこのサマリーを表示する:
```
Score snapshot saved:
  run_id: {run_id}
  scored: {N}銘柄 ({passed}件がスコア閾値通過, {rejected}件が閾値未達)
  weekly checkpoints: week1={week1_date}, week2={week2_date}, week3={week3_date}, week4={week4_date}
  → 毎週月曜の fetch_returns.py が各マイルストーンを順次埋めます
```

## Step 7: Report (display to user in Markdown)

Print the full research report in this format:

```markdown
# Research Report — {YYYY-MM-DD}

**マクロレジーム**: {regime} | **run_id**: `{run_id}`

---

## スキャン結果サマリー

| 指標 | 値 |
|---|---|
| スキャン銘柄数 | {N} 銘柄 |
| 候補（スコア ≥ 7.0） | {N} 銘柄 |
| 除外（スコア < 7.0） | {N} 銘柄（score_snapshots.json に記録済み） |
| マクロレジーム | {regime} |

---

## 候補銘柄一覧

| Ticker | スコア | Momentum | Fundmntl | Catalyst | Technical | Sentiment | 推奨 |
|---|---|---|---|---|---|---|---|
| NVDA | **8.2** | 9 | 8 | 9 | 7 | 8 | ✅ BUY候補 |
| ALAB | **7.6** | 8 | 7 | 7 | 8 | 7 | ✅ BUY候補 |

（スコア降順）

---

## 除外銘柄（スコア < 7.0）

| Ticker | スコア | 主な除外理由 |
|--------|-------|------------|
| TSLA   | 6.5   | Catalyst 不足 |
| COIN   | 5.8   | マクロ逆風 |

（全銘柄のスコアは score_snapshots.json に記録済み）

---

## 銘柄詳細

### {TICKER} — {company_name}  スコア: **{score}**

**ワンライナー**: {thesis の1文目}

| 項目 | 値 |
|---|---|
| 現在値 | ${current_price:,.2f} |
| エントリーゾーン | ${entry_zone} |
| 目標値 | ${target_price:,.2f} |
| ストップ | ${stop_loss:,.2f} |
| 期間 | {time_horizon} |
| ATR倍率 | {atr_multiplier_used}× ({atr_multiplier_reason}) |
| 決算まで | {days_until_earnings} 日 |
| アナリスト上値余地 | {analyst_upside_pct:.1f}% |
| RS シグナル | {rs_signal} (1m: {rs_1m:+.1f}%, 3m: {rs_3m:+.1f}%) |

**スコア根拠**:
- Momentum ({score_breakdown.momentum}/10): {score_evidence.momentum}
- Fundamentals ({score_breakdown.fundamentals}/10): {score_evidence.fundamentals}
- Catalyst ({score_breakdown.catalyst}/10): {score_evidence.catalyst}
- Technical ({score_breakdown.technical}/10): {score_evidence.technical}
- Sentiment ({score_breakdown.sentiment}/10): {score_evidence.sentiment}

**カタリスト**: {key_catalysts をカンマ区切り}
**リスク**: {key_risks をカンマ区切り}

---
（以下、全候補繰り返し）

---

> **Next step**: `/decision {run_id}` を実行して投資判断フェーズへ
```

レジーム別の注意書き:
- `HIGH_FEAR` → "⚠️ VIX高水準: 全スコアはMEDIUM上限、ポジションサイズ50%減で計算済み"
- `DOWNTREND` → "⚠️ 下降トレンド: 全候補にmarket headwind適用済み"
- `NORMAL` → 注意書き不要

---

## Step 8: Update watchlist last_score (standard mode only)

After saving `research_history.json`, check if any of the researched tickers appear in `data/watchlist.json` with `status == "active"`.

```bash
cat data/watchlist.json
```

For each match, update:
- `last_score` = score from this run
- `last_research_run_id` = this run's `run_id`

Do **not** change `reference_price` here — that is only reset by `/decision` (Step 6b Rule B) after a human reviews the debate.

Write back the updated `data/watchlist.json` and report:
```
Watchlist score update:
🔄 ALAB — last_score updated: null → 8.1 (run: c9ac08aa)
🔄 MRVL — last_score updated: null → 7.85 (run: c9ac08aa)
```

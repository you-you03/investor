# Seed Mode — /research --seed {TICKER}

**Trigger**: `/research --seed {TICKER}`

Use when Monitor raises `WATCHLIST_BREAKOUT`, `WATCHLIST_SETUP`, `RSI_COOLED`, or `WATCHLIST_EARNINGS` for a ticker.
Skips market scan (Steps 2–3). Delivers deep research on the single ticker within minutes.

---

## Seed Step 1: Load watchlist context

```bash
cat data/watchlist.json
cat data/research_history.json
```

From `watchlist.json`, extract for `{TICKER}`:
- `last_research_run_id`, `last_score`, `reference_price`, `added_at`, `reason`

If `last_research_run_id` is set, find that run in `research_history.json` and extract the previous candidate data for `{TICKER}`.

---

## Seed Step 2: Macro context (required even in seed mode)

```bash
.venv/bin/python scripts/tool.py get_market_context
```

State the current regime. Apply same scoring adjustments as standard mode.

---

## Seed Step 3: Deep research (same as standard Step 4)

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

---

## Seed Step 4: Score (same rubric as standard Step 5)

Use the same 5-axis scoring. Compute weighted total. Note: seed mode always proceeds regardless of score (user already flagged this ticker).

---

## Seed Step 5: Show diff vs previous research

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

---

## Seed Step 6: Save and update watchlist

Save to `data/research_history.json` as a new run (same format as standard Step 6a). Use a new UUID4 as `run_id`.

Then update `data/watchlist.json` for `{TICKER}`:
- Set `last_score` = new score
- Set `last_research_run_id` = new run_id
- Set `reference_price` = current_price (reset reference to today's price)
- **pipeline_status の更新**:
  - スコア ≥ 7.0 → `pipeline_status = "researched"`（/decision 候補として準備完了）
  - スコア < 7.0 → `pipeline_status = "watching"`（条件未達、リセット）

```bash
cat data/watchlist.json
```

Write back the updated file.

Report:
```
✅ Seed research complete:
  TICKER: {TICKER} | score: {score}
  pipeline_status: research_queued → researched  ← (score >= 7.0 の場合)
  → Next: /decision でペルソナディベートへ
```

---

## Seed Step 7: Report

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

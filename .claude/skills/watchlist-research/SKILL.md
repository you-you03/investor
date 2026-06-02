---
description: アクティブなウォッチリスト銘柄を全件深研究し、ESCALATE / MAINTAIN / REMOVE / ADD_NOTE を判断して watchlist.json を更新する
argument-hint: ""
allowed-tools: Bash(.venv/bin/python *) Bash(cat *) Read Write Agent
---

Run deep research on all active watchlist tickers, evaluate each against its original thesis, and update `data/watchlist.json` with the recommended action.

All Bash commands must be run from the `investor/` subdirectory:
```
cd "/Users/yutaobayashi/PERSONAL DEV/1_now/investor"
```

**前提条件**: `data/watchlist.json` に `status: "active"` の銘柄が存在すること。

---

## Step 1: Load watchlist and context

```bash
cat data/watchlist.json
.venv/bin/python scripts/tool.py get_market_context
```

From `watchlist.json`, extract all tickers where `status == "active"`.

State:
- Current macro regime (apply same scoring rules as `/research`)
- Number of active watchlist tickers to process

If no active tickers, output:
```
ウォッチリスト — アクティブ銘柄なし。/watchlist add --ticker X --reason "..." で追加してください。
```
...and stop.

---

## Step 2: Collect run_id + spawn per-ticker research agents

Generate a run_id:

```bash
.venv/bin/python -c "import uuid; print(uuid.uuid4())"
```

Record this value as `{RUN_ID}`.

Then spawn one Agent per active ticker **in parallel** (include all Agent calls in a single response).

- **description**: `"Watchlist research: {TICKER}"`
- **prompt** (fill in `{TICKER}`, `{REASON}`, `{LAST_SCORE}`, `{LAST_MONITOR_FLAG}`, `{REGIME}` per ticker):

---
You are a stock researcher evaluating a watchlist position.
Working directory: `/Users/yutaobayashi/PERSONAL DEV/1_now/investor`

Ticker: **{TICKER}**
Original thesis: "{REASON}"
Last score: {LAST_SCORE} (null = first time)
Last monitor flag: {LAST_MONITOR_FLAG}
Macro regime: {REGIME}

### Step A: Collect data via Bash from working directory:

```bash
.venv/bin/python scripts/tool.py get_stock_snapshot --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
.venv/bin/python scripts/tool.py get_financials --ticker {TICKER}
.venv/bin/python scripts/tool.py get_ticker_details --ticker {TICKER}
.venv/bin/python scripts/tool.py get_relative_strength --ticker {TICKER}
.venv/bin/python scripts/tool.py get_earnings_calendar --ticker {TICKER}
.venv/bin/python scripts/tool.py get_news --ticker {TICKER}
.venv/bin/python scripts/tool.py get_analyst_ratings --ticker {TICKER}
```

### Step B: Score (5-axis, 1–10 each):

| Axis | Weight | Signals |
|---|---|---|
| Momentum | 25% | RSI, MACD, % change, volume vs avg. `STRONG_OUTPERFORM` → +1pt; `STRONG_UNDERPERFORM` → −2pt |
| Fundamentals | 20% | revenue_growth_yoy, earnings_growth_yoy, forward_pe. forward_pe > 50 → "高バリュエーションリスク" |
| Catalyst | 25% | Upcoming events, analyst upside %. days_until_earnings ≤ 14 → +1pt. No catalyst → cap at 6 |
| Technical | 15% | RSI position, MACD crossovers, BB squeeze, EMA20/50 alignment |
| Sentiment | 15% | News tone, analyst_recommendation + count. strong_buy ≥ 10 analysts → 8+ |

Weighted total: `momentum×0.25 + fundamentals×0.20 + catalyst×0.25 + technical×0.15 + sentiment×0.15`

### Step C: Assign action

| Action | Condition |
|---|---|
| `ESCALATE` | score ≥ 7.5 かつ テーゼ継続 かつ エントリーゾーン圏内 |
| `MAINTAIN` | テーゼ継続 かつ エントリー条件未達（RSI過熱、ブレイクアウト待ち等） |
| `ADD_NOTE` | スコア更新のみ、特記事項あり |
| `REMOVE` | テーゼ破綻 / ファンダメンタルズ悪化 / 長期間動意なし |

**RSI_COOLED 特別チェック**: `MAINTAIN` または `ADD_NOTE` 判定後、以下を全て満たす場合 `ESCALATE` に昇格:
1. `last_monitor_flag` が `EXTREME_RSI` または original thesis に "RSI" + "WAIT" の記述がある
2. `last_score` ≥ 7.5
3. 現在の RSI ≤ 65

昇格した場合は reason に「RSI_COOLED: 過熱解消、エントリー条件成立」を追記し、`flag` を `"ESCALATE_TO_DECISION"` にする。

### Return ONLY this JSON (no prose):

```json
{
  "ticker": "{TICKER}",
  "action": "ESCALATE|MAINTAIN|ADD_NOTE|REMOVE",
  "new_score": 0.0,
  "note": "watchlist.json の note フィールドに追記する内容",
  "flag": "ESCALATE_TO_DECISION or null",
  "rsi": 0.0,
  "thesis_intact": "YES|PARTIAL|NO",
  "rationale": "1–2文の判断理由"
}
```
---

Collect all Agent JSON results.

## Step 3: Review results

Display each ticker result in this format:

```
=== {TICKER} ===
スコア: {new_score} (前回: {last_score}) | テーゼ継続: {thesis_intact}
ACTION: {action}
理由: {rationale}
```

No additional analysis needed — the subagents have already evaluated each ticker.

---

## Step 4: Save results

```bash
.venv/bin/python skills/watchlist_research.py --save '{
  "run_id": "{RUN_ID from Step 2}",
  "results": [
    {
      "ticker": "{TICKER}",
      "action": "{ESCALATE|MAINTAIN|ADD_NOTE|REMOVE}",
      "new_score": {score},
      "note": "{note content}",
      "flag": "{ESCALATE_TO_DECISION if ESCALATE, else null}"
    }
  ]
}'
```

The `--save` command updates `data/watchlist.json` for each ticker:
- `ESCALATE` → `last_monitor_flag = "ESCALATE_TO_DECISION"`, status remains `"active"`
- `MAINTAIN` → `last_score` と `last_research_run_id` を更新
- `ADD_NOTE` → `note` を更新、`last_score` を更新
- `REMOVE` → `status = "removed"`, `removed_at = TODAY`

---

## Step 5: Report

Print the full report in this format:

```markdown
# Watchlist Research Report — {YYYY-MM-DD}

**マクロレジーム**: {regime} | **アクティブ銘柄**: {N}件

---

## アクション サマリー

| アクション | 銘柄 |
|---|---|
| 🚀 ESCALATE | {tickers} |
| 👁 MAINTAIN | {tickers} |
| 📝 ADD_NOTE | {tickers} |
| ❌ REMOVE | {tickers} |

---

## ESCALATE 銘柄（/decision 最優先）

### {TICKER} — スコア: {new_score} (前回: {last_score})

**テーゼ**: {original reason from watchlist.json}
**評価**: {3 bullet points}
**判断**: {rationale}

> **Next step**: `/decision` を実行。{TICKER} は priority_8plus 候補として扱われます。

---

## MAINTAIN 銘柄

| Ticker | スコア変化 | 待機理由 | エントリー条件 |
|---|---|---|---|
| {TICKER} | {prev_score} → {new_score} | {reason} | {entry condition} |

---

## REMOVE 銘柄

| Ticker | 除外理由 |
|---|---|
| {TICKER} | {reason} |

---
```

End with:

```
/watchlist-research complete — {N} tickers processed
ESCALATE: {n} | MAINTAIN: {n} | ADD_NOTE: {n} | REMOVE: {n}
```

If any ESCALATE tickers exist:
```
⚠️ MANDATORY NEXT STEP: ESCALATE 銘柄があります。
   /decision を実行してください（{ESCALATED_TICKERS} が最優先候補として自動追加されます）。
```

---
description: 米国株のフルマーケットスキャンを実行し、今日の最有望銘柄を research_history.json に保存する
argument-hint: "[--seed TICKER]"
allowed-tools: Bash(.venv/bin/python *) Bash(cat *) Read Write Agent
---

Run a full market research scan for today's best US stock investment opportunities, then save results to `data/research_history.json`.

All Bash commands must be run from the `investor/` subdirectory:
```
cd "/Users/yutaobayashi/PERSONAL DEV/1_now/investor"
```

---

## Invocation modes

Check the argument **before** proceeding:

| Invocation | Behavior |
|---|---|
| `/research` | **Standard mode** — full market scan. Follow Steps 1–9 below. |
| `/research --seed {TICKER}` | **Seed mode** — fast-track deep research on a single watchlist ticker. See [reference/seed-mode.md](reference/seed-mode.md). |

---

## Step 1: Get macro context (MANDATORY FIRST)

```bash
.venv/bin/python scripts/tool.py get_market_context
```

Classify the regime from the output and apply the gate below **before proceeding**:

### HIGH_FEAR ゲート（ハードストップ）

**`HIGH_FEAR` (VIX > 30) の場合、ここで処理を停止する。**

以下を表示してセッションを終了する:

```
⛔ マクロゲート: BLOCKED

VIX={VIX値} / regime=HIGH_FEAR

新規ポジション非推奨。市場が極度の恐怖状態にあります。
既存ポジションのモニタリングに集中してください。

推奨アクション:
  - /monitor を実行して既存ポジションを確認
  - VIX が 25 以下に低下するまで /research を保留
```

Slack に通知する:
```bash
.venv/bin/python -c "
from investor.notifications.slack import SlackNotifier
SlackNotifier().send_text(':no_entry: /research BLOCKED — VIX高水準(HIGH_FEAR)のため新規リサーチを中止。既存ポジション監視に集中。')
"
```

**Steps 2–9 は実行しない。**

### その他のレジーム

- `DOWNTREND` (SPY < EMA50): 全候補の `risk_factors` に "market headwind" を追加。BUY 推奨の閾値を引き上げる。
- `NORMAL`: 通常の基準で進む。

State the regime before moving on.

---

## Step 2: Get market movers + screeners

```bash
.venv/bin/python scripts/tool.py get_market_movers
.venv/bin/python scripts/tool.py get_market_movers --direction actives
.venv/bin/python scripts/tool.py get_52w_breakouts
.venv/bin/python scripts/tool.py get_earnings_surprises
.venv/bin/python scripts/tool.py get_contrarian_screener
```

Also load `data/watchlist.json` and treat active watchlist tickers as priority candidates.

**逆張り候補の扱い（contrarian_tag=true）:**
- `get_contrarian_screener` の結果に `contrarian_tag: true` が付いた銘柄は、モメンタム候補とは**別スロット**として評価する
- 採用条件: (a) ファンダメンタルズ劣化がない（EPS成長が止まっていない） (b) 明確なカタリストまたはセクターの底打ちシグナルがある (c) 既存ポジションと異なるセクター
- 逆張り候補は最大2枠まで。モメンタム候補を押しのけない
- 候補ゼロなら無視して通常の Step 3 へ進む

---

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

---

## Step 4-5: Deep research + scoring per ticker (parallel subagents)

For **each ticker selected in Step 3**, spawn one Agent. Include **all Agent calls in a single response** to run them in parallel.

- **description**: `"Research + score: {TICKER}"`
- **prompt** (fill in `{TICKER}`, `{PRICE}`, `{REGIME}` per ticker):

---
You are a stock researcher. Working directory: `/Users/yutaobayashi/PERSONAL DEV/1_now/investor`

Research **{TICKER}** (current price ~${PRICE}, macro regime: {REGIME}) and return a single JSON object.

### Data collection — run ALL via Bash from working directory:

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
.venv/bin/python scripts/tool.py get_timeframe_alignment --ticker {TICKER}
```

Check `.env` for `PERPLEXITY_API_KEY` / `XAI_API_KEY`. If present, also run:

```bash
.venv/bin/python scripts/tool.py get_web_search --query "{TICKER} stock analyst catalysts 2026"
.venv/bin/python scripts/tool.py get_x_search --query "{TICKER} stock sentiment"
```

### Scoring (1–10 per axis, data-only — do not fabricate):

| Axis | Weight | Signals |
|---|---|---|
| Momentum | 25% | RSI, MACD, % change, volume vs avg. `STRONG_OUTPERFORM` rs_signal → +1pt; `STRONG_UNDERPERFORM` → −2pt |
| Fundamentals | 20% | revenue_growth_yoy, earnings_growth_yoy, forward_pe. forward_pe > 50 → add "高バリュエーションリスク"; peg_ratio > 3 → add "成長織り込み済みリスク" |
| Catalyst | 25% | Upcoming events, analyst upside %. days_until_earnings ≤ 14 → +1pt + "決算前カタリスト" + "決算ギャップリスク". No catalyst → cap at 6. DOWNTREND/HIGH_FEAR → −1~2pts |
| Technical | 15% | RSI positioning, MACD crossovers, BB squeeze, EMA20/50 alignment. **`tf_warning=true` → −1pt** (上位足逆向きペナルティ) |
| Sentiment | 15% | News tone, analyst_recommendation + count. `strong_buy` ≥ 10 analysts → 8+. Exception: `rs_signal == STRONG_OUTPERFORM` かつ `analyst_upside_pct < 0` → アナリスト目標乖離を減点しない |

**タイムフレーム整合ルール (`get_timeframe_alignment` の出力を使用):**
- `tf_warning: false` → 減点なし。スコアリングへの影響なし
- `tf_warning: true` (日足↑ かつ 週足または月足↓) → Technical スコアに −1pt。`tf_alignment` フィールドに `"WARNING"` を記入
- `alignment == "ALIGNED_DOWN"` → Momentum スコアに −2pt を追加で適用（全タイムフレーム下降）
- `alignment == "ERROR"` または `"unknown"` が含まれる場合 → ペナルティなし。`tf_alignment` フィールドに `"DATA_UNAVAILABLE"` を記入

Weighted total: `momentum×0.25 + fundamentals×0.20 + catalyst×0.25 + technical×0.15 + sentiment×0.15`

ATR target: use `get_atr_targets` as base. Imminent earnings ≤14d + strong fundamentals → 3.0×ATR. No catalyst → 1.5×ATR. Default → 2.0×ATR, stop = entry−1.0×ATR. Clear support closer than 1×ATR → use that as stop_loss.

### Return ONLY this JSON (no prose, no markdown wrapping):

```json
{
  "ticker": "...", "company_name": "...", "score": 0.0, "current_price": 0.00,
  "score_breakdown": {"momentum": 0, "fundamentals": 0, "catalyst": 0, "technical": 0, "sentiment": 0},
  "score_evidence": {"momentum": "...", "fundamentals": "...", "catalyst": "...", "technical": "...", "sentiment": "..."},
  "thesis": "2–3 sentence thesis.",
  "key_catalysts": [], "key_risks": [],
  "entry_zone": "XXX–YYY", "target_price": 0.00, "stop_loss": 0.00,
  "time_horizon": "4–6 weeks",
  "rs_signal": "...", "rs_1m": 0.0, "rs_3m": 0.0,
  "days_until_earnings": 0,
  "atr_multiplier_used": 2.0, "atr_multiplier_reason": "...",
  "analyst_upside_pct": 0.0, "conviction_floor": "MEDIUM",
  "tf_alignment": "ALIGNED_UP",
  "contrarian_tag": false,
  "macro_regime": "{REGIME}", "data_notes": ""
}
```

`tf_alignment` の値: `"ALIGNED_UP"` / `"PARTIAL_UP"` / `"MIXED"` / `"PARTIAL_DOWN"` / `"ALIGNED_DOWN"` / `"WARNING"` / `"DATA_UNAVAILABLE"`
`contrarian_tag`: `get_contrarian_screener` 由来の候補なら `true`、それ以外は `false`
---

Collect all Agent JSON results. **スコアに関わらず全結果を保持する。** Proceed to Step 6a with candidates where `score >= 7.0`; all results go to Step 6b.

---

## Step 6a: Save to research_history.json（スコア ≥ 7.0 のみ）

Generate a UUID4 as `run_id`. Read `data/research_history.json` if it exists (preserve prior runs), then append this run and write back.

Output format for each candidate:
```json
{
  "ticker": "NVDA",
  "company_name": "NVIDIA Corporation",
  "score": 8.2,
  "current_price": 875.00,
  "score_breakdown": {"momentum": 9, "fundamentals": 8, "catalyst": 9, "technical": 7, "sentiment": 8},
  "score_evidence": {
    "momentum": "RSI=71, +8% today on 2.4x avg volume, rs_signal=STRONG_OUTPERFORM",
    "fundamentals": "Revenue +122% YoY, forward_pe=24, peg_ratio=1.8",
    "catalyst": "GTC conference in 2 weeks, analyst upside +34%, 56 strong_buy analysts",
    "technical": "Above EMA20/EMA50, MACD bullish crossover, BB squeeze",
    "sentiment": "Analyst consensus strong_buy (56 analysts), X posts 80% bullish",
    "conviction_floor_reason": "Revenue +122% YoY → MEDIUM floor applied"
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
  "atr_multiplier_reason": "デフォルト2×ATR採用",
  "analyst_upside_pct": 34.2,
  "conviction_floor": "MEDIUM",
  "macro_regime": "NORMAL",
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

---

## Step 6b: Save ALL scored tickers to score_snapshots.json（検証用）

Read `data/score_snapshots.json` (if not exists, start with `{"snapshots": []}`).

**スコアに関わらず全銘柄**（スコア < 7.0 含む）を追記する。各エントリーのフォーマット:

```json
{
  "run_id": "<same uuid4 as Step 6a>",
  "scored_at": "<YYYY-MM-DD>",
  "ticker": "NVDA",
  "score": 8.2,
  "score_breakdown": {"momentum": 9, "fundamentals": 8, "catalyst": 9, "technical": 7, "sentiment": 8},
  "rank_in_run": 1,
  "total_scored_in_run": 18,
  "price_at_score": 880.00,
  "passed_threshold": true,
  "macro_regime": "NORMAL",
  "week1": {"target_date": "<+7日>", "price": null, "return_pct": null, "spy_return_pct": null, "alpha_pct": null, "fetched_at": null},
  "week2": {"target_date": "<+14日>", "price": null, "return_pct": null, "spy_return_pct": null, "alpha_pct": null, "fetched_at": null},
  "week3": {"target_date": "<+21日>", "price": null, "return_pct": null, "spy_return_pct": null, "alpha_pct": null, "fetched_at": null},
  "week4": {"target_date": "<+28日>", "price": null, "return_pct": null, "spy_return_pct": null, "alpha_pct": null, "fetched_at": null}
}
```

書き込み後にこのサマリーを表示する:
```
Score snapshot saved:
  run_id: {run_id}
  scored: {N}銘柄 ({passed}件が閾値通過, {rejected}件が閾値未達)
  weekly checkpoints: week1={week1_date}, week2={week2_date}, week3={week3_date}, week4={week4_date}
```

---

## Step 7: Report (display to user in Markdown)

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

（スコア降順）

---

## 除外銘柄（スコア < 7.0）

| Ticker | スコア | 主な除外理由 |
|--------|-------|------------|
| TSLA   | 6.5   | Catalyst 不足 |

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

また、ウォッチリストに存在する銘柄の `pipeline_status` を以下のルールで更新する:

| 現在の pipeline_status | スコア結果 | 更新後 |
|---|---|---|
| `research_queued` | ≥ 7.0 | `researched` |
| `research_queued` | < 7.0 | `watching`（条件未達、リセット） |
| `watching` | ≥ 7.0 | `researched` |
| その他 | - | 変更しない |

Write back the updated `data/watchlist.json` and report:
```
Watchlist score update:
🔄 ALAB — last_score updated: null → 8.1 (run: c9ac08aa) | pipeline_status: research_queued → researched
⬅️ SOME — score 6.5 < 7.0, pipeline_status: research_queued → watching
```

---

## Step 8b: Auto-add promising tickers to watchlist (standard mode only)

After updating existing watchlist entries (Step 8), check all scored tickers from this run for **auto-add candidates**.

### 対象条件（すべて満たす銘柄のみ）:

1. **スコア 5.5〜6.9** — Decision 閾値未満だが有望
2. **ウォッチリスト未登録** — `watchlist.json` の `items` に同一 ticker が存在しない（`status` に関わらず）
3. **既にポートフォリオに存在しない** — `portfolio.csv` の open ポジションに含まれない

### 追加フォーマット:

各対象銘柄を `watchlist.json` の `items` 配列に以下の形式で追加する:

```json
{
  "ticker": "SOME",
  "added_at": "<YYYY-MM-DD>",
  "source": "research_auto",
  "last_research_run_id": "<this run's run_id>",
  "last_score": 6.2,
  "reference_price": <current_price from scored result>,
  "reason": "スコア{score}（{date}）。{thesis の1文目}。主要カタリスト: {key_catalysts[0]}。エントリーゾーン {entry_zone}、目標 ${target_price}。",
  "status": "active",
  "last_monitor_flag": null,
  "last_monitor_date": null,
  "consecutive_drops": 0,
  "pipeline_status": "watching"
}
```

### 上限:

1回のリサーチで自動追加する銘柄は **最大5件**。スコア降順で上位5件を選ぶ。

### レポート:

```
Watchlist auto-add (score 5.5–6.9):
➕ SOME — score 6.2, added as watching (reason: {thesis 1文目の冒頭30文字}...)
➕ OTHER — score 5.8, added as watching (reason: ...)
⏭️ SKIP — score 6.0, already in watchlist (status: active)
⏭️ SKIP2 — score 5.5, already in portfolio (open)
```

自動追加がゼロ件の場合:
```
Watchlist auto-add: 対象なし（スコア 5.5–6.9 の新規銘柄なし）
```

---

## Step 9: Decision強制トリガー（standard mode only）

After saving watchlist updates (Step 8), check portfolio slots:

```bash
cat data/portfolio.csv
```

Count rows where `status == "open"`. Call this `open_count`.

**空きスロットがある場合（open_count < 5）:**

```
⚠️ MANDATORY NEXT STEP
────────────────────────────────────────────────────────────────
ポジション: {open_count}/5（空き {5 - open_count}枠）
候補銘柄: {スコア ≥ 7.0 の銘柄数}件

空きスロットがある状態でリサーチを完了しました。
必ず次のコマンドを実行してください:

  /decision {run_id}

候補が出ているのに Decision を実行しないことは運用漏れです。
────────────────────────────────────────────────────────────────
```

**ポジション満杯の場合（open_count == 5）:**

```
✅ ポジション満杯（5/5）— Decision 不要。既存ポジションのモニタリングに集中してください。
```

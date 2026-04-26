Run daily monitoring for all open positions, display a Markdown report, then send to Slack.

All Bash commands must be run from the `investor/` subdirectory:
```
cd "/Users/yutaobayashi/PERSONAL DEV/investor"
```

---

## Step 1: Load open positions

```bash
cat data/portfolio.csv
```

Extract all rows where `status == "open"` **and `shares > 0`**.
Zero-share entries are treated as closed — skip them silently.

If no open positions, output:

```markdown
# Monitor Report — {TODAY}

**ポジションなし** — 監視対象なし
```

...and stop here (skip Slack send).

---

## Step 2: Fetch snapshots per ticker

For each open position ticker, run in sequence:

```bash
.venv/bin/python scripts/tool.py get_stock_snapshot --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
```

---

## Step 3: Calculate metrics and check alert conditions

For each position compute:

| 計算値 | 算式 |
|---|---|
| `pnl` | `(current_price - entry_price) × shares` |
| `pnl_pct` | `(current_price - entry_price) / entry_price × 100` |
| `pct_to_target` | `(current_price - entry_price) / (target_price - entry_price) × 100` |
| `target_distance_pct` | `(target_price - current_price) / current_price × 100` |
| `stop_distance_pct` | `(current_price - stop_loss) / current_price × 100` |

Alert conditions (rule-based, no LLM needed):

| 条件 | Severity | 判定 |
|---|---|---|
| `current_price <= stop_loss` | **HIGH** | STOP_BREACH |
| `current_price >= target_price` | **HIGH** | TARGET_HIT |
| `current_price <= stop_loss × 1.03` | MEDIUM | NEAR_STOP |
| `current_price >= target_price × 0.97` | MEDIUM | NEAR_TARGET |
| `pnl_pct <= -5%` | MEDIUM | DOWN_5PCT |
| `pnl_pct >= +15%` | INFO | UP_15PCT |

---

## Step 3b: Watchlist monitoring

Load `data/watchlist.json`. For each item where `status == "active"`:

```bash
.venv/bin/python scripts/tool.py get_stock_snapshot --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
```

Also run for earnings proximity check:
```bash
.venv/bin/python scripts/tool.py get_earnings_calendar --ticker {TICKER}
```

For each watchlist ticker, check the following alert conditions:

| 条件 | フラグ | 意味 |
|---|---|---|
| 当日変化率 ≥ +5% かつ volume_vs_avg ≥ 1.5x | `WATCHLIST_BREAKOUT` | ブレイクアウト候補 → リサーチ推奨 |
| RSI 40〜60 かつ MACD bullish crossover | `WATCHLIST_SETUP` | テクニカルセットアップ → リサーチ推奨 |
| days_until_earnings ≤ 14 | `WATCHLIST_EARNINGS` | 決算接近 → リサーチ推奨 |
| `reference_price` が存在し、現在値が +15% 以上 | `WATCHLIST_MOVED` | 大幅上昇（乗り遅れリスク確認） |
| `reference_price` が存在し、現在値が -10% 以下 | `WATCHLIST_DROPPED` | 大幅下落（ウォッチリスト除外検討） |

`reference_price` が null の場合、WATCHLIST_MOVED / WATCHLIST_DROPPED はスキップ。

リサーチ推奨フラグ: `WATCHLIST_BREAKOUT`, `WATCHLIST_SETUP`, `WATCHLIST_EARNINGS` のいずれかが立った銘柄には `/research --seed {TICKER}` を推奨。

---

## Step 4: Output Markdown report (display to user)

Print the full report in this format:

```markdown
# Monitor Report — {YYYY-MM-DD}

## サマリー

| 指標 | 値 |
|---|---|
| オープンポジション | {N} 銘柄 |
| 合計未実現損益 | {+/-}${total_pnl:,.0f} |
| 🔴 HIGH アラート | {N} 件 |
| 🟡 MEDIUM アラート | {N} 件 |
| ウォッチリスト銘柄 | {N} 銘柄 |
| 🔬 リサーチ推奨 | {N} 銘柄（フラグあり） |

---

## ポジション詳細（Section A）

### {TICKER} — {company_name}

| 項目 | 値 |
|---|---|
| 現在値 | ${current_price:,.2f} |
| 買値 | ${entry_price:,.2f} |
| 目標値 | ${target_price:,.2f} |
| ストップ | ${stop_loss:,.2f} |
| 保有株数 | {shares} 株 |
| 未実現損益 | **{+/-}${pnl:,.0f} ({+/-}{pnl_pct:.1f}%)** |
| 目標まで | {target_distance_pct:.1f}% 残 |
| ストップまで | {stop_distance_pct:.1f}% 残 |

**進捗** `ストップ {bar} 目標` _{pct_to_target:.0f}% 達成_
（bar = "█" × (pct_to_target / 10 を切り捨て), "░" × 残り、合計10マス）

**テクニカル**: RSI {rsi} | MACD {macd_signal} | EMA20/50 {ema_signal}

> {alert_emoji} **{severity}**: {alert_message}
（アラートがない場合は "> ✅ アラートなし"）

---
（以下、全ポジション繰り返し）

## アラート一覧

| Ticker | Severity | 種別 | 詳細 |
|---|---|---|---|
| {TICKER} | 🔴 HIGH | STOP_BREACH | ストップ ${stop_loss} を割り込み（現値 ${current_price}） |
| {TICKER} | 🟡 MEDIUM | NEAR_STOP | ストップまで {stop_distance_pct:.1f}% |

（HIGH アラートが 0 件なら "✅ 重大アラートなし" と表示）

---

## ウォッチリスト監視（Section B）

| Ticker | 参照値 | 現在値 | 本日 | 参照比 | フラグ |
|--------|-------|-------|-----|--------|-------|
| {TICKER} | ${reference_price or "—"} | ${current_price} | {day_change_pct} | {ref_change_pct or "—"} | {flags or "—"} |

（フラグが立っていない銘柄は "—" 表示。参照値がない銘柄は参照比も "—"）

### リサーチ推奨
（WATCHLIST_BREAKOUT / WATCHLIST_SETUP / WATCHLIST_EARNINGS のいずれかを持つ銘柄を列挙）
- **{TICKER}**: {flag}（{trigger_detail}）
  → `/research --seed {TICKER}` で優先リサーチを実行

（推奨なしの場合は "ウォッチリスト — 特記事項なし" と表示）
```

Alert severity emojis:
- HIGH → 🔴
- MEDIUM → 🟡
- INFO → 🔵
- なし → ✅

---

## Step 4b: Write watchlist flag updates

After computing all watchlist flags (Step 3b), read `data/watchlist.json` and apply the following updates. Then write the file back.

```bash
cat data/watchlist.json
```

### Rule 1 — WATCHLIST_DROPPED → increment consecutive_drops

For each ticker that triggered `WATCHLIST_DROPPED`:
- Increment `consecutive_drops` by 1 (default 0 if field absent)
- Update `last_monitor_flag` to `"WATCHLIST_DROPPED"`
- Update `last_monitor_date` to today's date

If `consecutive_drops` reaches **2 or more**, add a note to the output:
```
⚠️ {TICKER} — WATCHLIST_DROPPED 2回連続。ウォッチリスト除外を検討してください。
```

### Rule 2 — Any other flag → reset consecutive_drops

For each ticker that triggered any flag OTHER than `WATCHLIST_DROPPED` (or no flag):
- Set `consecutive_drops` to 0
- Update `last_monitor_flag` to the flag name (or `null` if no flag)
- Update `last_monitor_date` to today's date

### Rule 3 — WATCHLIST_MOVED (未リサーチ) → note in reason

For each ticker with `WATCHLIST_MOVED` flag AND `last_score == null`:
- Append to `reason`: `【{TODAY} WATCHLIST_MOVED】参照比{ref_chg:+.1f}%（${reference_price}→${current_price}）。未リサーチ。/research --seed 検討。`
- Only append if this exact date's note is not already in `reason` (avoid duplicates on re-run)

### watchlist.json schema additions

These fields are added automatically by monitor. Do not require them to pre-exist:
```json
{
  "consecutive_drops": 0,
  "last_monitor_flag": "WATCHLIST_DROPPED",
  "last_monitor_date": "2026-04-11"
}
```

### Report changes

```
Watchlist flag sync (2026-04-11):
🔻 PLTR — WATCHLIST_DROPPED 1回目 (consecutive_drops: 1)
📈 AVGO — WATCHLIST_MOVED, reason 更新
📈 LRCX — WATCHLIST_MOVED, reason 更新
✅ ALAB — WATCHLIST_BREAKOUT, consecutive_drops リセット
— MU / NVDA / TSM ... — フラグなし, consecutive_drops リセット
```

---

## Step 5: Send to Slack

```bash
.venv/bin/python scripts/run_monitor.py
```

Slackへの送信完了後、最終行に以下を出力：

```
/monitor complete — {N} position(s) | Alerts: {high} HIGH / {medium} MEDIUM | Watchlist: {wl_count} tickers / {research_count} research recommended | Slack: sent
```

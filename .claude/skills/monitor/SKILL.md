---
description: オープンポジションとウォッチリスト銘柄を日次監視し、アラートを検知して Slack に送信する
argument-hint: ""
allowed-tools: Bash(.venv/bin/python *) Bash(cat *) Read Write Agent
---

Run daily monitoring for all open positions, display a Markdown report, then send to Slack.

All Bash commands must be run from the `investor/` subdirectory:
```
cd "/Users/yutaobayashi/PERSONAL DEV/1_now/investor"
```

---

## Step 0: マクロレジーム判定

```bash
.venv/bin/python scripts/tool.py get_market_context
```

取得した VIX 値で当日レジームを判定し、レポート冒頭に表示する:

| VIX | レジーム | 対応 |
|---|---|---|
| < 18 | **リスクオン** 🟢 | フルサイズ運用 |
| 18〜25 | **中立** 🟡 | 新規エントリーはサイズ×0.7 |
| ≥ 25 | **リスクオフ** 🔴 | 既存ポジション縮小を検討 |

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
| `pnl_pct >= +5%` かつ `exit_stage` が null または 0 | **HIGH** | STAGE1_HIT |
| `pnl_pct >= +15%` かつ `exit_stage == 1` | **HIGH** | STAGE2_HIT |
| `trailing_stop_price` が存在し `current_price <= trailing_stop_price` | **HIGH** | TRAILING_STOP_HIT |
| `current_price <= stop_loss × 1.03` | MEDIUM | NEAR_STOP |
| `pnl_pct >= +12%` かつ `exit_stage == 1` | MEDIUM | NEAR_STAGE2 |
| `pnl_pct <= -5%` | MEDIUM | DOWN_5PCT |
| `pnl_pct >= +25%` かつ `exit_stage == 2` | INFO | UP_25PCT_TRAILING |

注: `target_price` は参考値として保持するが、アラート判定には使用しない。

### STAGE1_HIT 処理ルール（第1段階 — 25%利確）

`STAGE1_HIT` を検出した場合（**確認不要、自動実行**）:

- 保有株数の25%を売却（端数切り捨て）
- `stop_loss` を `entry_price` に更新（リスクゼロ化）
- `exit_stage` = 1 を portfolio.csv に書き込む
- `note` に `【{TODAY} STAGE1】$${current_price}で25%利確。ストップ→買値$${entry_price}` を追記

レポート出力:
```
📈 STAGE1_HIT（第1段階利確）
  → {floor(shares×0.25)} 株を $${current_price} で売却し25%利確。
  → ストップを買値 $${entry_price} に移動（リスクゼロ化）。残り {shares - floor(shares×0.25)} 株。
```

### STAGE2_HIT 処理ルール（第2段階 — 追加25%利確 → トレーリング移行）

`STAGE2_HIT` を検出した場合（**確認不要、自動実行**）:

- 保有株数のうち初期の25%分（= 残り株数の1/3相当）を売却（累計50%利確）
- ATR × 1.0 のトレーリングストップを開始
- `exit_stage` = 2、`trailing_stop_price` = current_price − 1.0×ATR、`high_water_mark` = current_price を書き込む
- `note` に `【{TODAY} STAGE2】$${current_price}で追加25%利確。ATR×1.0トレーリング開始: $${trailing_stop_price}` を追記

レポート出力:
```
🎯 STAGE2_HIT（第2段階利確 → トレーリング移行）
  → 追加 {exit_shares} 株を $${current_price} で売却（累計50%利確完了）。
  → 残り {remaining_shares} 株はトレーリングストップ $${trailing_stop_price} で継続保有。
```

**TRAILING_STOP_HIT**（`exit_stage == 2` または `partial_exit_pct == 50` のポジション）:
- 残り全株を売却。`note` に `【{TODAY} TRAILING_STOP】$${current_price}でフルエグジット` を追記。

---

## Step 3c: Trailing stop high_water_mark 更新

`exit_stage == 2` **または** `partial_exit_pct == 50` のポジション（トレーリングストップ中）に対して:

1. `get_technical_indicators --ticker {TICKER}` で ATR を取得（Step 2 で取得済みであれば再利用）
2. 以下を計算:
   - `new_high_water_mark` = max(`high_water_mark`, `current_price`)
   - `new_trailing_stop_price` = `new_high_water_mark` − 1.0 × ATR
3. `new_trailing_stop_price` が前日より上昇した場合のみ portfolio.csv を更新:
   - `high_water_mark` ← `new_high_water_mark`
   - `trailing_stop_price` ← `new_trailing_stop_price`
   - `note` に `【{TODAY} TRAILING_UPDATED】HWM $X → TS $Y` を追記

レポートに表示（トレーリングストップ中ポジションのみ）:
```
🔄 TRAILING: HWM $${high_water_mark} | TS $${trailing_stop_price} | 現値 $${current_price}（TS まで {gap:.1f}%）
```

---

## Step 3d: MAE/MFE 日次更新

各オープンポジションについて、pnl_pct 計算後（Step 3 の直後）:

- `mae_pct` = min(既存の `mae_pct` または 0, 当日の `pnl_pct`)
- `mfe_pct` = max(既存の `mfe_pct` または 0, 当日の `pnl_pct`)
- 前日値から変化があった場合のみ portfolio.csv に書き込む（毎日書かない）

---

## Step 3e: テーゼ不発チェック

Step 3d で MAE/MFE を更新した後、**エントリー初期**のポジションを対象に「テーゼが機能しているか」を判定する。

### 判定条件（すべて満たす場合）

1. **エントリーから3営業日以内**（entry_date から今日まで、土日を除いた平日が3日以下）
2. **mfe_pct < +0.5%**（エントリー以降、一度もプラス0.5%を超えていない）

### 処理

条件を満たした場合:

- `note` に以下を追記（portfolio.csv に書き込む）:
  ```
  【{TODAY} テーゼ不発】{N}営業日経過でMFE={mfe_pct:+.2f}%。テーゼが市場に認識されていない可能性。次のバウンスで出口機会を検討。
  ```
- レポートに警告表示（Step 4 参照）

**⚠️ やってはいけないこと**: ストップロスを機械的に引き上げない。エントリー直後のノイズで退場するリスクがあるため、ハードストップは現行値を維持する。テーゼ不発フラグはあくまで「バウンス時の出口を意識する」ソフトシグナルとして扱う。

### 解除

同じポジションで `mfe_pct` が +0.5% を超えた時点で、このフラグは自動的に無効（条件2を満たさなくなる）。note の追記は残すが、以後のレポートでは警告を出さない。

---

## Step 3b: Watchlist monitoring (subagent delegation)

Delegate all watchlist monitoring to a single Agent call.

- **description**: `"Monitor watchlist"`
- **prompt**:

---
You are monitoring a stock watchlist.
Working directory: `/Users/yutaobayashi/PERSONAL DEV/1_now/investor`

Watchlist data (active tickers only):
```
{PASTE_ACTIVE_WATCHLIST_JSON_HERE}
```

For each active ticker, run these Bash commands:

```bash
.venv/bin/python scripts/tool.py get_stock_snapshot --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
.venv/bin/python scripts/tool.py get_earnings_calendar --ticker {TICKER}
```

Evaluate these flag conditions for each ticker:

| Flag | Condition |
|---|---|
| `WATCHLIST_BREAKOUT` | 当日変化率 ≥ +5% かつ volume_vs_avg ≥ 1.5x |
| `WATCHLIST_SETUP` | RSI 40〜60 かつ MACD bullish crossover |
| `WATCHLIST_EARNINGS` | days_until_earnings ≤ 14 |
| `WATCHLIST_MOVED` | reference_price が存在し、現在値 +15% 以上 |
| `WATCHLIST_DROPPED` | reference_price が存在し、現在値 −10% 以下 |
| `RSI_COOLED` | 下記条件を全て満たす場合 |

**RSI_COOLED 判定**: 以下を全て満たす場合のみ発動:
1. `last_monitor_flag` が `EXTREME_RSI` または `reason` 欄に "RSI" + "WAIT" / "押し目待ち" / "rsi_wait_entry" の記述がある
2. `last_score` ≥ 7.5
3. 現在の RSI ≤ 65
4. `status == "active"`

Return ONLY this JSON (no prose):

```json
[
  {
    "ticker": "...",
    "current_price": 0.00,
    "day_change_pct": 0.0,
    "ref_change_pct": null,
    "rsi": 0.0,
    "flags": ["FLAG1", "FLAG2"],
    "research_recommended": true,
    "escalate_recommended": false
  }
]
```
---

Use the Agent result to:
1. Populate the watchlist section of the Markdown report (Step 4)
2. Update `data/watchlist.json` flags (Step 4b)

The watchlist JSON to pass to the Agent is the `active` entries from `data/watchlist.json` loaded in Step 1. Pass only the fields: `ticker`, `reason`, `last_score`, `last_monitor_flag`, `reference_price`, `status`.

---

## Step 4: Output Markdown report (display to user)

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
| ⚠️ テーゼ不発 | {N} 銘柄（エントリー3営業日以内 / MFE<+0.5%） |

---

## ポジション詳細（Section A）

### {TICKER} — {company_name}

| 項目 | 値 |
|---|---|
| 現在値 | ${current_price:,.2f} |
| 買値 | ${entry_price:,.2f} |
| 保有株数 | {shares} 株 |
| 未実現損益 | **{+/-}${pnl:,.0f} ({+/-}{pnl_pct:.1f}%)** |
| 出口ステージ | Stage {exit_stage or 0} / 2 |
| 目標（参考） | ${target_price:,.2f} |
| ストップまで | {stop_distance_pct:.1f}% 残 |
| MAE（最大不利） | {mae_pct:+.1f}% |
| MFE（最大有利） | {mfe_pct:+.1f}% |
| トレーリングストップ | ${trailing_stop_price} （exit_stage == 2 の場合のみ） |

**進捗** `ストップ {bar} 目標` _{pct_to_target:.0f}% 達成_

**テクニカル**: RSI {rsi} | MACD {macd_signal} | EMA20/50 {ema_signal}

> {alert_emoji} **{severity}**: {alert_message}

（テーゼ不発フラグがある場合のみ表示）
> ⚠️ **テーゼ不発**: エントリー{N}営業日経過、MFE {mfe_pct:+.2f}% — テーゼが機能していない可能性。次のバウンスで出口機会を検討（ストップは現行値 ${stop_loss} を維持）。

---

## アラート一覧

| Ticker | Severity | 種別 | 詳細 |
|---|---|---|---|
| {TICKER} | 🔴 HIGH | STOP_BREACH | ストップ ${stop_loss} を割り込み（現値 ${current_price}） |

（HIGH アラートが 0 件なら "✅ 重大アラートなし" と表示）

---

## ウォッチリスト監視（Section B）

| Ticker | 参照値 | 現在値 | 本日 | 参照比 | フラグ |
|--------|-------|-------|-----|--------|-------|
| {TICKER} | ${reference_price or "—"} | ${current_price} | {day_change_pct} | {ref_change_pct or "—"} | {flags or "—"} |

### リサーチ推奨
- **{TICKER}**: {flag}（{trigger_detail}）
  → `/research --seed {TICKER}` で優先リサーチを実行
```

Alert severity emojis: HIGH → 🔴 | MEDIUM → 🟡 | INFO → 🔵 | なし → ✅

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

If `consecutive_drops` reaches **2 or more**, add a note:
```
⚠️ {TICKER} — WATCHLIST_DROPPED 2回連続。ウォッチリスト除外を検討してください。
```

### Rule 2 — Any other flag → reset consecutive_drops

For each ticker that triggered any flag OTHER than `WATCHLIST_DROPPED` (or no flag):
- Set `consecutive_drops` to 0
- Update `last_monitor_flag` to the flag name (or `null` if no flag)
- Update `last_monitor_date` to today's date

### Rule 2b — RSI_COOLED → ESCALATE_TO_DECISION に昇格

`RSI_COOLED` フラグが立った銘柄:
- `last_monitor_flag` を `"ESCALATE_TO_DECISION"` に更新
- `reason` 欄に `【{TODAY} RSI_COOLED】RSI={現RSI値} < 65 に冷却。last_score={last_score}。エントリー条件成立。/decision 最優先候補。` を追記

### Rule 3 — WATCHLIST_MOVED (未リサーチ) → note in reason

For each ticker with `WATCHLIST_MOVED` flag AND `last_score == null`:
- Append to `reason`: `【{TODAY} WATCHLIST_MOVED】参照比{ref_chg:+.1f}%。未リサーチ。/research --seed 検討。`

Report changes:
```
Watchlist flag sync (2026-05-10):
🔻 PLTR — WATCHLIST_DROPPED 1回目 (consecutive_drops: 1)
📈 AVGO — WATCHLIST_MOVED, reason 更新
✅ ALAB — WATCHLIST_BREAKOUT, consecutive_drops リセット
```

---

## Step 4c: pipeline_status 更新（ステートマシン）

Step 3b・4b のフラグ判定結果を受けて、`pipeline_status` を更新する。

### 更新ルール

| フラグ / 状況 | pipeline_status の変更 |
|---|---|
| `WATCHLIST_BREAKOUT` or `RSI_COOLED` | `watching → research_queued` |
| `ESCALATE_TO_DECISION` | `* → decision_queued` |
| `IN_PORTFOLIO` フラグ（ポートフォリオ入り確認） | `* → promoted` |
| `REMOVED` or `WATCHLIST_DROPPED` 2回連続 | `* → exited` |
| フラグなし（変化なし） | 変更しない |

**重要**: すでに `promoted` / `exited` の銘柄は上書きしない（terminal state）。

watchlist.json 書き込み時に同時に反映する。

### Step 4c: ペンディングアクション一覧（必ず表示）

watchlist.json 更新後、以下のサマリーをレポートに追記する:

```
## 📋 PENDING ACTIONS

| Ticker | pipeline_status | 推奨アクション |
|---|---|---|
| LRCX | research_queued | `/research --seed LRCX` を実行 |
| AMD  | decision_queued | 次回 `/decision` で優先議論 |
```

`pipeline_status` が `research_queued` または `decision_queued` の銘柄のみ表示。
対象なければ: `✅ ペンディングアクションなし`

---

## Step 5: Send to Slack

```bash
.venv/bin/python scripts/run_monitor.py
```

Slackへの送信完了後、最終行に以下を出力：

```
/monitor complete — {N} position(s) | Alerts: {high} HIGH / {medium} MEDIUM | Watchlist: {wl_count} tickers / {research_count} research recommended | Slack: sent
```

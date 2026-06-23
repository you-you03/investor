# Exit Decision Mode

**Trigger**: `/decision --mode exit --ticker {TICKER}`

Invoked when Monitor raises `TARGET_HIT` or `UP_30PCT` for a portfolio position, or when the user decides manually.
Skip the standard pipeline (Steps 0–10). Follow only the steps below.

---

## Exit Step 1: Load position and current data

```bash
cat data/portfolio.csv
```

Extract the row for `{TICKER}` where `status == "open"`. Record:
- `entry_price`, `target_price`, `stop_loss`, `shares`, `entry_date`
- `partial_exit_pct`（null または 0 = まだパーシャルエグジット未実施）
- `trailing_stop_price`（null = トレーリングストップ未設定）
- `high_water_mark`（null = 追跡なし）

**ポジション状態の確認**:
- `partial_exit_pct == 50` の場合 → このポジションはすでに50%利確済み・トレーリングストップ中。Exit Step 3 でペルソナに「残り50%を今売るか、トレーリングを継続するか」を問う。

```bash
.venv/bin/python scripts/tool.py get_stock_snapshot --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
.venv/bin/python scripts/tool.py get_market_context
```

Also load `data/research_history.json` and find the most recent run that contains `{TICKER}` as a candidate. Extract:
- `last_score`, `thesis`, `key_catalysts`, `key_risks`, `time_horizon`

Summarize the situation before starting the debate:

```
Exit Decision — {TICKER} ({company_name})
Entry: ${entry_price} on {entry_date} | Shares: {shares}
Current: ${current_price} | P&L: {+/-}${pnl} ({+/-}{pnl_pct:.1f}%)
Target: ${target_price} ({target_distance:+.1f}% from current)
Stop: ${stop_loss} ({stop_distance:+.1f}% from current)
Trigger: {monitor_alert, e.g. TARGET_HIT / UP_30PCT / manual}
Macro: {regime}
Original thesis: {thesis}
```

---

## Exit Step 2: Load persona definitions

Read `investor/investor/prompts/personas.py`. All 5 personas are convened for exit decisions (no sector routing — every persona is relevant to exits).

---

## Exit Step 3: Round 1 — Independent exit stance (all 5 personas)

Each persona evaluates the **exit question**: "Should we sell now, hold, or partially exit?"

Each persona uses their exit framework:

| ペルソナ | 出口判断の軸 |
|---|---|
| The Oracle | 現在値が内在価値（DCF）を大幅に上回っていないか。FCF yield vs 現在値 |
| The Innovator | 5年テーゼが変わっていないか。残っているカタリストはあるか |
| The Tape Reader | RSI・出来高・MACD でトレンド継続か。出来高が落ちてきたら撤退 |
| The Tenbagger | ストーリーが変わっていないか。PEG が過熱域（> 3）に入ったか |
| The Macro Mind | マクロ環境が引き続き追い風か。リスクオフ局面なら縮小推奨 |

Output format per persona:

```
=== [PERSONA NAME] — Exit Stance ===

RECOMMENDATION: [SELL / PARTIAL_SELL / HOLD]
CONVICTION: [HIGH / MEDIUM / LOW]

REASONING:
• [Data point] → [Exit framework interpretation]
• [Data point] → [Exit framework interpretation]
• [Data point] → [Exit framework interpretation]
```

---

## Exit Step 4: Round 2 — Cross-fire (same pairs as standard decision)

Run adversary pairs where stances differ. Format is identical to standard Round 2.
Focus debate on: "Is the original thesis still intact at this price level?"

---

## Exit Step 5: PM Exit Synthesis

The Portfolio Manager synthesizes all 5 stances and outputs one of four actions:

| アクション | 条件の目安 |
|---|---|
| `FULL_EXIT` | 多数(3+)が SELL / RSI 過熱 / マクロ逆風 / **テーゼ破綻**（テーゼが壊れた場合のみ）|
| `PARTIAL_EXIT` | 意見が割れる / トレンド継続だがリスク高め |
| `RAISE_TARGET` | 多数が HOLD / カタリスト残存 / テーゼ変わらず |
| `HOLD` | 全員 HOLD / 現状維持が最善 |

**TARGET_HIT トリガーの優先ルール**:
トリガーが `TARGET_HIT` の場合、**テーゼが継続中かどうかを最初に判定する**。
- テーゼ継続中（元の上昇thesis に変化なし、カタリスト残存）→ `PARTIAL_EXIT` または `RAISE_TARGET` を優先。`FULL_EXIT` は原則禁止。
- テーゼ破綻（元の上昇根拠が消えた、競合逆風、決算ミス等）→ `FULL_EXIT` を選択可。
- デフォルト行動として TARGET_HIT = フルイグジットにしないこと。初期ターゲットは最低ラインであり、モメンタムが続いている限り継続保有が期待値上有利。

For `PARTIAL_EXIT`: specify `exit_shares` (how many to sell) and `remaining_shares`.
- portfolio.csv に `partial_exit_pct = 50`、`trailing_stop_price = current_price - 0.5×ATR`、`high_water_mark = current_price` を書き込む。
- monitor.md Step 3c が毎日 `high_water_mark` と `trailing_stop_price` を更新して追跡する。

For `RAISE_TARGET`: specify `new_target_price` and `new_trailing_stop_pct`.
- `new_trailing_stop_pct` は `trailing_stop_price = current_price × (1 - new_trailing_stop_pct/100)` に変換し portfolio.csv に書き込む。

Output JSON:

```json
{
  "ticker": "{TICKER}",
  "mode": "exit",
  "action": "PARTIAL_EXIT",
  "conviction": "MEDIUM",
  "exit_shares": 10,
  "remaining_shares": 9,
  "new_target_price": 165.00,
  "new_trailing_stop_pct": 8,
  "rationale": "3–4文。どのペルソナの論点が決定打になったか。なぜこのアクションか。",
  "debate_summary": {
    "stances": {
      "oracle": "PARTIAL_SELL/MEDIUM",
      "innovator": "HOLD/HIGH",
      "tape_reader": "SELL/HIGH",
      "tenbagger": "HOLD/MEDIUM",
      "macro_mind": "PARTIAL_SELL/MEDIUM"
    },
    "final_alignment": "2 SELL / 2 HOLD / 1 PARTIAL_SELL"
  }
}
```

---

## Exit Step 6: Save and report

Write the exit report to `reports/decision/exit_{YYYY-MM-DD}_{TICKER}.md`:

```markdown
# Exit Decision — {TICKER} — {YYYY-MM-DD}

## 状況
| 項目 | 値 |
|---|---|
| 現在値 | ${current_price} |
| 買値 | ${entry_price}（{entry_date}） |
| 未実現損益 | {+/-}${pnl}（{+/-}{pnl_pct:.1f}%） |
| トリガー | {monitor_alert} |

## PM判断: {action} / {conviction}

{rationale}

## ペルソナスタンス
| ペルソナ | スタンス | 確信度 |
|---|---|---|
| The Oracle | {stance} | {conviction} |
| The Innovator | {stance} | {conviction} |
| The Tape Reader | {stance} | {conviction} |
| The Tenbagger | {stance} | {conviction} |
| The Macro Mind | {stance} | {conviction} |

## 推奨アクション
{action_detail based on action type}
```

Then send to Slack:
```bash
.venv/bin/python -c "
from investor.notifications.slack import SlackNotifier
SlackNotifier().send_text('Exit Decision: {TICKER} → {action} ({conviction})\n{rationale[:200]}')
"
```

---

## フィードバック記録（FULL_EXIT または全量売却時 — 必須）

`FULL_EXIT` または STAGE2 完了後の `TRAILING_STOP_HIT` など全量決済時に実行:

**① portfolio.csv に書き込む:**
- `mfe_capture_pct` = `exit_pnl_pct / mfe_pct × 100`（`mfe_pct > 0` の場合のみ）
- `rule_adherence_score` を判定して書き込む:
  - 3 = エントリー・サイジング・エグジットすべてがルール通り
  - 2 = 軽微な逸脱あり（サイズがわずかにずれた等）
  - 1 = ルールを無視した判断があった（焦ったエントリー、過大ポジション等）

**② `data/trade_journal.json` に1レコード追記（配列末尾）:**
```json
{
  "trade_id": "{TICKER}_{entry_date}",
  "signal_type": "{signal_type from portfolio.csv}",
  "conviction": "{conviction}",
  "conviction_driver": "{BUY時の主要根拠 1行}",
  "regime_at_entry": "{リスクオン/中立/リスクオフ（不明な場合は null）}",
  "hold_days": {exit_dateからentry_dateを引いた日数},
  "pnl_pct": {exit_pnl_pct},
  "mae_pct": {mae_pct from portfolio.csv or null},
  "mfe_pct": {mfe_pct from portfolio.csv or null},
  "mfe_capture_pct": {計算値 or null},
  "rule_adherence_score": {1-3},
  "decision_quality": {1-3},
  "outcome_quality": {1=損失 / 2=小利益(+5%未満) / 3=良好(+5%以上)},
  "would_take_again": true または false,
  "what_i_missed": "{振り返り1行。例: MFE +22%だったがSTAGE2到達前にストップアウト}"
}
```

**③ 意思決定品質マトリクスの自動判定:**
- `decision_quality ≤ 1` かつ `outcome_quality ≥ 2` → `what_i_missed` に追記:
  `「⚠️ ラッキートレード: 悪い判断だったが結果は良好。このトレードのやり方を再現しないこと。」`
- `decision_quality ≥ 2` かつ `outcome_quality = 1` → `what_i_missed` に追記:
  `「期待内の損失: ルールに従った正しい判断。プロセスを変えない。」`

ファイルが存在しない場合: `[]` で初期化してから追記。

Final output line:
```
/decision --mode exit complete — {TICKER} | {action} / {conviction} | Report: reports/decision/exit_{date}_{TICKER}.md
```

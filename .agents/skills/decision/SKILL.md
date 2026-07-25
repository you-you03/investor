---
description: 最新リサーチ結果に対して5ペルソナの投資ディベートを実行し、PM として最終判断を出して Slack に送信する
argument-hint: "[run_id | --mode exit --ticker TICKER]"
allowed-tools: Bash(.venv/bin/python *) Bash(cat *) Read Write
---

Run the multi-persona investment debate pipeline on the latest research results, then send a Slack notification with the final decision.

All Bash commands must be run from the `investor/` subdirectory:
```
cd "/Users/yutaobayashi/PERSONAL DEV/1_now/investor"
```

## Invocation modes

| Invocation | Behavior |
|---|---|
| `/decision` | Standard mode — debate on latest research run. Follow Steps 0–10. |
| `/decision {run_id}` | Standard mode with specific run. Follow Steps 0–10. |
| `/decision --mode exit --ticker {TICKER}` | **Exit mode** — skip to [reference/exit-mode.md](reference/exit-mode.md). |

---

## Step 0: Load Persona Definitions

Read `investor/investor/prompts/personas.py` in full. Internalize the 5 persona system prompts — you will embody them in debate rounds.

---

## Step 0.5: 固定戦略の検証 + 市場レジーム確認

```bash
.venv/bin/python scripts/record_outcomes.py
.venv/bin/python scripts/fetch_returns.py
.venv/bin/python scripts/show_calibration_stats.py
.venv/bin/python scripts/tool.py get_market_context
.venv/bin/python scripts/audit_portfolio_risk.py
```

検証統計はStrategy V2の監視に使う。12週間の評価窓が満期になる前に、同じデータへ
ウェイトを再適合しない。VIXは新規BUYの環境リスクとして議論するが、LLMの裁量サイズ計算には使わない。
portfolio auditがexit 2なら、そのrunの新規BUYは中止し、違反解消を優先する。

---

## Step 1: Load Research Data

```bash
cat data/research_history.json   # extract run_id, macro_regime, candidates
cat data/portfolio_20man.csv     # count open positions and audit risk fields
cat data/watchlist.json          # check priority_8plus candidates
```

**Repeat-ticker check:** For any candidate that appeared in ≥ 3 past runs, PM synthesis MUST quantify upside, zone position, and what changed. See [reference/pm-synthesis.md](reference/pm-synthesis.md).

**priority_8plus:** Extract tickers with `priority_8plus: true` + `status: "active"`. Add them as mandatory debate candidates even if absent from research history. Fetch live data for each:
```bash
.venv/bin/python scripts/tool.py get_stock_snapshot --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
.venv/bin/python scripts/tool.py get_financials --ticker {TICKER}
.venv/bin/python scripts/tool.py get_ticker_details --ticker {TICKER}
```

---

## Step 2: Per-Ticker — Dynamic Persona Selection

For each ticker, apply `select_personas()` from `personas.py`. Full routing table in [reference/debate-rules.md](reference/debate-rules.md). Max 4 personas; output the panel before debating.

---

## Step 3: Round 1 — Independent Stance

Each persona speaks **independently** (no cross-referencing). Output format and per-persona frameworks: [reference/debate-rules.md](reference/debate-rules.md).

---

## Step 4: Data Gap Resolution

Collect CRITICAL missing data items across all personas for the ticker. De-duplicate, then run the needed `tool.py` commands. Full data-item → command mapping: [reference/debate-rules.md](reference/debate-rules.md).

If a command fails → `data_gap_flag: true` → PM conviction capped at MEDIUM.

---

## Step 5: Round 2 — Cross-Fire

Run adversary pairs where stances differed. Pairs, turn templates: [reference/debate-rules.md](reference/debate-rules.md).

---

## Step 6: PM Synthesis

PM role. Full checklist, RSI gate, sizing formula, JSON output format: [reference/pm-synthesis.md](reference/pm-synthesis.md).

**Key rules (non-negotiable):**
- score ≥ 7.5、fundamentals/catalyst grade A/B
- CHASE_MOMENTUM または extension_risk HIGH → ライブBUY禁止
- stop/target/data gapに不備 → BUY禁止
- Max position: 25% of capital (~$335 for the default book)
- Max open positions: 3
- risk/trade 0.75%、portfolio heat 2.0%
- HIGH conviction は独立した満期OOS 30件まで無効

---

## Step 6b: Watchlist Sync

After PM synthesis:
- **BUY adopted** → `status: "promoted"`, `pipeline_status: "promoted"` in watchlist.json
- **WAIT** → `pipeline_status: "researched"`（条件待ち。次回 /monitor でエントリー条件を再チェック）
- **PASS** → `pipeline_status: "watching"`（リセット。監視継続）
- **PASS/WAIT, existing** → update `last_score`, `reference_price`, `reason`
- **PASS/WAIT, new, score ≥ 7.5** → add as `status: "active"`, `pipeline_status: "researched"`
- **priority_8plus BUY adopted** → remove `priority_8plus` flag

pipeline_status の変更をレポートに明示する:
```
Watchlist pipeline sync:
✅ LRCX — BUY採用 | pipeline_status: decision_queued → promoted
⏸ NVDA — WAIT（セクター集中） | pipeline_status: decision_queued → researched
❌ AMD  — PASS（Options未改善） | pipeline_status: researched → watching
```

```bash
# Apply changes to watchlist.json via Write tool
```

---

## Step 7: Send to Slack + Log

```bash
# Send enriched proposals (validates mandate rules before sending)
.venv/bin/python skills/decision.py --send '[{...proposals JSON...}]'
```

This single command: validates mandates, enriches sizing, posts to Slack, and logs to `decision_history.json`.

No-trade week:
```bash
.venv/bin/python -c "
from investor.notifications.slack import SlackNotifier
SlackNotifier().send_text(':white_check_mark: Decision complete — no actionable recommendations this run.')
"
```

---

## Step 8: Report (display to user)

```markdown
# Decision Report — {YYYY-MM-DD}

**run_id**: `{run_id}` | **マクロレジーム**: {macro_regime}

## ディベート結果サマリー

| Ticker | ペルソナ | Round1 | Round2変化 | PM判定 |
|---|---|---|---|---|
| NVDA | Innovator/Tenbagger/Tape/Macro | 3 BUY / 1 WAIT | Tape: HIGH→MEDIUM | ✅ BUY/MEDIUM |

## 推奨銘柄

### {TICKER} — {action} / {conviction}

| 項目 | 値 |
|---|---|
| エントリーゾーン | ${entry_price_range} |
| 目標値 | ${target_price:,.2f} |
| ストップ | ${stop_loss:,.2f} |
| ポジションサイズ | Python risk engine算出: ~${position_size_usd:,.2f} |
| 計画損失 | ${planned_risk_usd:,.2f} |
| 期間 | {time_horizon} |

**判断根拠**: {rationale}
**カタリスト**: {key_catalysts}
**リスク**: {risk_factors}

**Slack**: 送信済み ✅
> **Next step**: 実際の約定値で `skills/portfolio.py add --target ... --stop ...` を実行
```

Conviction icons: HIGH → ✅ | MEDIUM → 🟡 | LOW → 🔵 | PASS → ❌

---

## Step 9: B枠 Paper Portfolio — アクティブ仮説の自動並走

```bash
.venv/bin/python -c "
from investor.prompts.paper_decision_prompts import format_active_hypotheses_for_claude
print(format_active_hypotheses_for_claude())
"
```

出力が `"アクティブ仮説なし — B枠スキップ"` → このステップをスキップ。

**アクティブ仮説がある場合:**
1. A枠のRound 1/2 debateログを共有しつつ、`pm_rule_overrides` の差分ルールだけでPM合成を再実行
2. B枠proposalsをJSON配列で出力
3. 記録（BUYが0件の場合はスキップ可）:
   ```bash
   .venv/bin/python skills/decision.py --paper --send '[B枠proposals JSON]'
   ```
4. Step 8レポート末尾に追記:

```markdown
## B枠 Paper Portfolio（仮説並走）

| 仮説 | 説明 | B枠BUY | A枠との差分 |
|---|---|---|---|
| H-2 | RSI WAIT strict | MRVL（WAIT） | A枠: 縮小エントリー / B枠: WAIT |
```

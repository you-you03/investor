Run the multi-persona investment debate pipeline on the latest research results, then send a Slack notification with the final decision.

All Bash commands must be run from the `investor/` subdirectory:
```
cd "/Users/yutaobayashi/PERSONAL DEV/investor"
```

If a specific `run_id` was provided as an argument, use that. Otherwise use the most recent run.

---

## Invocation modes

Check the arguments **before** proceeding:

| Invocation | Behavior |
|---|---|
| `/decision` | Standard mode — debate on latest research run. Follow Steps 0–9 below. |
| `/decision {run_id}` | Standard mode with specific run. Follow Steps 0–9. |
| `/decision --mode exit --ticker {TICKER}` | **Exit mode** — skip to [Exit Decision section](#exit-decision-mode) at the bottom of this file. |

---

## Step 0: Load Persona Definitions

Read the file `investor/investor/prompts/personas.py` in its entirety.
This file contains the 5 investor persona definitions (PERSONAS dict) and the
`select_personas()` selection rules. Internalize all 5 persona system prompts —
you will embody each selected persona in the debate rounds below.

The 5 available personas:
- `oracle` — Warren Buffett: Value, moat, FCF, margin of safety
- `innovator` — Cathie Wood: Disruptive innovation, TAM, 5-year thesis
- `macro_mind` — Ray Dalio: Macro regime, debt cycles, correlation risk
- `tenbagger` — Peter Lynch: GARP, PEG ratio, simple story, undiscovered names
- `tape_reader` — Jesse Livermore: Momentum, volume confirmation, Line of Least Resistance

---

## Step 1: Load Research Data

```bash
# Read the latest (or specified) run from research history
cat data/research_history.json
```

Extract:
- `run_id` of the target run
- `macro_regime` of the run
- `candidates` list (each candidate's full research data)

```bash
# Read current open positions
cat data/portfolio.csv
```

Count open positions and note which sectors are already represented.

---

## Step 2: Per-Ticker — Dynamic Persona Selection

For each candidate ticker, apply the `select_personas()` rules from `personas.py`:

**Sector routing:**
| Sector keywords | Personas selected |
|---|---|
| technology, semiconductor, software, communication | innovator, tenbagger, tape_reader |
| healthcare, biotech, pharmaceutical | innovator, oracle, tenbagger |
| financial, banking, real estate | oracle, tenbagger, macro_mind |
| energy, materials, mining, commodity | oracle, macro_mind, tape_reader |
| consumer, retail, restaurant | tenbagger, oracle, tape_reader |
| industrial, aerospace, defense | oracle, tenbagger, macro_mind |
| (default / unclear) | tenbagger, tape_reader, innovator |

**Macro regime overlay (applied on top of sector):**
- `HIGH_FEAR` or `DOWNTREND` or `ELEVATED_RISK_DOWNTREND` → add `macro_mind` (mandatory)
  - If total would exceed 4: drop `innovator` first (least useful in risk-off)

**Strong momentum bonus:**
- `rs_signal = STRONG_OUTPERFORM` → ensure `tape_reader` is in the set

**Imminent earnings:**
- `days_until_earnings ≤ 14` → add `oracle` if not already present (fundamental lens needed)

**Hard cap:** Maximum 4 personas per ticker. If trimming needed, drop in this order: innovator → macro_mind.

Output the selected persona roster for each ticker before proceeding:
```
NVDA debate panel:
- The Innovator (Cathie Wood)
- The Tenbagger (Peter Lynch)
- The Tape Reader (Jesse Livermore)
- The Macro Mind (Ray Dalio) [regime-forced: DOWNTREND]
```

---

## Step 3: Round 1 — Independent Stance (per ticker, per persona)

Process one ticker at a time. For each ticker, run all selected personas sequentially.

**Critical rule:** Each persona speaks INDEPENDENTLY. Do not reference other personas'
views. Do not mention what "the bulls say" or "the bears say." Each persona has only
seen the research data, not the other personas' analyses.

For each persona, adopt their identity fully and output:

```
=== [PERSONA NAME] — [PERSONA MODEL] ===

STANCE: [BUY / WAIT / PASS]
CONVICTION: [HIGH / MEDIUM / LOW]

REASONING:
• [Data point from research] → [Interpretation through this persona's framework]
• [Data point from research] → [Interpretation through this persona's framework]
• [Data point from research] → [Interpretation through this persona's framework]
(3–5 bullets, each grounded in the research data)

MISSING DATA:
• [data_item]: [CRITICAL / NICE_TO_HAVE] — [why needed]
(or: • None)
```

Apply each persona's decision framework as defined in `personas.py`:
- **The Oracle**: moat → FCF → price vs. intrinsic value → balance sheet → management → margin of safety
- **The Innovator**: disruption? → S-curve position → 5-year TAM → convergence → platform effects → thesis intact?
- **The Macro Mind**: macro regime → debt cycle → growth+inflation quadrant → balance sheet → correlation → regime-appropriate?
- **The Tenbagger**: category → PEG ratio → story clarity → institutional discovery → on-ground evidence → fatal signs?
- **The Tape Reader**: trend direction → relative strength → base formation → volume confirmation → entry point → R/R ratio

---

## Step 4: Data Gap Resolution

After all Round 1 stances are complete for a ticker:

1. Collect all `CRITICAL` missing data items across all personas for that ticker.
2. De-duplicate (if multiple personas need `free_cash_flow`, call `get_financials` once).
3. Run the relevant `tool.py` commands (use the mapping from `decision_prompts.py` DATA_GAP_TOOL_MAPPING):

```bash
# Example — run only what's needed for CRITICAL items
.venv/bin/python scripts/tool.py get_financials --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
.venv/bin/python scripts/tool.py get_ticker_details --ticker {TICKER}
```

Complete data-item → command mapping (de-duplicate per command):
- `free_cash_flow`, `revenue_growth_yoy`, `return_on_equity`, `debt_to_equity`, `earnings_growth_yoy`
  → `get_financials`
- `forward_pe`, `peg_ratio`, `analyst_count`, `institutional_ownership_pct`
  → `get_ticker_details`
- `RSI`, `MACD`, `EMA20`, `EMA50`, `ATR`
  → `get_technical_indicators`
- `volume_vs_avg`
  → `get_stock_snapshot`
- `days_until_earnings`
  → `get_earnings_calendar`
- `recent_news`
  → `get_news`
- `analyst_ratings`
  → `get_analyst_ratings`
- `rs_signal`, `rs_1m`, `rs_3m`
  → `get_relative_strength`

If a command fails or returns no data:
→ Mark the item as `data_gap_flag: true`
→ This will cap PM conviction at MEDIUM for this ticker in Round 3

Announce what was retrieved before proceeding:
```
Data Gap Resolution for NVDA:
✓ get_financials → FCF: $26.8B, D/E: 0.42, ROE: 91%
✓ get_technical_indicators → RSI: 68, MACD: bullish cross, EMA20 > EMA50
✗ institutional_ownership_pct → API failed → data_gap_flag: true
```

---

## Step 5: Round 2 — Cross-Fire Debate (2 turns per adversary pair)

Identify the natural adversary pairs from the convened personas (defined in `personas.py` DEBATE_PAIRS):
- `oracle` ↔ `innovator` (Value vs. Growth)
- `macro_mind` ↔ `tape_reader` (Macro vs. Technical)
- `oracle` ↔ `tape_reader` (Fundamentals vs. Momentum)
- `macro_mind` ↔ `innovator` (Risk-off vs. Risk-on)

Only run pairs where BOTH personas are in the convened panel.

For each active pair, run 2 turns:

**Turn 1 — Attacker challenges Defender:**
```
=== ROUND 2 | [ATTACKER NAME] challenges [DEFENDER NAME] ===

CHALLENGE TO [DEFENDER NAME]:
• [Specific weakness in their Round 1 reasoning] → [Counter-evidence or framework argument]
• [Specific weakness] → [Counter-evidence]

MY STANCE REMAINS: [STANCE] — [one sentence why; or note if this cross-fire revised your own view]
```

The attacker is the persona whose Round 1 stance DIFFERED from the defender's.
If both agreed, skip this pair (no cross-fire needed).

**Turn 2 — Defender responds:**
```
=== ROUND 2 | [DEFENDER NAME] responds to [ATTACKER NAME] ===

RESPONSE TO [ATTACKER NAME]:
• [Engage with specific challenge point 1] — [Rebuttal or concession]
• [Engage with specific challenge point 2] — [Rebuttal or concession]

REVISED STANCE: [STANCE] (may be unchanged)
REVISED CONVICTION: [CONVICTION] (may be unchanged)
REASON FOR CHANGE: [one sentence explaining any change; or "Stance unchanged — [why]"]
```

Use the supplemental data from Step 4 (Data Gap Resolution) in Round 2 arguments.
Personas may update their conviction level (not necessarily their stance) based on new data.

---

## Step 6: Round 3 — Portfolio Manager Synthesis

Adopt the Portfolio Manager role. You have read the full debate log (Round 1 + Round 2
for this ticker). Make the final investment decision.

**PM constraints:**
- Available capital: ~$6,700 USD (~1,000,000 JPY)
- Weekly return target: +8% (~$536 / ¥80,000)
- Max open positions: 5
- Style: Balanced momentum — prioritize risk management and consistent returns.
  Spread risk across 3-5 positions. NEVER put more than 25% in a single stock.
- Sector concentration: flag if already in the same sector

**PM synthesis checklist (work through in order):**

1. **Data quality**: Was any `data_gap_flag: true` raised? If yes → cap conviction at MEDIUM
2. **Persona consensus**: 
   - All PASS → force PASS
   - 1 BUY vs rest PASS/WAIT → require overwhelming evidence to proceed
   - Majority BUY → evaluate the strongest dissenter objection
3. **Argument quality**: Which side cited more specific, verifiable data in Round 2?
4. **Portfolio fit**: Sector overlap with existing positions? Slots remaining?
   If 3+ positions already open in same sector → PASS even for HIGH conviction.
5. **Final verdict**: BUY (state conviction) or PASS

**Position sizing (diversified — NOT Half Kelly):**
- HIGH conviction   → 20–25% of capital (~$1,340–1,675)
- MEDIUM conviction → 15% of capital   (~$1,005)
- LOW conviction    → 10% of capital   (~$670)

Output a JSON array (one object per BUY recommendation):
```json
[
  {
    "ticker": "NVDA",
    "action": "BUY",
    "conviction": "HIGH",
    "entry_price_range": "860–880",
    "target_price": 1000,
    "stop_loss": 820,
    "position_size_usd": 1675,
    "rationale": "3–4 sentences. Cite which debate arguments were decisive. Explain why the bull case prevailed despite the dissenter's objection. Reference specific data.",
    "key_catalysts": ["GTC conference in 2 weeks", "H200 ramp"],
    "risk_factors": ["Valuation at 35x forward P/E", "China export restrictions"],
    "time_horizon": "4–6 weeks",
    "debate_summary": {
      "personas_convened": ["innovator", "tenbagger", "tape_reader", "macro_mind"],
      "round1_stances": {
        "innovator": "BUY/HIGH",
        "tenbagger": "BUY/MEDIUM",
        "tape_reader": "BUY/HIGH",
        "macro_mind": "WAIT/LOW"
      },
      "round2_stance_changes": ["macro_mind: WAIT/LOW → WAIT/MEDIUM (conceded momentum)"],
      "final_alignment": "3 BUY vs 1 WAIT",
      "data_gap_flags": []
    }
  }
]
```

If no candidates meet the HIGH conviction bar, return `[]`.
`debate_summary` is for internal logging only — NOT sent to Slack.

---

## Step 6b: Watchlist sync after decision

After PM synthesis is complete for all tickers, read `data/watchlist.json` and apply the following three rules:

```bash
cat data/watchlist.json
```

### Rule A — BUY adopted → mark as promoted

For each ticker in the BUY proposals JSON:
- If the ticker exists in `watchlist.json` with `status: "active"`, change `status` to `"promoted"`.
- This removes it from future monitor/research cycles without deleting history.

### Rule B — PASS/WAIT already on watchlist → update scores

For each PASS/WAIT ticker that already exists in `watchlist.json`:
- Update `last_score` with the score from this run.
- Update `last_research_run_id` with the current `RUN_ID`.
- Update `reference_price` with `current_price` from the research data (reset reference to today's price).
- Update `reason` with a summary of why PM decided PASS/WAIT this time.
- Do NOT change `added_at` or `source`.

### Rule C — PASS/WAIT new → add to watchlist

For each PASS/WAIT ticker that is **not** in `watchlist.json` and has research score ≥ 7.0:

```json
{
  "ticker": "{TICKER}",
  "added_at": "{TODAY_YYYY-MM-DD}",
  "source": "research_seeded",
  "last_research_run_id": "{RUN_ID}",
  "last_score": {score},
  "reference_price": {current_price_at_time_of_research},
  "reason": "{PM判断の要約。例: スコア7.9でPASS。RSI過熱域のため押し目待ち。}",
  "status": "active"
}
```

Tickers that scored < 7.0 are silently skipped.

### Report all changes

After writing the updated `data/watchlist.json`:

```
Watchlist sync:
🏆 ALAB — BUY adopted → status: promoted
🔄 MRVL — score 7.85 updated (was 7.6), reference_price reset to $128.49
✅ CRDO — score 7.9, new entry added (research_seeded)
✅ COHR — score 7.15, new entry added (research_seeded)
⏭ CRWV — score 7.4 < 7.0 threshold, skipped
```

---

## Step 7: Save Debate Results to research_history.json

Append the proposals (including `debate_summary`) to the target run in `research_history.json`.

```bash
# The proposals JSON was output in Step 6.
# Pass it to the decision script for saving:
.venv/bin/python scripts/tool.py save_proposals --run-id {RUN_ID} --proposals '{PROPOSALS_JSON}'
```

If `save_proposals` is not yet implemented in tool.py, write the proposals JSON to
`/tmp/proposals_{RUN_ID}.json` and note the path for manual inspection.

---

## Step 8: Send Slack Notification

```bash
.venv/bin/python scripts/send_slack_proposals.py --file /tmp/proposals.json
```

**Slack content (conclusion only — no debate transcript):**
The `send_slack_proposals.py` script uses `_format_proposals()` from `notifications/slack.py`,
which outputs only:
- ticker / action / conviction
- entry_price_range / target_price / stop_loss / position_size_usd
- rationale (3–4 sentences)
- key_catalysts
- risk_factors
- time_horizon

The `debate_summary` field is automatically excluded by the Slack formatter.

If proposals is `[]` (no recommendations), send a brief text:
```bash
.venv/bin/python -c "
from investor.notifications.slack import SlackNotifier
SlackNotifier().send_text(':white_check_mark: Decision complete — no actionable recommendations for this run.')
"
```

---

## Step 9: Report (display to user in Markdown)

Print the full decision report in this format:

```markdown
# Decision Report — {YYYY-MM-DD}

**run_id**: `{run_id}` | **マクロレジーム**: {macro_regime}

---

## ディベート結果サマリー

| Ticker | 招集ペルソナ | Round1 スタンス | Round2 変化 | PM判定 |
|---|---|---|---|---|
| NVDA | Innovator / Tenbagger / Tape Reader / Macro Mind | 3 BUY / 1 WAIT | Tape Reader: HIGH→MEDIUM | ✅ BUY / MEDIUM |
| ALAB | Tenbagger / Tape Reader / Innovator | 2 BUY / 1 PASS | なし | ❌ PASS |

---

## 推奨銘柄

（推奨なしの場合は "今回の推奨銘柄なし" のみ表示）

### {TICKER} — {action} / {conviction} Conviction

| 項目 | 値 |
|---|---|
| エントリーゾーン | ${entry_price_range} |
| 目標値 | ${target_price:,.2f} |
| ストップ | ${stop_loss:,.2f} |
| ポジションサイズ | ~${position_size_usd:,.0f} |
| 期間 | {time_horizon} |

**判断根拠**:
{rationale（3〜4文）}

**カタリスト**: {key_catalysts をカンマ区切り}
**リスク**: {risk_factors をカンマ区切り}

**ディベート内訳**:
- 最終: {final_alignment}（例: 3 BUY vs 1 WAIT）
- スタンス変化: {round2_stance_changes、なければ "なし"}
- データギャップ: {data_gap_flags、なければ "なし"}

---
（以下、全推奨銘柄繰り返し）

---

**Slack**: 送信済み ✅
> **Next step**: 承認する場合は `scripts/add_position.py` でポジション追加
```

Conviction 別アイコン: HIGH → ✅ | MEDIUM → 🟡 | LOW → 🔵 | PASS → ❌

---

## Example: Abbreviated debate for NVDA (DOWNTREND regime)

**Convened panel:** innovator, tenbagger, tape_reader, macro_mind (regime-forced)

**Round 1:**
- The Innovator: BUY/HIGH — AI infrastructure supercycle, TAM expanding, data center revenue +400%
- The Tenbagger: BUY/MEDIUM — PEG 1.8 acceptable for 50%+ growth, story simple and confirmable
- The Tape Reader: BUY/HIGH — RSI 68, MACD bullish cross, volume 2.1x avg, STRONG_OUTPERFORM
- The Macro Mind: WAIT/LOW — DOWNTREND regime, market headwind penalizes all longs, wait for SPY reclaim of EMA50

**Data Gap Resolution:**
- CRITICAL from Oracle (not convened) equivalent — FCF needed → get_financials → FCF: $26.8B ✓
- No data_gap_flag triggered

**Round 2 (macro_mind vs tape_reader):**
- macro_mind challenges tape_reader: "RSI 68 in a DOWNTREND is an oversold bounce pattern, not a new leg up"
- tape_reader responds: "Volume 2.1x confirms institutional accumulation, not a weak bounce — revised conviction MEDIUM (conceded regime risk is real)"

**Round 3 PM:**
- 3 BUY (innovator HIGH, tenbagger MEDIUM, tape_reader revised to MEDIUM) vs 1 WAIT (macro_mind)
- tape_reader's concession reduces aggregate confidence
- Macro regime headwind noted in risk factors
- Decision: BUY / MEDIUM conviction (regime penalty applied) → position $1,675

---

*This command replaces the legacy 3-stage Bullish/Bearish/PM pipeline.*
*The old pipeline prompts remain in decision_prompts.py for backward compatibility.*

---

## Exit Decision Mode

**Trigger**: `/decision --mode exit --ticker {TICKER}`

Invoked when Monitor raises `TARGET_HIT` or `UP_30PCT` for a portfolio position, or when the user decides manually.
Skip all steps above (Steps 0–9). Follow only the steps below.

---

### Exit Step 1: Load position and current data

```bash
cat data/portfolio.csv
```

Extract the row for `{TICKER}` where `status == "open"`. Record:
- `entry_price`, `target_price`, `stop_loss`, `shares`, `entry_date`

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

### Exit Step 2: Load persona definitions

Read `investor/investor/prompts/personas.py`. All 5 personas are convened for exit decisions (no sector routing — every persona is relevant to exits).

---

### Exit Step 3: Round 1 — Independent exit stance (all 5 personas)

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

### Exit Step 4: Round 2 — Cross-fire (same pairs as standard decision)

Run adversary pairs where stances differ. Format is identical to standard Round 2.
Focus debate on: "Is the original thesis still intact at this price level?"

---

### Exit Step 5: PM Exit Synthesis

The Portfolio Manager synthesizes all 5 stances and outputs one of four actions:

| アクション | 条件の目安 |
|---|---|
| `FULL_EXIT` | 多数(3+)が SELL / RSI 過熱 / マクロ逆風 / テーゼ破綻 |
| `PARTIAL_EXIT` | 意見が割れる / トレンド継続だがリスク高め |
| `RAISE_TARGET` | 多数が HOLD / カタリスト残存 / テーゼ変わらず |
| `HOLD` | 全員 HOLD / 現状維持が最善 |

For `PARTIAL_EXIT`: specify `exit_shares` (how many to sell) and `remaining_shares`.
For `RAISE_TARGET`: specify `new_target_price` and `new_trailing_stop_pct`.

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

### Exit Step 6: Save and report

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

Final output line:
```
/decision --mode exit complete — {TICKER} | {action} / {conviction} | Report: reports/decision/exit_{date}_{TICKER}.md
```

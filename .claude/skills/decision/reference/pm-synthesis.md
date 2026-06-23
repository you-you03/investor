# PM Synthesis Rules Reference

## Calibration-Based Sizing Adjustment (from Step 0.5 output)

Before running the PM Synthesis Checklist, read the `show_calibration_stats.py` output printed in Step 0.5 and apply the following rules:

| Condition | Action |
|---|---|
| `closed < 5` for any tier | Insufficient data — skip calibration adjustment, use default sizing |
| `MEDIUM avg_return > HIGH avg_return` (both ≥5 closed) | Apply **MEDIUM超過補正**: MEDIUMかつRevenue/EPS高成長候補のサイズを upper limit（20%）に引き上げる |
| `HIGH win_rate < 40%` (≥5 closed) | **HIGHサイズ上限キャップ**: HIGHでもサイズをMEDIUM上限（15%）に抑える。rationale に「確信度校正ペナルティ適用」を記載 |
| `HIGH win_rate ≥ 60%` AND `HIGH avg_return > 0` (≥5 closed) | 通常通り。補正なし |

補正を適用した場合、rationale に `「校正補正: MEDIUM超過補正適用（MEDIUMが統計的にHIGHをアウトパフォーム中）」` のように明記する。

---

## PM Synthesis Checklist (Step 6)

Work through in order:

**0. Catalyst quality gate (run first — blocks everything else)**

| Quality | 条件 | Catalyst score上限 |
|---|---|---|
| STRONG | 決算ビート＋ガイダンス引き上げ / 複数アナリスト同時格上げ | 上限なし(8-9) |
| MEDIUM | 単独アナリスト格上げ / セクターローテーション / 決算インライン | 上限7 |
| WEAK | テクニカルブレイクアウトのみ / 原因不明スパイク / ファンダ弱い（Revenue<20% YoY）のに格上げ | 上限5 |
| NONE | カタリスト不在 | 上限4 |

**`catalyst_quality == WEAK` → immediate PASS.** Skip debate entirely.
rationale: `"カタリスト質WEAK — 根拠不十分のため見送り"`

> 追加ルール: `signal_type == "technical_breakout"` かつ `fundamentals_score < 7` の組み合わせは自動的に catalyst_quality = WEAK と判定する。
> [根拠: AVGO(-4.1%), WAT(-7.3%)はいずれもtechnical/upgradeベースで採用。ファンダが伴わないブレイクアウトは勝率0%]

**0.5. Score-based adoption gate (新規 — catalyst gateの直後に実行)**

| Score | 採用条件 |
|---|---|
| ≥ 8.2 | HIGH conviction 許可（ただし fundamentals_score ≥ 8 が必要） |
| 7.5–8.1 | MEDIUM conviction 採用可。HIGH は fundamentals_score ≥ 8 かつ 過去run ≥3回出現でない場合のみ |
| 7.0–7.4 | MEDIUM conviction での採用は **STRONG catalyst 必須**。それ以外は WAIT に格下げ |
| < 7.0 | PASS 強制（採用不可） |

rationale例: `"スコア7.2 + catalyst_quality MEDIUM → WAITに格下げ。STRONG catalystなしでMEDIUM採用は禁止"`
[根拠: MEDIUM確信度の勝率27%は採用基準として低すぎる。WAT(score7.0/MEDIUM)が典型的な失敗パターン]

**1. Data quality:** `data_gap_flag: true` raised → cap conviction at MEDIUM.

**1.5. No-score cap:** Candidate missing `score` field or `null` → cap at MEDIUM. Note in rationale.

**2. Persona consensus:**
- All PASS → force PASS
- 1 BUY vs rest PASS/WAIT → need overwhelming evidence
- Majority BUY → evaluate strongest dissenter

**3. Argument quality:** Which side cited more specific, verifiable data in Round 2?

**4. Portfolio fit:** Sector overlap with open positions? Slots remaining?
If 3+ open in same sector → PASS even for HIGH conviction.

**4.3. Sector LAGGING hard block (新規)**

research reportの `sector_rs` を確認:
- 候補のセクターが LAGGING（bottom_sectors）に入っている場合:
  - catalyst_quality = STRONG のみ採用継続。STRONG でも conviction は MEDIUM が上限。
  - catalyst_quality = MEDIUM / WEAK → **PASS 強制**。debateの結果に関わらず。
  - rationale: `"セクターLAGGING + catalyst_quality {quality} → PASS強制。LAGGINGセクターでMEDIUM/WEAK催剤は採用禁止"`
  [根拠: WAT(Healthcare LAGGING -8.22% 1m) — セクター逆風を「リスク」として列挙しただけでPASS判断を怠った。MFE +0.04%でテーゼ未検証]

**4.5. Score 8.0+ priority rule:**
If score ≥ 8.0 and portfolio is full (5 positions):
- Check open positions for lowest-conviction or drawdown ≤ -3%
- If found: consider swap → note `「スコア{X}優先枠: {旧TICKER}と交換」` in rationale
- If not found: PASS is OK, but add `priority_8plus: true` to watchlist

**4.7. Timeframe alignment check:**

Read the `tf_alignment` field from the research candidate JSON:

| tf_alignment | Action |
|---|---|
| `ALIGNED_UP` / `PARTIAL_UP` | No penalty |
| `WARNING` (= `tf_warning: true` in research) | Cap conviction at **MEDIUM**. Note: `「TF不整合: 日足↑だが上位足↓。確信度キャップ(MEDIUM)適用」` |
| `ALIGNED_DOWN` | Force **PASS** unless catalyst_quality=HIGH AND all other gates pass. In that case cap at MEDIUM and halve position size |
| `DATA_UNAVAILABLE` / `ERROR` | No penalty — proceed on available data |

**5. RSI overheating gate:**

| Condition | Decision |
|---|---|
| RSI ≥ 85 | **WAIT (no exceptions)** — note entry condition in rationale |
| RSI 70–84, within 3% of 52W high | **WAIT (no exceptions)** |
| RSI 70–84, >3% below 52W high | SECTOR_LEADING exception applies (see below) |
| RSI < 70 | RSI condition OK, judge on other factors |

**SECTOR_LEADING exception (RSI 70–84, >3% below 52W high):**
- `rs_signal == STRONG_OUTPERFORM` → WAIT override allowed
- Reduce position size **2 tiers** (HIGH→LOW size, MEDIUM→LOW size)
- rationale: `「RSI過熱だがSECTOR_LEADING特例適用・ポジション縮小（2段階）」`

**6. Final verdict:** BUY (state conviction) or PASS

---

## Position Sizing — Default 20万円 Portfolio

Default account balance:
```
account_balance = 1340 USD   # 200,000 JPY, using the mandate's ¥1,000,000 ~= $6,700 assumption
```

The 20万円 portfolio is the default operating book and the only book used for
real execution recommendations.

The parallel 100万円 portfolio in `data/portfolio_100man.csv` is simulation-only.
It exists to collect decision-quality data, so it should not make the 20万円
book more conservative. When the user explicitly asks to operate or update the
100万円 simulation, apply the same quality gates but target higher capital usage.

**Step 1 — Quality gate first:**
- Do not buy just to fill cash.
- `catalyst_quality == WEAK`, score < 7.0, missing stop_loss, or CRITICAL data gap → PASS.
- If no qualified candidates exist, HOLD_CASH is correct even if utilization is low.

**Step 2 — Share and budget constraints:**
```
same_ticker_after_trade <= 2 shares
total_default_portfolio_exposure <= 1340 USD
```

**Step 3 — Cash utilization target:**
```
target_cash_utilization = 85%
```
Apply this only after the quality gate. If qualified candidates exist, choose integer/fractional
share quantities that use cash efficiently while respecting the 2-share same-ticker cap.
If utilization remains <85%, the rationale must state why cash is left idle.

**Step 4 — VIX regime multiplier (from Step 0.5):**
```
VIX < 18  → × 1.0 (risk-on)
18–24     → × 0.7 (neutral)
VIX ≥ 25  → × 0.5 (risk-off)
final_position_size_usd = planned_size_usd × multiplier
```

Required rationale note: `「20万円枠: planned $X → レジーム(×M): $Y / N株。稼働率Z%。同一ticker保有N/2株」`

Conviction labels (HIGH/MEDIUM/LOW) are for debate logging. Sizing is constrained by
the 20万円 budget, same-ticker 2-share cap, cash utilization target, and VIX multiplier.

---

## Position Sizing — 100万円 Simulation Portfolio

Use this section only when explicitly producing or recording `data/portfolio_100man.csv`
simulation trades.

Simulation account balance:
```
account_balance = 6700 USD   # 1,000,000 JPY, same FX assumption as the mandate
max_position_usd = 1675 USD  # 25% cap
max_positions = 5
target_cash_utilization = 90% to 100%
```

**Purpose:** This is not real capital. The objective is to improve decision accuracy
by collecting richer BUY/WAIT/PASS and sizing outcome data.

**Rules:**
- Keep all quality gates from the 20万円 book. Do not buy `catalyst_quality == WEAK`,
  score < 7.0, missing stop_loss, or CRITICAL data-gap candidates.
- If qualified candidates exist, fill the 100万円 simulation book more aggressively:
  prefer reaching 90%+ utilization across 3-5 names instead of holding cash.
- Use the full 25% per-position cap for HIGH conviction unless VIX risk-off or
  a specific stock risk argues for a smaller size.
- MEDIUM conviction can be sized 15-20% when score/catalyst quality is solid.
- LOW conviction remains tracking-size only; do not use LOW merely to fill cash.
- If utilization remains below 90%, rationale must state whether the blocker was
  candidate quality, event timing, sector concentration, or missing data.

Required rationale note: `「100万円sim: $X / N株。稼働率Z%。高稼働対象だが品質ゲート維持」`

---

## BUY JSON Output Format

```json
[
  {
    "ticker": "NVDA",
    "action": "BUY",
    "conviction": "HIGH",
    "signal_type": "earnings_beat",
    "entry_price_range": "860–880",
    "target_price": 1000,
    "stop_loss": 820,
    "position_size_usd": 1000,
    "shares_suggested": 2,
    "rationale": "3–4 sentences citing decisive debate arguments.",
    "key_catalysts": ["GTC conference in 2 weeks", "H200 ramp"],
    "risk_factors": ["Valuation at 35x forward P/E", "China export risk"],
    "time_horizon": "4–6 weeks",
    "debate_summary": {
      "personas_convened": ["innovator", "tenbagger", "tape_reader", "macro_mind"],
      "round1_stances": {"innovator": "BUY/HIGH", "tenbagger": "BUY/MEDIUM", "tape_reader": "BUY/HIGH", "macro_mind": "WAIT/LOW"},
      "round2_stance_changes": ["macro_mind: WAIT/LOW → WAIT/MEDIUM"],
      "final_alignment": "3 BUY vs 1 WAIT",
      "data_gap_flags": []
    }
  }
]
```

`debate_summary` is for internal logging only — NOT sent to Slack.

**No-trade-week output:**
```json
{"no_trade_week": true, "reason": "候補銘柄の理由を記載。", "action": "HOLD_CASH"}
```

---

## Repeating-ticker check (Step 1)

Count how many past runs each candidate appeared in. For tickers with **≥ 3 appearances**, the PM synthesis MUST explicitly state:
- Upside to target: `(target_price / current_price - 1) × 100`%
- Current price vs. entry zone (inside / above / below zone)
- What changed since last WAIT/PASS (or confirm nothing changed)

Skipping this check for repeat tickers is prohibited.

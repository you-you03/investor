# Decision Skill — Debate Rules Reference

## Persona Selection (Step 2)

**Sector routing:**
| Sector keywords | Personas |
|---|---|
| technology, semiconductor, software, communication | innovator, tenbagger, tape_reader |
| healthcare, biotech, pharmaceutical | innovator, oracle, tenbagger |
| financial, banking, real estate | oracle, tenbagger, macro_mind |
| energy, materials, mining, commodity | oracle, macro_mind, tape_reader |
| consumer, retail, restaurant | tenbagger, oracle, tape_reader |
| industrial, aerospace, defense | oracle, tenbagger, macro_mind |
| (default / unclear) | tenbagger, tape_reader, innovator |

**Macro regime overlay:**
- `HIGH_FEAR` / `DOWNTREND` / `ELEVATED_RISK_DOWNTREND` → add `macro_mind` (mandatory)
  - If > 4 total: drop `innovator` first

**Strong momentum bonus:** `rs_signal == STRONG_OUTPERFORM` → ensure `tape_reader` is present

**Imminent earnings:** `days_until_earnings ≤ 14` → add `oracle` if absent

**Hard cap:** Maximum 4 personas per ticker. Drop order: innovator → macro_mind.

---

## Round 1 Output Template

```
=== [PERSONA NAME] — [PERSONA MODEL] ===

STANCE: [BUY / WAIT / PASS]
CONVICTION: [HIGH / MEDIUM / LOW]

REASONING:
• [Data point] → [Interpretation through persona's framework]
• ...

MISSING DATA:
• [data_item]: [CRITICAL / NICE_TO_HAVE] — [why needed]
```

**Persona decision frameworks:**
- **Oracle**: moat → FCF → price vs. intrinsic value → balance sheet → margin of safety
- **Innovator**: disruption? → S-curve → 5-year TAM → convergence → thesis intact?
- **Macro Mind**: macro regime → debt cycle → growth+inflation quadrant → correlation → regime-fit?
- **Tenbagger**: category → PEG → story clarity → institutional discovery → fatal signs?
- **Tape Reader**: trend → RS → base formation → volume confirmation → entry point → R/R

---

## Data Gap Resolution — Tool Mapping (Step 4)

De-duplicate per command (run each command at most once per ticker):

| Data items | Tool command |
|---|---|
| `free_cash_flow`, `revenue_growth_yoy`, `ROE`, `debt_to_equity`, `earnings_growth_yoy` | `get_financials` |
| `forward_pe`, `peg_ratio`, `analyst_count`, `institutional_ownership_pct` | `get_ticker_details` |
| `RSI`, `MACD`, `EMA20`, `EMA50`, `ATR` | `get_technical_indicators` |
| `volume_vs_avg` | `get_stock_snapshot` |
| `days_until_earnings` | `get_earnings_calendar` |
| `recent_news` | `get_news` |
| `analyst_ratings` | `get_analyst_ratings` |
| `rs_signal`, `rs_1m`, `rs_3m` | `get_relative_strength` |

Failed command → `data_gap_flag: true` → caps PM conviction at MEDIUM.

---

## Round 2 Cross-Fire — Adversary Pairs

Active debate pairs from `personas.py` DEBATE_PAIRS (only when both are convened):
- `oracle` ↔ `innovator` (Value vs. Growth)
- `macro_mind` ↔ `tape_reader` (Macro vs. Technical)
- `oracle` ↔ `tape_reader` (Fundamentals vs. Momentum)
- `macro_mind` ↔ `innovator` (Risk-off vs. Risk-on)

Only run pairs where stances DIFFERED in Round 1. Both agree → skip pair.

**Attacker template:**
```
=== ROUND 2 | [ATTACKER] challenges [DEFENDER] ===
CHALLENGE TO [DEFENDER]:
• [Specific weakness] → [Counter-evidence]
MY STANCE REMAINS: [STANCE]
```

**Defender template:**
```
=== ROUND 2 | [DEFENDER] responds to [ATTACKER] ===
RESPONSE:
• [Engage challenge 1] — [Rebuttal or concession]
REVISED STANCE: [STANCE] / CONVICTION: [CONVICTION]
REASON: [one sentence]
```

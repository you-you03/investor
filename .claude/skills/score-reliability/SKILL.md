---
description: スコアの信頼性を振り返り、1〜8週リターンを使ってモメンタムモード別・因子別の予測力を評価し、researchの重み調整提案を出す
argument-hint: ""
allowed-tools: Bash(.venv/bin/python *) Bash(cat *) Read
---

Analyze how reliable the research scoring system is, using realized follow-up returns from `score_snapshots.json` and outcomes from `research_history.json`.

This skill is narrower than `/review`. Use it when the user wants to answer questions like:

- 「過去のスコアって本当に当たってる？」
- 「EARLY_MOMENTUM と CHASE_MOMENTUM で、どの観点が効いてる？」
- 「fundamentals / catalyst / technical の信頼性をリターンから見たい」
- 「research の重みや閾値を見直したい」

All Bash commands must be run from:

```bash
cd "/Users/yutaobayashi/PERSONAL DEV/1_now/investor"
```

---

## Step 1: Refresh tracked outcomes

Run these in order:

```bash
.venv/bin/python scripts/record_outcomes.py
.venv/bin/python scripts/fetch_returns.py
.venv/bin/python scripts/validate_scores.py
```

Read the command outputs. Do not fabricate counts or dates.

If `fetch_returns.py` says 5〜8週データがまだ `N/A` なら、そのまま分析を続けつつ「満期データ不足」と明記する。

---

## Step 2: Read the validation artifacts

Read:

- `reports/validation/validation_{today}.md` if today’s file exists
- otherwise the latest file under `reports/validation/`
- `data/score_snapshots.json`

Primary source of truth:

- Horizon-level return validation: `score_snapshots.json` and the generated validation report
- Closed/open realized outcome context: `data/research_history.json`

Use the validation report for summary numbers, but inspect raw JSON when the user asks a narrower question or when a section is empty / `N/A`.

---

## Step 3: Evaluate reliability at three layers

### 3a. Overall score reliability

Summarize:

- sample count by horizon (`week1` ... `week8`)
- Spearman ρ by horizon
- threshold split (`score >= 7.0` vs `< 7.0`)
- conviction summary (`HIGH / MEDIUM / LOW`)

Interpretation rules:

- `ρ >= 0.40`: strong predictive power
- `0.20 <= ρ < 0.40`: usable but moderate
- `0.05 <= ρ < 0.20`: weak
- `< 0.05`: no useful predictive power
- `N < 30`: treat as immature; do not over-interpret

Do not treat 1-week results as decisive if longer horizons disagree.

### 3b. Momentum-mode reliability

For each mode:

- `EARLY_MOMENTUM`
- `CHASE_MOMENTUM`
- `BALANCED`
- `NONE`

Summarize by horizon:

- sample count
- average return
- win rate
- average SPY alpha
- average sector alpha

Then state:

- which horizon looks best for each mode
- whether the mode degrades or improves as holding period extends
- whether 5〜8週 materially changes the conclusion vs 1〜4週

### 3c. Mode × factor reliability

For each mode and each factor:

- `momentum`
- `fundamentals`
- `catalyst`
- `technical`
- `sentiment`

Use the mode-specific reliability section from `validate_scores.py` output.

For each factor, judge:

- best horizon by Spearman ρ
- whether high factor scores (`>= 8`) materially outperform low scores (`<= 6`) in SPY alpha
- whether the factor is:
  - `Reliable`
  - `Conditional`
  - `Unreliable`

Use this rubric:

- `Reliable`: best-horizon `ρ >= 0.25` and high-score alpha clearly exceeds low-score alpha
- `Conditional`: some positive signal exists, but either `ρ < 0.25`, sample size is small, or alpha spread is inconsistent
- `Unreliable`: `ρ <= 0` or high-score alpha does not beat low-score alpha

If all rows are `N/A`, say the mode-specific sample has not matured yet.

---

## Step 4: Convert findings into research scoring guidance

Produce explicit guidance for `investor/prompts/research_prompts.py`.

Focus on:

- weight changes by factor
- whether a factor should be treated differently in `EARLY_MOMENTUM` vs `CHASE_MOMENTUM`
- whether 5〜8週 data suggests longer holding periods for certain modes
- whether the `7.0` threshold should change
- whether conviction mapping (`HIGH / MEDIUM / LOW`) is too loose or too strict

Examples of the type of recommendation expected:

- "In EARLY_MOMENTUM, fundamentals remain predictive through 6–8 weeks, so avoid underweighting fundamentals for early setups."
- "In CHASE_MOMENTUM, catalyst signal fades after 3–4 weeks, so catalyst should not justify long holding periods by itself."
- "Technical is only useful as an entry-timing filter; keep its weight low."
- "If CHASE_MOMENTUM + extension_risk=HIGH underperforms beyond week2, tighten the penalty or lower conviction ceiling."

Be specific. If you recommend a weight change, name the current factor and direction of change. If evidence is immature, say so instead of guessing.

---

## Step 5: Output format

Return a concise Markdown report with these sections:

```markdown
# Score Reliability Review

## Horizon Summary

## Momentum Mode Summary

## Mode × Factor Reliability

## Calibration Recommendations
```

Requirements:

- Put findings first, not process narration
- Use concrete horizons (`1週後` ... `8週後`)
- Separate `evidence-backed changes` from `watchlist / needs more data`
- If data is immature for 5〜8週 or for mode-specific analysis, say that explicitly

The final section, **## Calibration Recommendations**, must be directly actionable for future `/research` runs.

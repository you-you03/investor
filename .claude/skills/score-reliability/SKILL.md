---
description: スコアの信頼性を振り返り、1〜12週リターンとrun別alpha ICでStrategy V2を評価する
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

If `fetch_returns.py` says 長期データがまだ `N/A` なら、そのまま分析を続けつつ「満期データ不足」と明記する。

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

- sample count by horizon (`week1` ... `week12`)
- pool済みSpearman ρ（診断用）とrun別SPY alpha IC（主指標）
- threshold split (`score >= 7.5` vs `< 7.5`)
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
- whether 9〜12週 materially changes the conclusion vs shorter horizons

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

- Strategy V2ウェイトを変更すべき十分な独立OOSがあるか
- whether a factor should be treated differently in `EARLY_MOMENTUM` vs `CHASE_MOMENTUM`
- whether 9〜12週 data suggests longer holding periods for certain modes
- whether the `7.5` threshold should change
- whether conviction mapping (`HIGH / MEDIUM / LOW`) is too loose or too strict

Examples of the type of recommendation expected:

- "In EARLY_MOMENTUM, fundamentals remain predictive through 6–8 weeks, so avoid underweighting fundamentals for early setups."
- "In CHASE_MOMENTUM, catalyst signal fades after 3–4 weeks, so catalyst should not justify long holding periods by itself."
- "Technical is only useful as an entry-timing filter; keep its weight low."
- "If CHASE_MOMENTUM + extension_risk=HIGH underperforms beyond week2, tighten the penalty or lower conviction ceiling."

独立した満期runが10未満、またはStrategy V2開始から12週間未満なら、ウェイト変更は禁止。
pooled factor相関だけで変更を勧めない。証拠が未成熟なら計測継続とする。

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
- Use concrete horizons (`1週後` ... `12週後`)
- Separate `evidence-backed changes` from `watchlist / needs more data`
- If long-horizon or mode-specific data is immature, say that explicitly

The final section, **## Calibration Recommendations**, must be directly actionable for future `/research` runs.

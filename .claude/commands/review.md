Analyze investment performance: compare predicted scores vs actual returns, compute win rates by score bucket and conviction level, and identify which scoring factors are most predictive.

All Bash commands must be run from the `investor/` subdirectory:
```
cd "/Users/yutaobayashi/PERSONAL DEV/investor"
```

---

## Step 1: Update outcome records

```bash
.venv/bin/python scripts/record_outcomes.py
```

Read the output to see how many outcomes were newly recorded or updated.

---

## Step 2: Load enriched research history

Read `data/research_history.json`. For analysis, only consider candidates that have an `outcome` key with a non-null `realized_return_pct` or `unrealized_return_pct`.

---

## Step 3: Performance analysis

Perform each of the following analyses using only data from the JSON. Do not estimate or fabricate numbers.

### 3a. Overall summary

| Metric | Value |
|--------|-------|
| Total candidates with outcomes | — |
| Closed positions | — |
| Open positions | — |
| Overall win rate (return > 0%) | — |
| Average realized return | — |
| Average alpha vs SPY | — |

### 3b. Win rate by score bucket

Group candidates by their composite `score`:

| Score bucket | Count | Win rate | Avg return | Avg alpha |
|---|---|---|---|---|
| ≥ 8.5 (exceptional) | — | — | — | — |
| 8.0–8.4 (high) | — | — | — | — |
| 7.5–7.9 (medium-high) | — | — | — | — |
| 7.0–7.4 (medium) | — | — | — | — |
| < 7.0 (below threshold) | — | — | — | — |

### 3c. Win rate by conviction level

| Conviction | Count | Win rate | Avg return | Avg alpha |
|---|---|---|---|---|
| HIGH | — | — | — | — |
| MEDIUM | — | — | — | — |
| LOW | — | — | — | — |

### 3d. Outcome type breakdown

| Outcome type | Count | Avg return |
|---|---|---|
| TARGET_HIT | — | — |
| STOP_HIT | — | — |
| TIME_EXIT | — | — |
| OPEN / AT_TARGET / AT_STOP | — | — |

### 3e. Factor correlation analysis (if score_breakdown is available)

For each score factor (momentum, fundamentals, catalyst, technical, sentiment), compute:
- Pearson correlation between factor score and actual return_pct
- Note which factors had the strongest / weakest predictive power

Format:
| Factor | Avg score (winners) | Avg score (losers) | Correlation with return |
|---|---|---|---|

### 3f. Score calibration check

For positions that have `score_evidence` recorded, note whether the evidence cited in the research actually materialized. Flag specific cases where:
- Score was HIGH but outcome was STOP_HIT → potential overconfidence in that factor
- Score was LOW but outcome was TARGET_HIT → potential underconfidence

---

## Step 4: Key findings and calibration recommendations

Synthesize the analysis into 3–5 bullet points:

- **What's working**: which score buckets / factors are reliably predicting good outcomes
- **What's not**: where the model is overconfident or underconfident
- **Calibration suggestion**: specific weight or threshold adjustments for `investor/prompts/research_prompts.py`
  - Example: "Catalyst weight should be reduced from 25% to 20% — it shows weak correlation with outcomes in this sample"
  - Example: "Consider raising the minimum score threshold from 7.0 to 7.5"

---

## Step 5: Output

Print the full analysis as a readable Markdown report. End with a section titled **## Calibration Recommendations** containing any suggested changes to scoring weights or thresholds — ready to be applied if the user approves.

---

## Step 6: Spearman 相関検証（score_snapshots から）

```bash
.venv/bin/python scripts/validate_scores.py
```

スクリプトが `reports/validation/validation_{date}.md` を出力し、同時に stdout にも内容を表示する。

出力を読み込み、以下をキャリブレーション提案に統合する:

- **IC（Spearman ρ）が 0.2 未満の週がある場合**: 「スコアの予測力が低い（week{N}）」と注記し、スコアを超短期トレードの根拠として使わないよう注意を促す
- **IC が 0.4 以上の週がある場合**: 「スコアは良好な予測力を持っている（week{N}）」と評価し、そのホライゾンでの取引が有効であると記載する
- **ファクター別 ρ が最も弱いファクター**（`week4` ρ < 0.15）→ ウェイト引き下げを `Calibration Recommendations` に追記
- **ファクター別 ρ が最も強いファクター**（`week4` ρ > 0.3）→ ウェイト引き上げを `Calibration Recommendations` に追記
- **データ不足（N < 30）の週は「計測継続中」**と表示してスキップする

### 統合出力形式

Step 5 の **## Calibration Recommendations** に以下を追加:

```markdown
### スコア予測力検証（score_snapshots より）

| ホライゾン | Spearman ρ | 判定 |
|---|---|---|
| 1週後 | ... | ... |
| 2週後 | ... | ... |
| 3週後 | ... | ... |
| 4週後 | ... | ... |

**ファクター調整提案**（week4 ρ 基準）:
- {最強ファクター}: ρ={value} → ウェイト引き上げ検討
- {最弱ファクター}: ρ={value} → ウェイト引き下げ検討
```

`score_snapshots.json` にデータがない場合（スナップショット数 = 0）は Step 6 全体をスキップし、「スナップショットデータ蓄積中 — /research を継続実行してください」と表示する。

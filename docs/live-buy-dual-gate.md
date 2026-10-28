# 暫定ライブBUY デュアルゲート (Provisional)

**状態: 暫定 (provisional)。** Strategy V2 のスコアウェイトは凍結したまま、ライブ（実弾 / 20万円枠）の新規 BUY だけを狭くする判断規則である。

暫定である理由は [`reports/validation/validation_2026-10-28.md`](../reports/validation/validation_2026-10-28.md)。同レポートの Strategy version 内訳は `legacy_unversioned: 397`、`quality_momentum_v2_2026-07-25: 15`。V2 スナップショットは約15件で、OOS サンプルはまだ小さい。この件数でウェイトを再適合したり、HIGH conviction のサイズを開いたりしない。

出口 SOP（H-7 の 4–7日 prime exit review を含む）は **この文書の対象外**。ここには書かない。

## 何を変えないか

- Quality Momentum の配分は **ファンダ 60% / 中期RS 25% / 検証済み材料 15%** のまま。式は [`strategy-v2.md`](strategy-v2.md) を正とする。
- Technical と Sentiment は 0% のゲートのまま。新しい数値ウェイト、新しいスコア閾値、ファクター再配分は作らない。
- HIGH conviction のサイジングは、既存の `/review` ゲートを超えて有効化しない。独立した満期 OOS 観測が 30件に達するまで HIGH は無効（[`strategy-v2.md`](strategy-v2.md)、[`.claude/skills/review/SKILL.md`](../.claude/skills/review/SKILL.md)）。
- 既存のハードゲートは残る。このデュアルゲートはそれらを置き換えない。stop / target の欠損、catalyst grade C/D、`extension_risk=HIGH`、CRITICAL data gap、reward/risk 1.5 未満、portfolio audit の新規BUY停止は、これまでどおりライブBUY不可。

## 適用範囲

| 枠 | この規則 |
|---|---|
| ライブ（20万円 / A枠） | 下記デュアルゲートをすべて満たすときだけ BUY |
| WAIT | CHASE、またはゲート未達のときの原則 |
| paper（B枠）と 100万円シミュレーション | 実弾ではない。CHASE を学習用に残すことはできる。迷ったら WAIT |
| 出口判断 | 対象外。この PR / この文書では出口 SOP を追加しない |

## デュアルゲート（ライブBUYは両方必須）

スコアが既存閾値を超えただけでは買わない。Gate 1 と Gate 2 の両方と、上の既存ハードゲートを満たす。

### Gate 1 — スコア閾値（必要だが十分ではない）

- `score ≥ 7.5`（既存閾値）。
- 7.5 未満はライブBUY不可。
- 7.5 以上でも Gate 2 または既存ハードゲートを欠くなら BUY しない。`HOLD_CASH` または WAIT が正しい。

### Gate 2 — モメンタムモードと、相対的に強いファンダメンタルズ

次の二つとも必要。

1. **モード**は `momentum_profile.primary_mode` が `EARLY_MOMENTUM` または `BALANCED`。
   - `CHASE_MOMENTUM` は不可（次節）。
   - `NONE` もライブBUYのモードではない。
2. **ファンダメンタルズが、その候補の他ファクターと比べて相対的に強い。** 新しい点数は作らない。同じ銘柄の中で、次を言葉で確認する。
   - **下限は既存グレード**: `factor_grades.fundamentals` が A または B。C/D はライブBUY不可。これは従来の品質ゲートであり、新しい閾値ではない。
   - **相対比較**: 同じ候補の中期モメンタムおよび検証済みカタリストと比べて、ファンダメンタルズが弱い脚ではないこと。モメンタムやカタリストだけがスコアを押し上げ、事業品質が添え物になっている場合は、総合スコアが 7.5 以上でもライブBUYしない。
   - PM の rationale に、ファンダが他ファクターと比べて相対的に強いかを一文で書く。
   - technical と sentiment は参考であり、ファンダの代わりにしない。

## CHASE は原則ライブBUY禁止

`CHASE_MOMENTUM` をライブBUYに使わない。原則は **WAIT**（条件待ち。モードが `EARLY_MOMENTUM` または `BALANCED` になり、Gate 2 のファンダ条件も満たすまで実弾にしない）。

paper（B枠）または 100万円シミュレーションに学習記録として残すことはできる。どちらも実弾の発注ではない。記録するか WAIT にするか迷ったら **WAIT**。

現行文書に、CHASE のライブBUYを許す例外はない。次はいずれも例外許可ではない。

- [`strategy-v2.md`](strategy-v2.md) は `CHASE_MOMENTUM` または `extension_risk=HIGH` のライブBUYを避ける。
- [`.claude/skills/decision/reference/pm-synthesis.md`](../.claude/skills/decision/reference/pm-synthesis.md) の hard gate は CHASE と `extension_risk=HIGH` をライブBUYから外す。
- `investor/agents/decision_agent.py` の chase/extension gate は、その状態のライブ送信を拒否する。
- [`hypothesis-tracker.md`](hypothesis-tracker.md) の H-5 にある「CHASE が高 alpha なら追いかけを排除せず、extension risk で選別する」は仮説の判定基準であり、いまのライブBUY許可ではない。

新しいライブ例外はこの文書では作らない。

`extension_risk=HIGH` はデュアルゲートとは別の既存ハードゲートとして維持する。モードが `EARLY_MOMENTUM` または `BALANCED` でも、extension が HIGH ならライブBUYしない。

## `/review` のウェイト凍結

`/review` と `/decision` は、この暫定規則を理由にスコアを動かさない。

- Quality Momentum **60 / 25 / 15** を変更しない。
- 最初の12週間、および独立した満期 run が 10 未満のあいだは、既存どおりウェイトを固定する（[`strategy-v2.md`](strategy-v2.md) の検証節）。
- pooled IC や約15件の V2 スナップショットだけを根拠に重みを変えない。
- HIGH conviction のサイズは、既存レビューゲート（独立満期 OOS 30件、MEDIUM より上位群の alpha と downside の改善、最大DD 6% 以内、ルール遵守 100%）を満たすまで有効化しない。

## `/decision` での確認順

PM 合成でライブBUYを出す前に、次を上から確認する。一つでも欠ければライブBUYにしない。

1. `score ≥ 7.5` か（十分ではない）。
2. `primary_mode` が `EARLY_MOMENTUM` または `BALANCED` か。
3. その候補の他ファクターと比べてファンダが相対的に強く、fundamentals grade は A/B か。
4. CHASE なら WAIT。paper / 100万円シミュレーションへ残す場合も実弾にしない。
5. 既存ハードゲート（`extension_risk=HIGH`、catalyst A/B、stop/target、data gap、R/R、heat、audit）も満たすか。

サイズは従来どおり `investor/core/risk.py` が決める。LLM の裁量サイズは使わない。

## コードとの境界

既存の送信前チェック（`investor/agents/decision_agent.py`）は `CHASE_MOMENTUM` と `extension_risk=HIGH` をライブ送信から拒否する。スコアが 7.5 以上でも十分ではないこと、モードを `EARLY_MOMENTUM` / `BALANCED` に限ること、ファンダの相対比較は、この文書と `/decision` の PM 合成が適用する。この規則の追加では、スコアウェイトもその Python ゲートも変えない。

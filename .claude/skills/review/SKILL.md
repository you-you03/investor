---
description: Strategy V2のOOS予測精度・alpha・ドローダウン・ルール遵守を検証する
argument-hint: ""
allowed-tools: Bash(.venv/bin/python *) Bash(cat *) Read
---

# Review — Strategy V2

`quality_momentum_v2_2026-07-25` の検証を行う。pool済み観測へ繰り返し適合して
ウェイトを動かさない。

## 1. Outcomes更新

```bash
.venv/bin/python scripts/record_outcomes.py
.venv/bin/python scripts/fetch_returns.py
.venv/bin/python scripts/validate_scores.py
```

`week1`〜`week12` を追跡する。

## 2. データ分離

- `strategy_version` ごとに集計する
- legacyとStrategy V2を混ぜた数字は移行参考値としてだけ表示する
- 同一run・同一tickerのretry/backfillを1観測へ重複排除する
- ライブ方針の主指標はrun別12週SPY alpha IC
- pooled IC、単一tickerの反復観測、1〜3週結果は診断用

## 3. 必須評価

1. 12週SPY alpha、勝率、中央値、P10
2. 最大ドローダウンとportfolio heat
3. stop/target、サイズ、約定確認のrule adherence
4. score ≥7.5 と <7.5 の12週alpha差
5. fundamentals/catalyst grade別の12週alpha
6. CHASE/HIGH extensionを回避した機会損失とdownside回避
7. BUY、WAIT、PASSのcounterfactual

## 4. 変更禁止条件

- Strategy V2の独立した満期runが10未満ならウェイトを変更しない
- 最初の12週間はウェイトを固定する
- pooled factor correlationだけを理由に重みを変えない
- HIGH convictionは独立した満期OOS観測30件まで有効化しない

データ不足時は「計測継続」と結論し、具体的な次回判定日と必要run数を示す。

## 5. 転換条件

次のいずれかなら、ライブサイズ縮小または新規BUY停止を提案する。

- 最大DD > 6%
- rule adherence < 100%
- 独立runが10以上あり、12週run別alpha IC中央値 ≤ 0
- score ≥7.5群の12週SPY alphaが≤0

## 6. 出力

```markdown
# Strategy V2 Review — YYYY-MM-DD

## 判定
継続 / 縮小 / 停止 / 再設計

## 独立OOS
| 指標 | 値 | 必要水準 | 判定 |

## リスクと遵守
| 最大DD | Heat | Stop/Target欠損 | 未確認約定 | 遵守率 |

## 最も弱い仮説
...

## 次回まで固定するもの
...

## 転換条件
...
```

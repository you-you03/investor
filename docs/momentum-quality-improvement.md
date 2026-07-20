# Momentum 信頼性改善メモ

作成日: 2026-07-05

## 背景

現行 score の `momentum` は、初動/追いかけモメンタム、相対強度、extension risk を評価する。
信頼性を上げるには、単に「直近で上がっている銘柄」を拾うのではなく、**今後も買い需要が続きやすい価格・出来高・相対強度の構造**を測る必要がある。

## Momentum Grade

```text
momentum_grade:
  A: 相対強度が強く、出来高確認あり、過熱は許容範囲、継続構造がある
  B: 方向性は良いが、出来高・過熱・セクター追い風の一部が不足
  C: 上昇しているが entry が遅い、または early 根拠が弱い
  D: 急騰後の飛び乗り、出来高品質が悪い、相対強度が弱い
```

運用ルール:

- A: momentum score 8-9 許可
- B: momentum score 6-7
- C: momentum score 4-5。watchlist / WAIT
- D: momentum score 0-4。PASS / WAIT

## 評価軸

### 1. Relative Strength の持続性

単日の上昇率ではなく、SPY / QQQ / sector に対する継続的な優位を見る。

追加して見る指標:

- rs_1m
- rs_3m
- sector alpha
- QQQ alpha
- 相対強度の改善トレンド

暫定ゲート:

- rs_signal が STRONG_UNDERPERFORM の候補は momentum grade D
- market mover でも rs_1m / rs_3m が弱い場合は momentum grade C 以下
- セクターが LAGGING の場合、momentum grade A は原則不可

### 2. Volume Confirmation

上昇が本物の需要を伴っているかを見る。

高評価:

- 上昇日に volume_ratio_20d > 1.5
- 出来高増加が複数日続く
- pullback 時の出来高が低下
- breakout 後に高値圏を維持

低評価:

- 出来高のない上昇
- 1日だけの異常出来高
- 出来高急増の陰線
- gap up fade

暫定ゲート:

- volume confirmation がない chase momentum は score 上限 7
- 出来高急増陰線や gap up fade は momentum grade D

### 3. Early Momentum の品質

early momentum は「弱い値動き」ではない。
価格がまだ過熱していない状態で、上昇開始の構造があるかを見る。

高評価:

- RSI 45-65
- price が EMA20 / EMA50 近辺
- MACD 改善
- BB compression から拡大初期
- return_5d / return_20d が過熱していない
- relative strength が改善中

低評価:

- 単に動いていないだけ
- rs_signal が弱い
- 出来高が減少し続けている
- 価格がレンジ下限を割っている

暫定ゲート:

- rs_signal が UNDERPERFORM の early momentum は原則 C 以下
- 出来高または RS 改善がない early momentum は最大6

### 4. Chase Momentum の品質

chase momentum は「すでに上がっているが、まだ買い需要が続く」状態だけを高評価する。

高評価:

- STRONG_OUTPERFORM
- price above EMA20 / EMA50
- volume confirmation あり
- RSI 55-75
- high tight flag / consolidation after breakout

低評価:

- RSI 85以上
- 5日 +10%以上
- 20日 +25%以上
- 52週高値 3%以内で過熱
- gap up 後に失速

暫定ゲート:

- extension_risk HIGH の chase は momentum grade C 以下
- RSI 85以上は momentum grade D
- 52週高値 3%以内 + RSI 70以上は momentum grade C/D

### 5. Momentum Failure Signal

強かった momentum が崩れ始めていないかを見る。

失敗シグナル:

- breakout failure
- EMA20 割れ
- 出来高急増の下落
- RS の急低下
- catalyst 後に株価が維持できない
- 市場上昇日に逆行安

暫定ゲート:

- failure signal が複数ある場合は momentum grade D
- open position では exit review 対象

## 偽陽性を減らすルール

- 単日の上昇率だけで高評価しない
- movers / gainers に入っているだけでは momentum と見なさない
- 出来高確認のない chase momentum は高評価しない
- early momentum は「まだ動いていない」ではなく「上昇開始の構造あり」と定義する
- extension risk HIGH は明確に減点する

## 記録形式

`score_evidence.momentum` に最低限以下を残す。

```text
momentum_grade:
primary_mode:
early_momentum_score:
chase_momentum_score:
extension_risk:
rs_1m:
rs_3m:
volume_confirmation:
failure_signal:
reason_for_score:
```

## 実装候補

- `momentum_grade` を research output に追加する
- RS trend と volume confirmation を構造化して保存する
- `failure_signal` を technicals / monitor に追加する
- `momentum_grade` を `score_snapshots.json` に保存する
- mode 別だけでなく grade 別に validation できるようにする

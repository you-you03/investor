# Technical 信頼性改善メモ

作成日: 2026-07-05

## 背景

現行 score の `technical` は、RSI、MACD、EMA、Bollinger Bands、entry timing を評価する。
検証上は単独予測力が弱いため、technical を「上がりそうか」の主因として使うのではなく、**今の entry が割に合うかを測る entry quality / risk management 指標**として改善する。

## Technical Grade

```text
technical_grade:
  A: 低過熱、明確な支持線、出来高確認、risk/reward >= 2.0
  B: 形は良いが一部過熱または stop がやや遠い
  C: 方向は上だが entry が遅い、risk/reward 不十分
  D: RSI極端、垂直上昇後、支持線遠い、breakout failure リスク大
```

運用ルール:

- A: entry 許可。サイズ通常
- B: entry 許可。ただし少し小さめ
- C: WAIT。押し目条件を watchlist に記録
- D: PASS / WAIT。追いかけ禁止

## 評価軸

### 1. 価格位置

どこで買うのかを見る。

追加して見る指標:

- price vs EMA20
- price vs EMA50
- 52週高値からの距離
- 直近サポートからの距離
- ATR に対する stop 距離

暫定ゲート:

- price が EMA20 から +8%以上乖離なら technical grade C 以下
- 52週高値 3%以内かつ RSI 70以上なら technical grade C/D
- stop が明確に置けない場合は technical grade C 以下

### 2. 過熱

すでに伸び切っていないかを見る。

追加して見る指標:

- RSI
- return_5d_pct
- return_20d_pct
- pct_above_ema20
- pct_above_ema50

暫定ゲート:

- RSI 85以上: technical grade D
- RSI 70以上 + 52週高値 3%以内: technical grade C/D
- 5日 +10%以上: extension risk
- 20日 +25%以上: extension risk
- extension risk HIGH は entry quality を下げる

### 3. 出来高品質

ブレイクが本物かを見る。

高評価:

- breakout と同時に volume_ratio_20d > 1.5
- 出来高増加が複数日続く
- 上昇日に出来高増、下落日に出来高減

低評価:

- 出来高なしの breakout
- 出来高急増の陰線
- gap up fade
- 1日だけの急騰

暫定ゲート:

- 出来高なしの breakout は technical score 最大6
- 出来高急増陰線、または gap up fade は technical grade D

### 4. 構造

consolidation からの breakout か、垂直上昇後の飛び乗りかを見る。

高評価:

- volatility contraction
- Bollinger Band squeeze からの上放れ
- EMA20 近辺での反発
- 直近レンジを出来高付きで突破

低評価:

- 連続急騰後の新高値
- サポートから遠い位置
- breakout failure 後の再突入
- gap up 直後でリスクリワードが悪い

### 5. Risk/Reward

entry, target, stop の関係が成立しているかを見る。

暫定ゲート:

- target までの距離 / stop までの距離 < 2.0 なら technical grade C 以下
- stop が 1 ATR 以内に置けない場合は entry 品質を下げる
- technical が良くても RR 不足なら WAIT

## 偽陽性を減らすルール

- RSI や MACD だけで高評価しない
- breakout は出来高確認がなければ高評価しない
- 高値圏の強いチャートは、支持線との距離と RR を必ず確認する
- gap up は初動ではなく entry risk として扱う
- technical は thesis ではなく entry 判断に限定する

## 記録形式

`score_evidence.technical` に最低限以下を残す。

```text
technical_grade:
entry_quality:
extension_risk:
support_or_stop_reference:
risk_reward:
volume_confirmation:
wait_condition_if_any:
reason_for_score:
```

## 実装候補

- `risk_reward_ratio` を research output に追加する
- `distance_to_support_pct` を technicals に追加する
- `gap_up_fade` / `breakout_failure` を検出する
- `technical_grade` と `entry_quality` を `score_snapshots.json` に保存する
- technical grade C/D の場合は watchlist に具体的な wait condition を残す

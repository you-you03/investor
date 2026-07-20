# Fundamentals 信頼性改善メモ

作成日: 2026-07-05

## 背景

`score_snapshots.json` の検証では、fundamentals は他ファクターよりリターン予測力が高い。
ただし、現在の fundamentals 評価は主に `revenue_growth_yoy`、`earnings_growth_yoy`、`forward_pe`、`peg_ratio` に寄っており、以下のリスクを十分に落とし切れていない。

- 一時的な決算反動による高成長
- 売上だけ伸びて FCF / 利益品質が伴わない企業
- 赤字ハイグロースの増資・希薄化リスク
- バランスシート耐久性の不足
- セクターごとの見るべき指標の違い
- データ欠損を narrative で補ってしまうリスク

改善の方向性は、fundamentals のウェイトを上げることではなく、**fundamentals 自体を「高成長判定」から「持続可能な利益成長判定」に変えること**。

## 改善方針

### 1. FCF / Cash Flow を必須化する

Revenue / EPS が強くても、FCF が悪化している銘柄はモメンタム崩壊時に弱い。
特に赤字・ハイグロース・小型株では、売上成長よりも資金繰りと株主価値の希薄化が損失要因になりやすい。

追加して見る指標:

- free_cash_flow がプラスか
- operating_cash_flow が売上成長に追随しているか
- FCF margin が改善しているか
- FCF burn が縮小しているか
- cash runway が 18 か月以上あるか

暫定ゲート:

- FCF 不明なら fundamentals 8 以上不可
- FCF 赤字かつ cash runway < 18 か月なら HIGH conviction 不可
- Revenue 高成長でも FCF burn 拡大なら fundamentals を B 以下に制限

### 2. 成長率ではなく成長加速度を見る

単発の YoY 成長率だけでは、ピークアウト直前の銘柄を高く評価しやすい。
fundamentals の信頼性を上げるには、絶対値よりも四半期トレンドを重視する。

追加して見る指標:

- revenue_growth_yoy が加速しているか
- EPS growth が 2 四半期連続で改善しているか
- gross margin / operating margin が改善しているか
- guidance が上方修正されているか

判定例:

- `+18% → +26% → +35%`: 加速。高評価しやすい
- `+120% → +80% → +45%`: 高成長でも減速。過信しない
- Revenue 加速 + margin 改善: quality growth
- Revenue 加速 + margin 悪化: low-quality growth として扱う

### 3. 希薄化リスクを明示的に入れる

小型グロース、宇宙、量子、バイオ、赤字 AI 系は、株価が上がっても増資で株主価値が薄まる可能性がある。
Revenue growth が高くても、share count が増え続ける企業は fundamentals の質を下げて評価する。

追加して見る指標:

- shares_outstanding の YoY 増加率
- stock-based compensation
- 直近の増資履歴
- ATM offering / shelf registration の有無
- cash runway と追加資金調達の必要性

暫定ゲート:

- share count YoY +5%以上: 減点
- share count YoY +10%以上: 強めに減点
- FCF 赤字 + 希薄化進行: HIGH conviction 不可
- dilution data 不明の赤字企業: HIGH conviction 不可

### 4. バランスシート耐久性を中核に入れる

risk-off や金利高の局面では、成長率よりも財務耐久性が効く。
特に strict stop 運用では、バランスシートが弱い企業はニュース悪化や市場逆風で即座に売られやすい。

追加して見る指標:

- net debt / EBITDA
- interest coverage
- current ratio
- cash vs debt
- debt maturity risk
- debt_to_equity の異常値

暫定ゲート:

- debt/FCF が高い企業は fundamentals 上限を下げる
- interest coverage 不明かつ高 debt の企業は HIGH 不可
- cash < debt かつ FCF 赤字なら小型グロースは原則 WAIT/PASS

### 5. Quality of Growth を分けて評価する

同じ Revenue +50% でも、利益品質は企業によって大きく違う。
今後は「高成長」ではなく「質の高い成長」を評価対象にする。

高品質な成長:

- gross margin が高い、または改善中
- recurring revenue / backlog / RPO が伸びている
- operating leverage が出ている
- customer concentration が低い
- pricing power がある
- EPS / FCF が売上成長に追随している

低品質な成長:

- 赤字拡大
- gross margin 悪化
- 売上だけ伸びて EPS / FCF がついてこない
- 増資依存
- 一時的な特需
- analyst target だけが強く、実績データが弱い

### 6. セクター別チェックリストを導入する

全セクターを同じ PE / PEG / EPS 成長で見ると歪む。
fundamentals は汎用指標に加えて、セクターごとの重要指標を確認する。

半導体:

- revenue acceleration
- gross margin trend
- inventory / cycle risk
- capex cycle
- customer concentration

SaaS / Software:

- Rule of 40
- net revenue retention
- RPO / billings growth
- FCF margin
- sales efficiency

Fintech:

- take rate
- transaction volume
- credit loss / delinquency
- funding cost
- regulatory risk

Biotech:

- cash runway
- clinical catalyst quality
- dilution risk
- pipeline concentration

宇宙 / 防衛 / Gov-Tech:

- backlog
- contract quality
- gross margin
- milestone risk
- funding / dilution risk

### 7. データ欠損時は高評価しない

データが取れないときに narrative で補うと、fundamentals の信頼性が落ちる。
欠損は「不明」ではなく、fundamentals 評価の上限として扱う。

暫定ゲート:

- FCF 不明: fundamentals 8 以上不可
- revenue / EPS の四半期推移が不明: HIGH conviction 不可
- share dilution 不明の赤字企業: HIGH conviction 不可
- debt / cash 不明の小型グロース: MEDIUM 上限
- critical data gap がある場合: BUY ではなく WAIT を優先

## 推奨する新しい fundamentals 構造

数値の合成点を複雑にしすぎるより、まずは grade 化して PM 判断に使う。

```text
fundamentals_grade:
  A: 高成長 + 利益/FCF改善 + 財務健全 + 希薄化なし
  B: 高成長だが FCF/利益/財務に一部不安
  C: 売上成長のみ。利益・FCF・希薄化に不安
  D: 成長鈍化、赤字拡大、財務/希薄化リスク大
```

運用ルール:

- A: HIGH conviction 許可
- B: MEDIUM まで
- C: 原則 WAIT。強いカタリストがある場合のみ小さく検討
- D: PASS

内部スコア化する場合の構成:

```text
fundamentals_score =
  growth_quality
  + profitability_trend
  + cash_flow_quality
  + balance_sheet_quality
  + valuation_reasonableness
  - dilution_risk
  - data_gap_penalty
```

## 実装候補

### Data layer

- `get_financials` に FCF、operating_cash_flow、cash、debt、shares_outstanding を追加する
- 過去 4 四半期だけでなく、YoY / QoQ の加速度を計算して返す
- `get_ticker_details` に current_ratio、total_cash、total_debt、shares_outstanding、free_cashflow があれば保存する
- dilution history を `score_snapshots.json` に保存する

### Research prompt

- Step 1 Fundamentals を grade 方式に変更する
- Revenue / EPS だけで HIGH floor を付けない
- FCF / dilution / data gap の上限ルールを追加する
- `score_evidence.fundamentals` に以下を必須記録する:
  - revenue_growth_yoy
  - earnings_growth_yoy
  - FCF / FCF margin
  - margin trend
  - cash/debt
  - dilution risk
  - fundamentals_grade

### Decision prompt

- `fundamentals_grade=A` だけ HIGH 許可
- `fundamentals_grade=B` は MEDIUM 上限
- `fundamentals_grade=C` は原則 WAIT
- `fundamentals_grade=D` は PASS
- CRITICAL data gap がある場合は BUY を避ける

## 優先順位

最初に入れるべき改善:

1. FCF / cash runway gate
2. dilution risk gate
3. revenue / EPS acceleration
4. data gap ceiling
5. sector-specific checklist

特に効果が大きそうなのは、**低品質な高成長を落とすこと**。
fundamentals はすでに予測力があるため、次の改善はウェイト調整ではなく、false positive を減らす測定品質改善に集中する。

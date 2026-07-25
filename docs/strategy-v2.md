# Strategy V2 運用規約

Version: `quality_momentum_v2_2026-07-25`

## 勝ちの定義

週次の利益額を追わず、12週間ローリングで以下を満たすことを勝ちとする。

- SPY対比alphaがプラス
- 最大ドローダウン6%以内
- stop/target、サイズ、約定記録のルール遵守100%
- 独立したdecision run内で、スコア順位と12週SPY alphaが正の関係

条件を満たす候補がない週の `HOLD_CASH` は失敗ではない。

## 戦う市場

対象は、流動性があり、収益・キャッシュフローで事業品質を検証でき、3〜12週で認識され得る
材料と持続的な相対強度を持つ米国株。

次はライブBUYを避ける。

- pre-revenue、binary clinical、低流動性
- 1日/5日の急騰を主因とする追いかけ
- `CHASE_MOMENTUM` または `extension_risk=HIGH`
- fundamentals/catalyst grade C/D
- critical data gap、stop/target欠損、reward/risk 1.5未満

## スコア

```text
total = fundamentals * 0.60
      + medium_term_momentum * 0.25
      + verified_catalyst * 0.15
```

TechnicalとSentimentは加点軸ではなく、entry・risk・矛盾検知のgateとして扱う。
ライブ候補閾値は7.5。HIGH convictionは独立した満期OOS観測30件まで無効。

## リスク

- ライブ資金: 約$1,340
- 最大同時ポジション: 3
- 1銘柄最大: 25%
- 1トレード基準リスク: 0.75%
- portfolio heat上限: 2.0%
- gap/slippage buffer: entryの0.25%
- stopとtargetは新規記録時に必須
- 株価に依存して意味が変わる「同一ticker 2株上限」は廃止
- キャッシュ稼働率ノルマは廃止

LLMが提示した株数や金額は実行値にしない。`investor/core/risk.py` がentry、stop、target、
資金制約から決定する。既存ポジションにリスク欠損、stop breach、集中超過があれば新規BUYを停止する。

## 出口

- `shares >= 4` のみ段階利確を許可
- `shares < 4` は部分利確せず、目標到達時に全株exit review
- 3週目はテーゼレビューであり、自動決済期限ではない
- stop/trailing alertは発注計画。ブローカー約定確認後のみ台帳を更新する
- ブローカー接続がない状態で「売却済み」と記録しない

## 検証

- 全スコアを1〜12週追跡する
- pooled ICは診断専用
- 主指標は、同一run・同一tickerを重複排除した12週SPY alphaのrun別IC
- 10 independent matured runs未満ではウェイトを変更しない
- Strategy V2のウェイトは最初の12週間固定する

### 転換条件

次のいずれかでライブ運用を縮小し、Strategy V2を再設計する。

- 最大ドローダウンが6%を超える
- stop/target欠損または未確認約定の台帳反映が発生する
- 12週満期の独立runが10以上あり、run別alpha IC中央値が0以下
- fundamentals/catalyst A/B銘柄の12週alphaが継続してマイナス

次の全条件を満たすまでHIGH convictionを有効化しない。

- Strategy V2の独立した満期OOS観測が30件以上
- MEDIUMより上位群のalphaとdownsideが明確に改善
- 最大DD 6%以内、ルール遵守100%

## 現行ポジションの移行

既存データを自動で書き換えたり、約定なしにcloseしたりしない。代わりに新規BUYをfail-closedで止め、
各ポジションについてstop/target欠損、stop breach、集中超過を解消してから再開する。
実際の売買は人間または将来の確認可能なbroker connectorが行う。

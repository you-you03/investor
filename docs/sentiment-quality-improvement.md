# Sentiment 信頼性改善メモ

作成日: 2026-07-05

## 背景

現行 score の `sentiment` は、analyst rating、options flow、insider activity、news / X sentiment を評価する。
信頼性を上げるには、単に「人気がある」「強気コメントがある」ではなく、**株価を押し上げる継続的な需要や再評価が発生しているか**を測る必要がある。

## Sentiment Grade

```text
sentiment_grade:
  A: 複数ソースで一致した強気再評価。analyst revision / options / insider / news が整合
  B: 強気材料はあるが、ソースが一部に偏る
  C: 話題性はあるが、機関需要や業績接続が弱い
  D: 後追い人気、逆張りリスク、insider sell / bearish options などが目立つ
```

運用ルール:

- A: sentiment score 8-9 許可
- B: sentiment score 6-7
- C: sentiment score 4-5。BUY の主根拠にしない
- D: sentiment score 0-4。場合によっては逆風として扱う

## 評価軸

### 1. Analyst Revision Quality

analyst recommendation よりも、estimate revision と target revision の方向を重視する。

高評価:

- 複数アナリストの同時 upgrade
- EPS / revenue estimate の上方修正
- target price 引き上げが連続
- 強気理由が fundamentals / catalyst と整合

低評価:

- target price が高いだけ
- analyst_count が少ない
- 古い rating
- 株価急騰後の後追い target raise

暫定ゲート:

- analyst target upside だけでは sentiment A 不可
- analyst_count < 5 の strong buy は最大7
- estimate revision が確認できない場合は A 不可

### 2. Options Flow Quality

put/call ratio だけではなく、質を見る。

高評価:

- call volume が通常より大きく増加
- put/call ratio が低い
- expiration が近すぎず、イベントと整合
- price action と options flow が同方向

低評価:

- 0DTE / 短期 lottery 的な call 偏り
- 株価下落中の call 買いだけ
- put volume 増加
- earnings 前のギャンブル需要

暫定ゲート:

- options BULLISH だけでは sentiment A 不可
- earnings 直前の options 偏りは event risk として扱う
- options BEARISH は sentiment 上限6

### 3. Insider Activity Quality

insider buy / sell の中身を見る。

高評価:

- CEO / CFO / founder の open market buy
- 複数役員の買い
- 金額が meaningful
- 売却ではなく純買い

低評価:

- 10b5-1 plan による機械的売却
- small insider buy
- SBC / option exercise に伴う売却
- 大規模 insider sell

暫定ゲート:

- NET_BUYER でも金額・役職が弱い場合は +1 まで
- NET_SELLER は sentiment 上限6
- 大規模 insider sell + 高バリュエーションは HIGH conviction 不可寄り

### 4. News / X Sentiment Quality

話題化と投資需要を分ける。

高評価:

- 専門性の高い複数ソースが同じ thesis を支持
- news が fundamentals / catalyst と接続
- institutional ownership や analyst revision と整合

低評価:

- SNS だけの話題
- meme 的な急騰
- price action の後付け記事
- 情報源が少ない
- negative news が混在

暫定ゲート:

- X sentiment だけでは sentiment score 最大6
- news source が単発なら最大6
- meme / retail frenzy は sentiment 加点ではなく volatility risk として扱う

### 5. Cross-source Confirmation

sentiment は単一ソースではなく、複数ソースの整合で評価する。

高評価パターン:

- analyst estimate revision + options bullish + insider buy
- guidance raise + analyst upgrades + institutional accumulation
- positive news + analyst revision + ownership increase

低評価パターン:

- options bullish だけ
- X buzz だけ
- target upside だけ
- insider buy だけ

暫定ゲート:

- 強気ソースが1種類だけなら sentiment B まで
- 強気ソースが複数でも fundamentals / catalyst と矛盾するなら B 以下
- bearish options または insider sell がある場合は、強気 narrative を割り引く

## 偽陽性を減らすルール

- single-source sentiment を高評価しない
- X / news の話題性だけで sentiment A にしない
- analyst target upside だけを強気再評価として扱わない
- options flow は期間・イベント・価格反応と合わせて見る
- insider activity は役職、金額、取引種別を確認する

## 記録形式

`score_evidence.sentiment` に最低限以下を残す。

```text
sentiment_grade:
analyst_revision_quality:
options_flow_quality:
insider_activity_quality:
news_x_quality:
cross_source_confirmation:
contradictory_signals:
reason_for_score:
```

## 実装候補

- `sentiment_grade` を research output に追加する
- analyst target だけでなく estimate revision を取得する
- options flow に expiration / unusual volume / put volume を追加する
- insider activity に role / transaction type / plan sale 判定を追加する
- `single_source_sentiment` フラグを追加する
- `sentiment_grade` を `score_snapshots.json` に保存する

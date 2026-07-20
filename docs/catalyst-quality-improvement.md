# Catalyst 信頼性改善メモ

作成日: 2026-07-05

## 背景

現行 score の `catalyst` は、決算、ガイダンス、アナリスト改定、イベント、ニュースを評価する。
検証上は単独予測力が弱く、材料の存在と、実際に株価へ効く未織り込みの業績変化を混同している可能性がある。

改善の方向性は、catalyst を「ニュースがあること」ではなく、**1〜8週間以内に株価へ反映され得る、未織り込みの業績・期待値変化**として測ること。

## Catalyst Grade

```text
catalyst_grade:
  A: 業績インパクトが明確、1-8週以内、未織り込み、公式/複数ソース確認あり
  B: 方向性は強いが、業績インパクトまたはタイミングに一部不確実性
  C: ニュース性はあるが、株価/業績への接続が弱い
  D: 技術的ブレイク、SNS話題、単発記事、既に織り込み済み
```

運用ルール:

- A: catalyst score 8-9 許可
- B: catalyst score 6-7
- C: catalyst score 4-5。BUY の主根拠にしない
- D: catalyst score 0-4。場合によっては過熱リスクとして扱う

## 評価軸

### 1. 具体性

何が起きるのかが明確かを見る。

高評価:

- guidance raise
- estimate revision
- large contract
- product shipment
- regulatory approval
- backlog expansion

低評価:

- 「AI関連」「防衛テーマ」「量子テーマ」など narrative だけ
- 出所不明の期待
- 株価上昇後に付いた説明記事

### 2. 時間軸

1〜8週間以内に検証可能かを見る。

高評価:

- 決算後の estimate revision
- 近日中の investor day / product launch
- 近い受注・納入・承認イベント

低評価:

- 数年先の TAM narrative
- いつ業績に出るか不明なテーマ
- 期限がない期待

### 3. 業績接続

revenue / margin / EPS / FCF にどう効くか説明できるかを見る。

暫定ゲート:

- 業績接続を説明できない catalyst は最大5点
- 公式資料で revenue impact が確認できる場合のみ 8点以上を許可
- 「市場が好感しそう」だけでは STRONG catalyst 不可

### 4. 未織り込み度

材料がすでに株価に反映されていないかを見る。

暫定ゲート:

- catalyst 後に株価がすでに +15%〜20% 以上なら加点しない
- 既に大きく織り込まれた catalyst は grade C/D に落とす
- analyst target upside が高くても、株価がすでに急伸している場合は過信しない

### 5. ソース品質

情報源が信頼できるかを見る。

高評価:

- 会社公式発表
- 決算資料 / transcript
- 複数アナリストの estimate revision
- SEC filing

低評価:

- 単発ニュース
- SNS
- 出所不明の噂
- price action からの後付け narrative

暫定ゲート:

- source が 1 つだけ、かつ公式/決算資料でない場合は最大6点
- analyst target upside だけでは STRONG catalyst 不可
- earnings が近いだけでは catalyst 不可。beat / raise / revision が必要

## 偽陽性を減らすルール

- technical breakout だけを catalyst として扱わない
- unexplained spike は catalyst ではなく data gap として扱う
- 決算日接近だけで加点しない。期待値変化が必要
- 単発 upgrade は B まで。複数 upgrade / estimate revision があって初めて A 候補
- catalyst 後に急騰済みなら「材料あり」ではなく「織り込み済み」として扱う

## 記録形式

`score_evidence.catalyst` に最低限以下を残す。

```text
catalyst_grade:
catalyst_type:
event_date:
business_impact:
time_to_impact:
source_quality:
priced_in_check:
reason_for_score:
```

## 実装候補

- catalyst event date / source / source quality を保存する
- catalyst 後の price move を `priced_in_check` として計算する
- `business_impact` と `time_to_impact` を research output に必須化する
- source が弱い catalyst は自動で grade 上限を設ける
- `score_snapshots.json` に `catalyst_grade` を保存する

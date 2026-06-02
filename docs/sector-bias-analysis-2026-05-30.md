# investor セクター偏り分析

作成日: 2026-05-30

---

## 結論

`investor/` のリサーチ結果が IT や半導体に寄ったのは、相場がそうだっただけではない。  
プロジェクトの設計自体が、今の相場ではその方向に候補を集めやすい。

特に効いているのは次の3点。

1. 戦略が最初から「米国グロース株」「短中期」「モメンタム・決算・ブレイクアウト重視」
2. `top_sectors` を優先し、`bottom_sectors` を強く除外する prompt 設計
3. watchlist と過去の勝ち筋がテック寄りで、そのまま次の候補生成にも影響している

---

## 現状評価

### 戦略

評価: ○

今の `investor/` は、実質的に「AI・半導体・ソフトウェア中心のグロースモメンタム戦略」になっている。
これは意図とズレているというより、今の戦略定義にかなり忠実。

根拠:

- `/research` の system prompt が「US growth stocks」「high-risk/high-reward」「momentum / near-term catalysts / technical breakouts / earnings surprises」を明示している  
  [research_prompts.py](/Users/yutaobayashi/PERSONAL%20DEV/1_now/investor/investor/prompts/research_prompts.py:1)
- 直近の研究メモでも、強い地合いとして `Semiconductors / Technology / Cloud/Software` を上位セクターと認識している  
  [stock_research_2026-05-30.md](/Users/yutaobayashi/PERSONAL%20DEV/1_now/investor/reports/research/stock_research_2026-05-30.md:10)

### 戦術

評価: △

相場の強いセクターを取りにいく戦術自体は合理的。ただし、今の実装では「強いセクターを少し優先する」ではなく、
「強いセクター以外がかなり候補から落ちやすい」構造になっている。

根拠:

- `top_sectors` を優先し、`bottom_sectors` は strong catalyst がない限り除外するルール  
  [research_prompts.py](/Users/yutaobayashi/PERSONAL%20DEV/1_now/investor/investor/prompts/research_prompts.py:20)
- 候補選定時に「6-10銘柄を選ぶときは top_sectors を優先」と明記されている  
  [research_prompts.py](/Users/yutaobayashi/PERSONAL%20DEV/1_now/investor/investor/prompts/research_prompts.py:59)

### 手段

評価: △

コードとデータの運用を見ると、偏りを止める仕組みが弱い。

根拠:

- decision prompt には「sector concentration を避ける」とあるが、実コードの `validate_proposals()` は
  ポジション数・サイズ・stop しか見ていない  
  [decision_prompts.py](/Users/yutaobayashi/PERSONAL%20DEV/1_now/investor/investor/prompts/decision_prompts.py:178)  
  [decision_agent.py](/Users/yutaobayashi/PERSONAL%20DEV/1_now/investor/investor/agents/decision_agent.py:126)
- persona 選定も tech sector では `innovator / tenbagger / tape_reader` を優先しやすい  
  [personas.py](/Users/yutaobayashi/PERSONAL%20DEV/1_now/investor/investor/prompts/personas.py:375)

---

## どこで偏るか

### 1. 候補母集団がすでにテック寄り

`SCREEN_UNIVERSE` のセクターマッピングを見ると、`Semiconductors/AI` と `Cloud/Software` の候補数が多い。  
しかもスクリーニング条件が `52w breakouts`、`earnings surprises`、`momentum` なので、今の相場ではその2群が最も通りやすい。

参照:

- [research_prompts.py](/Users/yutaobayashi/PERSONAL%20DEV/1_now/investor/investor/prompts/research_prompts.py:36)
- [research_prompts.py](/Users/yutaobayashi/PERSONAL%20DEV/1_now/investor/investor/prompts/research_prompts.py:49)

### 2. セクター相対強度ルールが強い

`top_sectors` 優先と `LAGGING` 除外が強く、相場がテック主導の期間は候補が同じ方向に固まる。

今回の研究でも、上位セクターは `Semiconductors / Technology / Cloud/Software` だった。  
したがって、ルール通りにやると `NVDA / AMD / MRVL / MU / AMAT / TSM / TEAM` のような候補が自然に増える。

### 3. watchlist が自己増幅する

2026-05-30 時点の active watchlist 12銘柄は:

`MRVL / MU / AMAT / COHR / RKLB / AMD / FLY / LUNR / QBTS / INFQ / RGTI / NOK`

このうち、半導体系は `MRVL / MU / AMAT / COHR / AMD`、宇宙・量子・通信のようなテック隣接がさらに多い。
つまり watchlist 自体が次の研究候補をテック寄りに押し続ける。

### 4. 過去の勝ち筋がテック側に寄っている

closed positions を見ると、良かったトレードは `AAOI / ALAB / CRDO / PANW / TEAM` などテック寄りが多い。  
一方で `UAL / WAT` のような非テック側は弱かった。

その結果、

- 人間が watchlist に入れる銘柄
- `/watchlist-research` が残す銘柄
- `/decision` で許容される銘柄

が同じ方向に寄りやすい。

### 5. セクター分散のルールが文章止まり

「同じセクターに寄りすぎない」は prompt にあるが、機械的に止める処理がない。
そのため、最終的には PM 判断のニュアンス頼みになる。

実際、2026-05-30 時点の open positions は:

`TSM / TEAM / LRCX / NVDA / VRT`

で、かなりテック・AIインフラ寄りになっている。

---

## 問題点

1. `top_sectors` 優先が強く、相場がテック主導のときに候補が自然分散しない
2. watchlist の構成がすでにテック寄りで、候補生成の偏りを再生産している
3. セクター集中回避が prompt にはあるが、コードでは強制されていない
4. recent candidate data に `sector` が十分入っておらず、セクター制御を安定実装しにくい

---

## 改善案

### 1. セクター集中をコードで制御する

`validate_proposals()` に次のような制約を入れる。

- 同一セクター最大2銘柄
- 同一テーマ最大40%まで
- すでに半導体3枠ある場合、新規半導体は WAIT 強制

これをやらない限り、「避けるべき」と書いてあっても止まらない。

### 2. 候補選定にセクター上限を入れる

たとえば `/research` の最終候補 6-10件に対して:

- Semiconductors max 2
- Cloud/Software max 2
- Other sectors min 2

のようなバランス制約を持たせる。

### 3. watchlist をテーマ別に管理する

`watchlist.json` にカテゴリを持たせる。

- `semis`
- `software`
- `space`
- `quantum`
- `network`
- `defensive`

このカテゴリ単位で active 上限を設けると、watchlist の自己増幅が抑えやすい。

### 4. 候補データに sector を必ず保存する

直近の `research_history.json` の候補を見ると `sector=None` が多い。
これでは prompt はセクターを見ていても、実データに基づく制御が弱い。

### 5. 戦略を分ける

もし本当に分散したいなら、1つの戦略で全部やるより、

- `growth_momentum`
- `diversified_rotation`

のように戦略モードを分ける方が自然。

今の `investor/` は後者ではなく、前者としてはかなり一貫している。

---

## 要点

今回の IT・半導体偏りは、主に次の3つが原因。

1. 相場の主役がそのセクターだった
2. `investor/` の prompt と watchlist がその主役をさらに優先する設計だった
3. 最後に偏りを止めるコード上のガードが足りなかった

つまり「たまたまそうなった」のではなく、「今の設計ならそうなりやすい」が正しい。

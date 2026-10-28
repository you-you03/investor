# 仮説トラッカー

2026-10-28 に棚卸しした。判定済みは下の完了欄。paper のオープン行は閉じない。

| ID | 置き場 | 状態 | 次 |
|---|---|---|---|
| H-1 | 完了 | 判定不能（escalate 4件） | 時間配分は変えない。[signal-source-allocation.md](signal-source-allocation.md) |
| H-2 | 完了 | 判定不能（差分トレードなし） | RSI 特例は現状維持。paper の REZI は open のまま |
| H-3 | 完了 | 判定不能（クローズ2件、目標5） | 20万円枠はライブ台帳のまま。昇格判定はしない |
| H-4 | アクティブ | 終了日なし | 次回確認 2026-11-25 |
| H-5 | 完了 | 相対支持。CHASE 禁止を固定 | V2 単独のモード別は n 不足。絶対 alpha は未達 |
| H-6 | アクティブ | 終了日なし | [wait-trigger-reentry.md](wait-trigger-reentry.md)。次回 2026-11-25 |
| H-7 | アクティブ | 終了日なし | [exit-sop.md](exit-sop.md)。次回 2026-11-25 |

---

## アクティブ仮説

### H-4: 100万円シミュレーション枠は高稼働にした方が decision 精度改善に効くか

**状態**: 運用中。終了日は置いていない。次回確認 2026-11-25。`data/portfolio_100man.csv` は実弾ではない。

**運用ルール**:

- 総予算: 1,000,000円（概算 $6,700）
- 最大5銘柄、1銘柄上限25%（概算 $1,675）
- 採用品質ゲートは20万円枠と同じ。`catalyst_quality == WEAK`、score < 7.5、stop 未設定、CRITICAL data gap は BUY 禁止
- キャッシュ稼働率のノルマは置かない。候補がなければ `HOLD_CASH` を記録する
- HIGH はライブでは無効。シミュレーションでも、ライブの HIGH 解禁（満期 OOS 30）を先回りして開かない
- 記録は `[100man-sim]`。dual gate のあり/なしは [dual-gate-paper-log.md](dual-gate-paper-log.md)。Slack しない

**判定基準**:

- 高稼働シミュレーションの8週間後 alpha が20万円枠より高い、または BUY/PASS の反例が増える → 仮説支持
- 高稼働化で過熱エントリーが増え、勝率か alpha が悪化 → 仮説棄却

2026-10-28 は終了日が無く、8週比較を閉じていない。判定しない。

### H-6: DECISION_WAIT Trigger Recapture

**状態**: アクティブ。終了日なし。次回確認 2026-11-25。

**検証開始日**: 2026-07-12

**仮説**: WAIT を押し目、EMA20 回復、ブレイク再開の条件にすると、件数を無理に増やさず執行機会を回収できる。

**運用**:

- `decision_wait_trigger` に `lower` / `upper` / `reclaim_price` / `breakout_above` / `next_step`
- `/monitor` が `DECISION_WAIT_ENTRY_ZONE` / `DECISION_WAIT_TRIGGERED` / `DECISION_WAIT_NEAR_ZONE` を出す
- 成立は自動 BUY ではない。手順は [wait-trigger-reentry.md](wait-trigger-reentry.md)

**判定基準**:

- 成立後 BUY の平均 alpha が通常 BUY 以上、かつドローダウンが同等以下 → 継続
- 成立前の見逃しが多い → ゾーンの緩和を議題にする（その場で緩和しない）
- 成立後の負けが多い → 再投入にニュースか出来高の確認を必須にする

2026-10-28 は成立後の約定系列が揃っていない。判定しない。

### H-7: 4-7 Day Prime Exit Review

**状態**: アクティブ。終了日なし。次回確認 2026-11-25。

**検証開始日**: 2026-07-12

**仮説**: 保有4–7日の alpha が強いなら、その窓を集中して見ると MFE 捕捉が改善する。

**運用**: [exit-sop.md](exit-sop.md)。`/monitor` は暦日4–7日に `PRIME_EXIT_WINDOW`（INFO）を出す。売却指示ではない。HOLD / 利確 / ストップ引き上げの提案に分解する。

**判定基準**:

- MFE 捕捉が改善し、平均リターンが低下しない → 継続
- 早売りで伸びを逃す → 利確よりストップ引き上げを主にする

2026-10-28 のライブ open は TSM だけで、この窓の外。窓の成績はまだ閉じない。

---

## 完了済み仮説

### H-1: Watchlist ESCALATE銘柄は market-scan 銘柄より勝率が高いか

**状態**: 判定不能。2026-10-28 に閉じた。期間は 2026-05-10 〜 2026-08-10。目標はクローズ10件以上。

`data/portfolio.csv` のクローズは17件で、冊子としての件数目標は超える。escalate は4件しかない。+10pp の判定には足りないので、棄却とも支持ともしない。

| 区分 | n | 勝率 | 平均リターン |
|---|---:|---:|---:|
| watchlist_escalate | 4 | 75% | +12.7% |
| scan 合計（earnings / technical / analyst） | 13 | 69% | +17.1% |

勝率差は約 +6pp で、基準の +10pp に届かない。平均は scan の方が高く、1.2倍にも届かない。点推定は支持条件未達。n=4 のまま棄却もしない。

時間配分は変えない。[signal-source-allocation.md](signal-source-allocation.md)。

### H-2: RSI>80 でも SECTOR_LEADING なら縮小エントリーは正当か

**状態**: 判定不能。2026-10-28 に閉じた。期間は 2026-05-10 〜 2026-07-10。

paper の REZI（pos-003）は hypothesis H-2 だが、note は「RSI<70 のため strict WAIT の差分は発動せず、A枠と同じ BUY」。期間終了の 2026-07-10 より後の 2026-07-20 エントリーでもある。差分としての仮想エントリーは0件。DECK と WAY に仮説 ID は無い。

RSI の WAIT ルールは維持する。paper の3行は open のまま。この判定は行を閉じない。

### H-3: 20万円サテライトは機会損失を減らせるか

**状態**: 判定不能。2026-10-28 に閉じた。期間は 2026-06-20 〜 2026-09-20。目標は H-3 のクローズ5件。

ライブ台帳のクローズは SMTC（−22.5%）と FOUR（+11.0%）の2件。TSM は open なのでクローズ件数に入れない。5件に足りない。

20万円枠をライブのデフォルトにした運用決定は、この仮説の成否とは別で、すでに台帳の正本になっている。この判定はそれを取り消さない。昇格の可否も言わない。キャッシュ稼働率ノルマは strategy v2 で廃止済みで、ここでは復活させない。

### H-5: 初動と追いかけを分けるとエントリー品質が上がるか

**状態**: 相対支持。2026-10-28 に閉じた。ライブの CHASE 禁止は維持する。重みは変えない。

**検証開始日**: 2026-06-25

判定に使ったのは重複排除後のモード表と、[reports/validation/gate_counterfactual_2026-10-28.md](../reports/validation/gate_counterfactual_2026-10-28.md)。

- EARLY の4週 alpha −3.44% は CHASE −9.42% を上回り、4週のリターン勝率 56.5% は 50% 以上。分離は相対的には有効。
- 12週も EARLY −7.02% 対 CHASE −9.35%。どちらも絶対値はマイナス。
- CHASE が高 alpha なら排除しない、という分岐は不成立。
- extension HIGH の CHASE（12週 −4.71%、n=50）は、HIGH でない CHASE（−28.67%、n=12）より悪くない。ペナルティの強化はしない。HIGH 禁止の既存ゲートは残す。
- V2 単独は1 run（EARLY 6、CHASE 3、BALANCED 3）。V2 だけでの確定はまだできない。核を変える反証も無い。

`BALANCED` の12週 −19.09%（n=18）は、許可を暫定オプションのままにする理由。絞るかは 2026-11-25 の議題で、この判定では数値を変えない。

---

## B枠 運用ルール

B枠は実弾を使わない。

- エントリー記録: `python skills/decision.py --paper --send '[...]'`
- 一覧: `python skills/paper_portfolio.py list`
- クローズ: 仮説の期限が来ても、このトラッカー更新では閉じない。約定に相当する記録価格が決まったときだけ `python skills/paper_portfolio.py close`
- 比較: `python skills/paper_portfolio.py compare`

`note` には仮説 ID を書く。

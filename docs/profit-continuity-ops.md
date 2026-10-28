# 利益継続オペレーション

2026-10-28 の結論: **ライブ新規 BUY は出さない。TSM は全売却の提案だけ。執行は Yuta。60/25/15 は固定。HIGH は出さない。**

12週で SPY を超え、最大DD 6% 以内、ルール遵守 100% を守ったまま続けるための1枚。入口の通し方は [live-buy-dual-gate.md](live-buy-dual-gate.md)。出口の手順は [exit-sop.md](exit-sop.md)。混ぜない。

## 禁止

- ブローカーへの自動発注
- 約定前の `portfolio_20man.csv` 更新（open を closed にしない。空の `exit_price` を埋めない）
- スコア重み、7.5、HIGH 解禁ラインの変更
- dual gate の数値をこの週に硬くすること（成功/失敗条件と再判定日は dual gate 文書に追記済み）
- 提案を約定として記録すること

サイズ上限は MEDIUM のまま。HIGH は V2 の独立満期 OOS が 30 になるまで使わない。2026-10-28 は観測 15、run は 1。

## P0（資金と生存）

毎週、新規候補の前に見る。

1. TSM を含むオープン行が、台帳と「確認できた事実」で一致しているか。食い違いは [reports/monitor/tsm_pos003_factcheck_2026-10-28.md](../reports/monitor/tsm_pos003_factcheck_2026-10-28.md)。解消前は BUY を出さない。
2. [live-buy-unlock.md](live-buy-unlock.md) の6行が全部 Yes か。
3. オープン全行に stop と target があるか。欠損なら是正提案。埋めずに新規を止めない、ではなく、埋まるまで新規を止める。
4. heat ≤ 2.0%、1トレード ≤ 0.75%、1銘柄 ≤ 25%、同時 ≤ 3。超過は新規停止か縮小提案。執行は Yuta。

## P1（出口、検証、エッジ）

1. 保有 4–7日は [exit-sop.md](exit-sop.md) の prime レビュー。HOLD / 利確 / ストップ引き上げの提案。
2. `STOP_BREACH` と目標到達は、アラート → exit decision → Yuta 執行 → 台帳、の順。
3. 月曜の score validation と ledger reconcile が止まっていないか。[workflow_check_2026-10-28.md](../reports/validation/workflow_check_2026-10-28.md)。
4. ≥7.5 の12週 SPY alpha、ゲート反実仮想、V2 満期 run を読む。重みは run 10 未満では変えない。
5. 判定日は [review-calendar.md](review-calendar.md)。次は 2026-11-25。

## 週次の手順

1. `/monitor`（ライブは `portfolio_20man.csv`）。出口アラートがあれば exit SOP。
2. validation cron の PR を見る。中身が data と reports だけなら、依頼元の自動マージに任せる。人が約定を足す PR は自動マージしない。
3. [reports/templates/weekly-brief.md](../reports/templates/weekly-brief.md) の5点を書く。
4. 解禁表が Yes のときだけ `/decision`。`dual_gate` の1行が無い BUY は出さない。
5. WAIT の戻りは [wait-trigger-reentry.md](wait-trigger-reentry.md)。トリガー成立は自動 BUY ではない。

## 役割

| | monitor | decision | review |
|---|---|---|---|
| 見ること | オープンとウォッチの価格、アラート | 候補を買うか見送るか | 12週 alpha、DD、遵守、run 数 |
| 出してよいもの | アラートと出口の提案 | BUY / WAIT / PASS の提案 | 継続・縮小・停止の提案 |
| 出してはいけないもの | 約定済みの close | 解禁前のライブ BUY、重み変更 | run 10 未満の重み変更、HIGH 解禁 |
| 台帳 | 約定確認後の人が更新 | 約定確認後の人が add | 更新しない |

## 記録

- 提案と約定を分けて書く。decision の BUY は提案。`status=open` は約定後だけ。
- 監視と検証の記録 PR は、差分が `data/**` と `reports/**` に収まるとき自動マージしてよい。ポジションの close や重み変更は含めない。
- できないことは残課題に理由を書く。黙って飛ばさない。

## 関連

- 解禁: [live-buy-unlock.md](live-buy-unlock.md)
- 入口: [live-buy-dual-gate.md](live-buy-dual-gate.md)
- 出口: [exit-sop.md](exit-sop.md)
- 仮説: [hypothesis-tracker.md](hypothesis-tracker.md)
- 戦略: [strategy-v2.md](strategy-v2.md)
- 並走ログ: [dual-gate-paper-log.md](dual-gate-paper-log.md)
- シグナルの時間配分: [signal-source-allocation.md](signal-source-allocation.md)

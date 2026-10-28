# レビューカレンダー

次回の `/review` 判定日は **2026-11-25**（Asia/Tokyo）。

2026-10-28 に固定した。この日はウェイトを動かす日ではない。Strategy V2 の独立満期 run は 1 で、変更解除の 10 に届いていない。HIGH の解禁（満期 OOS 30）にも届いていない。

## その日に読むもの

| 入力 | 出所 |
|---|---|
| 12週の run 別 alpha IC 中央値 | V2 だけの満期 run。全バージョン混在は参考 |
| score ≥ 7.5 の12週 SPY alpha | [reports/validation/score_ge75_spy_alpha_2026-10-28.md](../reports/validation/score_ge75_spy_alpha_2026-10-28.md) の後継 |
| 最大ドローダウン | ライブ台帳のマーク。6%が線 |
| ルール遵守 | stop/target、サイズ、約定確認。100%が線 |
| V2 の独立満期 run 数 | [reports/validation/v2_matured_runs_2026-10-28.md](../reports/validation/v2_matured_runs_2026-10-28.md) の後継。ウェイト変更は 10、HIGH は OOS 30 |

直前の検証 cron は 2026-11-23 22:30 UTC（2026-11-24 07:30 JST）の score validation。その結果を見てから判定する。

## 事前分岐

当たった条件ごとに、出す提案は一つ。ウェイト変更はどの分岐にも入らない。run が 10 未満のあいだは再設計しない。

| 条件 | 提案 |
|---|---|
| 最大DD > 6% | 新規BUY停止を続ける。オープンの違反は縮小または全売却の提案。執行は Yuta |
| 遵守 < 100%（stop/target 欠損、未確認約定の台帳反映、集中や heat の未解消） | 新規BUY停止。欠損がある行は是正提案。約定していない出口は台帳に書かない |
| 独立満期 run ≥ 10 かつ 12週 run 別 alpha IC 中央値 ≤ 0 | 新規BUY停止。サイズ上限をさらに下げる提案。ウェイトは別ゲート（この表では動かさない） |
| score ≥ 7.5 群の12週 SPY alpha ≤ 0 | 新規BUY停止。V2 の n が小さいときは「計測継続」と併記し、混在サンプルだけで再設計しない |

2026-10-28 は DD、遵守、≥7.5 の12週 alpha が分岐に入っている。結論は新規BUY停止の継続と、TSM 全売却の提案。詳細は [reports/validation/strategy_v2_review_2026-10-28.md](../reports/validation/strategy_v2_review_2026-10-28.md)。

run ≥ 10 の IC 分岐は未使用（V2 満期 run は 1）。

## ウェイトと HIGH

- 60/25/15 は 2026-11-25 も固定
- HIGH は OOS 30までやらない
- dual gate の核（CHASE / extension HIGH の禁止）は維持。暫定オプションの再判定は同じ日。正本は [live-buy-dual-gate.md](live-buy-dual-gate.md)

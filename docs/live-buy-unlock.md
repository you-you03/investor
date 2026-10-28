# 新規ライブBUY 解禁条件

2026-10-28 時点では **未解禁**。下の表がすべて Yes になるまで、ライブ（20万円枠）の新規 BUY 提案を出さない。`HOLD_CASH` が正しい。

出口のやり方は [exit-sop.md](exit-sop.md)。通し方の中身は [live-buy-dual-gate.md](live-buy-dual-gate.md)。この1枚は「出してよいか」だけを見る。

## 判定

| # | 条件 | 2026-10-28 |
|---|---|---|
| 1 | TSM（pos-003）の違反が解消している。未決着の STOP_BREACH がなく、時価が資金の25%以内で、そのポジションの heat が上限内 | No。提案は全売却。執行は Yuta 待ち。台帳は open のまま |
| 2 | portfolio heat ≤ 2.0% | No。TSM 単体で 3.73%（2026-10-27 終値） |
| 3 | 同時オープン ≤ 3 | Yes。ライブは TSM の1銘柄 |
| 4 | 1銘柄の時価 ≤ 資金の25%（約 $335） | No。TSM 時価 $436.87 は 32.6% |
| 5 | オープン全行に stop と target がある | Yes。TSM は両方ある。欠損の是正ではない |
| 6 | その候補が dual gate を通過する | 候補を出さない。ゲートの正本は別紙 |

一つでも No のあいだ、`/decision` はライブ BUY を提案しない。paper と 100万円シミュレーションは実弾ではない。そこに記録しても解禁にはならない。

## 解禁した週にやること

1. この表を取り直す。価格の出所を書く。
2. 候補ごとに dual gate の1行を付ける。形式は [live-buy-dual-gate.md](live-buy-dual-gate.md) と PM 合成の `dual_gate`。
3. サイズはこれまでどおり `investor/core/risk.py`。MEDIUM 上限。HIGH は満期 OOS 30件まで使わない。
4. 提案のあと、Yuta の約定があるまで台帳へ `add` しない。

再判定の日付は [review-calendar.md](review-calendar.md) の **2026-11-25**。その日より前でも、TSM の約定確認が終わればこの表だけは更新してよい。表が Yes になる前に BUY 提案は出さない。

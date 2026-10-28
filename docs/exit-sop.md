# 出口 SOP

保有の見方と、ストップ / 目標への対応。ライブBUYの通し方は [live-buy-dual-gate.md](live-buy-dual-gate.md) にあり、ここには書かない。

提案は約定ではない。この手順のどこでも、ブローカー約定を確認する前に `status=closed` にしない。`exit_price` を空のまま埋めない。

## いつ使うか

| きっかけ | 次 |
|---|---|
| 保有4–7日（H-7） | 下の prime レビュー |
| `STOP_BREACH` | 下の共通手順。優先 |
| 目標到達（`TARGET_HIT`）または目標が目前 | 下の共通手順 |
| 保有約3週 | 既存のテーゼレビュー。自動決済ではない |

TSM（pos-003）は 2026-06-24 エントリーで、2026-10-28 時点では prime 窓の外。ストップ履歴と目標到達の手順で扱う。提案は [reports/monitor/tsm_pos003_factcheck_2026-10-28.md](../reports/monitor/tsm_pos003_factcheck_2026-10-28.md)。

## H-7: 保有4–7日

暦日で数える。`entry_date` の4日後から7日後まで。3週レビューと同じ数え方で、営業日では切らない。

1. `/monitor` がオープン行の経過日を見る。4–7日なら `PRIME_EXIT_WINDOW`（INFO）。
2. アラートは売却指示ではない。次の三つから一つを提案する。
   - **HOLD** — テーゼと相対強度が続いている。ストップも目標も残す
   - **利確** — 目標に近い、または伸びの理由が消えた。小口（4株未満）は一部売却しない。全株の出口レビューにする
   - **ストップ引き上げ** — 建値、または ATR 基準へ上げる提案。上げても集中25%や heat 2% が残るなら、それだけでは違反は消えない
3. 提案を `reports/decision/exit_{date}_{ticker}.md` に残す。
4. 執行は Yuta。約定確認後だけ台帳を更新する（下の共通手順）。

`investor/core/monitor.py` は 4–7日に `PRIME_EXIT_WINDOW` を出す。INFO なので、それ単体では売りアラートの扱いをしない。

## STOP_BREACH と目標近接

目標の「近接」に新しいパーセントは置かない。台帳の `target_price` 以上を `TARGET_HIT` とする。目標の手前は monitor の「目標まで」を人が読む。

`TARGET_HIT` は、目標が取得単価より下でも出す。TSM の目標 $434.19 は取得 $441 より下なので、到達は利益確定ではなく損失縮小の出口である。

### 共通手順

1. **アラート** — `/monitor` の `STOP_BREACH` または `TARGET_HIT`。過去にストップを割って戻した場合も、未決着なら同じ扱い。
2. **出口判断** — `/decision --mode exit --ticker {TICKER}`。結論は `FULL_EXIT` / `PARTIAL_EXIT` / `RAISE_TARGET` / `HOLD`。4株未満で端数売却ができない銘柄は、部分売却をルール内の解消策にしない。
3. **Yuta が執行** — 口座の残株、未約定のストップ、約定価格を確認する。エージェントは注文を出さない。
4. **台帳** — 約定価格が分かってからだけ更新する。

```bash
.venv/bin/python skills/portfolio.py close --ticker TICKER --price <約定価格> --portfolio 20man
```

このコマンドは `exit_date` を実行日にする。約定日と実行日が違うときは、実行後に人が `exit_date` を約定日へ直す。`note` に「Yuta 約定確認」と残す。`trade_journal.json` はこのコマンドでは増えない。必要なら約定後に人が追記する。

価格がストップの上に戻っていても、履歴上の `STOP_BREACH` を無かったことにしない。戻った価格で新規のストップを引き直す案は、集中と heat が上限内に戻るときだけ候補になる。戻らないなら全売却を先に検討する。

## やってはいけないこと

- アラートだけで `portfolio_20man.csv` の `status` を `closed` にする
- 約定前に `exit_price` を入れる
- 出口判断とライブBUYの dual gate を一つのチェックリストにまとめて、どちらかを飛ばす
- ストップ引き上げだけで、25%超や heat 超過を解消したことにする

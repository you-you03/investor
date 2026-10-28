# WAIT トリガーからの再エントリー（H-6）

WAIT は見送りであり、エントリー予約ではない。トリガーが付いた銘柄を、品質候補の戻り口として使う。

## 手順

1. `/decision` が WAIT にしたとき、`watchlist.json` の `decision_wait_trigger` にゾーンを書く。`lower` / `upper`、`reclaim_price`、`breakout_above`、`next_step`（原則 `/research --seed {TICKER}`）。
2. `/monitor` が `DECISION_WAIT_ENTRY_ZONE` / `DECISION_WAIT_TRIGGERED` / `DECISION_WAIT_NEAR_ZONE` を見たら、`next_step` に従う。
3. トリガー成立後は `/research --seed` で取り直す。前回の WAIT 理由がまだ残るなら、もう一度 WAIT。
4. seed のあと `/decision` に載せる。ライブ BUY にするには [live-buy-unlock.md](live-buy-unlock.md) が全部 Yes で、[live-buy-dual-gate.md](live-buy-dual-gate.md) も通過していること。
5. 通過しても提案まで。約定前に台帳へ足さない。

## 今はやらないこと

2026-10-28 は解禁条件が No なので、トリガーが付いてもライブ BUY 提案は出さない。paper への記録は実弾ではない。

H-6 は未判定。次回の確認は 2026-11-25。トリガー成立後の alpha が溜まるまで、ゾーンの幅は変えない。

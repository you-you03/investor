# シグナル源泉の時間配分

H-1（escalate が scan より勝つか）は 2026-10-28 に **判定不能** で閉じた。根拠は [hypothesis-tracker.md](hypothesis-tracker.md)。escalate のクローズは4件で、+10pp の判定には足りない。点推定は支持条件に届いていない（勝率差は約 +6pp、平均リターンは scan の方が高い）。

## 方針

寄せない。週の時間はこれまでどおり分ける。

- **scan** — 週次 `/research` の主経路。新規の候補はここから出す。
- **escalate** — `/monitor` が `research_queued` にした銘柄と、ウォッチの深掘りだけ。全件を毎週 decision に上げない。

escalate のクローズが10件揃うまで、どちらかへ時間を移す再配分はしない。判定不能を「ウォッチをやめろ」とも「スキャンをやめろ」とも読まない。

ライブ BUY は別問題で、[live-buy-unlock.md](live-buy-unlock.md) が Yes になるまで出さない。源泉の配分と解禁は独立。

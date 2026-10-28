# dual gate あり / なしの並走記録

paper（B枠）と 100万円シミュレーションで、同じ候補を「ゲートあり」と「ゲートなし」で残す。Slack は送らない。実弾の注文にはしない。ライブ台帳 `portfolio_20man.csv` は触らない。

ゲートの文言は [live-buy-dual-gate.md](live-buy-dual-gate.md)。ここは記録の型だけ。

## いつ書くか

`/decision` で候補を見た週。ライブが BUY 禁止の週も書く。禁止の週こそ、ゲートなしならどうしたかを残す。

## 1行の意味

- `with_gate` — 現行の暫定ゲートならライブではどうするか。見送り理由を書く
- `without_gate` — ゲートが無いときの反実仮想。CHASE や extension HIGH でも「買ったことにする」記録にしてよい
- どちらも `order_status=not_an_order`

## フォーマット

テンプレ: [reports/templates/dual-gate-parallel.json](../reports/templates/dual-gate-parallel.json)

置き場所は `data/dual_gate_parallel.jsonl`（1行1JSON）。ファイルが無い週はテンプレに従って新規作成する。スコアの重みは書かない。week4 / week12 は後から `score_snapshots` を run_id + ticker で埋める。未到来は null のまま。

```json
{
  "date": "2026-10-28",
  "ticker": "EXAMPLE",
  "run_id": "run-id",
  "book": "paper",
  "score": 8.1,
  "mode": "CHASE_MOMENTUM",
  "fundamentals_grade": "B",
  "extension_risk": "HIGH",
  "chase": true,
  "with_gate": "見送り:CHASE",
  "without_gate": "仮想BUY",
  "order_status": "not_an_order",
  "week4_alpha_vs_spy": null,
  "week12_alpha_vs_spy": null
}
```

`book` は `paper` または `100man-sim`。100万円側のサイズは既存のシミュレーションルールに従い、このログ自体は株数を台帳へ入れない。

## 読み方

2026-11-25 に、`with_gate=通過` の12週 alpha と `without_gate` が CHASE の行を比べる。比べる前に null を埋められる範囲だけ埋める。件数不足なら判定しない。

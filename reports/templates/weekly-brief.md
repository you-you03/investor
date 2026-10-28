# 週次短報 — YYYY-MM-DD

5点だけ書く。提案は約定ではない。ライブ台帳は Yuta の約定確認後だけ動かす。

## 1. 稼働可否

新規ライブ BUY は可 / 不可。根拠は [docs/live-buy-unlock.md](../../docs/live-buy-unlock.md) の6行。不可なら理由を1行。

## 2. DD と heat

| 項目 | 今 | 上限 |
|---|---|---|
| 最大DD |  | 6% |
| portfolio heat |  | 2.0% |
| 最大の1銘柄 |  | 25% |
| 1トレードリスク |  | 0.75% |

価格の日付と出所を書く。

## 3. 出口アラート

`STOP_BREACH` / `TARGET_HIT` / `PRIME_EXIT_WINDOW` の有無。あればティッカーと「提案のみ、執行は Yuta」。手順は [docs/exit-sop.md](../../docs/exit-sop.md)。

## 4. validation 要約

週次の score validation が走ったか。V2 満期 run 数、≥7.5 の12週 SPY alpha、レジームの注意を各1行。

レジームで見ること:

- `risk_on` の12週リターンが他レジームより悪いか（2026-10-28 レポートでは risk_on が最悪）
- スナップショットの `macro_regime` が `NORMAL_DOWNTREND` に寄っていないか
- VIX 18–25 の中立なら、新規サイズを語っても解禁条件が先
- レジームが悪い週の `HOLD_CASH` は失敗に数えない
- レジームを理由に 60/25/15 を動かさない

## 5. 新規BUY可否

1の結論をもう一度。可でも dual gate の1行が無い候補は出さない。不可なら「今週は BUY 提案なし」と書く。

# Monitor-Based Decision — 2026-06-12

**Research run_id**: `91278354-9178-4dbb-b21d-6c398d0c0683`  
**Watchlist run_id**: `f21c0e32-54c9-4aed-ba84-6acbf854fca6`  
**Monitor report**: `reports/monitor/monitor_2026-06-12.md`

---

## 結論

新規 BUY より先に、monitor の出口シグナルを処理する。

| Ticker | 判断 | 理由 |
|---|---|---|
| TEAM | FULL_EXIT | $89.20 が trailing stop $99.00 を下回った。5/30に部分利確済みの残り5株をルール通り売却。 |
| LRCX | FULL_EXIT | $362.52 が target $335.00 を大きく上回った。5/23に一部利確済みで、残り2株も利益確定。 |
| NVDA | FULL_EXIT | $204.87 が stop $205.00 を下回った。誤差でもルール上は損切り。 |
| AMAT | FULL_EXIT | $552.64 が target $530.67 を上回った。RSI72、アナリスト目標が現値下、watchlist research でも出口優先。 |
| VRT | HOLD | $297.88 は stop $296.00 をまだ割っていない。stop割れなら即FULL_EXIT。 |
| MU | CONDITIONAL BUY | score 8.4 の最優先候補。ただし売却執行前は 5/5 枠なので今は NO_TRADE。 |

---

## ポートフォリオ上の意味

推奨どおりに実行すると、`TEAM / LRCX / NVDA / AMAT` の4枠が空く。  
その後の新規候補は `MU` が最優先。買う場合は1株から始める。

`VRT` は継続。ただし stop $296.00 まで $1.88 しかないため、次回 monitor で割れたら迷わず FULL_EXIT。

---

## PM判断

`MU` は銘柄単体では BUY 候補だが、現時点では portfolio rule が優先。  
既存ポジションに stop breach と target reached が同時に出ているため、先に出口処理を行う。

今回の decision は Slack 送信済み。

*生成: 2026-06-12 20:57 JST*

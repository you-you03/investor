# Decision Report — 2026-06-20

**run_id**: `9a546d35-e5db-407d-a605-341e02f771d8` | **portfolio**: `data/portfolio_20man.csv` | **capital**: ~$1,340 | **macro**: NORMAL / VIX 16.78

## Final Decision

| Ticker | Panel | Round 1 | Round 2 | PM判定 |
|---|---|---:|---|---|
| AMD | Innovator / Tenbagger / Tape / Oracle | 2 BUY / 2 WAIT | Tape accepts only with tight stop; Oracle remains valuation-WAIT | BUY / MEDIUM |
| MU | Innovator / Tenbagger / Tape / Oracle | 3 BUY / 1 WAIT | PM rejects new 20man entry due price/risk concentration | PASS |
| MRVL | Innovator / Tenbagger / Tape | 1 BUY / 2 WAIT | Score 7.3 without STRONG catalyst | WAIT |
| AMAT | Innovator / Tenbagger / Tape | 1 BUY / 2 WAIT | RSI 76 + analyst target below current | WAIT |
| COHR | Innovator / Tenbagger / Tape | 1 BUY / 2 WAIT | Score 7.0 without STRONG catalyst | WAIT |

## 推奨銘柄

### AMD — BUY / MEDIUM

| 項目 | 値 |
|---|---:|
| Entry | $530-540 |
| Current used | $537.37 |
| Target | $620.00 |
| Stop | $511.00 |
| Size | 1 share / ~$537 |
| Time horizon | 4-6 weeks |

**判断根拠**: Watchlist Research 2026-06-20でESCALATE。売上+37.8% YoY、EPS+91.2% YoY、PEG 1.29、Strong Buy 48件で質は十分。RSI 61で過熱は限定的、52週高値から約3.8%下でAI半導体大型株への資金流入を取りに行く。

**リスク管理**: Analyst target $487.90が現値を下回り、MACD histogram -3.07で短期モメンタムは鈍化。20万円枠では1株でも約40%配分になるため、Kelly 2%に合わせてstop $511を必須にする。Kelly: risk/share $26.37、account risk $26.80 -> 1株。レジームNORMAL/VIX16.78 (x1.0) -> $537 / 1株。

## 見送り

- **MU**: スコア8.4で最強だが1株$1,133.99。20万円枠では1株で予算の約85%となり、決算前ギャップリスクも大きい。
- **MRVL**: スコア7.3。forward PE 50超、EPS YoY悪化、アナリスト目標が現値未満。7.0-7.4帯でSTRONG catalystなしのためWAIT。
- **AMAT**: スコア7.1。RSI 76、options bearish、現値がアナリスト目標を上回るため冷却待ち。
- **COHR**: スコア7.0。RSI 53は良いが、目標株価近辺で明確なブレイク確認待ち。

## Watchlist Pipeline Sync

- AMD — BUY採用 | `decision_queued -> promoted`
- AMAT — WAIT | `decision_queued -> researched`
- MRVL — WAIT維持 | `researched -> researched`
- COHR — WAIT維持 | `researched -> researched`

## Slack

Sent: BUY AMD / MEDIUM / 1 share / ~$537.

## Next Step

承認して執行する場合:

```bash
.venv/bin/python skills/portfolio.py add --portfolio 20man --ticker AMD --shares 1 --price 537.37 --target 620 --stop 511 --signal watchlist_escalate --conviction MEDIUM --proposal-date 2026-06-20 --note "Decision 2026-06-20: BUY/MEDIUM. 20man枠 1株、tight stop必須。"
```

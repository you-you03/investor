# Monitor ledger reconciliation — 2026-10-28

## Books

- Live book: `data/portfolio_20man.csv`. This is the ¥200,000 book in `settings.default_portfolio_path`.
- `data/portfolio.csv` is the historical A-frame ledger. It is not the live execution book. Differences below are informational.
- `data/portfolio_100man.csv` is the simulation book and is not reconciled here.
- `data/paper_portfolio.csv` is the B-frame hypothesis book and is not reconciled here.

- Open live rows: 1
- Latest monitor price date: 2026-10-25
- Auto-close: off. This job does not write `exit_price`, `exit_date`, or `status=closed`.

## Findings

| Ticker | Kind | Pending exit review | Monitor price | Stop | Target | Legacy book |
|---|---|---|---|---|---|---|
| TSM | unresolved_stop_alert | yes | 418.51 | 388.02 | 434.19 | portfolio.csv status=closed; stop_loss live=388.02 legacy=389.25; target_price live=434.19 legacy=428.87; shares live=1.0 legacy=3.0 |

- **TSM** (unresolved_stop_alert): TSM still open after STOP_BREACH on 2026-10-25. No broker fill is recorded. Leave the row open for exit review.

Next step for a flagged open row is `/decision --mode exit`, after a human confirms the broker status.

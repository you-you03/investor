# Validation 系 Actions の確認 — 2026-10-28

**結論: 壊れていない。まだ一度も走っていない。直す箇所は無かった。**

| Workflow | ファイル | GitHub 上 | 実行履歴 | 次回 cron |
|---|---|---|---|---|
| Investor score validation | `.github/workflows/score-validation.yml` | active | 0件 | 2026-11-02 22:30 UTC（火曜 07:30 JST） |
| Investor ledger reconcile | `.github/workflows/ledger-reconcile.yml` | active | 0件 | 2026-11-02 23:15 UTC |

YAML は両方読めた。score validation は `fetch_returns` → `record_outcomes` → `validate_scores` の順で、差分が `data/` と `reports/` だけのとき PR を開く。ledger reconcile はオープン行を閉じない。Slack はどちらも空。

この確認では workflow を手動起動していない。起動するとデータ PR が開く。初回は上記の月曜 cron に任せる。

既存の week1–12 は `score_snapshots.json` に入っている。2026-10-28 リサーチの20件は week1 未到来なので、`fetch_returns` の全件再取得はしていない。Yahoo 自体は TSM の日次で取得できた。

残課題: 2026-11-03 JST に、score validation の初回 run が PR を開けているかを見る。失敗ならログを直す。成功してもウェイトは変えない。

# GitHub Actions Operations

Codex が起動していない時間帯の代替として、GitHub Actions で最低限の監視と軽量スキャンを実行する。

## Workflows

### Investor monitor

File: `.github/workflows/monitor.yml`

目的:
- 20万円ポートフォリオの保有監視
- `STOP_BREACH`, `STAGE1_HIT`, `STAGE2_HIT`, `PRIME_EXIT_WINDOW`
- watchlist の `DECISION_WAIT` trigger と `PREQUALIFIED_RESEARCH_NEEDED`
- Slack 通知

Schedule:
- 23:45 JST, Monday-Friday
- 04:45 JST, Tuesday-Saturday

Manual run:
1. GitHub repo > Actions > `Investor monitor`
2. `Run workflow`
3. 初回確認は `dry_run=true`
4. 問題なければ `dry_run=false`

### Investor daily lite

File: `.github/workflows/daily-lite.yml`

目的:
- monitor-lite
- watchlist-lite
- research-lite
- pending action summary を Slack に送信

Schedule:
- 20:30 JST, Monday-Friday

Manual run:
1. GitHub repo > Actions > `Investor daily lite`
2. `Run workflow`
3. 初回確認は `dry_run=true`
4. `max_research_candidates` は通常 `5`

### Investor score validation

File: `.github/workflows/score-validation.yml`

目的:
- `scripts/fetch_returns.py`
- `scripts/record_outcomes.py`
- `scripts/validate_scores.py`
- 差分が `data/` と `reports/` だけなら commit して PR を開く
- Slack は送らない
- ライブのスコアウェイトは変えない

Schedule:
- 22:30 UTC Monday（米国市場クローズ後。ET 17:30 / JST 火曜 07:30）

Record PR は差分確認のあと auto-merge してよい。対象は `data/**` と `reports/**` に限る。ウェイト変更ゲート（満期 run 10 未満は変更しない、HIGH conviction は満期 OOS 30 まで無効）はこのジョブでは動かさない。

2026-10-28 確認: workflow は active。実行履歴はまだ無い。初回 cron は 2026-11-02 22:30 UTC。詳細は [reports/validation/workflow_check_2026-10-28.md](../reports/validation/workflow_check_2026-10-28.md)。

Manual run:
1. GitHub repo > Actions > `Investor score validation`
2. `Run workflow`

### Investor ledger reconcile

File: `.github/workflows/ledger-reconcile.yml`

目的:
- `scripts/reconcile_monitor_ledger.py --update-alerts`
- ライブ台帳 `data/portfolio_20man.csv` の stop / target / status と monitor alert を突合する
- STOP / TARGET が `open` のままなら `reports/monitor/reconcile_{date}.md` に出す
- ブローカー約定は作らない。`status=closed` にもしない
- Slack は送らない

`data/portfolio.csv` は以前の A枠台帳であり、ライブ執行ブックではない。同じ銘柄でも株数・stop・target・status が違い得る。`portfolio_100man.csv` はシミュレーション、`paper_portfolio.csv` は B枠で、この突合の対象外。

Schedule:
- 23:15 UTC Monday（score validation の後）

### Investor research data

File: `.github/workflows/research-data.yml`

目的:
- `/research` 用のmarket data JSONを収集してartifactに保存
- `/watchlist-research` 用のwatchlist deep data JSONを収集してartifactに保存
- SlackにActions run URLを通知

Schedule:
- Market research data: 20:30 JST, Monday and Thursday
- Watchlist research data: 10:00 JST, Saturday

Manual run:
1. GitHub repo > Actions > `Investor research data`
2. `Run workflow`
3. `mode` を `market` / `watchlist` / `both` から選ぶ
4. market mode の `max_tickers` は通常 `15`
5. 完了後、artifact `investor-research-data-{run_id}` をCodexの深掘り判断に使う

## Required GitHub Secret

Repository settings:

`Settings > Secrets and variables > Actions > Repository secrets`

Required:
- `SLACK_WEBHOOK_URL`

Optional:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PERPLEXITY_API_KEY`
- `XAI_API_KEY`

`SLACK_WEBHOOK_URL` が未設定のまま live run を実行すると workflow は失敗する。`dry_run=true` の手動実行では Slack secret なしでも動作確認できる。

## Operational Notes

- GitHub Actions の schedule は UTC 基準。workflow内のコメントにJST換算を明記している。
- GitHub-hosted runner は yfinance / Slack / Supabase へ外部通信するため、GitHub側の一時的な遅延やAPI rate limitで失敗することがある。
- schedule 実行は数分遅れることがある。秒単位の損切り用途ではなく、日次・準リアルタイム監視の代替として扱う。
- Pythonだけで完結する `monitor` と `daily-lite` はActionsで代替できる。
- `/research` と `/watchlist-research` はActionsでデータ収集までは代替できる。最終スコアリング、ESCALATE/REMOVE判断、PM decision はClaude/Codexで行う。
- `/decision` のフル版はClaude/Codexの5ペルソナ判断を含むため、Actions単体では完全代替しない。Actionsでは `daily-lite` の pending action と `research-data` artifact をSlackで受け取り、必要に応じてCodexで深掘りする。

## First Setup Checklist

1. `SLACK_WEBHOOK_URL` を repository secret に登録する。
2. `Investor monitor` を `dry_run=true` で手動実行する。
3. Summary と artifact に monitor result が出ることを確認する。
4. `Investor monitor` を `dry_run=false` で手動実行し、Slack通知を確認する。
5. `Investor daily lite` も同じ順序で確認する。
6. `Investor research data` を `mode=market` で手動実行し、artifactに `research_data.json` が出ることを確認する。
7. `Investor research data` を `mode=watchlist` で手動実行し、artifactに `watchlist_research_data.json` が出ることを確認する。

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

# Supabase 移行実装計画

作成日: 2026-06-18

## 目的

`data/` 配下の CSV / JSON / SQLite に分散している投資データを Supabase に集約し、Supabase Dashboard で状態確認できるようにする。既存の Python / yfinance ワークフローは維持し、GitHub Actions から monitor を定期実行して、結果を Supabase に蓄積する。

## 方針

- 既存ファイルはすぐ廃止しない。
- 最初はファイル保存と Supabase 保存を二重化する。
- Supabase 接続情報が未設定なら従来どおり動く。
- `portfolio` は当面手入力を継続する。
- 過去データは全件バックフィルする。
- Slack 通知は `monitor_alerts` から `notifications` を作り、送信済み状態を残す。
- 個人用運用のため、初期 migration では RLS を有効化しない。

## 実装範囲

### 1. Supabase migration

`supabase/migrations/001_initial_investor_schema.sql`

作成する主なテーブル:

- `positions`
- `watchlist_items`
- `monitor_runs`
- `monitor_positions`
- `monitor_alerts`
- `decision_requests`
- `decision_runs`
- `investment_proposals`
- `research_runs`
- `research_candidates`
- `score_snapshots`
- `trade_journal_entries`
- `market_news_sources`
- `market_news_items`
- `job_runs`
- `notifications`

Dashboard 用 view:

- `dashboard_open_positions`
- `dashboard_recent_alerts`
- `dashboard_monitor_runs`
- `dashboard_decision_queue`
- `dashboard_score_alpha`

### 2. Python Supabase保存

`investor/supabase_store.py`

- `.env` の `SUPABASE_URL` と `SUPABASE_SERVICE_ROLE_KEY` がある時だけ有効。
- Supabase REST API へ `upsert` / `insert` する。
- monitor 実行結果を保存する `sync_monitor_run()` を提供する。
- Slack通知用の pending notification を取得・更新する。

### 3. 過去データ移行

`scripts/backfill_supabase.py`

- `portfolio.csv`
- `paper_portfolio.csv`
- `watchlist.json`
- `monitor_history.json`
- `monitor_alerts.json`
- `decision_history.json`
- `research_history.json`
- `score_snapshots.json`
- `trade_journal.json`
- `market_news.sqlite`

を Supabase へ投入する。

### 4. GitHub Actions

`.github/workflows/monitor.yml`

- 平日 JST 朝に `scripts/run_monitor.py` を実行する。
- 実行後に `scripts/send_pending_notifications.py` を実行する。
- `workflow_dispatch` で手動実行もできるようにする。

## ユーザーが最後に行うこと

1. Supabase プロジェクトを作成する。
2. SQL Editor で `supabase/migrations/001_initial_investor_schema.sql` を実行する。
3. `.env` と GitHub Actions Secrets に以下を入れる。

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SLACK_WEBHOOK_URL
```

4. ローカルで一度バックフィルする。

```bash
.venv/bin/python scripts/backfill_supabase.py
```

5. GitHub Actions の `Monitor` workflow を手動実行して確認する。

## 段階的な切り替え

1. ファイル + Supabase の二重書き込みで1週間運用する。
2. Supabase Dashboard の view で日次確認する。
3. 問題がなければ `portfolio.csv` の手入力を Supabase Table Editor へ移す。
4. 最後に読み込み元も Supabase へ切り替える。

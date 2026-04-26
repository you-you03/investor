# investor — 再設計・実装計画 v2

作成日: 2026-04-04

---

## 背景と方針転換

### 現実装の問題

| 問題 | 影響 |
|---|---|
| Polygon.io（無料5req/min）| 1回のリサーチに10〜15分かかる |
| Anthropic SDK直呼び | ANTHROPIC_API_KEY必須、毎実行コスト発生 |
| SQLite/SQLModel | 重い依存、Skills化の障壁 |
| スタンドアロンPythonアプリ | `python scripts/run_research.py` でしか動かない |

### 採用する設計方針

- **yfinance採用**: Polygon.io → yfinance（無料・APIキー不要・EquityQueryでバルクスクリーニング）
- **Claude Code Skills化**: PythonをClaudeのツールとして設計（Research/Decision Agent）
- **ファイル永続化**: SQLite → CSV/JSON（ポートフォリオはCSV、設定はYAML、キャッシュはJSON）
- **3層アーキテクチャ**: Skills層（インターフェース）→ Core層（ビジネスロジック）→ Data層（データ取得）
- **Graceful degradation**: yfinanceのみで全機能動作。Grok/Perplexityはオプション

### first_planとの整合性

| first_planの要件 | 新設計のアプローチ |
|---|---|
| Research Agent（手動トリガー） | Claude Code Skill（自然言語で起動） |
| Decision Agent（自動連携） | Skillの延長でClaudeが判断 |
| Monitor Agent（毎平日7:00） | cronで動く独立スクリプト（ルールベース主体） |
| Slack通知 | 変わらない（Webhook） |
| Human-in-the-loop | 変わらない |

---

## ディレクトリ構造（新）

```
investor/
├── CLAUDE.md                     ← Claudeがセッション開始時に読む設計文書
├── SKILL.md                      ← Skills定義（4スキル）
├── .claude/
│   └── settings.json             ← Skills設定・ツール許可リスト
│
├── pyproject.toml                ← yfinance追加、sqlmodel/fastapi/uvicorn削除
├── .env.example                  ← SLACK_WEBHOOK_URL必須、他はオプション
│
├── data/                         ← ファイル永続化（SQLiteを廃止）
│   ├── portfolio.csv             ← 保有銘柄・売買履歴
│   ├── watchlist.json
│   ├── research_history.json     ← リサーチ+投資判断の履歴
│   └── cache/                    ← yfinanceキャッシュ（24時間TTL）
│       └── {ticker}_{date}.json
│
├── investor/
│   ├── config.py                 ← SLACK_WEBHOOK_URLのみ必須に変更
│   │
│   ├── data/                     ← Data層: データ取得の一元化
│   │   ├── yfinance_client.py    ← PolygonClientを完全代替
│   │   └── optional/
│   │       ├── grok_client.py    ← XAI_API_KEY未設定時はスキップ
│   │       └── perplexity_client.py  ← PERPLEXITY_API_KEY未設定時はスキップ
│   │
│   ├── core/                     ← Core層: ビジネスロジック
│   │   ├── screener.py           ← 市場スキャン（yfinance EquityQuery）
│   │   ├── analyzer.py           ← 個別銘柄分析（テクニカル+ファンダ）
│   │   ├── technical.py          ← テクニカル指標計算（technical_tools.pyを移行）
│   │   ├── portfolio.py          ← CSV読み書き・P&L計算
│   │   ├── watchlist.py          ← JSON読み書き
│   │   └── monitor.py            ← ルールベース閾値チェック（Claude不要）
│   │
│   ├── agents/
│   │   ├── research_agent.py     ← Skills経由で呼ばれる
│   │   ├── decision_agent.py     ← Skills経由で呼ばれる
│   │   └── monitor_agent.py      ← cronで動く（HIGHアラート時のみClaude呼び出し）
│   │
│   ├── notifications/
│   │   └── slack.py              ← SlackClient + formattersを統合
│   │
│   └── utils/
│       ├── logger.py             ← 変更なし
│       └── cache.py              ← JSONキャッシュ管理（新規）
│
├── skills/                       ← Skills層: 薄いエントリーポイント
│   ├── research.py
│   ├── decision.py
│   ├── portfolio.py
│   └── watchlist.py
│
├── scripts/
│   └── run_monitor.py            ← cronのみ（人間不在での自動実行）
│
└── tests/
    ├── test_screener.py
    ├── test_analyzer.py
    ├── test_technical.py
    ├── test_portfolio.py
    └── test_monitor.py
```

---

## 永続化データの仕様

### `data/portfolio.csv`

```
ticker,shares,entry_price,entry_date,exit_price,exit_date,status,target_price,stop_loss,note
NVDA,10,875.00,2026-04-04,,,,1000.00,820.00,AI chip momentum play
```

`status`: `open` / `closed`

### `data/research_history.json`

```json
{
  "runs": [
    {
      "run_id": "uuid",
      "date": "2026-04-04",
      "candidates": [...],
      "proposals": [
        {
          "ticker": "NVDA",
          "action": "BUY",
          "conviction": "HIGH",
          "target": 1000.0,
          "stop": 820.0,
          "rationale": "..."
        }
      ]
    }
  ]
}
```

### `data/watchlist.json`

```json
{
  "items": [
    {
      "ticker": "NVDA",
      "added_at": "2026-04-04",
      "reason": "AI chip momentum",
      "status": "active"
    }
  ]
}
```

---

## SKILL.md の設計（概要）

| スキル | トリガー例 | 処理 |
|---|---|---|
| `/research` | 「今日の注目銘柄を調べて」 | EquityQueryでスキャン → 分析 → research_history.jsonに保存 |
| `/decision` | 「投資判断を出して」 | 最新リサーチ読み込み → Bullish/Bearish討論 → Slack通知 |
| `/portfolio` | 「ポートフォリオを見せて」「NVDAを10株$875で購入した」 | CSV読み書き・P&L表示 |
| `/watchlist` | 「NVDAをウォッチリストに追加して」 | JSON読み書き |

Monitor AgentはSkillsではなくcronで動く独立スクリプト（`scripts/run_monitor.py`）。

---

## フェーズ別実装計画

### Phase 1: 基盤置き換え ★最優先（1〜2日）

**目標**: Polygon.io依存を完全除去。APIキー・レート制限問題を解消する。

**作業リスト**

- [ ] `pyproject.toml` 更新
  - 追加: `yfinance>=0.2.50`
  - 削除: `sqlmodel`, `fastapi`, `uvicorn`
- [ ] `investor/utils/cache.py` 新規作成（24時間TTL JSONキャッシュ）
- [ ] `investor/data/yfinance_client.py` 新規作成
  - `get_market_movers(direction, limit)` → `yf.screen("most_actives")` 等
  - `get_stock_snapshot(ticker)` → `yf.Ticker(ticker).fast_info`
  - `get_ohlcv_bars(ticker, days)` → `yf.Ticker(ticker).history()`
  - `get_financials(ticker)` → `yf.Ticker(ticker).quarterly_financials`
  - `get_ticker_details(ticker)` → `yf.Ticker(ticker).info`
  - テクニカル指標（RSI/MACD/ATR等）はOHLCVから`ta`ライブラリで計算
- [ ] `investor/tools/market_tools.py` の import を `YFinanceClient` に差し替え
- [ ] `investor/config.py` 更新（SLACK_WEBHOOK_URLのみ必須、他はオプション化）
- [ ] `data/portfolio.csv` 作成（空ファイルでOK）
- [ ] `python scripts/run_research.py --dry-run` で動作確認

**Phase 1完了時点でMVPとして動作する（リサーチ→Slack通知のループが回る）**

---

### Phase 2: Skills化（2〜3日）

**目標**: Claude Codeから自然言語で呼び出せるようにする。

**作業リスト**

- [ ] `CLAUDE.md` 作成（アーキテクチャ概要・データフロー・モジュール責務・ファイル仕様）
- [ ] `SKILL.md` 作成（4スキルの定義・引数・処理フロー）
- [ ] `skills/research.py` 作成
  - 引数パース → `ResearchAgent.run()` → `data/research_history.json` に保存
- [ ] `skills/decision.py` 作成
  - `data/research_history.json` 読み込み → `DecisionAgent.run()` → Slack通知
- [ ] `skills/portfolio.py` 作成（サブコマンド: list/add/close/snapshot）
- [ ] `skills/watchlist.py` 作成
- [ ] `.claude/settings.json` 設定（Bash実行許可スコープ）

---

### Phase 3: Monitor Agentのルールベース化（1〜2日）

**目標**: Claude呼び出しをHIGHアラート時のみに限定し、cron実行の信頼性を高める。

**閾値チェック仕様（Pythonで完結）**

| 条件 | アラートレベル |
|---|---|
| `current_price <= stop_loss` | HIGH（STOP_LOSS） |
| `current_price >= target_price` | MEDIUM（TARGET_REACHED） |
| 1日の変動 `< -5%` | HIGH（SHARP_DROP） |
| 累計損益 `< -8%` | MEDIUM（SIGNIFICANT_DRAWDOWN） |

**動作フロー**

```
portfolio.csv読み込み
  → yfinanceで現在価格取得
  → 閾値チェック（Pythonのみ）
  → HIGHアラートがある場合のみClaudeを呼んでコメント生成
  → Slackにデイリーサマリー送信
```

**作業リスト**

- [ ] `investor/core/monitor.py` 新規作成（閾値チェックロジック）
- [ ] `scripts/run_monitor.py` 更新（ルールベース化後のMonitor Agentを呼ぶ）
- [ ] cron設定をREADMEに記載

```
0 7 * * 1-5 cd "/path/to/investor" && .venv/bin/python scripts/run_monitor.py >> logs/monitor.log 2>&1
```

---

### Phase 4: Graceful degradation（1日）

**目標**: オプションAPIなしで完全動作する状態を確保。

**作業リスト**

- [ ] `investor/data/optional/grok_client.py` に `is_available()` 追加
- [ ] `investor/data/optional/perplexity_client.py` に `is_available()` 追加
- [ ] `news_tools.py` 更新
  - `get_news`: yfinance.Ticker.newsをメインに（APIキー不要）
  - `get_web_search`: Perplexity未設定時はエラーJSON返却（Agentがスキップして継続）
  - `get_x_search`: Grok未設定時はエラーJSON返却（Agentがスキップして継続）
- [ ] 動作確認: APIキー全なし（yfinanceのみ）でresearch → decision → monitor が通ること

---

## 現在のコードの移行方針

### 捨てる

| ファイル/モジュール | 理由 |
|---|---|
| `investor/db/` 全体 | SQLite → CSV/JSON移行 |
| `investor/clients/polygon_client.py` | yfinanceで完全代替 |
| `investor/clients/news_client.py` (NewsAPIClient) | yfinance.Ticker.newsで代替 |
| `investor/api.py` | FastAPI不要（Skills化するため） |
| `scripts/add_position.py`, `show_portfolio.py`, `close_position.py` | Skills化 |

### 再利用する

| ファイル | 移行先 | 変更内容 |
|---|---|---|
| `investor/tools/technical_tools.py` | `investor/core/technical.py` | ほぼそのまま |
| `investor/slack/formatters.py` | `investor/notifications/slack.py` | SlackClientと統合 |
| `investor/clients/slack_client.py` | 同上 | 変更なし |
| `investor/prompts/` 全体 | そのまま移行 | ツール名をyfinance版に更新 |
| `investor/utils/logger.py` | そのまま移行 | 変更なし |

---

## 必要な環境変数（新）

| 変数名 | 必須/任意 | 用途 |
|---|---|---|
| `SLACK_WEBHOOK_URL` | **必須** | Slack通知 |
| `ANTHROPIC_API_KEY` | 任意 | Monitor AgentのHIGHアラート時のコメント生成（なければ生データをSlack送信） |
| `PERPLEXITY_API_KEY` | 任意 | Webリサーチ強化（なければスキップ） |
| `XAI_API_KEY` | 任意 | X(Twitter)トレンド取得（なければスキップ） |

旧設定から削除: `POLYGON_API_KEY`, `NEWSAPI_KEY`

---

## yfinance使用上の注意点

1. **ETF判定**: `bool()` チェック必須。`is not None` では空リストを見逃す
2. **配当利回り**: `>1` の場合は `/100` するサニタイズが必要（パーセント値で返ることがある）
3. **Ticker.info**: ETFと個別株でキー名が異なる → 安全なデフォルト値を設定
4. **EquityQuery**: `region="us"` で米国株に絞れる
5. **キャッシュ**: 同日中に同じティッカーを複数回呼ぶ場合はキャッシュ必須（サーバー負荷軽減）

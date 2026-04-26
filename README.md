# AI Investment Agent

LLMを中核に据えた自律型の米国株投資エージェント。  
AIが調査・分析・提案を行い、**人間が最終判断を承認する**ヒューマン・イン・ザ・ループ設計。

---

## システム概要

```
Research Agent  →  Decision Agent  →  Slack通知  →  人間が承認・執行
  （逐次 or 並列）    （3段階討論）                        ↓
                                               Monitor Agent（毎日 7:00）
                                                          ↓
                                               売り提案 → 人間が執行
                                                          ↓
                                          ProposalResult に結果記録（Reflection）
```

### 3エージェント構成

| エージェント | 役割 | 実行タイミング |
|---|---|---|
| **Research Agent** | 市場スキャン → 財務/テクニカル/ニュース分析 → 候補銘柄リスト（逐次 or 並列） | 手動（任意のタイミング） |
| **Decision Agent** | 強気/弱気アナリスト討論 → PM判断 → 提案生成 → Slack通知 | Research直後に自動実行 |
| **Monitor Agent** | 保有銘柄の日次監視 → 異常検知 → 売り提案 | 毎平日 7:00（cron） |

### 主要な設計方針

- **ハーフ・ケリー基準**: ポジションサイズはLLMではなくPythonが計算。コンビクション（HIGH/MEDIUM/LOW）をもとに資本の50/25/10%を上限に配分。過去5件以上の実績がある場合は動的Kelly公式に切り替わる。
- **ATRベース価格目標**: `target = entry + 2×ATR14`、`stop = entry - 1×ATR14`。LLMは価格を推測しない。
- **強気/弱気討論**: Decision Agentは強気アナリスト→弱気アナリスト→PMの3段階構造で判断の偏りを抑制する。
- **Reflectionループ**: 過去の投資結果（ProposalResult）をPMプロンプトに注入し、勝率を動的Kellyに反映する。
- **並列リサーチ**: `--parallel` モードではThreadPoolExecutorで複数銘柄を並行分析し、最後にClaude合成で上位3〜5を選出。

---

## セットアップ

### 1. 必要要件

- Python 3.11+
- 各種 API キー（下記参照）

### 2. 依存関係のインストール

```bash
cd "/Users/yutaobayashi/PERSONAL DEV/investor"
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集して以下を入力：

| 変数名 | 取得先 | 備考 |
|---|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | claude-sonnet-4-6 使用 |
| `POLYGON_API_KEY` | [polygon.io](https://polygon.io) | 無料プランで開始可（5 req/min、15分遅延） |
| `NEWSAPI_KEY` | [newsapi.org](https://newsapi.org) | 無料プランで開始可（100 req/日） |
| `PERPLEXITY_API_KEY` | [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api) | Sonar モデル使用（有料、$5〜） |
| `SLACK_WEBHOOK_URL` | [api.slack.com](https://api.slack.com/apps) → Incoming Webhooks | Slack App → Incoming Webhooks で取得 |

### 4. データベース初期化

```bash
python -c "from investor.db.database import create_db; create_db(); print('DB OK')"
```

`investor.db`（SQLite）が作成されます。

### 5. 動作確認

```bash
# APIキーが正しいか確認（Polygon疎通テスト）
python -c "
from investor.clients.polygon_client import PolygonClient
print(PolygonClient().get_stock_snapshot('AAPL'))
"

# リサーチのドライラン（DBに保存せず、Claude出力を表示）
python scripts/run_research.py --dry-run
```

---

## 日常的な使い方

### リサーチを実行する（手動）

```bash
python scripts/run_research.py
```

1. Research Agent が市場スキャン → 上位3〜5銘柄を分析
2. Decision Agent が投資提案を生成
3. Slack に提案通知が届く
4. Slack を見て、気に入った銘柄を証券口座で購入

### 購入を記録する

```bash
python scripts/add_position.py NVDA 3 875.00
python scripts/add_position.py NVDA 3 875.00 --target 1000 --stop 820 --note "GTC catalyst play"
```

| 引数 | 説明 |
|---|---|
| `NVDA` | ティッカーシンボル |
| `3` | 株数 |
| `875.00` | 購入価格 |
| `--target` | 目標価格（任意） |
| `--stop` | 損切りライン（任意） |
| `--note` | メモ（任意） |

### ポートフォリオを確認する

```bash
python scripts/show_portfolio.py              # 保有銘柄一覧
python scripts/show_portfolio.py --live       # 現在価格も取得（API使用）
python scripts/show_portfolio.py --proposals  # 過去の提案履歴
python scripts/show_portfolio.py --watchlist  # ウォッチリスト
python scripts/show_portfolio.py --history    # 売却済みも含む
```

### 売却を記録する

```bash
python scripts/close_position.py NVDA 920.00
python scripts/close_position.py NVDA 920.00 --note "Target reached"
```

### 日次モニタリングを手動実行する

```bash
python scripts/run_monitor.py
python scripts/run_monitor.py --dry-run  # Slack送信なし
```

### 日次モニタリングを自動化する（cron）

```bash
crontab -e
```

以下を追加：
```
0 7 * * 1-5 cd "/Users/yutaobayashi/PERSONAL DEV/investor" && .venv/bin/python scripts/run_monitor.py >> logs/cron.log 2>&1
```

---

## Slack 通知の種類

### 1. 投資提案（Research 実行後）

```
🧠 Investment Proposals — 2026-04-03
─────────────────────────────
📈 NVDA — BUY | 🟢 HIGH Conviction
Entry: $860-880 | Target: $1,000 | Stop: $820 | Size: 3 shares (~$2,640)

> NVIDIA continues to dominate AI infrastructure...

Catalysts: GTC conference, H200 supply ramp
Risks: Valuation stretched at 35x forward P/E
Horizon: 4-6 weeks
─────────────────────────────
⚠️ Price data has 15-min delay. Human approval required.
```

### 2. 日次サマリー（毎朝 Monitor Agent）

```
📈 Daily Portfolio Summary — 2026-04-03
─────────────────────────────
Portfolio P&L: +$320 (+4.8%)

✅ NVDA  $875  +2.3%  (Entry: $855  P&L: +$60)
⚠️ TSLA  $210  -1.1%  (Entry: $220  P&L: -$33)
```

### 3. 売りアラート（HIGH severity）

```
🚨 SELL ALERT — TSLA
Action Required: Consider Selling

Current: $198 (15-min delay) | Entry: $220 | P&L: -10%
Stop Loss: $200 — BREACHED

> Stop-loss level breached on high volume...
```

---

## ディレクトリ構成

```
investor/
├── .env                    # シークレット（gitignore済み）
├── .env.example            # テンプレート
├── pyproject.toml          # Python依存関係
├── investor.db             # SQLiteデータベース（自動生成）
│
├── investor/               # Pythonパッケージ
│   ├── config.py           # 設定・環境変数
│   ├── api.py              # FastAPI（ダッシュボード用）
│   ├── db/
│   │   ├── models.py       # テーブル定義
│   │   └── database.py     # DB接続
│   ├── agents/
│   │   ├── research_agent.py   # ★ ツールループエージェント
│   │   ├── decision_agent.py   # 投資判断エージェント
│   │   └── monitor_agent.py    # 日次監視エージェント
│   ├── clients/
│   │   ├── polygon_client.py   # Polygon.io API
│   │   ├── news_client.py      # NewsAPI + Perplexity
│   │   └── slack_client.py     # Slack Webhook
│   ├── tools/
│   │   ├── market_tools.py     # Claude用ツール定義
│   │   ├── news_tools.py
│   │   └── technical_tools.py  # Bollinger Bands等
│   ├── prompts/            # システムプロンプト
│   ├── slack/
│   │   └── formatters.py   # Block Kitメッセージ
│   └── utils/
│       └── logger.py
│
├── scripts/                # CLIエントリポイント
│   ├── run_research.py     # リサーチ実行
│   ├── run_monitor.py      # 日次モニター
│   ├── add_position.py     # 購入記録
│   ├── close_position.py   # 売却記録
│   └── show_portfolio.py   # 確認
│
├── tests/
│   ├── test_clients.py
│   └── test_agents.py
│
└── logs/                   # ログファイル（自動生成）
```

---

## データベース構造

| テーブル | 説明 |
|---|---|
| `position` | 保有・売却済み銘柄（status: open/closed） |
| `research_report` | Research Agentの分析結果（run_idでバッチ管理） |
| `investment_proposal` | Decision Agentの提案（human_decision: pending/approved/rejected） |
| `monitor_alert` | Monitor Agentのアラート（severity: HIGH/MEDIUM/LOW） |
| `watchlist_item` | 注目銘柄リスト（status: active/converted/dropped） |
| `stock_universe` | 分析済み銘柄マスター |

直接確認する場合：
```bash
sqlite3 investor.db "SELECT ticker, score, created_at FROM research_report ORDER BY created_at DESC LIMIT 5;"
sqlite3 investor.db "SELECT ticker, action, conviction, human_decision FROM investment_proposal ORDER BY created_at DESC LIMIT 5;"
sqlite3 investor.db "SELECT ticker, shares, entry_price, status FROM position;"
```

---

## API制限と注意事項

| サービス | 無料枠 | 注意 |
|---|---|---|
| Polygon.io | 5 req/min、15分遅延 | Research実行に約10〜15分かかる（意図的なスロットリング） |
| NewsAPI | 100 req/日 | Research(〜10回) + Monitor(〜5回) = 約15回/日で余裕あり |
| Claude API | 従量課金 | 1回のリサーチで約$0.05〜0.20程度 |

**価格データの遅延について:** Polygon無料プランは15分遅延。Slackメッセージには必ず "(15-min delay)" を表示する設計になっています。リアルタイムデータが必要な場合は Polygon Starter ($29/月) へのアップグレードを検討してください。

---

## テスト

```bash
# 全テスト（APIキー不要、モック使用）
.venv/bin/pytest tests/ -v

# 統合テスト（実APIキー必要）
.venv/bin/pytest tests/ -m integration -v
```

---

## ダッシュボード（オプション）

FastAPI サーバーを起動すると、`http://localhost:8000` でポートフォリオデータをAPIで取得できます：

```bash
.venv/bin/uvicorn investor.api:app --reload --port 8000
```

エンドポイント：
- `GET /api/portfolio` — 保有銘柄
- `GET /api/proposals` — 提案履歴
- `GET /api/alerts` — モニターアラート
- `GET /api/watchlist` — ウォッチリスト

---

## ロードマップ

- [x] Research Agent（銘柄スキャン・分析）
- [x] Decision Agent（投資提案・Slack通知）
- [x] Monitor Agent（日次監視・売り提案）
- [x] ポートフォリオ管理 CLI
- [x] FastAPI バックエンド
- [ ] Next.js ダッシュボード UI
- [ ] シミュレーション機能（仮想トレード）
- [ ] Alpaca API 連携（自動執行、将来フェーズ）

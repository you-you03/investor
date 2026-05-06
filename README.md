# AI Investment Agent

Claude Code を中核に据えた米国株投資エージェント。  
Python スクリプトがデータを収集し、Claude が分析・判断し、Slack で通知する。**人間が最終承認する**ヒューマン・イン・ザ・ループ設計。

---

## 投資マンデート

| 項目 | 値 |
|---|---|
| 予算 | ¥1,000,000（約 $6,700 USD） |
| 週次目標リターン | +8%（¥80,000/週） |
| 戦略スタイル | モメンタム — リスク管理優先、分散投資 |
| 最大同時ポジション数 | 5銘柄 |
| 1銘柄最大配分 | 予算の25%（$1,675） |
| ストップロス | 厳格遵守（ATR 1× またはリサーチ指定値） |

---

## システム概要

```
/research
  Python → yfinance でデータ収集 → stdout に JSON
  Claude → スクリーニング・スコアリング → research_history.json に保存

/decision
  Python → research_history.json + watchlist を読み込み → stdout に出力
  Claude → 5ペルソナ討論 → PM 合成判断 → Slack 通知

/monitor（cron 毎平日 7:00）
  Python → ポジション × 現在値 → stdout
  Claude → 異常検知・売り提案 → Slack 通知

人間 → Slack を確認 → 証券口座で執行 → /portfolio で記録
```

### 設計方針

**Claude Code IS the agent** — Python スクリプトは Anthropic SDK を呼ばない。`ANTHROPIC_API_KEY` 不要。Claude Code セッション自体がエージェントとして動作する。

**5ペルソナ討論** — Decision では Warren Buffett (oracle) / Cathie Wood (innovator) / Ray Dalio (macro_mind) / Peter Lynch (tenbagger) / Jesse Livermore (tape_reader) の 5 ペルソナが独立スタンスを取り、Round 2 でクロスファイアを行い、PM が合成判断を下す。セクター・マクロ状況に応じてペルソナを動的に選出。

**yfinance ベース** — Polygon.io や NewsAPI の API キーは不要。株価・テクニカル・財務・ニュースはすべて yfinance で取得（15分遅延）。オプションで Perplexity（Web検索）・xAI（X センチメント）を強化に使用可。

**CSV/JSON 永続化** — データベース不要。`data/portfolio.csv`・`data/research_history.json` 等のフラットファイルで管理。

**ポジションサイジング（分散型）**  
確信度による基本サイズ: HIGH = 20–25%、MEDIUM = 15%、LOW = 10%  
ファンダ成長率副軸: Revenue YoY > 100% または EPS YoY > 200% → 上限まで増額可  
RSI 特例: RSI > 80 でも `STRONG_OUTPERFORM` × セクターLEADING の場合、1段階縮小でエントリー許可

---

## セットアップ

### 1. 必要要件

- Python 3.11+
- Claude Code CLI（`claude` コマンドが使えること）

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

`.env` を編集:

| 変数名 | 必須 | 用途 |
|---|---|---|
| `SLACK_WEBHOOK_URL` | **必須** | Decision・Monitor の通知先 |
| `PERPLEXITY_API_KEY` | 任意 | Web 検索強化（Sonar モデル） |
| `XAI_API_KEY` | 任意 | X/Twitter センチメント（Grok） |

> `ANTHROPIC_API_KEY` は不要。Claude Code セッション自体がエージェントとして動作するため。

### 4. 動作確認

```bash
# yfinance 疎通テスト
.venv/bin/python -c "
import yfinance as yf
snap = yf.Ticker('AAPL').fast_info
print('Price:', snap.last_price)
"

# ポートフォリオ確認
.venv/bin/python skills/portfolio.py list
```

---

## 日常的な使い方

すべての操作は Claude Code セッション内で `/スキル名` を呼び出す。

### リサーチを実行する

```
/research
```

1. yfinance で市場モーバー・52週高値ブレイクアウト・決算サプライズを取得
2. Claude がスクリーニング → 各銘柄を 5 軸（モメンタム/ファンダ/カタリスト/テクニカル/センチメント）でスコアリング
3. スコア ≥ 7.0 の候補を `data/research_history.json` に保存
4. 空きスロットがある場合、自動的に `/decision` 実行を促す

単一銘柄を優先リサーチする場合:

```
/research --seed NVDA
```

### 投資判断を出す

```
/decision
```

または特定 run_id を指定:

```
/decision {run_id}
```

1. 最新リサーチの候補 + ウォッチリスト ESCALATED 銘柄を読み込み
2. 5ペルソナ討論（Round 1 → データ補完 → Round 2 クロスファイア → PM 合成）
3. BUY 推奨を Slack に送信（Block Kit 形式）
4. `data/decision_history.json` に結果を記録

### ポジションを管理する

```bash
# ポートフォリオ一覧（現在値・含み損益）
.venv/bin/python skills/portfolio.py list

# 購入記録
.venv/bin/python skills/portfolio.py add --ticker NVDA --shares 10 --price 875

# 売却記録
.venv/bin/python skills/portfolio.py close --ticker NVDA --price 950

# 現在値スナップショット取得
.venv/bin/python skills/portfolio.py snapshot
```

### ウォッチリストを管理する

```bash
.venv/bin/python skills/watchlist.py list
.venv/bin/python skills/watchlist.py add --ticker MRVL --reason "半導体モメンタム継続"
.venv/bin/python skills/watchlist.py remove --ticker MRVL
```

### ウォッチリスト銘柄を深掘りする

```
/watchlist-research
```

active なウォッチリスト銘柄に対して深研究を実行し、`ESCALATE / MAINTAIN / REMOVE / ADD_NOTE` を判断する。ESCALATE になった銘柄は次回 `/decision` で自動的に優先候補に昇格する。

### 日次モニタリング

```
/monitor
```

保有銘柄の現在値・テクニカル指標を確認し、ストップロス接近・目標達成・異常値を検知して Slack に通知する。

自動化（毎平日 7:00）:

```bash
crontab -e
# 以下を追加:
0 7 * * 1-5 cd "/Users/yutaobayashi/PERSONAL DEV/investor" && .venv/bin/python skills/monitor.py >> logs/cron.log 2>&1
```

### 出口判断を出す

```
/decision --mode exit --ticker NVDA
```

5ペルソナが保有継続 vs 売却を討論し、FULL_EXIT / PARTIAL_EXIT / RAISE_TARGET / HOLD のいずれかを提案する。

---

## スキル一覧

| スキル | CLI | 主な出力 |
|---|---|---|
| `/research` | `python skills/research.py` | `data/research_history.json` + `reports/research/` |
| `/research --seed {TICKER}` | 同上 | 単一銘柄の深研究レポート |
| `/watchlist-research` | `python skills/watchlist_research.py` | `data/watchlist_research_history.json` + `reports/research/` |
| `/decision` | `python skills/decision.py` | Slack 通知 + `reports/decision/` |
| `/decision --mode exit` | 同上 | 出口判断レポート + Slack |
| `/portfolio` | `python skills/portfolio.py` | ターミナル表示 |
| `/watchlist` | `python skills/watchlist.py` | ターミナル表示 |
| `/monitor` | `python skills/monitor.py` | Slack 通知 + `reports/monitor/` |

---

## ディレクトリ構成

```
investor/
├── .env                    # シークレット（gitignore済み）
├── .env.example
├── pyproject.toml
│
├── .claude/
│   └── commands/           # Claude Code スキル定義（Markdown）
│       ├── research.md
│       ├── decision.md
│       ├── monitor.md
│       └── review.md
│
├── investor/               # Python パッケージ（データ収集層）
│   ├── config.py
│   ├── data/
│   │   └── yfinance_client.py      # yfinance ラッパー
│   ├── notifications/
│   │   └── slack.py                # Slack Webhook 送信
│   ├── prompts/
│   │   ├── research_prompts.py
│   │   ├── decision_prompts.py     # 5ペルソナ・PM プロンプトテンプレート
│   │   ├── monitor_prompts.py
│   │   └── personas.py             # ペルソナ定義 + select_personas() ルール
│   ├── slack/
│   │   └── formatters.py           # Block Kit フォーマッター
│   └── utils/
│       ├── cache.py                # 24時間 TTL キャッシュ
│       └── logger.py
│
├── skills/                 # Claude Code スキル エントリポイント
│   ├── research.py
│   ├── watchlist_research.py
│   ├── decision.py
│   ├── portfolio.py
│   ├── watchlist.py
│   ├── monitor.py
│   └── screen.py
│
├── scripts/                # ユーティリティ・メンテナンス用
│   ├── tool.py             # 全ツールの統合エントリポイント（Claude が呼ぶ）
│   ├── add_position.py
│   ├── close_position.py
│   ├── show_portfolio.py
│   ├── fetch_returns.py    # score_snapshots.json の週次リターン埋め
│   ├── record_outcomes.py
│   ├── show_calibration_stats.py
│   └── send_slack_proposals.py
│
├── data/                   # 永続化データ（CSV/JSON）
│   ├── portfolio.csv               # オープン/クローズポジション
│   ├── research_history.json       # リサーチ実行履歴
│   ├── watchlist.json              # ウォッチリスト銘柄
│   ├── watchlist_research_history.json
│   ├── decision_history.json       # ディベート結果ログ
│   ├── score_snapshots.json        # 全スコア記録（週次検証用）
│   ├── monitor_alerts.json
│   └── cache/                      # 24時間 TTL キャッシュ
│
├── reports/                # 実行レポート（Markdown）
│   ├── research/
│   ├── decision/
│   ├── monitor/
│   └── review/
│
├── docs/                   # 設計ドキュメント
│   └── retrospective-2026-04.md
│
└── tests/
```

---

## データ構造

### portfolio.csv

```
ticker, shares, entry_price, entry_date, exit_price, exit_date, status, target_price, stop_loss, note
NVDA, 10, 875.00, 2026-04-25, , , open, 1000.00, 820.00, HIGH確信
AAOI, 19, 103.91, 2026-04-05, 150.60, 2026-04-11, closed, 131.18, 90.28, TARGET_HIT +44.9%
```

### research_history.json（骨格）

```json
{
  "runs": [
    {
      "run_id": "<uuid4>",
      "date": "2026-04-25",
      "macro_regime": "NORMAL",
      "candidates": [
        {
          "ticker": "NVDA",
          "score": 8.2,
          "score_breakdown": { "momentum": 9, "fundamentals": 8, ... },
          "entry_zone": "860–880",
          "target_price": 1000,
          "stop_loss": 820,
          "rs_signal": "STRONG_OUTPERFORM"
        }
      ]
    }
  ]
}
```

### watchlist.json（エントリー例）

```json
{
  "ticker": "MRVL",
  "added_at": "2026-04-11",
  "source": "research_seeded",
  "last_score": 7.85,
  "reference_price": 128.49,
  "reason": "RSI過熱でWAIT。押し目を待機中。",
  "status": "active"
}
```

---

## Slack 通知の種類

### 投資提案（/decision 後）

```
🧠 Investment Proposals — 2026-04-25
────────────────────────────────────
📈 ALAB — BUY | 🟢 HIGH Conviction
Entry: $145-150 | Target: $213 | Stop: $128 | Size: ~$1,675

> AI インフラ向けカスタム ASIC の需要が急増...

Catalysts: 決算発表（14日以内）, アナリスト目標 +42%
Risks: 高バリュエーション, セクター集中リスク
Horizon: 3-4 weeks
────────────────────────────────────
```

### 日次サマリー（毎朝 /monitor）

```
📊 Portfolio Monitor — 2026-05-04
────────────────────────────────────
Portfolio P&L: +$2,175 (+32.5%)

✅ PANW   $181.08  +1.4%  (Entry: $178.54)
⚠️ TSM    $397.67  -1.2%  (Entry: $402.46)  ← ストップ接近
```

### 売りアラート

```
🚨 EXIT SIGNAL — NVDA
ACTION: STOP_LOSS — 損切りライン到達

Current: $197.50 | Entry: $208.27 | P&L: -5.2%
Stop: $198.00 — BREACHED
```

---

## テスト

```bash
.venv/bin/pytest tests/ -v
```

---

## ロードマップ

- [x] yfinance によるデータ収集（無料、API キー不要）
- [x] 5ペルソナ討論 + PM合成（Decision）
- [x] ウォッチリスト管理・ESCALATE フロー
- [x] ポートフォリオ管理 CLI
- [x] スコア検証（score_snapshots.json + 週次リターン埋め）
- [x] 出口判断（/decision --mode exit）
- [x] ファンダ成長率副軸・RSI特例ルール
- [ ] 確信度校正レポートの自動週次集計
- [ ] ダッシュボード UI（FastAPI + フロントエンド）

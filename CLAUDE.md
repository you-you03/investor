# investor — AI-powered US Stock Investment Agent

## Investment Mandate

| 項目 | 値 |
|---|---|
| **予算** | ¥1,000,000（約 $6,700 USD） |
| **週次目標リターン** | +8%（¥80,000/週） |
| **戦略スタイル** | 通常モメンタム — リスク管理優先、分散投資 |
| **最大同時ポジション数** | 5銘柄 |
| **1銘柄最大配分** | 予算の25%（¥250,000 / 約$1,675） |
| **ストップロス** | 厳格遵守（ATR 1×またはリサーチ指定値） |

ポジションサイジング: HIGH確信=20-25%、MEDIUM=15%、LOW=10%。1銘柄50%以上は禁止。

---

## Critical Design Rule: Claude Code IS the Agent

**Python スクリプトは Anthropic SDK を呼ばない。** Claude Code セッション自体がエージェント。

- Python スクリプト → データ収集 → stdout に JSON 出力
- Claude → 出力を読んで分析・判断
- Claude → 保存スクリプトまたは通知スクリプトを呼ぶ

`ANTHROPIC_API_KEY` は不要。`investor/` 内のどのファイルも `anthropic` ライブラリを import してはならない。

---

## Repository Layout

```
skills/                    ← Claude Code Skills エントリポイント
investor/
  agents/                  ← Research / Decision のオーケストレーター（旧設計、現在は Claude が担当）
  clients/                 ← yfinance_client.py
  core/                    ← ビジネスロジック
  notifications/           ← Slack webhook
  prompts/                 ← Claude に渡すプロンプトテンプレート
  tools/                   ← Claude 用ツール関数（JSON Schema 付き）
  utils/                   ← logger.py, cache.py
data/                      ← CSV/JSON 永続化
  portfolio.csv            ← オープン/クローズポジション
  research_history.json    ← リサーチ実行履歴
  watchlist.json           ← ウォッチリスト銘柄
  watchlist_research_history.json
  cache/{key}_{date}.json  ← 24時間 TTL キャッシュ
reports/
  research/research_{date}.md    ← /research 実行後に作成
  decision/decision_{date}.md    ← /decision 実行後に作成
scripts/                   ← Cron 対応スタンドアロンランナー
```

---

## Skills (エントリポイント)

詳細は [SKILL.md](SKILL.md) を参照。

| スキル | CLI | 出力 |
|---|---|---|
| `/research` | `python skills/research.py` | `data/research_history.json` + `reports/research/` |
| `/watchlist-research` | `python skills/watchlist_research.py` | `data/watchlist_research_history.json` + `reports/research/` |
| `/decision` | `python skills/decision.py` | Slack 通知 + `reports/decision/` |
| `/portfolio` | `python skills/portfolio.py list\|add\|close\|snapshot` | ターミナル表示 |

---

## Data Flow

```
/research:
  1. python skills/research.py
       → yf.screen() でマーケットムーバー取得
       → 銘柄ごとに snapshot/technicals/financials/news
       → stdout に JSON 出力
  2. Claude がスクリーニング → top 3-5 候補を選定
       → python skills/research.py --save '{"run_id":"...","candidates":[...]}'

/decision:
  1. python skills/decision.py
       → research_history.json + watchlist_research_history.json を読む
       → ESCALATED 銘柄が market-scan より優先
       → stdout に候補を出力
  2. Claude が Bullish → Bearish → PM ディベートを内部実行
       → python skills/decision.py --send '[{...proposals...}]'
       → Slack (Block Kit) に送信
```

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `SLACK_WEBHOOK_URL` | **Yes** | Slack 通知 |
| `PERPLEXITY_API_KEY` | No | Web 検索強化 |
| `XAI_API_KEY` | No | X/Twitter センチメント (Grok) |

---

## yfinance 注意点（非自明なもの）

- `yf.screen()` の戻り値は `{"quotes": [...]}` — `quotes` キーを参照する
- `Ticker.news` はネストされた `content` キーを持つ構造体
- ETF チェックは `bool(val)` を使う（`is not None` では不足）
- レート制限を避けるため、銘柄ごとの呼び出しはすべてキャッシュすること
- `Ticker.fast_info` でリアルタイム価格/出来高（遅延なし）

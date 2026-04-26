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

### ポジションサイジング方針

- **HIGH確信** → 予算の20-25%（¥200,000-250,000 / $1,340-1,675）
- **MEDIUM確信** → 予算の15%（¥150,000 / $1,005）
- **LOW確信** → 予算の10%（¥100,000 / $670）
- **集中投資（1銘柄に50%以上）は禁止** — 分散によるリスク低減を優先

週次8%目標は3-5銘柄に分散し、各銘柄で+2-4%の寄与を積み上げる形を想定。

---

## Architecture Overview

```
skills/          ← Entry points (Claude Code Skills / CLI commands)
investor/
  agents/        ← Orchestrators (Research + Decision)
  data/          ← Data layer (yfinance_client.py)
  core/          ← Business logic (planned)
  notifications/ ← Slack (slack.py)
  prompts/       ← Claude prompts
  tools/         ← Tool functions called by agents
  utils/         ← logger.py, cache.py
data/            ← File persistence (CSV/JSON)
scripts/         ← Cron-compatible standalone runners
```

## Design Principle: Claude Code as the Agent

**No Anthropic SDK calls in agents.** Claude Code (the current session) IS the agent.
- Python scripts collect data and print to stdout
- Claude reads the output, performs analysis/debate
- Claude saves results or calls send scripts

## Data Flow

```
/research:
  Step 1 (Python): python skills/research.py
    → YFinanceClient.get_market_movers()
    → per-ticker: snapshot, technicals, financials, news (yfinance)
    → prints JSON report to stdout

  Step 2 (Claude Code): reads output, screens top 3-5 candidates
    → python skills/research.py --save '{"run_id":"...","candidates":[...]}'
    → saves → data/research_history.json

/decision:
  Step 1 (Python): python skills/decision.py
    → reads data/research_history.json
    → prints candidates + open positions to stdout

  Step 2 (Claude Code): Bullish → Bearish → PM debate internally
    → python skills/decision.py --send '[{...proposals...}]'
    → sends → Slack (Block Kit)

/portfolio  → reads/writes data/portfolio.csv
/watchlist  → reads/writes data/watchlist.json
```

## Module Responsibilities

| Module | Role |
|---|---|
| `investor/data/yfinance_client.py` | Fetch market data (no API key needed) |
| `investor/utils/cache.py` | 24-hr TTL JSON cache in data/cache/ |
| `investor/tools/market_tools.py` | Tool functions + JSON Schema for Claude |
| `investor/tools/news_tools.py` | News (yfinance primary), optional Perplexity/Grok |
| `investor/agents/research_agent.py` | Sequential/parallel research loop |
| `investor/agents/decision_agent.py` | Bullish/Bearish/PM debate pipeline |
| `investor/notifications/slack.py` | Slack webhook + Block Kit formatters |

## Persistence Files

| File | Format | Content |
|---|---|---|
| `data/portfolio.csv` | CSV | Open/closed positions, entry/exit prices |
| `data/research_history.json` | JSON | Research runs with candidates |
| `data/watchlist.json` | JSON | Watchlist tickers |
| `data/cache/{key}_{date}.json` | JSON | 24-hr yfinance cache |

## Reports Directory

ユーザーへの提案レポート・調査レポートはすべて `reports/` 以下に保存する。

```
reports/
  research/    ← /research 実行後のリサーチレポート（research_YYYY-MM-DD.md）
  decision/    ← /decision 実行後の投資判断レポート（decision_YYYY-MM-DD.md）
```

- リサーチ実行後は `reports/research/research_{date}.md` を作成すること
- 投資判断レポートは `reports/decision/decision_{date}.md` を作成すること

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `SLACK_WEBHOOK_URL` | **Yes** | Slack notifications |
| `ANTHROPIC_API_KEY` | Yes (Research/Decision) | Claude API calls |
| `PERPLEXITY_API_KEY` | No | Web search enhancement |
| `XAI_API_KEY` | No | X/Twitter sentiment via Grok |

## Running Skills

```bash
# Research scan (140+ stocks → Phase 1 screen → Phase 2 deep research)
python skills/research.py
python skills/research.py --sequential
python skills/research.py --tickers NVDA,TSLA

# Watchlist deep research (active watchlist only, ~10 stocks, fast)
python skills/watchlist_research.py
python skills/watchlist_research.py --sequential
python skills/watchlist_research.py --save '{"run_id":"...","results":[...]}'

# Investment decision (auto-merges latest watchlist research if available)
python skills/decision.py
python skills/decision.py --run-id <uuid>
python skills/decision.py --watchlist-run-id <uuid>

# Portfolio management
python skills/portfolio.py list
python skills/portfolio.py add --ticker NVDA --shares 10 --price 875
python skills/portfolio.py close --ticker NVDA --price 950
python skills/portfolio.py snapshot

# Watchlist CRUD
python skills/watchlist.py list
python skills/watchlist.py add --ticker NVDA --reason "AI chip momentum"
python skills/watchlist.py remove --ticker NVDA
```

## yfinance Notes

- `yf.screen()` returns `{"quotes": [...]}` for market movers
- `Ticker.fast_info` for real-time price/volume (no delay)
- `Ticker.history()` for OHLCV bars
- `Ticker.news` returns structured dicts with nested `content` key
- ETF check: use `bool(val)` not `is not None` for list fields
- Cache all per-ticker calls to avoid rate limiting

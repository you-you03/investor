# investor Skills

This project exposes 4 Claude Code skills, invocable via natural language.

## /research — Market Research Scan

**Triggers**: 「今日の注目銘柄を調べて」「リサーチして」「相場スキャンを実行して」

**What it does**:
1. Calls `yf.screen()` to get today's market movers (gainers/losers/actives)
2. Screens candidates with Claude
3. Runs per-ticker deep research (price snapshot, technicals, financials, news)
4. Saves results to `data/research_history.json`

**CLI**:
```bash
python skills/research.py [--parallel/--sequential] [--tickers NVDA,TSLA] [--dry-run]
```

**Output**: `run_id` (UUID) saved to research_history.json

---

## /watchlist-research — Watchlist Deep Research

**Triggers**: 「ウォッチリスト銘柄を調べて」「ウォッチリストのリサーチをして」「watchlist-researchを実行して」

**What it does**:
1. Reads all `active` items from `data/watchlist.json`
2. Runs full deep research on each ticker (same as `/research` per-ticker step)
3. Claude evaluates each ticker vs. its original thesis and proposes an action
4. Saves results to `data/watchlist_research_history.json` and updates `watchlist.json`

**Actions Claude may propose per ticker**:
- `ESCALATE` — strong entry setup found → promote to `/decision` consideration
- `MAINTAIN` — thesis intact, keep watching
- `REMOVE` — thesis broken or fundamentals degraded → remove from watchlist
- `ADD_NOTE` — update score/note, no status change

**CLI**:
```bash
python skills/watchlist_research.py                    # collect + print for Claude
python skills/watchlist_research.py --sequential       # sequential mode
python skills/watchlist_research.py --save '{"run_id":"...","results":[...]}'  # save Claude's analysis
```

**Save JSON format**:
```json
{
  "run_id": "<uuid from collection step>",
  "results": [
    {
      "ticker": "NVDA",
      "action": "ESCALATE",
      "new_score": 8.2,
      "note": "RSI冷却、エントリーゾーン$205-210",
      "flag": "ESCALATE_TO_DECISION"
    }
  ]
}
```

**Output**: `reports/research/watchlist_research_{date}.md`

---

## /decision — Investment Decision

**Triggers**: 「投資判断を出して」「リサーチ結果から判断して」「Slackに提案を送って」

**What it does**:
1. Reads the latest research run from `data/research_history.json`
2. If `data/watchlist_research_history.json` exists, automatically merges the latest watchlist research — ESCALATED tickers take priority over market-scan duplicates
3. Runs Bullish Analyst → Bearish Analyst → Portfolio Manager pipeline
4. Sends proposals to Slack (Block Kit format)

**CLI**:
```bash
python skills/decision.py [--run-id <uuid>] [--watchlist-run-id <uuid>] [--dry-run]
```

**Output**: Slack message with BUY proposals (HIGH conviction only)

---

## /portfolio — Portfolio Management

**Triggers**: 「ポートフォリオを見せて」「NVDAを10株$875で購入した」「NVDAをクローズした」「P&Lを確認して」

**What it does**: Read/write `data/portfolio.csv`

**CLI**:
```bash
python skills/portfolio.py list
python skills/portfolio.py add --ticker NVDA --shares 10 --price 875
python skills/portfolio.py close --ticker NVDA --price 950
python skills/portfolio.py snapshot   # current prices via yfinance
```

**Output**: Rich table with positions and P&L

---

## /watchlist — Watchlist Management

**Triggers**: 「NVDAをウォッチリストに追加して」「ウォッチリストを見せて」「TSLAをウォッチリストから削除して」

**What it does**: Read/write `data/watchlist.json`

**CLI**:
```bash
python skills/watchlist.py list
python skills/watchlist.py add --ticker NVDA --reason "AI chip momentum"
python skills/watchlist.py remove --ticker NVDA
```

---

## Typical Workflow

```
Weekly (market research scan):
1. /research              → scans 140+ stocks → generates run_id
2. /decision              → merges research + watchlist results → Slack proposals
3. (human approves)       → /portfolio add --ticker X --shares N --price P
4. Monitor (cron 7am)     → checks stop-loss/target → Slack alert

Between scans (watchlist follow-up):
1. /watchlist-research    → deep research on active watchlist only (~11 stocks, fast)
2. Claude proposes actions: ESCALATE / MAINTAIN / REMOVE / ADD_NOTE
3. --save                 → updates watchlist.json scores/flags
4. /decision              → auto-includes latest watchlist research in debate context

Adding/removing from watchlist:
- /watchlist add --ticker X --reason "..."
- /watchlist remove --ticker X
- /watchlist list
```

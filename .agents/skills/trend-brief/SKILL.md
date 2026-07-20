---
name: trend-brief
description: Market trend and key-term brief for US stock investing. Use when the user wants a short human-readable Japanese report of important market trends, themes, words, narratives, sector rotations, news terms, earnings keywords, or a proposal for what terms/trends should be monitored.
allowed-tools: Bash(.venv/bin/python *) Bash(mkdir *) Read Write
---

# Trend Brief

Create a short Japanese brief that helps a human quickly understand:

1. which market trends matter now
2. which words or narratives should be watched
3. why they matter for the investor mandate
4. what should be checked next

Keep the output short, concrete, and readable before any deep research.

All Bash commands must be run from the `investor/` subdirectory:

```bash
cd "/Users/yutaobayashi/PERSONAL DEV/1_now/investor"
```

## Inputs

Use the freshest available local data first:

```bash
.venv/bin/python scripts/tool.py get_market_context
.venv/bin/python scripts/tool.py get_market_movers
.venv/bin/python scripts/tool.py get_market_movers --direction actives
.venv/bin/python scripts/tool.py get_52w_breakouts
.venv/bin/python scripts/tool.py get_earnings_surprises
```

Also read these files when present:

- `data/daily_lite_history.json` for latest alerts and pending actions
- `data/research_history.json` for recently scored candidates
- `data/watchlist.json` for names already under observation
- `data/score_snapshots.json` for recurring high-score themes

If the user provides raw notes, news, or a manual list of terms, prioritize those and use local data only as context.

## Trend Selection

Pick only trends that pass at least two of these gates:

- **Price confirmation**: relevant tickers/ETFs are breaking out, outperforming SPY/QQQ, or appearing in movers/breakouts
- **Volume/attention**: high relative volume, repeated active list appearance, or notable news flow
- **Catalyst clarity**: earnings, guidance, regulation, macro data, product cycle, analyst revision, or sector event
- **Portfolio relevance**: affects open positions, watchlist, or likely /research candidates
- **Risk regime impact**: VIX, yields, dollar, oil, or market breadth changes the entry/position sizing stance

Classify each accepted trend:

- `TRADEABLE_NOW`: can generate /research or /decision candidates
- `WATCH`: important but needs confirmation or cooling off
- `RISK`: can invalidate entries, stops, or sector exposure
- `BACKGROUND`: useful context, not actionable yet

Do not over-cover. Default to 3-5 trends.

## Word Selection

Select 8-15 words or phrases a human should recognize. Favor terms that are:

- repeated in market/news context
- connected to watchlist or research candidates
- ambiguous enough that a short definition prevents misunderstanding
- likely to affect catalysts, risk, or position sizing

Use this priority order:

1. Portfolio/watchlist terms
2. Macro risk terms
3. Sector rotation terms
4. Earnings/catalyst terms
5. New narratives that may become screens

When the user asks what terms/trends should be monitored in general, read `reference/trend-taxonomy.md` and propose a compact monitoring universe.

## Report Format

Write in Japanese. Keep the whole report short enough to read in 2-3 minutes.

Use this structure:

```markdown
# Trend Brief — YYYY-MM-DD

## 結論
- 今日押さえるべき流れ: ...
- 投資判断への影響: ...
- 次の一手: ...

## トレンド
| 優先 | トレンド | 状態 | なぜ重要か | 見る指標/銘柄 |
|---|---|---|---|---|
| 1 | ... | TRADEABLE_NOW | ... | ... |

## 押さえる単語
| 単語 | 一言で | 投資上の意味 |
|---|---|---|
| ... | ... | ... |

## アクション候補
- `/research --seed TICKER`: 理由
- `/monitor`: 理由
- 何もしない: 条件待ち
```

Rules:

- One trend explanation must fit in one short sentence.
- One word definition must fit in roughly 30 Japanese characters.
- Avoid generic dictionary definitions. Tie each word to market impact.
- If evidence is weak, mark the trend as `WATCH` or `BACKGROUND` instead of overstating it.
- Include dates for time-sensitive claims.
- Mention data gaps explicitly when they change confidence.

## Save Output

If the user asks to save the brief, create:

```bash
mkdir -p reports/trend
```

Write the report to:

```text
reports/trend/trend_brief_YYYY-MM-DD.md
```

Do not update `portfolio.csv`, `research_history.json`, or `watchlist.json`. This skill is for compression, monitoring design, and next-action suggestions only.

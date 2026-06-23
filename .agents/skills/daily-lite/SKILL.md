---
description: 軽量な daily 実行。monitor-lite + watchlist-lite + research-lite を 1 回でまとめて走らせる
argument-hint: ""
allowed-tools: Bash(.venv/bin/python *) Read
---

Run the lightweight daily workflow in one execution.

All Bash commands must be run from the `investor/` subdirectory:
```bash
cd "/Users/yutaobayashi/PERSONAL DEV/1_now/investor"
```

## Command

```bash
.venv/bin/python skills/daily_lite.py
```

## Dry run

```bash
.venv/bin/python skills/daily_lite.py --dry-run
```

## What it does

- monitor-lite: open positions の価格監視と HIGH/MEDIUM alert 検知
- watchlist-lite: active watchlist の簡易フラグ判定と `pipeline_status` 更新
- research-lite: 市場全体の軽量スクリーニングから `/research --seed` 候補を抽出
- report: `reports/daily/daily_lite_{date}.md`
- history: `data/daily_lite_history.json`

## Behavior

- LLM を使わない
- `portfolio.csv` や `research_history.json` には書き込まない
- `watchlist.json` は軽い状態更新のみ行う
- `decision` は呼ばない。必要なときだけ pending action として出す

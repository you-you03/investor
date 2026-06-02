# investor — AI-powered US Stock Investment Agent

## Investment Mandate

| 項目 | 値 |
|---|---|
| **予算** | ¥1,000,000（約 $6,700 USD） |
| **週次目標リターン** | +2.5%（¥25,000/週、年換算+130%） |
| **戦略スタイル** | バランスモメンタム — リスク管理優先、分散投資 |
| **最大同時ポジション数** | 5銘柄 |
| **1銘柄最大配分** | 予算の25%（¥250,000 / 約$1,675） |
| **ストップロス** | 厳格遵守（ATR 1×またはリサーチ指定値） |

ポジションサイジング: ケリー基準（リスク2%固定）で計算後、25%上限キャップ → VIXレジーム乗数。1銘柄50%以上は禁止。

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
.claude/skills/               ← Claude Code スキル（エントリポイント）
  decision/
    SKILL.md                  ← 5ペルソナ投資ディベート + PM 判断
    reference/
      exit-mode.md            ← Exit Decision Mode（--mode exit）
  research/
    SKILL.md                  ← フルマーケットスキャン
    reference/
      seed-mode.md            ← Seed モード（--seed TICKER）
  monitor/
    SKILL.md                  ← 日次ポジション + ウォッチリスト監視
  review/
    SKILL.md                  ← パフォーマンス分析・スコア校正
  watchlist-research/
    SKILL.md                  ← ウォッチリスト集中リサーチ
  daily-lite/
    SKILL.md                  ← 日次軽量サマリー（monitor-lite + watchlist-lite + research-lite）

investor/
  prompts/                    ← Claude に渡すプロンプトテンプレート
    personas.py               ← 5ペルソナ定義
    decision_prompts.py       ← PM 合成プロンプト
    research_prompts.py       ← リサーチプロンプト
    paper_decision_prompts.py ← B枠仮説定義（PAPER_HYPOTHESES）
  clients/                    ← yfinance_client.py
  core/                       ← ビジネスロジック
  notifications/              ← Slack webhook
  tools/                      ← Claude 用ツール関数（JSON Schema 付き）
  utils/                      ← logger.py, cache.py

skills/                       ← Python スクリプト（データ収集・保存）
scripts/                      ← Cron 対応スタンドアロンランナー

data/
  portfolio.csv               ← A枠 オープン/クローズポジション
  paper_portfolio.csv         ← B枠 仮想ポジション（仮説検証用）
  research_history.json       ← /research 実行履歴
  watchlist.json              ← ウォッチリスト銘柄
  watchlist_research_history.json
  score_snapshots.json        ← 全銘柄スコア（/review の検証用）
  decision_history.json       ← /decision 実行履歴
  trade_journal.json          ← クローズトレード詳細記録
  cache/{key}_{date}.json     ← 24時間 TTL キャッシュ

reports/
  research/research_{date}.md
  decision/decision_{date}.md
  decision/exit_{date}_{ticker}.md
docs/
  hypothesis-tracker.md       ← A/B枠 仮説定義・判定基準
```

---

## Skills（エントリポイント）

| スキル | Claudeが担う判断 | 前提条件 | 呼び出し頻度 |
|---|---|---|---|
| `/research` | マーケットスキャン → 5軸スコアリング → 候補選定 | なし（常時実行可） | 週1〜2回 |
| `/research --seed {TICKER}` | 単一銘柄の深研究 + 前回比較 | watchlist.json に対象が存在することが望ましい | ウォッチリストアラート時 |
| `/watchlist-research` | 全ウォッチリスト銘柄を深研究 → ESCALATE/MAINTAIN/REMOVE 判断 | watchlist.json に active 銘柄が存在すること | 週1回または手動 |
| `/daily-lite` | monitor-lite + watchlist-lite + research-lite を一括実行 → Slack送信 | なし | 毎朝（Scheduled 推奨） |
| `/decision` | 5ペルソナディベート → PMとして最終BUY/PASS判断 → Slack送信 | research_history.json に最新 run が存在すること | /research の直後 |
| `/decision --mode exit --ticker {TICKER}` | 全5ペルソナで Exit 議論 → FULL_EXIT/PARTIAL_EXIT/RAISE_TARGET/HOLD | portfolio.csv に open ポジションが存在すること | TARGET_HIT/STOP_BREACH 時 |
| `/monitor` | ポジション P&L + アラート判定 + ウォッチリスト監視 → Slack送信 | なし（ポジションなしでも実行可） | 毎営業日 |
| `/review` | スコア予測精度・勝率・確信度校正分析 | research_history.json に outcome データが蓄積されていること | 月1回程度 |

### Python CLIとの対応

| スキル | Python CLI |
|---|---|
| `/research` | `python skills/research.py` |
| `/watchlist-research` | `python skills/watchlist_research.py` |
| `/daily-lite` | `python skills/daily_lite.py` |
| `/decision` | `python skills/decision.py --send '[...]'` |
| `/decision --paper` | `python skills/decision.py --paper --send '[...]'` |
| `/monitor` | `python scripts/run_monitor.py` |
| ポジション操作 | `python skills/portfolio.py list\|add\|close\|snapshot` |
| B枠操作 | `python skills/paper_portfolio.py list\|add\|close\|compare` |

---

## 典型的な週次オペレーション

### 毎営業日

```
/daily-lite
  ↓ HIGH exit alert         → /decision --mode exit --ticker {TICKER}
  ↓ WATCHLIST / MARKET seed → /research --seed {TICKER}
  ↓ WATCHLIST escalation    → /decision
```

### イントラデイ監視

```
/monitor
  ↓ STAGE1_HIT / STAGE2_HIT → 自動利確処理
  ↓ STOP_BREACH             → /decision --mode exit --ticker {TICKER}
```

### 週次スキャン

```
/research
  ↓ スコア ≥ 7.0 の候補が出たら
/decision
  ↓ BUY 採用
(human が portfolio.csv に追加)
  ↓ 8週後
/review（パフォーマンス分析）
```

### ウォッチリスト集中フォロー

```
/watchlist-research
  ↓ ESCALATE 銘柄が出たら
/decision（ESCALATE 銘柄が最優先候補として自動追加）
```

### 仮説検証（B枠並走）

```
/decision の Step 10 で自動実行
  → paper_decision_prompts.py の active 仮説を検出
  → A枠のペルソナdebate(Round 1/2)を共有
  → PMルールのみ差し替えてB枠合成
  → paper_portfolio.csv に記録（Slack 送信なし）
  → 8週後: python skills/paper_portfolio.py compare で A/B 比較
```

---

## A枠/B枠（実験設計）

- **A枠（実弾）**: `data/portfolio.csv` — 現行ルール通りに実際に執行するポジション
- **B枠（仮想）**: `data/paper_portfolio.csv` — 仮説検証用の仮想ポジション（Slack送信なし、お金は動かない）
- **仮説管理**: `docs/hypothesis-tracker.md` — 何を検証しているかの定義と判定基準
- **仮説コード**: `investor/prompts/paper_decision_prompts.py` — `active: True` にするだけで /decision Step 10 で自動並走

B枠を使うケース:
- RSI>70でWAITした銘柄が「もしエントリーしたらどうなるか」を記録したい（H-2検証）
- 予算制約・セクター制限を外した場合のパフォーマンスを測りたい
- 新しいルール変更の前後比較を取りたい

---

## Data Flow

```
/research:
  1. python skills/research.py
       → yf.screen() でマーケットムーバー取得 + ウォッチリスト銘柄をマージ
       → 銘柄ごとに snapshot/technicals/financials/news
       → stdout に JSON 出力
  2. Claude がスコアリング → top candidates を選定
       → python skills/research.py --save '{"run_id":"...","candidates":[...]}'
       → data/research_history.json + data/score_snapshots.json に保存

/watchlist-research:
  1. python skills/watchlist_research.py
       → watchlist.json から active 銘柄を全件取得
       → 銘柄ごとに深研究データを収集
       → stdout に JSON 出力
  2. Claude がテーゼ継続性を評価 → ESCALATE / MAINTAIN / REMOVE / ADD_NOTE を判断
       → python skills/watchlist_research.py --save '{"run_id":"...","results":[...]}'
       → data/watchlist_research_history.json + data/watchlist.json を更新

/decision:
  1. python skills/decision.py
       → research_history.json から最新 run を読む
       → watchlist.json の ESCALATED 銘柄を priority 候補として追加
       → stdout に候補を出力
  2. Claude が5ペルソナディベート（Round 1 → Data Gap → Round 2 → PM合成）を内部実行
       → python skills/decision.py --send '[{...proposals...}]'
       → Slack (Block Kit) に送信 + reports/decision/ に保存
  3. Step 10: B枠仮説がアクティブならPM合成を再実行 → paper_portfolio.csv に記録

/monitor:
  1. python scripts/tool.py get_stock_snapshot --ticker {TICKER} (各ポジション)
     python scripts/tool.py get_technical_indicators --ticker {TICKER}
       → Claude がアラート判定 (STOP_BREACH / STAGE1_HIT / STAGE2_HIT 等)
       → 自動処理: portfolio.csv 更新（利確記録・ストップ移動）
  2. ウォッチリスト監視 → フラグ判定 → watchlist.json 更新
  3. python scripts/run_monitor.py → Slack 送信
```

---

## Pipeline State Machine（エージェント分業設計）

`watchlist.json` の各エントリは `pipeline_status` フィールドでステートマシンを構成する。
**DBが状態管理、エージェントが実行、人間が判断** の三角形を維持する。

```
watching
  ↓ /monitor: WATCHLIST_BREAKOUT / RSI_COOLED / WATCHLIST_SETUP
research_queued          ← 「/research --seed TICKER を実行せよ」
  ↓ /research --seed TICKER 完了
researched               ← 「/decision の候補として取り込め」
  ↓ /decision: WAIT判定
  ↑ researched に戻す（条件待ちの場合）
  ↓ /decision: PASS判定
watching                 ← リセット
  ↓ /decision: BUY採用 / /monitor: ESCALATE_TO_DECISION
decision_queued          ← 「次回 /decision で必ず議論せよ」
  ↓ /decision: BUY確定
promoted                 ← portfolio.csv への add_position 待ち
  ↓ add_position.py 実行
（portfolio.csv で管理、watchlist 側は promoted のまま）
  ↓ /decision --mode exit / STOP_BREACH
exited                   ← terminal state
```

### 各エージェントの pipeline_status 更新責任

| エージェント | 検出 | 変更 |
|---|---|---|
| `/monitor` | WATCHLIST_BREAKOUT / RSI_COOLED | `watching → research_queued` |
| `/monitor` | ESCALATE_TO_DECISION | `* → decision_queued` |
| `/monitor` | IN_PORTFOLIO確認 | `* → promoted` |
| `/monitor` | REMOVED / STOP_BREACH | `* → exited` |
| `/research --seed` | 完了時 | `research_queued → researched` |
| `/decision` | BUY採用 | `* → promoted` |
| `/decision` | WAIT | `* → researched`（条件待ち）|
| `/decision` | PASS | `* → watching`（リセット）|
| `/watchlist-research` | ESCALATE | `* → decision_queued` |
| `/watchlist-research` | REMOVE | `* → exited` |

### 人間の介入ポイント

`pipeline_status` を直接編集することで、どのステップにも割り込める：
- `watching → research_queued`：手動でリサーチをキューに入れる
- `researched → decision_queued`：デシジョン優先度を上げる
- `exited → watching`：一度外した銘柄を再監視に戻す

---

## Environment Variables

`.env` ファイルは `investor/` ディレクトリ直下に置く。

| Variable | Required | Purpose |
|---|---|---|
| `SLACK_WEBHOOK_URL` | **Yes** | Slack 通知 |
| `PERPLEXITY_API_KEY` | No | Web 検索強化（/research Step 4） |
| `XAI_API_KEY` | No | X/Twitter センチメント (Grok) |

---

## portfolio.csv フィールド一覧

| フィールド | 設定タイミング | 説明 |
|---|---|---|
| `ticker` | entry | 銘柄コード |
| `shares` | entry / stage更新 | 現在保有株数 |
| `entry_price` / `entry_date` | entry | 取得単価・日付 |
| `exit_price` / `exit_date` | close | 決済単価・日付 |
| `status` | — | `open` / `closed` |
| `target_price` | entry | 参考目標値（3段階出口では参照のみ） |
| `stop_loss` | entry / STAGE1更新 | 現在のストップ（STAGE1でentry_priceに移動） |
| `note` | 随時 | 経緯・アラート履歴 |
| `signal_type` | entry | `earnings_beat` / `analyst_upgrade` / `watchlist_escalate` / `sector_rotation` / `technical_breakout` |
| `exit_stage` | stage更新 | `0`=未着手 / `1`=25%利確済 / `2`=50%利確済・トレーリング中 |
| `mae_pct` | 日次（monitor Step 3d） | 最大不利到達率 |
| `mfe_pct` | 日次（monitor Step 3d） | 最大有利到達率 |
| `mfe_capture_pct` | close | 実現利益 / MFE × 100 |
| `trailing_stop_price` | STAGE2 | トレーリングストップ価格（ATR×1.0基準） |
| `high_water_mark` | STAGE2 / 日次更新 | トレーリング基準の最高値 |
| `rule_adherence_score` | close | 1=ルール違反あり / 2=軽微な逸脱 / 3=完全遵守 |

`trade_journal.json` にクローズ時の詳細記録（MAE/MFE・意思決定品質マトリクス等）を保存する。

---

## yfinance 注意点（非自明なもの）

- `yf.screen()` の戻り値は `{"quotes": [...]}` — `quotes` キーを参照する
- `Ticker.news` はネストされた `content` キーを持つ構造体
- ETF チェックは `bool(val)` を使う（`is not None` では不足）
- レート制限を避けるため、銘柄ごとの呼び出しはすべてキャッシュすること
- `Ticker.fast_info` でリアルタイム価格/出来高（遅延なし）

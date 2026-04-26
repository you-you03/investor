# investor 改善計画

作成日: 2026-04-11

---

## 背景・課題

現状のワークフローには以下の4つの欠落がある。

| # | 課題 |
|---|---|
| 1 | Monitor がウォッチリストを見ておらず、目をつけている銘柄の動きが把握できない |
| 2 | TARGET_HIT 後の出口判断プロセスが存在しない |
| 3 | 売り（Exit Decision）の意思決定がワークフローに組み込まれていない |
| 4 | ウォッチリストに何を入れるかの基準と管理フローがない |

---

## 改善後の全体フロー

```
【新規エントリー】
/research（全体スキャン）
  ↓ スコア ≥ 7.0 の候補
/decision（BUY判断）
  ├─ BUY採用 → portfolio.csv に追加、watchlist から除外
  └─ PASS/WAIT → watchlist.json に自動追加（"research_seeded" フラグ付き）

【毎日の監視】
/monitor
  ├─ Section A: ポジション監視（portfolio.csv の保有銘柄）
  │     └─ HIGH アラート検知 → Exit Decision を推奨
  └─ Section B: ウォッチリスト監視（watchlist.json）
        └─ リサーチ推奨フラグ検知 → /research --seed TICKER を推奨

【ウォッチリスト銘柄の昇格】
/research --seed TICKER（シード券リサーチ）
  ↓ 市場スキャンをスキップ、当該銘柄のみ深掘り
  ↓ 前回スコアがあれば差分チェック
/decision（通常と同じ判断フロー）

【出口判断】
/decision --mode exit --ticker TICKER
  ↓ ペルソナ討論（出口戦略）
  └─ PM判断 → 全利確 / 半分利確 / 目標引き上げ+トレーリングストップ
```

---

## 修正①: Monitor にウォッチリストセクションを追加

### 変更内容

`.claude/commands/monitor.md` を修正して、Section B を追加する。

#### Step 1（変更）

`portfolio.csv` の open ポジション（shares > 0）のみを監視対象とする。
ゼロ株エントリーはウォッチリストに移行済みとして無視する。

#### 新 Step 2b: ウォッチリスト監視

`data/watchlist.json` を読み込み、各銘柄に対して以下を取得：

```bash
.venv/bin/python scripts/tool.py get_stock_snapshot --ticker {TICKER}
.venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}
```

#### ウォッチリストのアラート条件

| 条件 | フラグ | 意味 |
|---|---|---|
| 当日変化率 ≥ +5% かつ出来高 ≥ 1.5x | `WATCHLIST_BREAKOUT` | ブレイクアウト候補 → リサーチ推奨 |
| RSI 40〜60 かつ MACD bullish crossover | `WATCHLIST_SETUP` | テクニカルセットアップ → リサーチ推奨 |
| 決算まで ≤ 14日 | `WATCHLIST_EARNINGS` | 決算接近 → リサーチ推奨 |
| 参照値比 ≥ +15% | `WATCHLIST_MOVED` | 大幅上昇（乗り遅れリスク確認） |
| 参照値比 ≤ -10% | `WATCHLIST_DROPPED` | 大幅下落（ウォッチリスト除外検討） |

#### Section B の出力フォーマット

```markdown
## ウォッチリスト監視

| Ticker | 参照値 | 現在値 | 本日 | 参照比 | フラグ |
|--------|-------|-------|-----|--------|-------|
| ALAB   | $117  | $149  | +12.9% | +27.2% | 🔬 WATCHLIST_BREAKOUT |
| CRDO   | $72   | $119  | +10.9% | +65.3% | 🔬 WATCHLIST_BREAKOUT |

### リサーチ推奨
- **ALAB**: WATCHLIST_BREAKOUT（+12.9% / 出来高2.1x）
  → `/research --seed ALAB` で優先リサーチを実行
- **CRDO**: WATCHLIST_BREAKOUT（+10.9% / 出来高1.8x）
  → `/research --seed CRDO` で優先リサーチを実行
```

---

## 修正②: ウォッチリスト管理フロー（何を入れるか）

### 追加ルール

| ソース | 条件 | アクション |
|---|---|---|
| `/decision` 実行後 | スコア ≥ 7.0 かつ PASS or WAIT になった銘柄 | `watchlist.json` に自動追加（`source: "research_seeded"`） |
| `/decision` 実行後 | BUY 採用された銘柄 | `portfolio.csv` へ移行、`watchlist.json` から削除 |
| 手動 | ユーザーが気になる銘柄 | `source: "manual"` で追加（現状のまま） |
| `/monitor` 実行後 | `WATCHLIST_DROPPED` が2回連続した銘柄 | ウォッチリスト除外を推奨 |

### watchlist.json のスキーマ変更（追加フィールド）

```json
{
  "ticker": "ALAB",
  "added_at": "2026-04-11",
  "source": "research_seeded",
  "last_research_run_id": "c9ac08aa-...",
  "last_score": 8.1,
  "reference_price": 149.05,
  "reason": "スコア8.1でPASS。ブレイクアウト待ち。"
}
```

`last_research_run_id` と `last_score` を持つことで、シード券リサーチ時に前回との差分チェックができる。

---

## 修正③: `/research --seed TICKER` シード券リサーチ

### 概要

市場全体スキャン（Step 1〜3）をスキップして、指定銘柄だけを深掘りする高速リサーチモード。Monitor でリサーチ推奨フラグが立ったときに使う。

### 通常リサーチとの違い

| 項目 | 通常 `/research` | `/research --seed TICKER` |
|---|---|---|
| 対象銘柄 | 市場スキャンから選出 | 指定銘柄のみ |
| マクロ判定 | 毎回実行 | 実行（スキップしない） |
| Step 1〜3 | 実行 | スキップ |
| Step 4〜（深掘り） | 実行 | 実行 |
| 前回スコア参照 | なし | あり（差分表示） |
| 出力先 | `research_history.json` に追記 | 同じ（run単位で保存） |

### 差分チェックの出力例

```
前回リサーチ (2026-04-05, run: c9ac08aa):
  スコア: 7.6 / エントリーゾーン: $120–124 / 目標: $143

今回 (2026-04-11):
  スコア: 8.1 (+0.5) / 現在値: $149（エントリーゾーン上限を+20%超過）
  変化点: RSI 66→66.2（横ばい）/ MACD bullish 継続 / Revenue +91.8% YoY（確認済み）
  → 目標値を ATR 3.0× で再計算: $176.81
```

そのまま `/decision` に流せる状態でレポートを出力する。

---

## 修正④: `/decision --mode exit` 出口判断

### 概要

保有銘柄に対して「今売るか・ホールドするか・部分利確するか」をペルソナ討論で判断する。

### 起動タイミング

- Monitor で `TARGET_HIT` または `UP_30PCT`（新設）アラートが発生したとき
- ユーザーが任意に実行したいとき

### 討論フォーマット

通常 `/decision` と同じ3ラウンド構成だが、議題が「出口戦略」になる。

**各ペルソナの出口視点:**

| ペルソナ | 出口判断の軸 |
|---|---|
| The Oracle | 現在値が内在価値を大幅に上回っていないか。FCF比で割高なら利確 |
| The Innovator | 5年テーゼが変わっていなければホールド。カタリストが残っているか |
| The Tape Reader | RSI・出来高でトレンド継続か判断。出来高が落ちてきたら撤退 |
| The Tenbagger | ストーリーが変わっていないか。PEG が過熱域に入ったか |
| The Macro Mind | マクロ環境が引き続き追い風か。リスクオフなら縮小推奨 |

**PM最終判断の選択肢:**

| 判断 | 条件の目安 |
|---|---|
| 全利確 | 多数ペルソナが SELL / RSI 過熱 / マクロ逆風 |
| 半分利確 + 残りホールド | 意見が割れる / トレンド継続だがリスク高め |
| 目標引き上げ + トレーリングストップ | 多数ペルソナが HOLD / カタリスト残存 |
| ホールド（変更なし） | 全ペルソナ HOLD / テーゼ変わらず |

**出力 JSON（例）:**

```json
{
  "ticker": "AAOI",
  "mode": "exit",
  "action": "PARTIAL_EXIT",
  "conviction": "MEDIUM",
  "exit_shares": 10,
  "remaining_shares": 9,
  "new_target_price": 165.00,
  "new_trailing_stop_pct": 8,
  "rationale": "RSI 71.73で過熱域だが MACDはbullish継続。目標を$165に引き上げトレーリングストップ8%を設定し、残り9株でアップサイドを追う。",
  "debate_summary": { ... }
}
```

---

## 改善後のワークフロー全体図（更新版）

```
/research（全体スキャン）
  ↓ 候補選別（スコア ≥ 7.0）
  → reports/research/research_YYYY-MM-DD.md

/decision（BUY判断）
  ├─ BUY → portfolio.csv 追加
  └─ PASS/WAIT → watchlist.json に自動追加（research_seeded）
  → reports/decision/decision_YYYY-MM-DD.md
  → Slack 送信

/monitor（毎日）
  ├─ Section A: ポジション監視
  │    └─ TARGET_HIT / UP_30PCT → "Exit Decision を推奨" 表示
  └─ Section B: ウォッチリスト監視
       └─ WATCHLIST_BREAKOUT 等 → "/research --seed TICKER を推奨" 表示
  → reports/monitor/monitor_YYYY-MM-DD.md
  → Slack 送信

/research --seed TICKER（シード券リサーチ）
  ↓ 前回スコア差分チェック + 深掘り
  → research_history.json に追記

/decision（BUY 判断 / 通常と同じ）

/decision --mode exit --ticker TICKER（出口判断）
  ↓ ペルソナ討論（出口戦略）
  → 全利確 / 半分利確 / 目標引き上げ / ホールド
  → reports/decision/exit_YYYY-MM-DD.md
  → Slack 送信

/review（週次・任意）
  → スコア精度分析 + キャリブレーション提案
```

---

## 実装優先順位

| 優先度 | 対象 | 変更ファイル |
|---|---|---|
| 1 | Monitor にウォッチリストセクション追加 | `.claude/commands/monitor.md` |
| 2 | watchlist.json スキーマ拡張（source / last_score 等） | `data/watchlist.json` + `scripts/` |
| 3 | `/decision` の PASS/WAIT 銘柄をウォッチリストへ自動追加 | `.claude/commands/decision.md` |
| 4 | `/research --seed` シード券モード | `.claude/commands/research.md` |
| 5 | `/decision --mode exit` 出口判断 | `.claude/commands/decision.md` |
| 6 | portfolio.csv のゼロ株エントリー整理 | `data/portfolio.csv` + monitor.md |

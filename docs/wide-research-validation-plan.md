# 広範囲リサーチ + スコア検証システム 実装計画

作成日: 2026-04-19  
更新日: 2026-04-19

---

## 概要・目的

| 目的 | 内容 |
|---|---|
| **実際の投資パフォーマンス向上** | 広範囲スキャンで毎回15〜20銘柄を深掘りし、取りこぼしを減らす |
| **スコア精度の長期検証** | 週次でリターンを取得し、スコアと各週リターンの順位相関（Spearman ρ）を継続計測する |

---

## 現状の課題

| 問題 | 詳細 |
|---|---|
| スキャン対象が少ない | `/research` は5〜8銘柄のみを深研究 → 有望株を見逃す可能性 |
| スコア下位銘柄を捨てている | スコア < 7.0 の銘柄はデータが残らず、相関検証に使えない |
| リターンを追跡していない | `research_history.json` は提案時点で止まり、結果を自動追跡しない |
| 相関分析がない | `/review` はスコアバケット別の勝率分析止まり（全銘柄の順位相関は未計算） |

---

## 設計方針

### データフローの変更（Before / After）

**Before**
```
market movers (20件) → 候補5-8件を選別 → 深研究 → スコア ≥7.0 → research_history.json
                                                          スコア <7.0 → 廃棄
```

**After**
```
market movers (30件) → 候補15-20件を選別 → 深研究 → スコア ALL → score_snapshots.json
                                                          スコア ≥7.0 → research_history.json（従来通り）
                                                          ↓（週1回 fetch_returns.py）
                                                          1w後に price_1w を記録
                                                          2w後に price_2w を記録
                                                          3w後に price_3w を記録
                                                          4w後に price_4w を記録
                                                          ↓
                                                          各週の Spearman ρ → /review で表示
```

### 新ファイル

| ファイル | 用途 |
|---|---|
| `data/score_snapshots.json` | 全スコア付き銘柄の記録（週次リターン含む） |
| `scripts/fetch_returns.py` | **週1回**実行 → 経過週数に応じたリターンを埋める |
| `scripts/validate_scores.py` | 週ごとの Spearman ρ・IC を計算してレポート生成 |
| `reports/validation/` | 検証レポートの出力先 |

---

## Phase 1: score_snapshots スキーマ設計

**ファイル**: `data/score_snapshots.json`

```json
{
  "snapshots": [
    {
      "run_id": "uuid4",
      "scored_at": "2026-04-19",
      "ticker": "NVDA",
      "company_name": "NVIDIA Corporation",
      "score": 8.2,
      "score_breakdown": {
        "momentum": 9,
        "fundamentals": 8,
        "catalyst": 9,
        "technical": 7,
        "sentiment": 8
      },
      "rank_in_run": 1,
      "total_scored_in_run": 18,
      "price_at_score": 880.00,
      "passed_threshold": true,
      "macro_regime": "NORMAL",

      "week1": {
        "target_date": "2026-04-26",
        "price": null,
        "return_pct": null,
        "spy_return_pct": null,
        "alpha_pct": null,
        "fetched_at": null
      },
      "week2": {
        "target_date": "2026-05-03",
        "price": null,
        "return_pct": null,
        "spy_return_pct": null,
        "alpha_pct": null,
        "fetched_at": null
      },
      "week3": {
        "target_date": "2026-05-10",
        "price": null,
        "return_pct": null,
        "spy_return_pct": null,
        "alpha_pct": null,
        "fetched_at": null
      },
      "week4": {
        "target_date": "2026-05-17",
        "price": null,
        "return_pct": null,
        "spy_return_pct": null,
        "alpha_pct": null,
        "fetched_at": null
      }
    }
  ]
}
```

**フィールド説明**

| フィールド | 説明 |
|---|---|
| `rank_in_run` | このrunでのスコア順位（1=最高） |
| `total_scored_in_run` | このrunで評価した銘柄総数 |
| `passed_threshold` | `score >= 7.0` かどうか（decision agentに渡したかどうか） |
| `week{N}.target_date` | `scored_at + 7N日`（例: week1=+7日, week4=+28日） |
| `week{N}.price` | `target_date` 時点の終値（週次 fetch_returns.py が埋める） |
| `week{N}.return_pct` | `(price - price_at_score) / price_at_score * 100`（累積リターン） |
| `week{N}.spy_return_pct` | 同期間のSPY累積リターン |
| `week{N}.alpha_pct` | `return_pct - spy_return_pct` |

**週次リターンの考え方（累積 vs 差分）**

```
week1.return_pct  = スコア日から1週間の累積リターン
week2.return_pct  = スコア日から2週間の累積リターン（week1からの差分ではなく累積）
week3.return_pct  = スコア日から3週間の累積リターン
week4.return_pct  = スコア日から4週間の累積リターン（最終ホライゾン）
```

検証時には各週の累積リターンをスコアと比較することで、
「スコアが1週後のリターンより4週後のリターンをより強く予測している」等の時間軸分析が可能。

---

## Phase 2: 広範囲リサーチ（`/research` コマンド更新）

### 変更点

**Step 3（候補選別）の拡張**

現在: 5〜8銘柄を選別  
変更後: **15〜20銘柄**を選別

インプット拡張:
- gainers 20件 + actives 20件 → 現在と同じ
- 52w breakouts（`get_52w_breakouts`）
- earnings surprises（`get_earnings_surprises`）
- ウォッチリスト（優先スロット 最大10件）

除外基準（変更なし）:
- ETF・インバース・日次出来高 < $1M は除外
- 上限: 20銘柄

**Step 4（深研究）の拡張**

- 全15〜20銘柄に対して9ツール実行（現在は5〜8銘柄のみ）
- `scripts/tool.py` の並列実行で所要時間を抑える

**Step 5（スコアリング）の変更**

- スコアは引き続き1〜10で計算
- **スコアに関わらず全銘柄をスコアリングする**
- `score < 7.0` の銘柄はレポートに「除外銘柄」として記載（現状と同じ）

**Step 6a（従来: research_history.json 保存）— 変更なし**

- `score >= 7.0` の候補のみ `research_history.json` に保存（decision agent 用）

**Step 6b（新規: score_snapshots.json 保存）**

全スコア付き銘柄を `data/score_snapshots.json` に追記する。

```bash
cat data/score_snapshots.json  # 既存データ読み込み（なければ {"snapshots": []} から開始）
```

各銘柄について以下を計算して追加:
- `target_date` = `scored_at` + 28日（例: 2026-04-19 → 2026-05-17）
- `rank_in_run` = スコア降順での順位
- `total_scored_in_run` = このrunの全銘柄数
- `passed_threshold` = `score >= 7.0`

各銘柄の週次チェックポイントを計算して設定:
- `week1.target_date` = `scored_at + 7日`
- `week2.target_date` = `scored_at + 14日`
- `week3.target_date` = `scored_at + 21日`
- `week4.target_date` = `scored_at + 28日`
- 全 week の `price`, `return_pct`, `spy_return_pct`, `alpha_pct`, `fetched_at` は `null` で初期化

書き込み後に確認メッセージを表示:
```
Score snapshot saved:
  run_id: {run_id}
  scored: {N}銘柄 ({passed}件がスコア閾値通過)
  weekly checkpoints: week1={week1_date}, week2={week2_date}, week3={week3_date}, week4={week4_date}
  → 毎週月曜の fetch_returns.py が各マイルストーンを順次埋めます
```

### research.md レポート（Step 7）の変更

既存の表に「除外銘柄」セクションを追加:

```markdown
## スキャン結果サマリー

| 指標 | 値 |
|---|---|
| スキャン銘柄数 | 18 銘柄 |
| 候補（スコア ≥ 7.0） | 5 銘柄 |
| 除外（スコア < 7.0） | 13 銘柄（score_snapshots.json に記録済み） |
| マクロレジーム | NORMAL |

## 除外銘柄（スコア < 7.0）
| Ticker | スコア | 主な除外理由 |
|--------|-------|------------|
| TSLA   | 6.5   | Catalyst 不足 |
| COIN   | 5.8   | マクロ逆風 |
```

---

## Phase 3: リターン追跡スクリプト

**ファイル**: `scripts/fetch_returns.py`

### 動作

1. `data/score_snapshots.json` を読み込む
2. 各エントリーの `week1`〜`week4` のうち `target_date <= today` かつ `fetched_at is None` のものをリストアップ
3. 対象ティッカー × 日付の組み合わせで yfinance から終値を取得
4. SPY の同期間リターン（`scored_at` → `target_date`）を計算
5. `price`, `return_pct`, `spy_return_pct`, `alpha_pct`, `fetched_at` を更新
6. ファイルを書き戻す

### 週次マイルストーンの判定ロジック

```python
for snapshot in snapshots:
    for week_key in ["week1", "week2", "week3", "week4"]:
        wk = snapshot[week_key]
        if wk["fetched_at"] is None and wk["target_date"] <= today:
            # このマイルストーンの価格を取得する
            fetch_price(snapshot["ticker"], wk["target_date"])
            compute_cumulative_return(snapshot["price_at_score"], fetched_price)
            fetch_spy_return(snapshot["scored_at"], wk["target_date"])
```

### 実行方法

```bash
# 手動実行（経過済みの全マイルストーンを一括更新）
.venv/bin/python scripts/fetch_returns.py

# 出力例（初回 fetch: スコアから1週後のマイルストーン）
Checking score_snapshots for matured milestones...
  NVDA  week1 (2026-04-26) → $901.20 | +2.4% | SPY: +1.1% | alpha: +1.3%  ✅
  AAOI  week1 (2026-04-26) → $111.00 | +6.8% | SPY: +1.1% | alpha: +5.7%  ✅
  TSLA  week1 (2026-04-26) → $214.40 | +1.9% | SPY: +1.1% | alpha: +0.8%  ✅
  NVDA  week2 (2026-05-03) → target_date is in the future, skip
  ...
Updated 3 milestone(s) across 3 snapshot(s) in data/score_snapshots.json
```

### cron 設定（毎週月曜 8:00）

```
0 8 * * 1 cd "/Users/yutaobayashi/PERSONAL DEV/investor" && .venv/bin/python scripts/fetch_returns.py >> logs/cron.log 2>&1
```

毎週月曜に実行することで、経過した週のマイルストーンが順次埋まっていく。
`/research` を週2回実行している場合、毎週月曜の実行で前週分の week1/week2/... が埋まる。

---

## Phase 4: 相関検証レポート

**ファイル**: `scripts/validate_scores.py`

### 計算内容

| 指標 | 説明 |
|---|---|
| **週次 Spearman ρ（IC）** | 各週（1w/2w/3w/4w）でスコア順位 vs 累積リターン順位の相関。週によってρがどう変化するかを追う |
| **p値** | 統計的有意性（p < 0.05 で有意） |
| **スコアバケット別 × 週別の平均リターン** | スコア帯ごとに、時間が経つほどリターンが広がっていくかを確認 |
| **ファクター別週次相関** | どのファクターが何週目のリターンと最も相関するか |
| **passed_threshold 銘柄 vs 除外銘柄の比較** | スコア閾値の妥当性検証 |

対象データは「`week{N}.fetched_at` が埋まっているエントリー」のみ。
データ量が不足している週は「データ不足（N < 30）」と表示してスキップ。

### 実行方法

```bash
# 全期間を対象に検証レポート生成
.venv/bin/python scripts/validate_scores.py

# 出力先: reports/validation/validation_{date}.md
```

### 出力レポート例

```markdown
# スコア検証レポート — 2026-07-19

## データサマリー

| 項目 | 値 |
|---|---|
| 検証期間 | 2026-04-19 〜 2026-07-12 |
| スナップショット総数 | 312 件 |
| week1 リターン取得済み | 294 件 |
| week2 リターン取得済み | 276 件 |
| week3 リターン取得済み | 258 件 |
| week4 リターン取得済み | 240 件 |

---

## 週次 IC（Spearman ρ）— スコア vs 累積リターン

| ホライゾン | サンプル数 | Spearman ρ | p値 | 判定 |
|---|---|---|---|---|
| 1週後 | 294 | +0.18 | 0.042 | ⚠️ 弱い正の相関 |
| 2週後 | 276 | +0.26 | 0.008 | ✅ 正の相関あり |
| 3週後 | 258 | +0.31 | 0.001 | ✅ 正の相関あり |
| 4週後 | 240 | +0.34 | 0.0003 | ✅ 正の相関あり（最強） |

→ スコアの予測力は時間とともに強まる。短期（1週）より中期（4週）で効く。

---

## スコアバケット別 × 週別 平均リターン

| スコアバケット | 件数 | 1w avg | 2w avg | 3w avg | 4w avg |
|---|---|---|---|---|---|
| ≥ 8.5（exceptional） | 18 | +1.8% | +3.1% | +4.9% | +6.3% |
| 8.0–8.4（high）      | 42 | +1.2% | +2.3% | +3.2% | +4.1% |
| 7.5–7.9（medium-high）| 67 | +0.7% | +1.4% | +2.0% | +2.4% |
| 7.0–7.4（medium）    | 54 | +0.3% | +0.7% | +0.9% | +1.2% |
| < 7.0（below threshold）| 64 | -0.1% | -0.2% | -0.3% | -0.4% |

→ 高スコア帯ほど、時間とともにリターンが積み上がっている。

---

## ファクター別 Spearman ρ（4週後リターンとの相関）

| ファクター | 1w ρ | 2w ρ | 3w ρ | 4w ρ | 傾向 |
|---|---|---|---|---|---|
| Catalyst    | +0.22 | +0.31 | +0.38 | +0.41 | 時間で強化 → 中期向き |
| Fundamentals| +0.19 | +0.27 | +0.33 | +0.36 | 時間で強化 |
| Momentum    | +0.21 | +0.24 | +0.26 | +0.29 | 安定して予測的 |
| Technical   | +0.14 | +0.15 | +0.16 | +0.18 | 弱い |
| Sentiment   | +0.08 | +0.09 | +0.10 | +0.12 | 非常に弱い |

---

## キャリブレーション提案

- Catalyst ウェイトを 25% → 30% に引き上げ（4週後ρ=0.41で最強）
- Sentiment ウェイトを 15% → 10% に引き下げ（ρ=0.12で最弱）
- スコア閾値は 7.0 を維持（<7.0 群の平均リターンが全週でマイナス）
- 1週後のICが弱い（ρ=0.18）ため、超短期トレード目的には本スコアは不向き
```

---

## Phase 5: `/review` コマンド拡張

既存の `review.md` に **Step 6: Spearman 相関検証** を追加する。

```markdown
## Step 6: Spearman 相関検証（score_snapshots から）

```bash
.venv/bin/python scripts/validate_scores.py
```

出力を読み込み、以下を Step 5（キャリブレーション提案）に組み込む:
- IC（Spearman ρ）が 0.2 未満の場合: 「スコアの予測力が低い」と注記
- IC が 0.4 以上の場合: 「スコアは良好な予測力を持っている」と評価
- ファクター別ρの弱いファクター → ウェイト引き下げを提案
```

---

## 実装優先順位

| 優先度 | フェーズ | 変更ファイル | 工数目安 |
|---|---|---|---|
| **1** | Phase 1: スキーマ設計 | `data/score_snapshots.json` 初期化 | 5分 |
| **2** | Phase 2: research.md 更新（Step 3拡張 + Step 6b追加） | `.claude/commands/research.md` | 30分 |
| **3** | Phase 3: fetch_returns.py | `scripts/fetch_returns.py` | 2時間 |
| **4** | Phase 4: validate_scores.py | `scripts/validate_scores.py` | 3時間 |
| **5** | Phase 5: review.md 更新 | `.claude/commands/review.md` | 15分 |

---

## 実装メモ・注意事項

### データ量と統計的有意性

| データ量 | 信頼性 |
|---|---|
| < 30件 | 統計的に不十分（参考値として扱う） |
| 30〜100件 | 傾向は見えるが p値に注意 |
| > 100件 | 信頼できる相関分析が可能 |

週2回程度 `/research` を実行（各18銘柄スコア）した場合:
- **1週後には初の week1 データが揃い始める** → 早期フィードバックが得られる
- 1ヶ月で約144件のスナップショット、うち week1 は全件揃う
- 4週リターンが揃うのは1ヶ月後
- → **最初の意味ある検証は約1ヶ月後（2026-05月中旬〜）**、week4 の分析は2ヶ月後

### `research_history.json` は変更しない

- decision agent のインプットとして引き続き `score >= 7.0` 銘柄のみを保存
- `score_snapshots.json` は相関検証専用の別ファイル
- 2ファイルで役割分担する

### yfinance の過去日付取得

`Ticker.history(start=target_date, end=target_date+1日)` で `target_date` の終値を取得できる。
週末・祝日の場合は直前の営業日の終値を yfinance が自動選択する。

---

## 将来の拡張（対象外、参考）

- **セクター別IC**: テクノロジー・ヘルスケアなどセクターごとに予測力を評価
- **マクロレジーム別IC**: NORMAL / DOWNTREND / HIGH_FEAR 別の予測力を分析
- **ダッシュボード組み込み**: `dashboard.html` に IC トレンドチャートを追加

# investor データ契約棚卸し

作成日: 2026-05-30  
対象: `data/portfolio.csv` / `data/paper_portfolio.csv` / `data/decision_history.json` / `data/research_history.json` / `data/trade_journal.json`

---

## 1. 結論

- `decision_history.json` は提案ログ
- `portfolio.csv` は実約定ログ
- `paper_portfolio.csv` は B枠の仮説検証ログ
- `trade_journal.json` はクローズ後の事後評価ログ

同じ概念を別名で持たないため、列名の正を次で固定する。

---

## 2. 採用する共通ポートフォリオ列

`portfolio.csv` と `paper_portfolio.csv` の共通採用列:

| 列名 | 用途 | 状態 |
|---|---|---|
| `position_id` | 行の一意キー | 採用 |
| `ticker` | 銘柄 | 採用 |
| `shares` | 株数 | 採用 |
| `entry_price` | 約定/仮想約定価格 | 採用 |
| `entry_date` | 実際に建てた日 | 採用 |
| `proposal_date` | AIが提案した日 | 採用 |
| `exit_price` | クローズ価格 | 採用 |
| `exit_date` | クローズ日 | 採用 |
| `status` | `open` / `closed` | 採用 |
| `target_price` | 利確目標 | 採用 |
| `stop_loss` | 損切り価格 | 採用 |
| `note` | 人間メモ / 仮説メモ | 採用 |
| `signal_type` | 入口ルール分類 | 採用 |
| `conviction` | HIGH / MEDIUM / LOW | 採用 |
| `hypothesis_id` | B枠仮説ID | 採用 |
| `exit_stage` | 段階利確用 | 採用 |
| `mae_pct` | 最大不利到達率 | 採用 |
| `mfe_pct` | 最大有利到達率 | 採用 |
| `mfe_capture_pct` | 実現利益 / MFE | 将来予約 |
| `rule_adherence_score` | ルール遵守度 | 将来予約 |

補足:

- `mfe_capture_pct` と `rule_adherence_score` は現状 `trade_journal.json` が正本
- ただし将来は portfolio 系CSVにも保持できるよう列は予約しておく

---

## 3. 指標名の正

| 概念 | 正式名 | 保存先 |
|---|---|---|
| 最大不利到達率 | `mae_pct` | portfolio / paper / trade journal |
| 最大有利到達率 | `mfe_pct` | portfolio / paper / trade journal |
| MFE捕捉率 | `mfe_capture_pct` | trade journal |
| ルール遵守度 | `rule_adherence_score` | trade journal |
| ベンチマーク超過 | `alpha_pct` | research_history.outcome |

ルール:

- `mfe_pct` を `mfe_capture_pct` の代用として読まない
- `mfe_capture_pct` が必要な処理は `trade_journal.json` を読む
- `alpha_pct` は outcome の正式名として固定する

---

## 4. 実ファイルの役割

| ファイル | 何を保存するか |
|---|---|
| `data/decision_history.json` | BUY / PASS / HOLD_CASH の提案履歴、提案数サマリー、PASS候補メタデータ |
| `data/portfolio.csv` | 人間が実際に執行したA枠ポジション |
| `data/paper_portfolio.csv` | B枠で記録する仮説検証ポジション |
| `data/research_history.json` | リサーチ候補と outcome、`alpha_pct` を含む判断前後データ |
| `data/trade_journal.json` | クローズ後の事後評価と MFE capture / rule adherence |

---

## 5. 廃止・注意

廃止:

- `BUY実行` という週次レビュー表記

注意:

- closed row で `exit_price` / `exit_date` が欠けた行は不正データとして warning を出す
- `entry_price_range` は hyphen / en dash / em dash を同一ロジックで解釈する
- A枠とB枠は「Slack送信あり/なし」の違いではなく、「実約定/仮説検証」の違いとして扱う

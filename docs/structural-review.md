# システム構造レビュー

作成: 2026-04-29  
対象: improvement-plan.md（2026-04-11）では扱われていない構造レベルの問題

---

## 問題① 確信度ラベルが統計的に無意味

### 現状

`/decision` が出力する HIGH / MEDIUM / LOW 確信度は、Claude がその場でつける定性ラベルであり、過去の判断と照合されたことが一度もない。「HIGH確信」が実際に高リターンに対応するかどうか未検証のまま、ポジションサイジングの根拠として使われている。

`record_outcomes.py` と `fetch_returns.py` は存在するが `/decision` フローから切り離されており、結果が次の判断に影響しない。

### 改善案

**`/decision` 実行冒頭に確信度校正レポートを自動表示する。**

```bash
# decision_agent.py の format_research_for_claude() に追加
python scripts/record_outcomes.py          # クローズドポジションのリターンを更新
python scripts/fetch_returns.py            # week1〜week4 マイルストーンを更新
python scripts/show_calibration_stats.py   # 確信度別の勝率・平均リターンを出力
```

`show_calibration_stats.py` の出力イメージ:

```
=== 確信度校正レポート (n=7) ===
HIGH   (n=3): 勝率 100%  平均リターン +43.7%  中央値 +42.8%
MEDIUM (n=3): 勝率 100%  平均リターン +45.9%  中央値 +34.4%
LOW    (n=1): 勝率 -     平均リターン (open)   中央値 -

⚠ サンプル数が少なすぎて統計的意味なし（n < 20）
⚠ 全ポジションが強気相場（2026-04）に集中。ベンチマーク比較を参照。
```

Claudeはこのレポートを見た上で確信度を判断する。サンプルが少ない間は「確信度ラベルは参考値」と明示的に扱う。

### ベンチマーク比較の追加

各クローズポジションの保有期間中の SPY リターンを `fetch_returns.py` で取得し、超過リターン（Alpha）を記録する。

```python
# portfolio.csv に alpha_vs_spy カラムを追加
alpha_vs_spy = position_return - spy_return_same_period
```

「+44.9% のリターン」が SPY の同期間 +30% に対して +14.9% のアルファなのか、SPY +5% に対して +39.9% のアルファなのかで、システムの評価は全く変わる。

---

## 問題② ストップロスは価格監視ではなく翌朝の事後確認

### 現状

monitor cron は `0 7 * * 1-5`（JST 7時 = 前日の米国市場クローズ後）。イントラデイのギャップダウンや急落は、発生から最大24時間後にしか検知されない。`stop_loss` として記録された価格は「損切りライン」ではなく「翌朝確認される参照値」にすぎない。

### 改善案

**短期対応: cron を米国市場時間中に複数回実行する。**

```cron
# 米国市場時間（JST 22:30〜翌06:00）に30分ごと実行
*/30 22-23 * * 1-5 cd "/Users/.../investor" && .venv/bin/python scripts/run_monitor.py >> logs/cron.log 2>&1
*/30 0-5   * * 2-6 cd "/Users/.../investor" && .venv/bin/python scripts/run_monitor.py >> logs/cron.log 2>&1
```

**Slack アラートへの注意書き追加:**

HIGH アラートの Block Kit メッセージに以下を追加する（`notifications/slack.py` を修正）。

```
⚠️ このアラートは市場クローズ後の確認です。
   イントラデイに大きく動いた場合、現在値はストップ価格と乖離している可能性があります。
   証券口座で現在の約定可能価格を確認してください。
```

**中期対応: SIGNIFICANT_DRAWDOWN の閾値を引き上げる。**

現状: unrealized_pnl < -8% で MEDIUM アラート  
変更: < -5% で HIGH アラート（ストップロスに到達する前に早期警告）

---

## 問題③ システムは「BUYしない」という判断を出せない

### 現状

`/research` を実行すれば必ず候補が出る。`/decision` を実行すれば必ずディベートになる。「今週はポジションを取らない」という出力パスが設計に存在しない。マクロ環境が悪化しても、スクリーニングが何らかの銘柄を通過する限り BUY の検討が始まる。

### 改善案

**Phase 1 にマクロゲートを追加する（`research_agent.py`）。**

`get_market_context()` の出力に基づき、HIGH_FEAR レジームで処理を止める。

```python
# research_agent.py の collect_market_data() に追加
if regime == "HIGH_FEAR":
    return {
        "gate": "BLOCKED",
        "reason": f"VIX={vix:.1f} / regime=HIGH_FEAR",
        "recommendation": "新規ポジション非推奨。既存ポジションのモニタリングに集中。"
    }
```

stdout にこの JSON が出た場合、Claude は `/decision` を実行せずにセッションを終了する。

**`/decision` の PM 判断に全銘柄 PASS を追加する。**

```json
{
  "no_trade_week": true,
  "reason": "候補銘柄はすべて過去2週間で30%以上上昇済み。新規エントリーのリスクリワードが成立しない。",
  "action": "HOLD_CASH"
}
```

この出力を `decision_agent.py` が受け取った場合、Slack に「今週はエントリーなし」の通知を送る。

---

## 問題④ ウォッチリストが運用実態と乖離している

### 現状

`watchlist.json` が空（0件）。リサーチ実行の9ランすべてが `/research` → `/decision` の直行で、ウォッチリストを経由したポジションは一件もない。アーキテクチャの中心的な機能が実運用で使われていない。

### 判断

ウォッチリストが使われない理由は「セットアップが良ければその日のうちに入る」というトレードスタイルと、「ウォッチリストに入れてから再度リサーチという2ステップが重い」という UX の問題が組み合わさっている可能性が高い。

**選択肢 A: ウォッチリストを廃止し、research_history を「自動ウォッチリスト」として使う。**

`/decision` で PASS になった銘柄は `research_history.json` の `status: "pending"` として残す。次回 `/research` 実行時に pending 銘柄を自動的に先頭に含める。専用の watchlist.json を維持する必要がなくなる。

**選択肢 B: ウォッチリスト追加を `/decision` の PASS 出力に自動連動させる（improvement-plan.md 案）。**

どちらにせよ、現状の「手動で `/watchlist add` して管理する」フローは機能していないと認め、廃止または自動化の方針を決める必要がある。

---

## 問題⑤ システムが機能しているかどうかを判定できない

### 現状

現在のクローズドポジション（AAOI +44.9%、ALAB +42.8%、CRDO +63.1%）は高リターンに見えるが、2026年4月は相場の急回復局面と重なっている。「システムが機能している」と「強い相場で何を持ってても上がった」を区別する方法がない。

### 改善案

**週次で自動生成する `reports/review/` レポートを追加する。**

```bash
# cron: 毎週月曜 JST 8時（米国市場クローズ後の週次集計）
0 8 * * 1 cd "/Users/.../investor" && .venv/bin/python scripts/weekly_review.py >> logs/cron.log 2>&1
```

`weekly_review.py` が出力する内容:

```markdown
## 週次パフォーマンスレビュー (2026-04-21 〜 2026-04-27)

### ポジション損益
| Ticker | 確信度 | 期間リターン | SPY同期間 | Alpha |
|--------|--------|------------|----------|-------|
| ALAB   | HIGH   | +42.8%     | +8.2%    | +34.6% |
| CRDO   | MEDIUM | +63.1%     | +8.2%    | +54.9% |

### 累積確信度校正 (n=7)
HIGH の平均 Alpha: +34.6%
MEDIUM の平均 Alpha: +54.9%  ← HIGH より高い（逆転）
LOW の平均 Alpha: (open)

### 判断数サマリー
BUY実行: 7件 / PASS: 不明（記録なし）
```

PASS 件数が記録されていないことが問題なので、`decision_agent.py` に PASS 判断のログを追加する。

```python
# decision_history.json（新規）
{
  "date": "2026-04-25",
  "candidates_evaluated": ["NVDA", "PANW", "TSM", "UAL", "CRWV"],
  "buy_decisions": ["NVDA", "PANW", "TSM", "UAL", "CRWV"],
  "pass_decisions": [],
  "no_trade_week": false
}
```

---

## 優先順位

| 優先度 | 改善 | 工数 |
|---|---|---|
| 1 | cron を市場時間中に頻度増加（ストップロス実時間化） | 30分 |
| 2 | `show_calibration_stats.py` 作成 + `/decision` 冒頭に組み込み | 2時間 |
| 3 | `decision_history.json` に PASS 記録を追加 | 1時間 |
| 4 | マクロゲート（HIGH_FEAR で /research をブロック） | 2時間 |
| 5 | `weekly_review.py` + SPY ベンチマーク比較 | 3時間 |
| 6 | ウォッチリストの廃止/自動化方針を決定 | 議論のみ |

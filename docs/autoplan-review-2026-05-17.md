# investor プロジェクト 総合レビュー（/autoplan）

作成日: 2026-05-17  
レビュー者: Claude Code / garrytan-autoplan  
対象: investor/ ディレクトリ全体（戦略・実装・運用・DX）  
モデル構成: Claude subagent × 3（CEO / Eng / DX）、Codex 未使用（CLI なし）  
前提ゲート: すべて受け入れ → フルレビュー続行  

---

## エグゼクティブサマリー

システムは実弾で動いており、10トレードで勝率70%・平均リターン+21% という実績を出した。ただし **3つの根本的な問題** が並行して存在する：

1. **テストスイートが存在しない実装を検証している**（CRITICAL）— 現在動いているコードパス（skills/*.py）のテストはゼロ。test_agents.py は廃止された SDK ベースの旧アーキテクチャのみをカバーしている。
2. **Slack 送信失敗がサイレントサクセスになる**（CRITICAL）— 人間の承認ループの要であるSlack 通知が `slack.py:35` で全例外を飲み込み、`decision.py:142` は戻り値を無視して成功を報告する。04-25/26 の停止で実証済み。
3. **評価基盤がない**（HIGH）— SPY アルファ未計算、`rule_adherence_score`/`mfe_capture_pct` が空欄のまま、B 枠（paper portfolio）未起動。「勝っているかどうか」を正確に測る手段がない。

---

## Phase 1: CEO レビュー（戦略・前提・スコープ）

### Step 0A: 前提の検証（CEO Subagent による独立評価）

| # | 前提 | CEO Subagent 評価 | 根拠 |
|---|------|-----------------|------|
| P1 | +2.5%/週（+130% 年換算）目標 | ⚠️ 野心的すぎる | 持続的+130%は top 0.01%。$6,700 規模では年収より訓練データとしての価値が高い |
| P2 | 5ペルソナ討論が独立した判断を生む | ⚠️ 統計的に独立していない | 同一モデルの相関した事前分布。全会一致は多様性ではなくバイアスの可能性 |
| P3 | Anthropic SDK 不使用（Claude Code IS the agent） | ❌ 実装が矛盾 | test_agents.py が anthropic.Anthropic をパッチしている。現コードパスのテストはゼロ |
| P4 | yfinance 15分遅延データで momentum 成立 | ⚠️ 構造的 late-chasing リスク | モメンタムエッジはイントラデイで減衰。WAT MFE=+0.04% は遅延エントリーが一因 |
| P5 | Slack → 人間承認ループが信頼できる | ❌ 実証的に壊れている | slack.py が全例外を飲み込む。decision.py が戻り値を無視して成功表示 |
| P6 | 10トレードで戦略を検証できている | ⚠️ サンプル不足 | 6週間・1つの市場レジーム（NORMAL）。rule_adherence_score が空でキャリブレーション未実施 |

**ユーザー確認**: すべての前提チャレンジを受け入れ、現在の方向性を維持してフルレビュー続行。

### Step 0B: 既存コードの活用マップ

| サブ課題 | 既存実装 | ギャップ |
|---------|---------|---------|
| SPY アルファ計算 | fetch_returns.py（骨格あり）, weekly_review.py（未実装） | weekly_review.py に SPY 比較ロジック追加が必要 |
| B 枠検証 | paper_portfolio.csv（空）, paper_decision_prompts.py（H-2 仮説） | active: True にすれば /decision Step 10 で自動並走 |
| Slack 信頼性 | notifications/slack.py:35 | 例外処理と戻り値チェックを追加 |
| ポジション追跡 | portfolio.csv（18フィールド） | position_id カラム追加が必要 |
| テスト | tests/（旧 SDK アーキテクチャのみ） | skills/*.py の実コードパスのテストをゼロから書く必要あり |

### Step 0C: ドリームステート図

```
CURRENT（2026-05-17）           THIS PLAN（修正後）              12-MONTH IDEAL
─────────────────────          ──────────────────               ─────────────────
・Slack silent fail             ・Slack に例外ハンドリング        ・完全な信頼性
・tests = 旧 SDK のみ            ・実コードパスのテスト追加        ・100% コードカバレッジ
・SPY アルファ未計算             ・weekly_review.py 実装         ・週次アルファダッシュボード
・B 枠未起動                    ・H-2 仮説並走開始              ・複数仮説の A/B 検証
・portfolio_id なし             ・position_id 追加              ・正確なロット管理
・rule_adherence_score=空       ・record_outcomes.py 修正        ・完全なキャリブレーション
・手動ウォッチリスト管理          ・watchlist.json 整合性修正       ・自動フロー管理
```

### Step 0C-bis: 実装アプローチの選択肢

| アプローチ | 工数（人間） | 工数（CC） | リスク | 推奨度 |
|-----------|-----------|-----------|------|------|
| A) 最優先 3 件を今週修正（Slack + tests + position_id） | 2日 | 1h | 低 | ✅ |
| B) すべて一度に修正 | 1週間 | 4h | 中（実弾運用中）| △ |
| C) 何もしない | 0 | 0 | 高（次の Slack 停止でトレード消失）| ❌ |

**自動判断**: A を選択（P3・明示性、P6・行動バイアス）

### Step 0D: スコープ評価

| 優先 | 機能 | 現状 | インパクト |
|------|------|------|----------|
| 🔴 最優先 | Slack 送信失敗を例外として扱う | サイレント失敗 | STOP/BUY が消失するリスク |
| 🔴 最優先 | 実コードパスのテスト（skills/*.py） | ゼロ | 旧 SDK のテストが保守コストを生んでいる |
| 🔴 最優先 | position_id 追加（portfolio.csv） | なし | CRDO 重複行で計算バグ発生中 |
| 🟡 高 | SPY アルファ計算 | weekly_review.py 未実装 | 評価基盤なし |
| 🟡 高 | B 枠（paper portfolio）起動 | paper_portfolio.csv 空 | H-2 仮説検証が始まっていない |
| 🟡 高 | portfolio.csv の --send 入力検証 | なし | マンデートルール（25%上限等）が無効化される |
| 🟡 中 | atomic CSV 書き込み（temp + os.replace） | なし | クラッシュでデータ破損リスク |
| 🟡 中 | watchlist.json 整合性修正 | AVGO/WAT/UAL がずれ | /decision で誤った候補セット |
| 🟢 低 | README ディレクトリ構成の更新 | .claude/commands 記載は古い | 新規セットアップ時に詰まる |
| 🟢 低 | .env.example から ANTHROPIC_API_KEY 削除 | 混乱を招く | セットアップ DX の問題 |
| 🟢 低 | macro gate（HIGH_FEAR で /research ブロック） | 未実装 | 下落相場での損失制限 |

### Step 0E: テンポラル評価（運用上のリスクシナリオ）

| 時刻 | 問題シナリオ | 現在の対応 |
|------|-----------|----------|
| 23:00（米市場クローズ） | STOP_BREACH 発生 | cron JST 7:00 まで 8 時間未検知 |
| 翌 7:00 | monitor 実行 → Slack 送信試行 | Slack が down していれば silent success |
| 翌 8:00 | 人間が確認 → 通知なし | 気付けない。broker で手動確認するしかない |
| 最悪ケース | 8 時間 × ポジション × 市場変動 | WAT で -7.27% がこのシナリオの実例 |

### Step 0F: モード確認

SELECTIVE EXPANSION を選択（既存システムの改善、新機能追加は最小限）。

### Step 0.5: CEO Dual Voices

**CLAUDE SUBAGENT (CEO — strategic independence):**

主要発見：
- 問題の再定義: 本質的価値は「スコア→アウトカムの校正データセット」。P&L はその副産物。
- +130% 年換算目標が25%/銘柄という過集中を構造的に誘導している。
- B 枠を実弾より先に動かすべきだった（逆順になっている）。
- WAT/UAL のロスは「ストップが機能した」ではなく「エントリーが間違っていた」可能性が高い（MFE=+0.04%）。
- `rule_adherence_score` / `mfe_capture_pct` が空であるため、キャリブレーションループ自体が機能していない。

**CODEX SAYS: [codex-unavailable — CLI not found]**

```
CEO DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                        Claude-subagent  Consensus
  ──────────────────────────────── ────────────     ─────────
  1. 前提は妥当か？                  ❌ P1/P2/P4疑問  [subagent-only]
  2. 解くべき問題は正しいか？          ⚠️ 再定義余地あり [subagent-only]
  3. スコープ調整は正確か？           ⚠️ B枠未起動    [subagent-only]
  4. 代替案は十分に検討されたか？      ❌ paper-first が未検討 [subagent-only]
  5. 競争リスクは対応済みか？         ✅ ソロ用途として問題なし [subagent-only]
  6. 6ヶ月の軌跡は健全か？          ⚠️ 1レジームのみ [subagent-only]
═══════════════════════════════════════════════════════════════
```

### CEO セクション 1-10 評価

**セクション 1: 問題定義の妥当性**
+2.5%/週の目標は野心的だが、システムの本質的価値（キャリブレーションエンジン）と混同されている。現時点では「P&L を最大化する」より「予測モデルの精度を高める」目的の方がシステム設計に忠実。未解決。

**セクション 2: エラー & レスキューレジストリ**

| エラーケース | 現状 | 重要度 |
|-----------|------|------|
| Slack 送信失敗 | サイレント成功（最悪ケース）| 🔴 CRITICAL |
| yfinance レートリミット | ログなし、graceful degradation なし | 🟡 HIGH |
| --send JSON 不正形式 | KeyError 未処理、決断が消失 | 🟡 HIGH |
| CSV 書き込みクラッシュ | atomic write なし、データ破損リスク | 🟡 HIGH |
| position_id 重複 | 重複 CRDO 行で計算バグ | 🟡 HIGH |

**セクション 3: スコープ境界**
「NOT in scope」として自動除外したもの：ダッシュボード UI（FastAPI）、リアルタイムデータフィード（有料 API 追加）、複数ポートフォリオ管理。これらは TODOS.md に追記。

**セクション 4: 既存コードとの重複チェック**
`show_calibration_stats.py` は実装済みだが `/decision` 冒頭に組み込まれていない。1 行追加で有効化できる。DRY 違反ではなく統合不足。

**セクション 5: 成長率・モメンタム検証**
10トレード: 勝率70%（7勝3敗）、平均+21.0%。ただし：
- signal_type 別分析で `watchlist_escalate` は 1件 -0.2%（サンプル不足）
- `earnings_beat` 3件中1件損失（NVDA -4.72%）
- 上昇相場（2026年4月急回復）のベータが含まれている可能性を排除できない

**セクション 6: リスク管理の評価**
ストップロスは機能している（NVDA -4.72%、WAT -7.27%、UAL -0.2%で止まった）。ただしイントラデイ監視は cron JST 7:00 のみ。30分ごとの cron 追加が必要。

**セクション 7: 代替案の評価**
B 枠（paper portfolio）が H-2 仮説を検証するために設計されているが、未起動。最も明確な改善機会。

**セクション 8: 競合分析**
個人用途のソロシステムとして競合リスクは低い。yfinance ベースのコスト 0 は適切。

**セクション 9: チームと実行可能性**
ソロ運用。Claude Code セッションが主要なエージェントとして機能している（P3 の実装は正しい。テストが追いついていないだけ）。

**セクション 10: 6ヶ月ビジョン**
成熟した6ヶ月後の姿：30+ クローズドトレード × 2+ 市場レジーム × SPY アルファ測定済み × B 枠仮説の検証結果。現在はその途中段階。

### CEO フェーズ完了サマリー

**戦略の方向性は正しい**。Claude Code as agent の設計、yfinance コスト 0 運用、ヒューマン・イン・ザ・ループ — いずれも正しい選択。

**致命的な欠陥は 2 つ**：
1. Slack 送信失敗がサイレント成功になっている（人間の承認機会が消失する）
2. テストスイートが現在のアーキテクチャを一切カバーしていない

---

**Phase 1 COMPLETE.** Codex: [unavailable]. Claude subagent: 6件の重要所見.  
Consensus: 1/6 confirmed（競合リスクのみ）、5 disagreements → 自動判断済み  
Passing to Phase 3 (no UI scope detected, skipping Phase 2).

---

## Phase 3: エンジニアリングレビュー

### Step 0.5: Eng Dual Voices

**CLAUDE SUBAGENT (Eng — independent review):**

主要発見（Eng subagent の完全版）：

1. **CRITICAL E-1: テストスイートが旧アーキテクチャを検証している**
   - `tests/test_agents.py:91,117,138,193` が `investor.agents.research_agent.anthropic.Anthropic` をパッチ
   - `tests/test_clients.py` が `PolygonClient`/`NewsClient` をテスト（現実装は yfinance のみ）
   - `tests/test_agents.py` が `investor.db.database` / `investor.db.models`（SQLite）をインポート — 現実装は CSV/JSON
   - **現在の実コードパス（skills/decision.py, skills/research.py, skills/monitor.py）のテストはゼロ**

2. **CRITICAL E-2: Slack サイレント失敗**
   - `slack.py:35` が全例外を `except Exception` で飲み込んで `False` を返す
   - `decision.py:142` が戻り値を無視して `print("Sent N proposal(s)")` を実行
   - 実証済みの失敗: 2026-04-25/26 の Slack 停止で BUY 通知が消失

3. **HIGH E-3: エントリー価格パース失敗で silent ゼロ株ポジション**
   - `decision.py:57` でエンダッシュ（`–`）形式の価格帯（例: `"150–160"`）を `float()` に渡すと ValueError
   - except で捕捉されて `mid = 0.0` → `shares = 0` → 空のエントリー価格のゼロ株ポジションがCSVに書き込まれる
   - ダウンストリームの EV/リターン計算で除算エラーまたは 0 除算が発生

4. **HIGH E-4: 損失トレードのサイレント除外（キャリブレーション汚染）**
   - `research.py:48` で `closed` ステータスの行が `exit_price` を持たない場合に `ValueError` → silently dropped
   - 損失トレードが calibration stats から除外され、システムが実際より高精度に見える
   - `edge_decay` チェック（`research.py:128`）に符号バグあり：`all_ev` が負の場合に判定が逆転する

5. **HIGH E-5: position_id なし — CRDO 重複行が計算を汚染**
   - `portfolio.csv` に CRDO が2行（同じ entry_date/entry_price、異なる exit）
   - ticker でマッチングするコードが「どちらの CRDO か」を判断できない
   - `/decision --mode exit --ticker CRDO` が誤った行を更新するリスク

6. **HIGH E-6: --send JSON にマンデートルール検証なし**
   - `decision.py:116` の `json.loads(send)` は全フィールドを信頼する
   - `position_size_usd`, `stop_loss`, `target_price` が範囲チェックなしで CSV と Slack に書き込まれる
   - Claude が `position_size_usd: 670000`（全額一銘柄）を出力しても止まらない
   - CLAUDE.md:11-14 のマンデートルール（25%上限、5銘柄上限）がコードレベルで無効化されている

7. **MEDIUM E-7: paper_portfolio.csv と A枠のスキーマ不一致**
   - `PAPER_FIELDNAMES` (decision.py:36-41) は 14 フィールド
   - A枠ヘッダーは 18 フィールド（mae_pct, mfe_pct, rule_adherence_score 等が欠落）
   - paper_portfolio.py compare でスキーマ不一致による KeyError リスク

8. **MEDIUM E-8: atomic CSV 書き込みなし**
   - `_log_paper_proposals` がファイル全体を書き直す（`decision.py:80`）
   - temp ファイル + `os.replace` を使っていないため、クラッシュ時に CSV が壊れる
   - portfolio.csv も同様のリスク

9. **MEDIUM E-9: select_personas の未テストと HIGH_FEAR_DOWNTREND バグ**
   - `personas.py:435-445` の cap-at-4 トリムが、`HIGH_FEAR_DOWNTREND` レジームで macro_mind を誤って除外する可能性あり
   - 80行の分岐ロジックが完全に未テスト

10. **LOW E-10: note フィールドをパーサーとして使用**
    - `research.py:54` が `"HIGH確信"` を note フィールドのフリーテキストから grep
    - `"確信度HIGH"` 表記でサイレントミスバケット → calibration data ロスト

**CODEX SAYS: [codex-unavailable]**

```
ENG DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                        Claude-subagent  Consensus
  ──────────────────────────────── ────────────     ─────────
  1. アーキテクチャは健全か？         ⚠️ 分離は良いが tests が嘘 [subagent-only]
  2. テストカバレッジは十分か？        ❌ 実コードパス = ゼロ [subagent-only]
  3. パフォーマンスリスクは対応済みか？ ✅ yfinance キャッシュあり [subagent-only]
  4. セキュリティ脅威は対応済みか？    ❌ --send 未検証 [subagent-only]
  5. エラーパスは処理済みか？        ❌ Slack silent fail [subagent-only]
  6. デプロイリスクは管理可能か？     ⚠️ cron パスが古い可能性 [subagent-only]
═══════════════════════════════════════════════════════════════
```

### セクション 1: アーキテクチャ（ASCII 依存グラフ）

```
Claude Code Session（判断主体）
  │
  ├─ .claude/skills/{skill}/SKILL.md（エントリポイント）
  │     ├─ research/SKILL.md
  │     ├─ decision/SKILL.md   ← 627行、Step 0〜10（複雑すぎる可能性）
  │     ├─ monitor/SKILL.md
  │     └─ watchlist-research/SKILL.md
  │
  ├─ skills/{skill}.py（データ収集・保存）
  │     ├─ research.py          ← research_history.json への書き込み
  │     ├─ decision.py          ← portfolio.csv, paper_portfolio.csv への書き込み ⚠️ atomic write なし
  │     ├─ monitor.py
  │     └─ watchlist_research.py
  │
  ├─ investor/（ビジネスロジック）
  │     ├─ prompts/personas.py  ← select_personas() 80行分岐、未テスト
  │     ├─ notifications/slack.py ← ❌ 全例外を飲み込む
  │     └─ clients/yfinance_client.py
  │
  ├─ data/（永続化）
  │     ├─ portfolio.csv         ← ❌ position_id なし、CRDO 重複行
  │     ├─ paper_portfolio.csv   ← スキーマ A枠と不一致
  │     └─ research_history.json
  │
  └─ tests/                     ← ❌ 旧 SDK アーキテクチャのみカバー
        ├─ test_agents.py        ← investor.agents.* (存在しない) をテスト
        └─ test_clients.py       ← PolygonClient/NewsClient（使っていない）
```

**結論**: Python ↔ Claude の責務分離は正しい。問題はテストが別の実装を検証していること、データレイヤーの耐障害性が低いこと。

### セクション 2: コード品質

E-4（符号バグ）、E-10（note grep）が主なコード品質問題。命名は一貫している。

### セクション 3: テストダイアグラム（コードパス → テストカバレッジ）

| コードパス | テストあり? | ギャップ |
|-----------|-----------|--------|
| skills/decision.py（--send パース） | ❌ なし | E-3: zero-share ポジション |
| skills/decision.py（Slack 送信） | ❌ なし | E-2: silent fail |
| skills/research.py（calibration stats） | ❌ なし | E-4: 損失トレード除外 |
| skills/monitor.py | ❌ なし | E-2: Slack silent fail |
| investor/prompts/personas.py | ❌ なし | E-9: select_personas バグ |
| investor/notifications/slack.py | ❌ なし | 送信失敗パス |
| investor/agents/*.py（旧 SDK） | ✅ あり（だが死んでいる） | — |
| investor/db/*.py（旧 SQLite） | ✅ あり（だが死んでいる） | — |

**テストプランアーティファクト**: `~/.gstack/projects/PERSONAL-DEV-investor/test-plan-20260517.md` に出力。

### セクション 4: パフォーマンス

- yfinance 24h TTL キャッシュは適切。
- `monitor.py` の銘柄ごとの API 呼び出しはシリアル化されている。5銘柄で問題なし（10銘柄以上で遅延懸念）。
- `research.py:128` の `all_ev` 符号バグがパフォーマンスではなく精度に影響。

### Eng フェーズ完了サマリー

アーキテクチャの骨格は正しい。3つの即時修正が必要：
1. Slack 送信失敗を例外として raise/retry する
2. 旧テストスイートを削除し、実コードパスのテストを追加
3. portfolio.csv に position_id カラムを追加

---

**Phase 3 COMPLETE.** 10件の所見、CRITICAL 2件、HIGH 4件、MEDIUM 3件、LOW 1件  
Passing to Phase 3.5 (DX scope detected — Claude Code skills, CLI).

---

## Phase 3.5: DX レビュー（Claude Code スキル + CLI）

### Step 0.5: DX Dual Voices

**CLAUDE SUBAGENT (DX — independent review):**

主要発見（DX subagent の完全版）：

1. **CRITICAL D-1: .env.example に ANTHROPIC_API_KEY が記載されている**
   - アーキテクチャの根幹設計（Claude Code IS the agent、API Key 不要）と完全に矛盾
   - 初回セットアップ者が API Key を取得しようとして時間を無駄にする
   - Fix: .env.example から削除し、コメントで説明を追加

2. **HIGH D-2: README のディレクトリ構成が古い**
   - README には `.claude/commands/research.md` と記載
   - 実際は `.claude/skills/research/SKILL.md`
   - README の skills 一覧も `/review`, `/watchlist-research` が欠落
   - Fix: CLAUDE.md を source of truth にして README を再生成

3. **HIGH D-3: Slack webhook の疎通確認がセットアップフローにない**
   - セットアップ §4 は `skills/portfolio.py list` で動確するが Slack を確認しない
   - 最初の `/decision` 実行後（5ペルソナ討論数分後）に初めて Slack 問題が発覚する
   - Fix: セットアップ §4 に `python -c "from investor.notifications.slack import SlackNotifier; SlackNotifier().send_text('setup OK')"` を追加

4. **MEDIUM D-4: SKILL.md に絶対パスのハードコード**
   - `/Users/yutaobayashi/PERSONAL DEV/1_now/investor` が複数の SKILL.md に記載
   - 別マシンや別パスでのセットアップで即座に失敗
   - Fix: `$INVESTOR_HOME` 環境変数または `$(pwd)` で相対参照に変更

5. **MEDIUM D-5: CLI コントラクトのドリフト**
   - README、CLAUDE.md、SKILL.md で同一スキルの呼び出し方が食い違っている
   - decision/SKILL.md Step 7 に "if save_proposals is not yet implemented" という未実装パスの記述が残っている
   - 627行の decision/SKILL.md は Step 0〜10 のネスト構造が深く（Step 6 に 0,1,1.5,2,3,4,4.5,5,6 という小ステップ）、日常オペレーターが記憶するには複雑すぎる

**CODEX SAYS: [codex-unavailable]**

```
DX DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                        Claude-subagent  Consensus
  ──────────────────────────────── ────────────     ─────────
  1. 初回セットアップ < 5分?         ❌ .env.example 誤解   [subagent-only]
  2. API/CLI 名は推測可能か?         ⚠️ drift あり         [subagent-only]
  3. エラーメッセージは行動可能か?    ❌ tool.py failure なし [subagent-only]
  4. ドキュメントは2分で見つかるか?   ❌ README が古い       [subagent-only]
  5. アップグレードパスは安全か?      ✅ フラットファイルで問題なし [subagent-only]
  6. 開発環境のフリクションは低いか?  ⚠️ hardcoded paths    [subagent-only]
═══════════════════════════════════════════════════════════════
```

### DX スコアカード

| ディメンション | スコア | 所見 |
|-------------|-------|------|
| 1. TTHW（Time to Hello World） | 4/10 | .env.example の誤解、Slack 未確認 |
| 2. API/CLI エルゴノミクス | 6/10 | スキル名は直感的。CLI contract drift が問題 |
| 3. エラーメッセージの品質 | 3/10 | yfinance 失敗時のトラブルシューティングなし |
| 4. ドキュメントの発見可能性 | 4/10 | README が古い。SKILL.md が長すぎる |
| 5. エスケープハッチ | 7/10 | フラットファイルで手動修正が容易 |
| 6. オペレーター体験 | 5/10 | decision/SKILL.md が627行で記憶困難 |
| 7. セットアップ信頼性 | 3/10 | Slack 疎通なし。API Key 誤解 |
| 8. ドリフト管理 | 4/10 | README/CLAUDE.md/SKILL.md が乖離 |
| **総合** | **4.5/10** | 設計は正しいが実装ドキュメントが追いついていない |

**TTHW**: 推定 30〜60分（.env.example の混乱 + Slack 確認なし）→ 目標 < 10分

### DX フェーズ完了サマリー

最高優先度: `.env.example` から `ANTHROPIC_API_KEY` を削除（5分の作業、DX スコアを +3 改善）

---

**Phase 3.5 COMPLETE.** 5件の所見、CRITICAL 1件、HIGH 2件、MEDIUM 2件  
DX Overall: 4.5/10。TTHW: 30-60分 → 目標 < 10分  
Passing to Phase 4 (Final Gate).

---

## 意思決定ログ（自動判断）

| # | フェーズ | 判断内容 | 分類 | 原則 | 採用 | 却下 |
|---|---------|---------|------|------|------|------|
| 1 | CEO | Slack silent fail を最優先修正 | Mechanical | P1（完全性） | 即修正 | 後回し |
| 2 | CEO | テストを旧 SDK から実コードパスへ置換 | Mechanical | P5（明示性） | 即修正 | 旧テストを残す |
| 3 | CEO | SPY アルファ計算を高優先に | Mechanical | P1 | 今月中 | 来月以降 |
| 4 | CEO | B 枠（paper portfolio）をすぐに起動 | Mechanical | P1 | active: True にする | 待つ |
| 5 | CEO | watchlist_escalate ルールはサンプル不足で廃止しない | Mechanical | P6（行動バイアス） | 継続観察 | 廃止 |
| 6 | CEO | +2.5%/週目標はユーザーの意向として維持 | User direction | — | 維持 | 変更 |
| 7 | Eng | --send JSON にマンデートルール検証を追加 | Mechanical | P2（全域対応） | 追加 | なし |
| 8 | Eng | portfolio.csv に position_id を追加 | Mechanical | P5 | 追加 | なし |
| 9 | Eng | atomic CSV 書き込みに変更 | Mechanical | P2 | 変更 | なし |
| 10 | Eng | 旧 SDK テストを削除して実パステストを追加 | Mechanical | P5 | 削除 + 新規追加 | 旧テスト維持 |
| 11 | DX | .env.example から ANTHROPIC_API_KEY を削除 | Mechanical | P5 | 削除 | 残す |
| 12 | DX | README ディレクトリ構成を更新 | Mechanical | P5 | 更新 | 放置 |

---

## クロスフェーズテーマ

**テーマ T-1: 人間の承認ループの信頼性（CEO + Eng）**
Slack サイレント失敗（CEO: ヒューマン・イン・ザ・ループ設計の欠陥 + Eng: slack.py:35 の実装バグ）。最高優先度の横断テーマ。

**テーマ T-2: テストと実装の乖離（Eng + DX）**
tests/ が旧アーキテクチャをカバー（Eng: ゼロカバレッジ + DX: README が古い構成を記載）。ドキュメントとテストが実装から分離している状態。

**テーマ T-3: 評価基盤の欠如（CEO + Eng）**
rule_adherence_score/mfe_capture_pct 空（CEO: キャリブレーションループ未完成 + Eng: calibration stats から損失トレードが除外される符号バグ）。

---

## 全体スコア

| 軸 | スコア | コメント |
|---|--------|---------|
| 戦略の方向性 | 7/10 | 設計思想は正しい。P&Lとキャリブレーションの目的を明確化すべき |
| 実装の完成度 | 5/10 | コアは動いている。test suite が現実を反映していない |
| オペレーションの安定性 | 4/10 | Slack silent fail が最大リスク。証明済みの穴 |
| リスク管理 | 6/10 | ストップロスは機能。--send 検証なしが穴 |
| 学習ループ | 4/10 | rule_adherence_score 空でキャリブレーション未完成 |
| DX | 4.5/10 | 設計は良い。ドキュメントが追いついていない |

**総合**: 5/10。実弾運用中のシステムとして「CRITICAL を今週中に修正」が最優先。

---

## 推奨アクション（優先順位順）

### 🔴 今週中（CRITICAL 修正）

**A1: slack.py の例外処理を修正して送信失敗を loud にする**
```python
# slack.py:35 を変更
# Before: except Exception as e: return False
# After:
def send_text(self, text: str) -> bool:
    try:
        response = requests.post(self.webhook_url, json={"text": text}, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"SLACK_SEND_FAILED: {e}")
        raise  # または再試行ロジック
```

**A2: decision.py:142 で Slack 戻り値を確認する**
```python
ok = send_result  # bool を確認
if not ok:
    print("CRITICAL: Slack 送信失敗。Slack の設定を確認してください。")
    sys.exit(1)  # 成功を詐称しない
```

**A3: 旧テストスイートを削除し、実コードパスのテストを追加**
```bash
# 削除
rm tests/test_agents.py tests/test_clients.py

# 新規追加（最低限）
# - Slack 送信失敗パスのテスト
# - --send JSON parse の invalid 入力テスト
# - portfolio.csv round-trip のテスト
```

**A4: portfolio.csv に position_id を追加**
```
# ヘッダーに追加
position_id,ticker,shares,...

# 既存行に UUID を割り当て
```

**A5: .env.example から ANTHROPIC_API_KEY を削除**
```bash
# .env.example の ANTHROPIC_API_KEY 行を削除
# コメントで「不要な理由」を追記
```

### 🟡 今月中

**B1: --send JSON のマンデートルール検証を追加**
```python
def validate_proposal(p: dict) -> None:
    """CLAUDE.md のマンデートルールを enforce する"""
    assert p.get("position_size_usd", 0) <= 1675, f"25%上限違反: {p}"
    assert p.get("stop_loss"), "stop_loss は必須"
    assert p.get("ticker"), "ticker は必須"
```

**B2: portfolio.csv の atomic write に変更**
```python
import tempfile, os
with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.tmp') as tf:
    writer.writerows(rows)
    tf.flush()
os.replace(tf.name, CSV_PATH)
```

**B3: B 枠（paper portfolio）を起動**
```python
# investor/prompts/paper_decision_prompts.py の H-2 仮説を active: True に変更
```

**B4: SPY アルファ計算を weekly_review.py に実装**
```python
alpha_vs_spy = position_return - spy_return_same_period
```

**B5: watchlist.json の整合性修正**
- AVGO: "active" → "promoted"
- UAL: "active" → "promoted"
- WAT: "active" → "removed"

### 🟢 来月以降

**C1: decision/SKILL.md を短縮・モジュール化**
627行の SKILL.md を `reference/` に分割して、デイリーオペレーション向けの短縮版を作成。

**C2: research.py:128 の符号バグを修正**
```python
# Before（バグあり）:
if recent_ev < all_ev * 0.5:  # all_ev が負の場合は判定逆転
# After:
if all_ev > 0 and recent_ev < all_ev * 0.5:  # 正の EV のみで比較
```

**C3: README を CLAUDE.md から自動生成する仕組みを作成**

---

## H-1 / H-2 仮説の現在地

### H-1: Watchlist ESCALATE 銘柄は market-scan 銘柄より勝率が高い

| signal_type | 件数（クローズド） | 勝率 | 平均リターン |
|-------------|----------------|------|------------|
| watchlist_escalate | 1（UAL） | 0% | -0.2% |
| その他 | 9 | 78% | +24.5% |

判定: サンプル不足（TSM/LRCX はまだオープン）。検証期間（〜2026-08-10）まで継続。

### H-2: RSI>80 でも SECTOR_LEADING 条件なら縮小エントリーは正当化される

B 枠が空のため検証未開始。B3 対応後に再確認。

---

*Generated by Claude Code (garrytan-autoplan) on 2026-05-17*  
*Review model: Claude subagent × 3 [subagent-only — Codex CLI not found]*
<!-- /autoplan restore point: /Users/yutaobayashi/.gstack/projects/PERSONAL-DEV-investor/main-autoplan-restore-20260517-122052.md -->

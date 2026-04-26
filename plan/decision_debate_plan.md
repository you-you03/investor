# Decision Agent — ペルソナ・ディベート設計計画

作成日: 2026-04-07  
対象: `/decision` コマンドの全面改訂  
方針: 動的ペルソナ召喚 / 精度重視ラウンド制ディベート / Slackは結論のみ

---

## 現状と変更の概要

### 現行フロー（直列モノローグ）

```
research_history.json 読み込み
  → Bullish Analyst（Claude が演じる）
  → Bearish Analyst（Claude が演じる）
  → Portfolio Manager（最終決定）
  → Slack 送信
```

問題点:
- 3ロールが直列で「反論なし」。同じコンテキストが流れるだけで議論が発生しない
- 情報不足でも強引に判断する（データギャップを検出しない）
- ペルソナに哲学がない（プロンプトが汎用的すぎる）

### 新フロー（動的ペルソナ × ラウンド制ディベート）

```
[Step 0] リサーチデータ読み込み
[Step 1] 銘柄属性の分析 → ペルソナ動的召喚（3〜4名）
[Step 2] Round 1: 各ペルソナが独立してスタンス表明
[Step 3] データギャップ検出 → 不足データを tool.py で補完
[Step 4] Round 2: 対立ペルソナが相互反論（2〜3ターン）
[Step 5] Round 3: PM がディベートログを総括 → 最終決定 JSON
[Step 6] Slack 送信（結論のみ）
```

---

## ペルソナ設計

### 5名のペルソナ一覧

| ID | ペルソナ名 | モデル | 投資哲学 | 強みのある局面 |
|---|---|---|---|---|
| `oracle` | **The Oracle** | Warren Buffett | 価値・堀・長期保有・理解できないものは買わない | 安定 CF・低 PEG・strong moat |
| `innovator` | **The Innovator** | Cathie Wood | 破壊的イノベーション・5 年 horizon・VolatilityはRisk でなくOpportunity | AI / biotech / genomics / EV |
| `macro_mind` | **The Macro Mind** | Ray Dalio | マクロ環境最優先・相関リスク・レジームシフト察知 | 金利局面・VIX 急騰・セクターローテーション |
| `tenbagger` | **The Tenbagger** | Peter Lynch | GARP・PEG ratio・自分が使えるビジネスに投資 | 中小型成長株・reasonable valuation |
| `tape_reader` | **The Tape Reader** | Jesse Livermore | モメンタム主体・テクニカル・ Line of Least Resistance | 出来高急増・ブレイクアウト・トレンド相場 |

---

### 動的召喚ルール

召喚は銘柄の **属性** と **マクロレジーム** の組み合わせで決定する。  
常時召喚ペルソナ（必須）はなく、毎回 3〜4 名を選ぶ。

#### 銘柄属性ルール

| 条件 | 召喚するペルソナ |
|---|---|
| テック / AI / 半導体（sector: Technology） | `innovator`, `tenbagger`, `tape_reader` |
| バイオ / ヘルスケア | `innovator`, `oracle`, `tenbagger` |
| 金融 / エネルギー / 素材（value sector） | `oracle`, `tenbagger`, `tape_reader` |
| 中小型（market cap < $10B） | `tenbagger`, `tape_reader` |
| 大型（market cap > $50B） | `oracle`, `innovator` |
| 純モメンタム（volume spike > 2x, rs_signal = STRONG_OUTPERFORM） | `tape_reader`（+1 名追加） |

#### マクロレジームルール（銘柄ルールに重ねる）

| レジーム | 追加ルール |
|---|---|
| `HIGH_FEAR`（VIX > 30） | `macro_mind` を必ず召喚 |
| `DOWNTREND`（SPY < EMA50） | `macro_mind` を必ず召喚 |
| `NORMAL` | `macro_mind` は召喚しない（他ペルソナの数が十分なら） |

#### 召喚数の上限

- 最大 4 名。5 名全員の召喚は禁止（コンテキスト肥大化を防ぐ）
- 重複排除後 4 名を超える場合は、属性ルールを優先してマクロルールからの重複を除く

---

## ディベート・ラウンド構造（精度重視）

### Round 1 — 初期スタンス表明（各ペルソナ独立）

各ペルソナが **他のペルソナの意見を知らない状態** で判断する。  
バイアス汚染を防ぐため、ペルソナ間の参照禁止。

各ペルソナの出力形式:
```
ペルソナ: The Oracle
スタンス: PASS / WAIT / BUY
確信度: HIGH / MEDIUM / LOW
根拠（哲学フィルター経由）:
  - [引用: 具体的なデータポイント]
  - [引用: 具体的なデータポイント]
不足データリスト:
  - free_cash_flow（moat 評価に必要）
  - debt_to_equity（財務健全性確認）
```

### データギャップ補完（Round 1 と Round 2 の間）

各ペルソナの「不足データリスト」を集約し、`tool.py` で補完する。

補完可能なデータ一覧（`tool.py` が対応しているもの）:
```
get_financials        → revenue, FCF, debt_to_equity, EPS
get_ticker_details    → forward_pe, peg_ratio, analyst_count
get_technical_indicators → RSI, MACD, ATR, EMA
get_earnings_calendar → days_until_earnings
get_news              → 最新ニュース
get_analyst_ratings   → 格付け変更
get_relative_strength → rs_signal, rs_1m, rs_3m
```

補完できないデータ（外部 API 未設定等）は「データ不足フラグ」として PM に渡す。  
フラグがある場合、PM は確信度の上限を MEDIUM に制限する。

### Round 2 — 交差反論（精度重視: 2 ターン）

対立ペルソナのペアリング:
- `oracle` ↔ `innovator`（価値 vs 成長）
- `macro_mind` ↔ `tape_reader`（マクロ vs テクニカル）
- `tenbagger` は両陣営に介入可能（中立的 GARP 視点）

各ペアのやり取り:
```
Turn 1: ペルソナ A が、ペルソナ B の Round 1 スタンスを反駁
        補完されたデータを活用して論拠を強化してよい
Turn 2: ペルソナ B が応答（譲歩 or 再反論）
        譲歩の場合はスタンス変更を明示すること
```

形式:
```
[The Innovator → The Oracle]
反論: "FCF が低いのは成長再投資フェーズの証拠。R&D / Revenue 比率を見ると..."
スタンスを維持: YES（BUY）

[The Oracle → The Innovator]
応答: "R&D 比率の点は認める。しかし現在の FCF Yield では安全マージンが薄い..."
スタンス変更: NO → 引き続き PASS
```

### Round 3 — PM 総括・最終決定

Portfolio Manager がディベートログ全体（Round 1 + データ補完結果 + Round 2）を読んで総括する。

判断軸（優先順）:
1. **データ品質**: 不足データフラグの有無。フラグあり → 確信度上限 MEDIUM
2. **ペルソナ合意度**: 3〜4 名中何名が BUY か。全員 PASS → 強制 PASS
3. **論点の優位性**: どちらの論点がより証拠に基づいているか
4. **ポートフォリオ制約**: セクター集中・残り枠・利用可能資金
5. **最終確信度**: HIGH / MEDIUM / LOW → Half Kelly でポジションサイズ確定

出力（JSON のみ、プロズなし）:
```json
[
  {
    "ticker": "NVDA",
    "action": "BUY",
    "conviction": "HIGH",
    "entry_price_range": "860-880",
    "target_price": 1000,
    "stop_loss": 820,
    "position_size_usd": 3350,
    "rationale": "3〜4文。ディベートの勝因を引用。データギャップがあれば言及。",
    "key_catalysts": ["GTC conference in 2 weeks"],
    "risk_factors": ["Valuation at 35x forward P/E"],
    "time_horizon": "4-6 weeks",
    "debate_summary": {
      "personas_convened": ["innovator", "tenbagger", "tape_reader", "macro_mind"],
      "round1_stances": {
        "innovator": "BUY/HIGH",
        "tenbagger": "BUY/MEDIUM",
        "tape_reader": "BUY/HIGH",
        "macro_mind": "WAIT/LOW"
      },
      "final_alignment": "3 BUY vs 1 WAIT"
    }
  }
]
```

`debate_summary` フィールドは Slack には**送らない**（ログとして `research_history.json` に保存するのみ）。

---

## 実装フェーズ

---

### Phase 1: ペルソナライブラリの構築

**目的**: 5 ペルソナの哲学・プロンプト・動的召喚ルールを一か所で管理する  
**変更ファイル**: 新規 `investor/investor/prompts/personas.py`

#### 内容設計

```python
# personas.py の構造（実装イメージ）

PERSONAS = {
    "oracle": {
        "name": "The Oracle",
        "model": "Warren Buffett",
        "system_prompt": """...""",
        "decision_framework": [
            "Does this company have a durable competitive moat?",
            "Can I understand the business model in simple terms?",
            "Is the current price justified by intrinsic value (DCF / normalized earnings)?",
            "Is management shareholder-friendly (FCF allocation, buybacks, no dilution)?",
            "Would I be comfortable holding this for 10 years?",
        ],
        "bullish_triggers": ["low_peg", "strong_fcf", "high_moat_indicators"],
        "bearish_triggers": ["negative_fcf", "high_pe_with_no_growth", "dilutive_management"],
    },
    "innovator": { ... },
    "macro_mind": { ... },
    "tenbagger": { ... },
    "tape_reader": { ... },
}

def select_personas(ticker_data: dict, macro_regime: str) -> list[str]:
    """
    銘柄属性とマクロレジームからペルソナ ID を動的に選択。
    Returns: 3〜4 名のペルソナ ID リスト
    """
    ...
```

**作業チェックリスト**:
- [ ] `personas.py` 新規作成
- [ ] 5 ペルソナの `system_prompt` 執筆（各 150〜200 words）
- [ ] `decision_framework` リスト（各ペルソナ 4〜6 項目）
- [ ] `select_personas()` 関数実装（属性ルール + マクロルール）
- [ ] ユニットテスト（召喚ルールの境界値確認）

---

### Phase 2: データギャップ検出の設計

**目的**: Round 1 の出力から不足データを集約し、`tool.py` で補完するロジックを確立する  
**変更ファイル**: `investor/.claude/commands/decision.md`（フロー追加）

#### データギャップ検出の仕様

Round 1 の各ペルソナ出力には、以下のフィールドを含める:
```
missing_data: list[str]   # 判断に必要だが取得できていないデータ名
data_impact: "critical" | "nice_to_have"
```

`decision.md` の中間ステップ（Round 1 と Round 2 の間）:

```
## Data Gap Resolution Step

1. 全ペルソナの missing_data を集約する
2. critical に分類されたデータのみ補完対象とする
3. 以下のマッピングで tool.py コマンドを実行:

   missing_data に "free_cash_flow" または "revenue_growth" が含まれる場合:
   → .venv/bin/python scripts/tool.py get_financials --ticker {TICKER}

   missing_data に "forward_pe" または "peg_ratio" が含まれる場合:
   → .venv/bin/python scripts/tool.py get_ticker_details --ticker {TICKER}

   missing_data に "RSI" または "MACD" が含まれる場合:
   → .venv/bin/python scripts/tool.py get_technical_indicators --ticker {TICKER}

   missing_data に "days_until_earnings" が含まれる場合:
   → .venv/bin/python scripts/tool.py get_earnings_calendar --ticker {TICKER}

4. 取得成功 → Round 2 コンテキストに注入
5. 取得失敗（ツール未対応 / API 非対応） → data_gap_flag: true を PM に渡す
   PM はこのフラグがある場合、確信度の上限を MEDIUM に制限する
```

**作業チェックリスト**:
- [ ] `decision.md` に「Data Gap Resolution Step」セクション追加
- [ ] データ名 → `tool.py` コマンドのマッピング表を `decision.md` に記載
- [ ] `data_gap_flag` の PM への渡し方を定義（プレーンテキストで注記）
- [ ] 動作確認: 意図的に不完全なリサーチデータでテスト

---

### Phase 3: `/decision` コマンドの全面改訂

**目的**: 現行の 3 ステージを新ラウンド制フローに置き換える  
**変更ファイル**: `investor/.claude/commands/decision.md`

#### 改訂後のコマンド構造

```
## Step 1: データ読み込み
  - research_history.json から対象 run を読み込む
  - portfolio.csv から現在のオープンポジションを確認

## Step 2: 銘柄属性分析 → ペルソナ召喚決定
  - 各候補の sector / market_cap / rs_signal / macro_regime を確認
  - select_personas() ルールを適用して 3〜4 名を選定
  - 選定したペルソナ名と理由を出力する

## Step 3: Round 1 — 初期スタンス表明
  - 各ペルソナが順番に（他のペルソナを参照せずに）スタンスを表明
  - 形式: スタンス / 確信度 / 根拠リスト / 不足データリスト

## Step 4: データギャップ補完
  - Phase 2 で定義したロジックで tool.py を実行
  - 取得できたデータを「補完データ」として明示

## Step 5: Round 2 — 交差反論（Turn 1 + Turn 2）
  - 対立ペルソナペアを特定して反論実施
  - 補完データを論拠として使用可
  - スタンス変更は明示すること

## Step 6: Round 3 — PM 総括
  - ディベートログ全体を読んで最終 JSON を出力
  - data_gap_flag がある場合は確信度上限を MEDIUM にする
  - ポジションサイジングは Half Kelly で自動計算

## Step 7: Slack 送信
  - scripts/send_slack_proposals.py で送信
  - 送信内容: ticker / action / conviction / position_size_usd / rationale / catalysts / risks のみ

## Step 8: research_history.json への保存
  - proposals + debate_summary を最新 run に追記保存
```

**作業チェックリスト**:
- [ ] `decision.md` を上記構造に全面改訂
- [ ] ペルソナ召喚決定ロジックをコマンド内に明示
- [ ] 各ラウンドの出力フォーマットをコマンド内に明示
- [ ] `debate_summary` の保存先（research_history.json）の書き込み方法を明示
- [ ] 既存コマンドとの後方互換テスト（`run_id` 引数の扱い）

---

### Phase 4: プロンプトエンジニアリング

**目的**: `decision_prompts.py` にペルソナ別プロンプトとラウンド別テンプレートを追加する  
**変更ファイル**: `investor/investor/prompts/decision_prompts.py`, `personas.py`

#### 追加・変更するプロンプト

| プロンプト | 役割 |
|---|---|
| `PERSONA_SYSTEM_PROMPTS["oracle"]` など | 各ペルソナの system prompt |
| `ROUND1_USER_TEMPLATE` | Round 1 の指示テンプレート（リサーチデータ + 役割指示） |
| `DATA_GAP_EXTRACTION_PROMPT` | Round 1 後、不足データリストを構造化させる指示 |
| `ROUND2_CROSSFIRE_TEMPLATE` | 交差反論の指示（反論対象ペルソナ名 + Round 1 スタンスを注入） |
| `PM_SYNTHESIS_PROMPT` | PM 総括の system prompt（現行の `PM_DECISION_PROMPT` を強化） |
| `PM_SYNTHESIS_USER_TEMPLATE` | ディベートログ + data_gap_flag を注入するテンプレート |

#### ペルソナ system prompt の設計原則

各ペルソナは以下を必ず含める:
1. **役割宣言**: 誰の哲学で判断するか
2. **判断フレームワーク**: 必ず確認する 4〜6 項目
3. **制約**: 例「私は理解できないビジネスには投資しない（The Oracle）」
4. **出力フォーマット制約**: スタンス / 確信度 / 根拠リスト / 不足データリストの形式を強制

**作業チェックリスト**:
- [ ] `PERSONA_SYSTEM_PROMPTS` dict を `personas.py` に実装（5 ペルソナ分）
- [ ] `ROUND1_USER_TEMPLATE` 実装
- [ ] `DATA_GAP_EXTRACTION_PROMPT` 実装
- [ ] `ROUND2_CROSSFIRE_TEMPLATE` 実装（対立ペアのペルソナ名を変数として受ける）
- [ ] `PM_SYNTHESIS_PROMPT` を現行 `PM_DECISION_PROMPT` から改訂
- [ ] `PM_SYNTHESIS_USER_TEMPLATE` を現行 `DECISION_USER_TEMPLATE` から改訂
- [ ] プロンプト変更後の出力品質テスト（実データでのドライラン）

---

### Phase 5: Slack 出力の最小化

**目的**: Slack 送信内容を「結論のみ」に絞る  
**変更ファイル**: `investor/investor/notifications/slack.py`（または `formatters.py`）

#### 送信する情報（結論のみ）

```
[BUY] NVDA — HIGH conviction
Entry: $860–880 | Target: $1,000 | Stop: $820
Size: $3,350 (50% Kelly)
Rationale: ...3文...
Catalysts: GTC conference in 2 weeks
Risks: Valuation at 35x forward P/E
```

#### 送らない情報

- ディベートのやり取り（Round 1 / Round 2 の全文）
- ペルソナごとの個別スタンス
- `debate_summary` の詳細（これは `research_history.json` にのみ保存）

**作業チェックリスト**:
- [ ] `send_proposals()` の Slack Block Kit フォーマットを「結論のみ」に刷新
- [ ] `debate_summary` を Slack ペイロードから除外する確認
- [ ] テスト: ドライランで Slack プレビューを確認

---

## ファイル変更マップ（全フェーズ）

| ファイル | 変更種別 | フェーズ | 説明 |
|---|---|---|---|
| `investor/investor/prompts/personas.py` | **新規** | Phase 1 | 5 ペルソナ定義 + 動的召喚ロジック |
| `investor/.claude/commands/decision.md` | **全面改訂** | Phase 2, 3 | ラウンド制ディベートフローに置き換え |
| `investor/investor/prompts/decision_prompts.py` | **追加・改訂** | Phase 4 | ペルソナ別 / ラウンド別プロンプト追加 |
| `investor/investor/notifications/slack.py` | **軽微な変更** | Phase 5 | Slack 出力を結論のみに絞る |
| `investor/data/research_history.json` | スキーマ拡張 | Phase 3 | `debate_summary` フィールドを追加 |

既存の `decision_agent.py` と `market_tools.py` は**変更しない**。  
データ取得ロジックはそのまま使い、プロンプトレイヤーとコマンドレイヤーの変更に留める。

---

## リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| コンテキスト肥大化（ラウンドが増えるほど） | 高 | ペルソナ上限 4 名、Round 2 は 2 ターンまでに制限 |
| データギャップ補完でのタイムアウト | 中 | `tool.py` の呼び出しは critical フラグのみ対象 |
| ペルソナが既存のペルソナに引きずられる（Round 2） | 中 | Round 1 はペルソナ間参照禁止のプロンプト制約を明示 |
| PM が全ペルソナの意見に引きずられて結論を出せない | 低 | PM の system prompt に「最終決定者はあなた一人」と明示 |
| `debate_summary` が Slack に流出する | 低 | Slack フォーマッター関数でフィールドを明示的に除外 |

---

## 実装着手順序の推奨

```
Phase 1（ペルソナライブラリ）
  → Phase 4（プロンプト）   ← プロンプトが固まらないと 3 は書けない
  → Phase 2（データギャップ検出設計）
  → Phase 3（decision.md 改訂）← 2 と 4 が揃ってから書く
  → Phase 5（Slack 最小化）   ← 最後で良い、独立している
```

Phase 1 → 4 を先に作り、ドライラン（リアルのリサーチデータを使った手動テスト）でペルソナの出力品質を確認してから Phase 3 に進むことを推奨する。

---

*このドキュメントは実装開始前の設計合意用。実装後は各フェーズの完了チェックをここに記録すること。*

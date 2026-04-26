# AI投資エージェント — 実装計画

作成日: 2026-04-04  
ベース: `research_findings.md` + コードベース実査  
対象ブランチ: main

---

## 現行システム状態（コード実査済み）

| コンポーネント | 現状の問題点 | 根拠RQ |
|--------------|------------|--------|
| `decision_prompts.py` | LLMが `shares_suggested`, `position_size_usd`, `target_price`, `stop_loss` を直接生成 | C2, C3 |
| `research_prompts.py` | LLMが `target_price`, `stop_loss` を推定値で生成。CoT構造なし。`get_x_search` ツールを使う指示がない | C3, D1, B2 |
| `research_agent.py` | 逐次ツールループのみ。Debate・並列分析なし | A1 |
| `decision_agent.py` | 単一Claude呼び出し。BullishDebate・Reflectionなし | A1, A3 |
| `db/models.py` | `ProposalResult`（提案の実績追跡）モデルが存在しない | A3 |
| `news_tools.py` | `get_x_search` は定義・配線済み。プロンプトから呼ばれていないだけ | B2 |

> **重要な発見**: `get_x_search` はすでに `TOOL_DISPATCH` に登録済み（`research_agent.py:43`）。  
> X sentimentの有効化は `research_prompts.py` のプロンプト変更のみで完了する。

---

## 変更分類

### Group A — 既存ファイル内の変更（アーキテクチャを壊さない）

プロンプト・計算ロジックのみの変更。現行の3エージェント構造を維持したまま即着手できる。

### Group B — エージェント間設計の変更（構造変更）

新コンポーネント追加・エージェント間インターフェース変更を伴う。Group Aが安定してから着手する。

---

## Phase 1 — 即時改善（Group A）

### P1-1: ポジションサイジングをLLMから切り離す ★★★

**対象**: `decision_prompts.py`, `decision_agent.py`  
**根拠**: C2（Fractional Kelly）, C3（LLMに数値を生成させない原則）

**変更概要**:

`decision_prompts.py` の出力スキーマから削除:
- `shares_suggested` — LLM生成を廃止
- `position_size_usd` — LLM生成を廃止
- `target_price` — ResearchReportから引き継ぐだけにする
- `stop_loss` — ResearchReportから引き継ぐだけにする

LLMに出力させるのは `conviction: HIGH | MEDIUM | LOW` のみに絞る。

`decision_agent.py` の `_parse_and_save` にHalf Kelly計算を追加:
```
# conviction → Kelly fraction
conviction_map = {"HIGH": 0.5, "MEDIUM": 0.25, "LOW": 0.1}
kelly_fraction = conviction_map[conviction]
position_size_usd = available_capital * kelly_fraction
shares_suggested = position_size_usd / entry_price
```
デフォルト `available_capital` は `settings` から読む（現行プロンプトの ~$6,700）。

---

### P1-2: CoT構造をプロンプトに追加 ★★★

**対象**: `research_prompts.py`, `decision_prompts.py`  
**根拠**: D1（4ピラー）, D2（CoTが費用対効果最高）

**`research_prompts.py` の変更点**:

1. リサーチプロセスのステップを明示的な推論チェーンに変更:
   ```
   For each candidate, follow this reasoning chain:
   Step 1 — Fundamentals: Cite specific revenue/EPS numbers from get_financials
   Step 2 — Momentum: Cite RSI, MACD values from get_technical_indicators  
   Step 3 — Catalyst: Cite specific upcoming events from get_news / get_web_search
   Step 4 — Sentiment: Call get_x_search for "$TICKER stock sentiment" and cite findings
   Step 5 — Synthesis: Score each factor based on evidence above, then aggregate
   ```

2. Mandatory Evidence Chain制約を追加:
   ```
   CRITICAL: Every score value must cite the specific data point justifying it.
   BAD:  "momentum": 8
   GOOD: "momentum": 8  // RSI=71, volume 2.3x 30-day avg, +18% last 5 days
   ```

**`decision_prompts.py` の変更点**:

```
Decision reasoning chain:
Step 1 — Review each report's evidence chain (are claims backed by data?)
Step 2 — Apply portfolio constraints (sector concentration, max positions)
Step 3 — Assess conviction: does the evidence justify HIGH conviction?
Step 4 — Final recommendation or PASS
```

---

### P1-3: Xセンチメントをリサーチフローに組み込む ★★

**対象**: `research_prompts.py`  
**根拠**: B2（X sentimentは `get_x_search` ツールで既に利用可能）

`research_prompts.py` のステップ3の末尾に1行追加するだけで有効化できる:

現行:
```
3. For each candidate, call: get_stock_snapshot, get_technical_indicators, get_financials,
   get_news, and get_web_search (for analyst sentiment and catalysts)
```

変更後:
```
3. For each candidate, call: get_stock_snapshot, get_technical_indicators, get_financials,
   get_news, get_web_search (for analyst sentiment and catalysts),
   and get_x_search (for retail/institutional X sentiment on the ticker)
```

合わせて `score_breakdown` の `sentiment` 因子の説明を更新し、X検索結果を反映するよう明示する。

---

### P1-4: スコア因子の整合 ★★

**対象**: `research_prompts.py`  
**根拠**: C1（業界標準: momentum / value / quality / sentiment）

現行の `score_breakdown` 因子:
```json
{"momentum": _, "fundamentals": _, "catalyst": _, "technical": _}
```

変更後（X sentimentを独立因子として追加、重み再配分）:
```json
{
  "momentum": _,      // 25%: price action, volume, trend
  "fundamentals": _,  // 20%: revenue growth, profitability
  "catalyst": _,      // 25%: upcoming events, binary outcomes  
  "technical": _,     // 15%: RSI, MACD, support/resistance
  "sentiment": _      // 15%: X/news sentiment, analyst consensus
}
```

`research_agent.py` の `_parse_and_save` は `score_breakdown` をJSON blobとして保存しているため、コード変更不要。

---

### P1-5: ハルシネーション抑制制約の強化 ★★

**対象**: `research_prompts.py`  
**根拠**: C3（LLMに数値生成させない原則）

現行のCRITICAL RULESに追加:
```
- NEVER estimate target_price or stop_loss from memory or reasoning alone.
  Use only values derivable from tool-returned data:
  target_price: entry_price * 1.15 to 1.30 based on catalyst strength
  stop_loss: entry_price * (1 - ATR_pct) where ATR_pct comes from get_technical_indicators
- If technical data is unavailable, omit target_price and stop_loss (set to null)
```

> Note: Phase 2でATR計算を専用ツール化するまでの暫定ルール。

---

## Phase 2 — 中期改善

### P2-1: ATRベースのtarget_price/stop_loss計算ツール

**対象**: `market_tools.py`, `research_agent.py`  
**根拠**: C3（数値はAPIから注入する原則）

`market_tools.py` に `get_atr_targets(ticker, entry_price)` 関数を追加。  
`get_technical_indicators` のATR値から以下を計算して返す:
- `target_price = entry_price + 2.0 * ATR`
- `stop_loss = entry_price - 1.0 * ATR`

`research_prompts.py` のステップ3にこのツール呼び出しを追加。LLMが直接数値を推定する必要がなくなる。

---

### P2-2: Bullish/Bearish Debateレイヤー

**対象**: `decision_agent.py`, `decision_prompts.py`  
**根拠**: A1（TradingAgentsの中核設計）

`DecisionAgent.run()` を2段階呼び出しに変更:

```
Stage 1a: Bullish Analyst
  - 同じリサーチレポートを強気視点で分析
  - 出力: bullish_case (string)

Stage 1b: Bearish Analyst  
  - 同じリサーチレポートを弱気視点で分析
  - 出力: bearish_case (string)

Stage 2: Portfolio Manager
  - bullish_case + bearish_case + 現行ポジション → 最終意思決定
  - 現行の DECISION_SYSTEM_PROMPT に近い役割
```

`DECISION_SYSTEM_PROMPT` を `BULLISH_ANALYST_PROMPT`, `BEARISH_ANALYST_PROMPT`, `PM_DECISION_PROMPT` の3つに分割。

---

### P2-3: ProposalResultモデルとReflectionループ基盤

**対象**: `db/models.py`  
**根拠**: A3（フィードバックループ設計）

新モデル `ProposalResult` を追加:
```python
class ProposalResult(SQLModel, table=True):
    id: Optional[int]
    proposal_id: int  # FK → investment_proposal.id
    ticker: str
    entry_price: float
    exit_price: Optional[float]
    exit_date: Optional[date]
    actual_return_pct: Optional[float]
    outcome: str  # "win" | "loss" | "neutral" | "pending"
    notes: Optional[str]
```

Phase 3でDecisionAgentのプロンプトに過去実績を注入するための基盤。  
この段階ではモデル追加とAPIエンドポイント（実績記録用）のみ実装する。

---

## Phase 3 — 長期アーキテクチャ改善

### P3-1: Reflectionループの完成

**対象**: `decision_agent.py`, `decision_prompts.py`  
**根拠**: A3（X調査でも逐次エラー増幅の緩和策として確認）

`DECISION_USER_TEMPLATE` に過去実績セクションを追加:
```
Past performance (last 10 closed proposals):
{past_results_json}
Win rate: {win_rate:.0%} | Avg win: {avg_win:+.1%} | Avg loss: {avg_loss:+.1%}
```

`decision_agent.py` の `run()` が `ProposalResult` から過去実績を取得してプロンプトに注入する。Half Kelly計算の `p`（勝率）もここから動的に算出する（現行はデフォルト値）。

---

### P3-2: ResearchAgentの並列分析構造

**対象**: `research_agent.py`  
**根拠**: Google Research: 並列+81% / 逐次-70%（A1/A3）

現行の単一ループを、**専門アナリスト並列呼び出し**に変更:

```
[候補ティッカー確定後]
並列実行:
  - Fundamental Analyst (get_financials, get_ticker_details)
  - Technical Analyst  (get_technical_indicators, get_stock_snapshot)
  - Sentiment Analyst  (get_news, get_x_search, get_web_search)
  - Catalyst Analyst   (get_web_search, get_analyst_ratings)
結果を統合してスコアリング
```

`asyncio` または並列Claude呼び出しを検討。最も実装コストが高い変更のため最後に着手する。

---

## 実装優先順位まとめ

```
Phase 1 (即時)
  P1-1 ★★★  ポジションサイジング切り離し    decision_prompts.py, decision_agent.py
  P1-2 ★★★  CoT構造追加                    research_prompts.py, decision_prompts.py
  P1-3 ★★   X sentiment有効化（1行変更）     research_prompts.py
  P1-4 ★★   スコア因子整合                  research_prompts.py
  P1-5 ★★   ハルシネーション抑制制約追加     research_prompts.py

Phase 2 (中期)
  P2-1 ★★   ATRベース価格計算ツール          market_tools.py, research_agent.py
  P2-2 ★★   Bullish/Bearish Debate          decision_agent.py, decision_prompts.py
  P2-3 ★    ProposalResultモデル追加         db/models.py

Phase 3 (長期)
  P3-1 ★    Reflectionループ完成            decision_agent.py
  P3-2 ★    並列リサーチ構造               research_agent.py
```

---

## 着手順序の補足

Phase 1は相互に独立しているため、P1-1〜P1-5を任意の順で実装できる。  
ただし最初に**P1-1（ポジションサイジング）**を完了させることを強く推奨する。  
他の改善でプロンプトが良くなるほど、LLMが大きなポジションを自信を持って推奨するリスクが増大するため。

---

*次のステップ: P1-1から着手、または各タスクをIssueに分解する。*

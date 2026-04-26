# AI投資エージェント — ベストプラクティス リサーチ計画

作成日: 2026-04-04
フェーズ: リサーチ計画（実行前）

---

## 1. リサーチの目的

現行システム（Research Agent → Decision Agent → Monitor Agent の3エージェント構成）を、実際のAI投資エージェント事例とアカデミック/OSS知見に基づいてアップグレードする。
APIキー取得後の実装フェーズに向けて、「何を・どこで・どういう観点で調べるか」を先に確定させる。

---

## 2. 現行システムの課題仮説

リサーチ前に立てる仮説。調査でこれらを検証・更新する。

| # | 課題仮説 | 関連コンポーネント |
|---|---------|-----------------|
| H-1 | スコアリングが単一LLM呼び出しで行われており、バイアスが大きい | ResearchAgent・DecisionAgent |
| H-2 | X/SNSセンチメント信号がない（NewsAPIのみ） | news_tools.py |
| H-3 | ポジションサイジングがLLMの主観に依存している | DecisionAgent |
| H-4 | エージェント間にフィードバックループがない（失敗した提案が次回に活かされない） | 3エージェント全体 |
| H-5 | リサーチのスコープが「モバーズ追跡」に偏っており、見落としが多い | research_prompts.py |
| H-6 | モニタリングがルールベースでなく、売りシグナルの再現性が低い | MonitorAgent |

---

## 3. リサーチクエスチョン（RQ）

### RQ-A: アーキテクチャ
- A1. マルチエージェントLLM投資システムの主流パターンは何か？（ReAct / Reflection / Debate / Ensemble）
- A2. エージェント間の記憶共有（メモリシステム）はどう実装されているか？
- A3. フィードバックループ（提案→実績→次回プロンプト改善）はどう設計されているか？

### RQ-B: シグナル・データ
- B1. LLM投資エージェントが使う主要シグナルの種類と優先順位は？
- B2. X/Twitterセンチメントの有効な取得・フィルタリング方法は？（ノイズ除去）
- B3. オルタナティブデータ（SEC filings, earnings call transcript等）の活用パターンは？
- B4. ファンダメンタルズ vs テクニカル vs センチメントの重み付けに関するベストプラクティスは？

### RQ-C: スコアリング・意思決定
- C1. 投資候補のスコアリングフレームワーク（因子分解・重み・正規化）の設計例は？
- C2. ポジションサイジング（Kelly基準 / 固定比率 / リスクパリティ等）とLLMの組み合わせ方は？
- C3. LLMのハルシネーションを財務数値に対して抑制するプロンプト設計は？

### RQ-D: プロンプトエンジニアリング
- D1. 財務分析に特化したシステムプロンプトの構造（役割定義・出力形式・制約）は？
- D2. Chain-of-Thought / Tree-of-Thought を投資判断に適用した事例は？
- D3. LLMに「数値を生成させない」ための設計パターンは？

### RQ-E: 実運用・リスク
- E1. AI投資エージェントの代表的な失敗事例とその原因は？
- E2. ドローダウン管理・損切りロジックの自動化に関するパターンは？
- E3. バックテスト設計（ルックアヘッドバイアス回避等）のベストプラクティスは？

---

## 4. リサーチ対象・情報源

### 4-A: Webリサーチ（Claude WebSearch使用）

#### 学術・技術論文
| 検索クエリ | 目的 RQ |
|-----------|---------|
| `FinAgent LLM stock trading agent 2024` | A1, B1 |
| `FinGPT financial NLP sentiment trading` | B2, C1 |
| `multi-agent debate investment decision LLM` | A1, A3 |
| `LLM hallucination financial data mitigation` | C3, D3 |
| `RAG retrieval augmented finance earnings SEC` | B3 |
| `Kelly criterion LLM position sizing` | C2 |
| `ReAct agent agentic loop trading` | A1 |

#### OSSリポジトリ（GitHub）
| リポジトリ候補 | 調査観点 |
|--------------|---------|
| `AI4Finance-Foundation/FinGPT` | プロンプト設計、センチメント処理 |
| `AI4Finance-Foundation/FinRL` | 強化学習+LLMハイブリッド設計 |
| `virattt/ai-hedge-fund` | 実装パターン、エージェント分業 |
| `microsoft/autogen` 金融サンプル | マルチエージェント協調パターン |
| `langchain-ai/langchain` 金融チェーン事例 | ツール設計、メモリ管理 |

#### ブログ・事例記事
| 検索クエリ | 目的 RQ |
|-----------|---------|
| `AI hedge fund architecture 2024 2025` | A1, A2 |
| `LLM stock screener best practices` | B1, C1 |
| `Twitter sentiment stock price prediction accuracy` | B2 |
| `earnings call transcript LLM analysis` | B3 |
| `AI investment agent failure case study` | E1 |

---

### 4-B: X（Twitter）リサーチ（X API使用）

#### 検索キーワード（英語）
| キーワード / ハッシュタグ | 目的 RQ | 期待する情報 |
|--------------------------|---------|------------|
| `"AI trading agent" lang:en -is:retweet` | A1 | 実装者の知見・議論 |
| `FinGPT lang:en` | B1, B2 | 開発者コミュニティの議論 |
| `"LLM stock" OR "AI stock picker" lang:en` | C1 | 実際の使い方・結果報告 |
| `"multi-agent" finance trading lang:en` | A1, A3 | アーキテクチャ議論 |
| `"position sizing" LLM lang:en` | C2 | 実践的な実装知見 |
| `#quantfinance #LLM lang:en` | 全般 | コミュニティトレンド |

#### 検索キーワード（日本語）
| キーワード | 目的 RQ | 期待する情報 |
|-----------|---------|------------|
| `AI 投資エージェント 米国株` | 全般 | 国内実践者の知見 |
| `LLM 株 スクリーニング` | B1, C1 | プロンプト設計事例 |
| `ChatGPT 株分析 プロンプト` | D1, D2 | 具体的なプロンプト例 |

#### X検索の制約と方針
- **検索期間**: 直近6ヶ月（2025-10〜2026-04）を優先
- **ノイズ除去**: リツイート除外（`-is:retweet`）、最小エンゲージメント閾値設定
- **取得上限**: 各クエリ最大20件 → 合計200件以内
- **目的**: 「何が話題か」のトレンド把握と、参照先URL収集（詳細はWebリサーチで深掘り）

---

## 5. リサーチの優先順位

**Phase 1（最優先 — システムの骨格に直結）**
1. A1: マルチエージェントアーキテクチャパターン
2. C1: スコアリングフレームワーク設計
3. D1: 財務特化プロンプト設計
4. D3: LLMに数値生成させない設計

**Phase 2（重要 — 信号品質向上）**
5. B2: X/Twitterセンチメント取得・フィルタリング
6. B3: オルタナティブデータ（SEC, earnings call）
7. C2: ポジションサイジング

**Phase 3（中長期 — 運用品質向上）**
8. A3: フィードバックループ設計
9. E1: 失敗事例研究
10. E3: バックテスト設計

---

## 6. 収集情報の整理フォーマット

各ソースから得た知見を以下のフォーマットで記録する（リサーチ実行時に `research_findings.md` へ記述）：

```
### [RQ-X] タイトル

**ソース**: URL or @account
**信頼度**: High / Mid / Low
**要点**:
- 箇条書き3〜5点

**現行システムへの示唆**:
- 具体的にどのファイル・コンポーネントに影響するか
```

---

## 7. リサーチ結果の反映先（実装マッピング）

リサーチ後にどこに何を組み込むかの仮マッピング。調査結果で更新する。

| 改善テーマ | 対象ファイル | 改善の方向性（仮） |
|-----------|------------|-----------------|
| スコアリング多軸化 | `research_prompts.py` | 因子（モメンタム・バリュー・クオリティ・センチメント）を分離してスコア |
| センチメント信号追加 | `news_tools.py`, `clients/` | X APIクライアント追加、ツール定義追加 |
| ポジションサイジング | `decision_prompts.py` | Kelly基準 or リスクバジェット計算をプロンプトに組み込み |
| Reflectionループ | `research_agent.py` | スコア低い候補を再分析する2ndパス追加 |
| フィードバックDB | `db/models.py` | ProposalResult（実績）モデル追加 |
| プロンプト品質向上 | `prompts/` 全体 | CoT構造化、ハルシネーション抑制制約追加 |

---

## 8. リサーチ実行の手順（次のステップ）

1. **Webリサーチ（Phase 1〜3）** — Claude WebSearchで上記クエリを順次実行
2. **OSSコード調査** — GitHub上の主要リポジトリのソースを読む
3. **Xリサーチ** — X APIキーを受け取り次第、上記クエリを実行（取得上限を守る）
4. **findings統合** — `research_findings.md` に整理
5. **実装計画策定** — findingsを踏まえ `implementation_plan.md` を作成（APIキー取得後）

---

*このドキュメントはリサーチ開始前の計画書です。実行後に `research_findings.md` へ知見を記録します。*

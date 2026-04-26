Plan: investor Claude Code Usage 削減（質維持版）
Context
investorプロジェクトは /research → /decision → /monitor の3フェーズ構成。 Claude Codeの消費（トークン＝課金）は主に以下から発生：

/research 分析フェーズ: 15-20銘柄 × 8データ型 の大きなJSONをそのままClaudeに渡す（推定50-100KB）
会話コンテキスト蓄積: /researchの大きな出力が会話に残った状態で /decision を実行するとコンテキストが巨大になる
ディープ研究の銘柄数: 候補数が多いほど収集データが増える
除外した戦略（質が落ちるリスクがあるため）:

❌ ディベートフェーズ統合: Bullish/Bearishの独立性が失われ、アンカリングが起きやすい
❌ プロンプト圧縮: 「冗長に見える」記述がエッジケースで重要な役割を持つ可能性が高い
採用戦略（質への影響ゼロまたは最小）
優先度1: OHLCVバーをClaudeに見せない
問題: collect_market_data() は60日分のOHLCVバーをJSONに含めて出力しているが、Claudeはこれを使わない。RSI/MACD/ATR等の指標はPython側（technical_tools.py）で既に計算済み。生データはノイズになっている。

対策: investor/skills/research.py のstdout出力前に ohlcv_bars フィールドを除去するフィルタを追加。

# skills/research.py — stdout出力前に追加
def strip_raw_ohlcv(data: dict) -> dict:
    for ticker_data in data.get("ticker_data", {}).values():
        ticker_data.pop("ohlcv_bars", None)
    return data
対象ファイル:

investor/skills/research.py — json.dumps() の直前に strip_raw_ohlcv() を呼ぶ
質への影響: なし（Claudeは生バーではなく計算済み指標を使ってスコアリングしている）

期待削減: /research 入力トークン 30-40%削減（OHLCVが全体の大部分を占めるため）

優先度2: コンテキスト分離（/research → 新セッションで /decision）
問題: 同一セッションで /research → /decision を実行すると、研究JSONが会話コンテキストに残ったまま /decision のLLM呼び出しが発生し、コンテキストが二重になる。

対策: .claude/commands/research.md の末尾に明示的な指示を追加：

## 完了後の手順
research.py --save でデータを保存したら、このセッションを終了し、
新しいセッションで /decision を起動してください。
/decision は data/research_history.json からファイル経由でデータを読む設計になっているため、新セッションでも問題なく動作する。

対象ファイル:

.claude/commands/research.md — 末尾に完了後手順を追記
質への影響: なし（Claudeが見るデータは同じ、タイミングが変わるだけ）

期待削減: /decision フェーズの入力トークン 30-40%削減

優先度3: ディープ研究銘柄数を15-20→10に削減
問題: /screen 後にClaudeが15-20候補を選び、それ全てに8種類のデータを収集している。

対策: /screen のコマンドドキュメントで「上位10銘柄に絞る」よう指示を更新。collect_market_data(max_tickers=10) をデフォルトに変更。

/screen で既に150+銘柄の snapshot+technicals でフィルタリングしている
その段階で質の高い候補が絞られているため、10でも十分な多様性がある
対象ファイル:

investor/agents/research_agent.py — collect_market_data(max_tickers=15) → max_tickers=10
.claude/commands/screen.md — 選出候補数の指示を更新
質への影響: 低リスク（/screenで既に高品質な候補が絞られている）

期待削減: 収集データ量 + /research 入力トークン 20-30%削減

実装順序
strip_raw_ohlcv() を skills/research.py に追加（最大インパクト、リスクゼロ）
.claude/commands/research.md に完了後手順を追記
max_tickers=10 をデフォルトに変更
検証方法
実装前後で python skills/research.py 出力のJSON byte数をターミナルで比較
2-3サイクル実施し、Claude Codeの usage 表示（input tokens）を記録
投資判断の候補がまだ十分な多様性を持っているか確認
期待される総削減効果
戦略	対象フェーズ	削減率（入力トークン）	質リスク
OHLCVバー除去	/research	-30~40%	なし
コンテキスト分離	/decision	-30~40%	なし
max_tickers=10	/research	-20~30%	低
全体の推定削減: 現在の使用量の 40-55%削減（質を維持しながら）
# リサーチ2フェーズ化 実装計画

## 背景・課題

| 現状の問題 | 詳細 |
|---|---|
| GROWTH_UNIVERSEが偏っている | AI半導体・クラウド・フィンテック中心の約50銘柄に固定 |
| 1回のリサーチが重い | 15銘柄に対してfull data（financials/news/options/insider）を全取得 |
| セクター横断的な発見ができない | 強いセクターが変化しても自動的に候補が変わらない |

## 目標

- **広く（全11セクター150〜200銘柄）・薄く**スクリーニングしてから
- **狭く（通過銘柄のみ）・深く**リサーチする2段構えへ移行
- トークン使用量削減・実行速度改善・発見の多様化

---

## 新しいデータフロー

```
Phase 1: /screen
  python skills/screen.py
    → 150-200銘柄から snapshot + technicals のみ取得（軽量）
    → stdout に JSON 出力
  Claude: 数値ベースで素早く足切り → 上位10-15銘柄をリスト化

Phase 2: /research --tickers <Phase1通過銘柄>
  python skills/research.py --tickers NVDA,ALAB,...
    → 通過銘柄のみ full data 取得（現状と同じ深さ）
  Claude: 現状と同じ詳細スコアリング → candidates 保存
```

---

## 変更ファイル一覧

### 1. `investor/data/yfinance_client.py`

**GROWTH_UNIVERSE を SCREEN_UNIVERSE（150〜200銘柄）に拡張・リネーム**

```python
SCREEN_UNIVERSE: list[str] = [
    # AI / Semiconductor (現状維持)
    "NVDA", "AMD", "ALAB", "CRDO", "MRVL", "AVGO", "ARM", "QCOM",
    "AAOI", "COHR", "MPWR", "KLAC", "LRCX", "ENTG", "SMCI", "AMAT",
    "MU", "TSM", "ASML", "INTC",

    # Cloud / Enterprise Software (現状維持+追加)
    "MSFT", "AMZN", "GOOGL", "META", "CRM", "NOW", "SNOW", "DDOG",
    "MDB", "NET", "ZS", "CRWD", "PANW", "HUBS", "SHOP", "TTD",
    "GTLB", "VEEV", "WDAY", "ADSK", "ORCL", "SAP", "INTU",

    # Space / Defense / Gov-Tech (現状維持+追加)
    "RKLB", "ASTS", "PLTR", "AXON", "LUNR", "LMT", "RTX", "NOC",
    "GD", "HII", "LDOS", "SAIC",

    # Fintech / Consumer Finance (現状維持+追加)
    "SQ", "HOOD", "SOFI", "AFRM", "COIN", "NU", "V", "MA", "PYPL",
    "FIS", "FISV", "GPN", "WEX",

    # Healthcare / Biotech
    "MRNA", "RXRX", "CERE", "BEAM", "LLY", "NVO", "ABBV", "BMY",
    "REGN", "VRTX", "GILD", "AMGN", "ISRG", "DXCM", "GEHC",

    # Energy / Power Infrastructure
    "VST", "CEG", "GEV", "NEE", "FSLR", "ENPH", "XOM", "CVX",
    "COP", "SLB", "HAL", "OXY",

    # Industrials / Manufacturing
    "CAT", "DE", "EMR", "ETN", "HON", "MMM", "GE", "ITW",
    "PH", "ROK", "AME", "FTV",

    # Consumer Discretionary / Retail
    "TSLA", "UBER", "ABNB", "DASH", "RBLX", "AMZN", "NKE", "LULU",
    "DECK", "RH", "PTON", "W",

    # Financial Services / Banking
    "JPM", "GS", "MS", "BAC", "C", "WFC", "BX", "KKR", "APO",
    "SCHW", "ICE", "CME",

    # Consumer Staples / FMCG
    "COST", "WMT", "PG", "KO", "PEP", "MDLZ", "CL", "CHD",

    # Real Estate / REITs
    "AMT", "PLD", "EQIX", "CCI", "DLR", "SBAC",
]
```

既存の `GROWTH_UNIVERSE` は削除。参照箇所を `SCREEN_UNIVERSE` に置換。

---

### 2. `investor/agents/research_agent.py`

**新関数 `collect_screen_data()` を追加**

```python
def collect_screen_data(
    max_tickers: int = 200,
    parallel: bool = True,
) -> dict:
    """
    Phase 1: 全SCREEN_UNIVERSEを対象にsnapshot+technicalsのみ軽量収集。
    全銘柄に対して並列取得し、結果をそのまま返す。
    """
    # watchlist active tickers も含める
    # snapshot + technicals のみ（financials/news/options/insiderは取らない）
    # 各銘柄のデータ収集関数 collect_screen_ticker_data() を別途定義
```

**新関数 `collect_screen_ticker_data()` を追加**

```python
def collect_screen_ticker_data(ticker: str) -> dict:
    """snapshot + technicals のみ。Phase 1専用の軽量収集。"""
    result: dict = {"ticker": ticker}
    try:
        result["snapshot"] = json.loads(get_stock_snapshot(ticker))
    except Exception as e:
        result["snapshot"] = {"error": str(e)}
    try:
        result["technicals"] = json.loads(get_technical_indicators(ticker))
    except Exception as e:
        result["technicals"] = {"error": str(e)}
    return result
```

既存の `collect_market_data()` は **Phase 2専用**としてそのまま残す。

---

### 3. `investor/investor/prompts/research_prompts.py`

**新しいプロンプト `SCREEN_PROMPT` を追加**

Phase 1用：スナップショットとテクニカルだけで素早く足切りするプロンプト。

```
判定基準（足切り — どれか1つでもアウトなら除外）:
- 出来高が極端に少ない（出来高 < 100万株/日）
- RSIが入手不能かつ価格データもエラー
- 価格が $5 未満（ペニーストック）

優先スコアリング基準（足切り通過後、上位15件に絞る）:
1. モメンタム: 直近の価格変化率（+% 優先）
2. 出来高: 平均比（volume_ratio > 1.5 を優先）
3. テクニカル: RSI 50-75 ゾーン + EMA上方が望ましい
4. セクターRS: sector_rs.top_sectors に属する銘柄を優先

出力: ["TICKER1", "TICKER2", ...] のJSON配列（15銘柄以内）
```

---

### 4. `investor/skills/screen.py` (新規作成)

```
Usage:
  python skills/screen.py              # 全SCREEN_UNIVERSEをスキャン
  python skills/screen.py --max 100    # 最大100銘柄に制限（テスト用）
```

- `collect_screen_data()` を呼ぶ
- stdout に JSON 出力（Claude が読む）
- Phase 1完了後、Claudeが上位銘柄リストを選定
- その後 `python skills/research.py --tickers <list>` を手動or自動で実行

---

### 5. `investor/investor/prompts/research_prompts.py`

既存の `RESEARCH_SYSTEM_PROMPT` の以下を修正：

- Step 0.5 の `Sector-to-ticker mapping` を `SCREEN_UNIVERSE` の新セクター分類に更新
- Step 1 の候補プール説明を「Phase 1通過済みtickers」前提に修正
  （movers/screenerからの候補選別ではなく、すでに絞り込まれた前提）

---

## 実行フロー（新）

```bash
# Phase 1: 広くスキャン（約2-5分、軽量）
cd investor
python skills/screen.py

# → Claude が stdout を読み、上位10-15銘柄を選定・提示

# Phase 2: 選定銘柄を深くリサーチ（現状と同じ深さ）
python skills/research.py --tickers NVDA,ALAB,CRDO,VRT,LLY
```

---

## 期待される改善

| 指標 | 現状 | 改善後 |
|---|---|---|
| スキャン対象銘柄数 | ~50銘柄 | 150〜200銘柄 |
| Phase 1データ量/銘柄 | full（7種） | 2種（snapshot+technicals） |
| Phase 1トークン消費 | (なし) | 小（数値データのみ） |
| Phase 2対象銘柄 | 最大15銘柄（全データ） | 10〜15銘柄（通過のみ・全データ） |
| セクターカバレッジ | AI/クラウド/フィンテック中心 | 全11セクター |
| 取りこぼしリスク | 低（固定ユニバース） | 中（Phase 1の足切り精度に依存）→ 許容 |

---

## 実装順序

1. `yfinance_client.py`: SCREEN_UNIVERSE定義・GROWTH_UNIVERSE置換
2. `research_agent.py`: `collect_screen_ticker_data()` + `collect_screen_data()` 追加
3. `research_prompts.py`: `SCREEN_PROMPT` 追加 + 既存プロンプト修正
4. `skills/screen.py`: 新規作成
5. 動作確認: `python skills/screen.py --max 30` でテスト実行
6. 既存 `/research` スキルの動作確認（Phase 2として変わらず動くか）

---

## 非変更事項

- `skills/research.py` のインターフェース（`--tickers` オプションは既存のまま使える）
- `data/research_history.json` の形式（Phase 2の出力は変わらない）
- `/decision`, `/monitor`, `/portfolio` スキル（影響なし）
- `RESEARCH_SYSTEM_PROMPT` のスコアリングロジック（Phase 2は変わらない）

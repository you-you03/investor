# Investor System Architecture

## 図①: システム全体アーキテクチャ

```mermaid
graph TD
    User(["👤 User / Claude Code Session"])

    subgraph Skills["Skills Layer（エントリポイント）"]
        S1["skills/research.py\n/research"]
        S2["skills/watchlist_research.py\n/watchlist-research"]
        S3["skills/decision.py\n/decision"]
        S4["skills/portfolio.py\n/portfolio"]
        S5["scripts/run_monitor.py\n/monitor (cron 7am)"]
        S6["skills/dashboard.py\n/dashboard"]
        S7["skills/watchlist.py\n/watchlist"]
    end

    subgraph Agents["Agents Layer（データ収集・永続化）"]
        A1["research_agent.py\ncollect_market_data()\ncollect_screen_data()"]
        A2["watchlist_research_agent.py\ncollect_watchlist_research_data()"]
        A3["decision_agent.py\nformat_research_for_claude()\nenrich_proposals()"]
        A4["monitor_agent.py\nMonitorAgent.run()"]
    end

    subgraph DataClients["Data Clients"]
        YF["YFinanceClient\nyfinance_client.py\n─────────────\nget_stock_snapshot()\nget_ohlcv_bars()\nget_financials()\nget_ticker_details()\nget_relative_strength()\nget_market_context()\nget_sector_rs()\nget_52w_breakouts()\nget_earnings_surprises()\nget_options_flow()\nget_insider_activity()\nget_news()"]
        Cache["Cache\nutils/cache.py\n24h TTL\ndata/cache/"]
    end

    subgraph Core["Core Logic"]
        MON["core/monitor.py\ncheck_all_positions()\n─────────────\nSTOP_LOSS\nSHARP_DROP (-5%)\nTARGET_REACHED\nSIGNIFICANT_DRAWDOWN (-8%)"]
    end

    subgraph Ext["External Services"]
        EXT_YF["yfinance\n（無料・APIキー不要）"]
        EXT_SL["Slack Webhook\nBlock Kit通知"]
        EXT_PX["Perplexity API\nWeb検索（任意）"]
        EXT_XA["xAI/Grok API\nX/Twitterセンチメント（任意）"]
    end

    subgraph DataFiles["Data Files（永続化）"]
        DF1["data/portfolio.csv\nopenポジション\nclosedポジション"]
        DF2["data/watchlist.json\nactive / promoted / removed"]
        DF3["data/research_history.json\nリサーチ実行履歴"]
        DF4["data/watchlist_research_history.json\nWLリサーチ履歴"]
        DF5["data/monitor_alerts.json\nアラート累積ログ"]
        DF6["data/monitor_history.json\n日次モニタースナップショット"]
    end

    subgraph Reports["Reports（出力）"]
        R1["reports/research/*.md"]
        R2["reports/decision/*.md"]
        R3["reports/monitor/*.md"]
        R4["reports/dashboard.html"]
    end

    subgraph Notifications["Slack Notifications"]
        N1["投資提案\n(BUY proposals)"]
        N2["日次ポートフォリオ\nサマリー"]
        N3["HIGH アラート\n(個別SELL通知)"]
    end

    User -->|"トリガー"| Skills

    S1 --> A1
    S2 --> A2
    S3 --> A3
    S4 --> DF1
    S5 --> A4
    S6 --> YF
    S7 --> DF2

    A1 -->|"stdout JSON"| User
    A2 -->|"stdout JSON"| User
    A3 -->|"stdout 整形済みレポート"| User

    User -->|"--save 分析結果"| A1
    User -->|"--save アクション判定"| A2
    User -->|"--send BUY提案"| A3

    A1 --> YF
    A2 --> YF
    A4 --> YF

    YF <-->|"読み書き（24h TTL）"| Cache
    YF --> EXT_YF

    A4 --> MON

    A1 --> DF3
    A2 --> DF2
    A2 --> DF4
    A3 --> DF3
    A3 --> DF4
    A4 --> DF5
    A4 --> DF6
    A4 --> MON

    A3 -->|"Block Kit"| EXT_SL
    A4 -->|"Block Kit"| EXT_SL

    EXT_SL --> N1
    EXT_SL --> N2
    EXT_SL --> N3

    A1 --> R1
    A3 --> R2
    S6 --> R4

    S6 --> DF1
    S6 --> DF2
```

---

## 図②: /research フロー

```mermaid
sequenceDiagram
    actor User
    participant Claude as Claude Code Session
    participant Script as skills/research.py
    participant Agent as research_agent.py
    participant YF as YFinanceClient
    participant Cache as Cache (24h TTL)
    participant History as data/research_history.json

    User->>Claude: 「今日の注目銘柄を調べて」
    Claude->>Script: python skills/research.py

    Note over Script,Agent: === Phase 1: マクロ・スクリーナー並列取得 ===

    par マクロコンテキスト
        Agent->>YF: get_market_context()
        YF->>Cache: キャッシュ確認
        YF-->>Agent: SPY/QQQ/VIX/TLT + regime分類\n(NORMAL / ELEVATED_RISK / HIGH_FEAR)
    and セクターRS
        Agent->>YF: get_sector_rs()
        YF-->>Agent: 12セクターETF RSランキング\n(LEADING / NEUTRAL / LAGGING)
    and 52週高値ブレイク
        Agent->>YF: get_52w_breakouts(SCREEN_UNIVERSE)
        Note right of YF: 140+銘柄をスクリーニング
        YF-->>Agent: 52w高値95%以内 + 出来高1.3x以上の銘柄
    and 決算サプライズ
        Agent->>YF: get_earnings_surprises(SCREEN_UNIVERSE)
        YF-->>Agent: EPS予想比+5%以上（直近6ヶ月）の銘柄
    and 市場モーバー
        Agent->>YF: get_market_movers("gainers", limit=20)
        Agent->>YF: get_market_movers("actives", limit=20)
        YF-->>Agent: 当日の上昇率上位 + 出来高上位
    end

    Note over Agent: watchlistのactiveティッカーを先頭にして\n重複排除 → 最大15銘柄を選定

    Note over Script,Agent: === Phase 2: 選定15銘柄のDeep Research（並列） ===

    loop 各ティッカー（並列 max_workers=5）
        par
            Agent->>YF: get_stock_snapshot(ticker)
            Note right of YF: fast_info: price/OHLCV/volume/52w高安値/change_pct
        and
            Agent->>YF: get_technical_indicators(ticker)
            Note right of YF: RSI/MACD/EMA/ATR/Bollinger
        and
            Agent->>YF: get_financials(ticker)
            Note right of YF: 直近4四半期: Revenue/NI/EPS/FCF
        and
            Agent->>YF: get_ticker_details(ticker)
            Note right of YF: sector/forward PE/PEG/売上成長率/アナリスト目標
        and
            Agent->>YF: get_news(ticker, limit=5)
        and
            Agent->>YF: get_options_flow(ticker)
            Note right of YF: P/C比率 → BULLISH/NEUTRAL/BEARISH
        and
            Agent->>YF: get_insider_activity(ticker, 90d)
            Note right of YF: SEC Form4 → NET_BUYER/NET_SELLER
        and
            Agent->>YF: get_atr_targets(ticker, entry_price)
            Note right of YF: ATR×1倍=ストップ, ×2/3倍=ターゲット
        end
        YF->>Cache: 各データをキャッシュ保存
    end

    Agent-->>Script: JSON report (run_id + 全データ)
    Script-->>Claude: stdout に JSON出力

    Note over Claude: === Claudeによる分析・スクリーニング ===
    Note over Claude: マクロレジームを確認\nセクターローテーション把握\n15銘柄を比較してtop 3-5候補を選定\n確信度(HIGH/MEDIUM/LOW)・エントリー価格・\nターゲット・ストップを設定

    Claude->>Script: python skills/research.py --save\n'{"run_id":"...","candidates":[...]}'
    Script->>Agent: save_run(run_id, candidates)
    Agent->>History: 候補リストを追記保存
    History-->>Script: 保存完了
    Script-->>Claude: run_id を stdout に出力
```

---

## 図③: /watchlist-research フロー

```mermaid
sequenceDiagram
    actor User
    participant Claude as Claude Code Session
    participant Script as skills/watchlist_research.py
    participant Agent as watchlist_research_agent.py
    participant YF as YFinanceClient
    participant WL as data/watchlist.json
    participant WRH as data/watchlist_research_history.json

    User->>Claude: 「ウォッチリスト銘柄を調べて」
    Claude->>Script: python skills/watchlist_research.py

    Script->>Agent: collect_watchlist_research_data()
    Agent->>WL: activeステータスの銘柄を読み込み
    WL-->>Agent: active銘柄リスト（例: 10-15銘柄）

    Note over Agent: マクロコンテキスト + セクターRSも並列取得

    loop 各activeティッカー（並列）
        Agent->>YF: collect_ticker_data(ticker)
        Note right of YF: snapshot / technicals / financials\ndetails / news / options_flow\ninsider_activity / ATR targets
        YF-->>Agent: full JSON data
    end

    Agent-->>Script: 全銘柄データ JSON (run_id付き)
    Script-->>Claude: stdout に JSON出力

    Note over Claude: === Claudeによる各銘柄評価 ===
    Note over Claude: 各銘柄に対してアクションを判定:
    Note over Claude: ESCALATE  — 強いエントリーセットアップ\n           /decisionに優先昇格
    Note over Claude: MAINTAIN  — テーゼ継続、監視継続
    Note over Claude: REMOVE    — テーゼ崩壊 or 悪化、削除
    Note over Claude: ADD_NOTE  — スコア・メモ更新のみ

    Claude->>Script: python skills/watchlist_research.py --save\n'{"run_id":"...","results":[{"ticker":"NVDA","action":"ESCALATE","new_score":8.2,"note":"...","flag":"ESCALATE_TO_DECISION"}]}'

    Script->>Agent: save_watchlist_research(run_id, results)

    loop 各結果
        alt ESCALATE
            Agent->>WL: flag="ESCALATE_TO_DECISION" を更新
        else MAINTAIN
            Agent->>WL: スコア・ノートを更新
        else REMOVE
            Agent->>WL: status="removed" に更新
        else ADD_NOTE
            Agent->>WL: ノート・スコアのみ更新
        end
    end

    Agent->>WRH: ランを保存（run_id / date / results）
    WRH-->>Script: 保存完了
    Script-->>Claude: 保存完了通知
```

---

## 図④: /decision フロー

```mermaid
sequenceDiagram
    actor User
    participant Claude as Claude Code Session
    participant Script as skills/decision.py
    participant Agent as decision_agent.py
    participant RH as data/research_history.json
    participant WRH as data/watchlist_research_history.json
    participant Slack as SlackNotifier\n(Block Kit)

    User->>Claude: 「投資判断を出して」
    Claude->>Script: python skills/decision.py

    Script->>Agent: format_research_for_claude(run_id, watchlist_run_id)

    Agent->>RH: 最新の research run を読み込み
    RH-->>Agent: candidates（market scan銘柄）

    Agent->>WRH: 最新の watchlist research run を確認（存在すれば自動マージ）
    WRH-->>Agent: watchlist results

    Note over Agent: マージルール:\n① ESCALATE_TO_DECISION フラグ銘柄を優先\n② market scan と重複する場合はwatchlist版で上書き\n③ 最終的な候補リストを作成

    Agent-->>Script: 整形済み候補レポート
    Script-->>Claude: stdout に出力

    Note over Claude: === Claudeによる3ロール内部ディベート ===

    Note over Claude: [Bullish Analyst]\n各候補のポジティブケースを構築\n・モメンタム・テクニカル・ファンダ強調\n・エントリー根拠・カタリスト整理

    Note over Claude: [Bearish Analyst]\n各候補の反論・リスクを提示\n・マクロ逆風・競合・バリュエーション懸念\n・テクニカル弱点・下落シナリオ

    Note over Claude: [Portfolio Manager]\n全体最適化（最大5ポジション・予算¥1M）\nHIGH確信=20-25%・MEDIUM=15%・LOW=10%\nVaR・相関・セクター分散を考慮\n最終 BUY / PASS を決定

    Claude->>Script: python skills/decision.py --send\n'[{"ticker":"NVDA","action":"BUY","conviction":"HIGH","entry_price":208.27,"target_price":268.00,"stop_loss":202.99,"position_size_usd":1458,"rationale":"..."}]'

    Script->>Agent: enrich_proposals(raw_proposals, candidates)
    Note over Agent: ATRベースのターゲット/ストップを補完\nポジションサイズを確認・調整

    Agent->>Slack: send_proposals(enriched_proposals)
    Slack-->>User: Slack Block Kit通知\n（BUY提案: ticker/確信度/価格/サイズ/根拠）

    Agent->>Script: レポートを reports/decision/decision_{date}.md に保存
```

---

## 図⑤: /monitor フロー

```mermaid
flowchart TD
    START(["⏰ cron 0 7 * * 1-5\nまたは手動実行"])
    LOAD["portfolio.csv を読み込み\nstatus='open' の行を抽出"]
    CHECK_EMPTY{オープン\nポジション\nあり?}
    NO_POS["Slack送信:\n'No open positions'\n（空サマリー）"]
    FETCH["各ポジションのSnapshot取得\n（YFinanceClient並列）\nfast_info: price/change_pct/volume"]

    subgraph RULE_CHECK["ルールベース閾値チェック（core/monitor.py）"]
        R1{"current_price\n<= stop_loss?"}
        R2{"intraday\nchange_pct\n< -5%?"}
        R3{"current_price\n>= target_price?"}
        R4{"unrealized_pnl\n< -8%?"}
        AL1["🔴 HIGH\nSTOP_LOSS\n即時損切検討"]
        AL2["🔴 HIGH\nSHARP_DROP\n急落モニタリング"]
        AL3["🔴 HIGH\nTARGET_REACHED\n利確検討"]
        AL4["🟡 MEDIUM\nSIGNIFICANT_DRAWDOWN\n要注意"]
    end

    SAVE_ALERTS["data/monitor_alerts.json\nに追記（累積ログ）"]
    SAVE_HISTORY["data/monitor_history.json\nに日次スナップショット保存\n（positions + alerts + 日時）"]
    SLACK_SUMMARY["Slack送信:\n📊 Daily Summary\n全ポジション現在値 / 損益 / アラート数"]
    CHECK_HIGH{HIGH\nアラート\nあり?}
    SLACK_HIGH["各HIGHアラートに対して\nSlack個別送信:\n🚨 SELL ALERT\n（ticker/現値/entry/stop/target）"]
    CLAUDE["Claude セッションが\nアラートを読んで commentary\n→ reports/monitor/ に保存"]
    END(["完了"])

    START --> LOAD
    LOAD --> CHECK_EMPTY
    CHECK_EMPTY -->|"なし"| NO_POS
    CHECK_EMPTY -->|"あり"| FETCH
    NO_POS --> END

    FETCH --> R1
    R1 -->|"Yes"| AL1
    R1 -->|"No"| R2
    R2 -->|"Yes"| AL2
    R2 -->|"No"| R3
    R3 -->|"Yes"| AL3
    R3 -->|"No"| R4
    R4 -->|"Yes"| AL4
    R4 -->|"No"| SAVE_HISTORY

    AL1 --> SAVE_ALERTS
    AL2 --> SAVE_ALERTS
    AL3 --> SAVE_ALERTS
    AL4 --> SAVE_ALERTS
    SAVE_ALERTS --> SAVE_HISTORY

    SAVE_HISTORY --> SLACK_SUMMARY
    SLACK_SUMMARY --> CHECK_HIGH
    CHECK_HIGH -->|"あり"| SLACK_HIGH
    CHECK_HIGH -->|"なし"| CLAUDE
    SLACK_HIGH --> CLAUDE
    CLAUDE --> END
```

---

## 図⑥: データファイル 読み書き関係図

```mermaid
graph LR
    subgraph Scripts["スクリプト・スキル"]
        SC1["skills/research.py\n--save"]
        SC2["skills/watchlist_research.py\n--save"]
        SC3["skills/decision.py"]
        SC4["skills/portfolio.py\nadd / close"]
        SC5["skills/portfolio.py\nlist / snapshot"]
        SC6["skills/watchlist.py\nadd / remove / list"]
        SC7["scripts/run_monitor.py"]
        SC8["skills/dashboard.py"]
    end

    subgraph DataLayer["Data Files"]
        D1[("data/portfolio.csv")]
        D2[("data/watchlist.json")]
        D3[("data/research_history.json")]
        D4[("data/watchlist_research_history.json")]
        D5[("data/monitor_alerts.json")]
        D6[("data/monitor_history.json")]
        D7[("data/cache/*.json\n24h TTL")]
    end

    subgraph ReportLayer["Report Files"]
        R1["reports/research/\nresearch_{date}.md"]
        R2["reports/decision/\ndecision_{date}.md"]
        R3["reports/monitor/\nmonitor_{date}.md"]
        R4["reports/dashboard.html"]
    end

    subgraph External["External"]
        EXT["yfinance API"]
    end

    %% portfolio.csv
    SC4 -->|"write (add/close)"| D1
    SC5 -->|"read"| D1
    SC7 -->|"read (open only)"| D1
    SC8 -->|"read (open+closed)"| D1

    %% watchlist.json
    SC6 -->|"write"| D2
    SC2 -->|"write (status/score update)"| D2
    SC8 -->|"read (active+promoted)"| D2

    %% research_history.json
    SC1 -->|"write (append run)"| D3
    SC3 -->|"read (latest run)"| D3

    %% watchlist_research_history.json
    SC2 -->|"write (append run)"| D4
    SC3 -->|"read (latest run, auto-merge)"| D4

    %% monitor files
    SC7 -->|"write (append alerts)"| D5
    SC7 -->|"write (daily record)"| D6

    %% cache
    EXT -->|"fetch"| D7
    D7 -->|"cache hit"| SC1
    D7 -->|"cache hit"| SC2
    D7 -->|"cache hit"| SC7
    D7 -->|"cache hit"| SC8

    %% reports
    SC1 -->|"write"| R1
    SC3 -->|"write"| R2
    SC8 -->|"write"| R4
```

---

## 図⑦: ポジション管理ライフサイクル

```mermaid
stateDiagram-v2
    [*] --> Discovered : 市場スキャン or 手動発見

    Discovered --> Watchlist : /watchlist add --ticker X --reason "..."
    Discovered --> DecisionCandidate : /research で直接候補選定

    state Watchlist {
        [*] --> active
        active --> active : /watchlist-research\n→ MAINTAIN\n（thesis継続）
        active --> active : /watchlist-research\n→ ADD_NOTE\n（スコア/メモ更新）
        active --> escalated : /watchlist-research\n→ ESCALATE\n（強いセットアップ検出）
        active --> removed : /watchlist-research\n→ REMOVE\n（thesis崩壊 or 悪化）
    }

    escalated --> DecisionCandidate : /decision に優先昇格\n（market scan より優先）
    removed --> [*] : ウォッチリストから除外

    state DecisionCandidate {
        [*] --> Debating
        Debating --> BullishCase : Bullish Analyst\n強気根拠を構築
        BullishCase --> BearishCase : Bearish Analyst\nリスク・反論を提示
        BearishCase --> PMDecision : Portfolio Manager\n最終判断
    }

    PMDecision --> Portfolio : BUY決定\n/portfolio add\n確信度でサイズ決定\nHIGH=20-25%/MEDIUM=15%/LOW=10%
    PMDecision --> [*] : PASS\n（見送り）

    state Portfolio {
        [*] --> open
        open --> open : /monitor\n閾値チェック（毎朝7時）\n→ 異常なし
        open --> TargetReached : monitor HIGH\nTARGET_REACHED\n（current >= target）
        open --> StopLossHit : monitor HIGH\nSTOP_LOSS\n（current <= stop）
        open --> SharpDrop : monitor HIGH\nSHARP_DROP\n（日中 -5%以上）
        open --> ManualClose : /portfolio close\n（手動決済）
    }

    state closed {
        TargetReached : ✅ TARGET_REACHED\n利確
        StopLossHit : ❌ STOP_LOSS\n損切
        SharpDrop : ⚠️ SHARP_DROP\n緊急判断
        ManualClose : 📋 手動クローズ\nTIME_EXIT等
    }

    TargetReached --> closed
    StopLossHit --> closed
    SharpDrop --> closed
    ManualClose --> closed

    closed --> [*] : portfolio.csv\nstatus=closed として記録\n確定損益に反映
```

---

## システム設計原則メモ

| 原則 | 詳細 |
|---|---|
| **Claude Code IS the Agent** | Pythonスクリプトは `anthropic` ライブラリを一切使用しない。Claude Codeセッション自体がエージェント |
| **データフロー** | Python → stdout JSON出力 → Claude読み取り・判断 → Python --save/--send で永続化/通知 |
| **キャッシュ** | yfinanceの全呼び出しは `data/cache/` に24h TTLでキャッシュ。同一銘柄の重複取得を防止 |
| **スキルの役割分担** | Pythonは「データ収集・保存・通知」のみ。「スクリーニング・分析・判断」はすべてClaudeが担当 |
| **ポジションサイジング** | HIGH確信=20-25%、MEDIUM=15%、LOW=10%。1銘柄50%以上禁止、最大5ポジション同時保有 |
| **モニタリング** | ルールベース閾値チェック（Python）+ Claudeコメンタリー（Claude Code）の2層構造 |

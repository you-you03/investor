# PM Synthesis Rules — Strategy V2

`quality_momentum_v2_2026-07-25` のライブ判断規約。LLMは候補を比較するが、最終サイズは
`investor/core/risk.py` が決定する。週次利益ノルマ、投票数、キャッシュ稼働率をBUY理由にしない。

## 勝ちの定義

- 12週間ローリングでSPY対比alphaを検証する。
- 最大ドローダウン6%以内、ルール遵守100%を先に守る。
- 条件がない週は `HOLD_CASH` を正解とする。

## Live BUY hard gates

次を上から順に確認し、1つでも不合格ならBUY禁止。

1. `score >= 7.5`
2. `factor_grades.fundamentals` が A/B
3. `factor_grades.catalyst` が A/B
4. `factor_grades.technical` と `sentiment` が D ではない
5. `data_gap_flag` / `data_gap_flags` にCRITICAL未解決がない
6. `momentum_profile.primary_mode != CHASE_MOMENTUM`
7. `momentum_profile.extension_risk != HIGH`
8. `0 < stop_loss < planned_entry < target_price`
9. gap buffer込み reward/risk が1.5以上
10. 既存ポジションにstop/target欠損、未解決STOP_BREACH、25%集中超過がない

HIGH conviction は独立した満期OOS観測が30件に達するまで無効。入力がHIGHでもMEDIUMへ落とす。

## Debate usage

5ペルソナの票数は確率ではない。PMは以下だけを抽出する。

- 最も強い、検証可能なbull case
- 最も強い、検証可能なbear case
- 結論を変える未確認データ
- テーゼを壊す観測可能な条件

全員BUYでもhard gateを上書きしない。少数意見でも具体的な反証なら重く扱う。

## Portfolio constraints

- ライブ資金: `settings.available_capital_usd`
- 最大同時ポジション: 3
- 1銘柄最大: 資金の25%
- 1トレードの基準リスク: 0.75%
- 全ポジションheat上限: 2.0%
- ギャップ/スリッページbuffer: entryの0.25%
- 同一tickerの「株数」上限は使わない
- キャッシュ稼働率目標は使わない

サイズ計算:

```text
buffered_risk_per_share = entry - stop + entry * 0.0025
risk_budget = capital * 0.0075 * conviction_multiplier
shares_by_risk = risk_budget / buffered_risk_per_share
shares_by_notional = capital * 0.25 / entry
shares = min(shares_by_risk, shares_by_notional)
```

`conviction_multiplier`: MEDIUM=0.75、LOW=0.5。ライブHIGHは現在無効。
fractional share対応は設定値に従う。LLMが出した `position_size_usd` / `shares_suggested` は参考値として
保存するが、実行値には使わない。

## Output

```json
[
  {
    "ticker": "NVDA",
    "action": "BUY",
    "conviction": "MEDIUM",
    "signal_type": "earnings_beat",
    "entry_price_range": "860-880",
    "target_price": 1000,
    "stop_loss": 820,
    "research_score": 8.1,
    "factor_grades": {
      "momentum": "B",
      "fundamentals": "A",
      "catalyst": "B",
      "technical": "B",
      "sentiment": "C"
    },
    "momentum_profile": {
      "primary_mode": "EARLY_MOMENTUM",
      "extension_risk": "LOW"
    },
    "data_gap_flags": [],
    "rationale": "検証可能な根拠と最大の反証を記載",
    "key_catalysts": [],
    "risk_factors": [],
    "time_horizon": "3-12 weeks"
  }
]
```

`skills/decision.py --send` がrisk sizeを付与し、hard gateを再検証する。違反時は送信しない。

No-trade:

```json
{"no_trade_week": true, "reason": "hard gateを通る候補なし", "action": "HOLD_CASH"}
```

## Repeating ticker

過去runに3回以上出たtickerは、現在のupside、entry zoneとの位置、前回から変化した事実を明示する。
「再登場した」こと自体は根拠にしない。

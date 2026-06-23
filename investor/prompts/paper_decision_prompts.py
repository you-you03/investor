"""
Paper Decision Prompts — B枠仮説ごとのPMルールオーバーライド定義。

## 使い方

`active: True` にするだけで /decision 実行時に自動的にB枠が並走する。
仮説が終わったら `active: False` にする（履歴として残す）。

## 設計原則

- A枠との差分だけを `pm_rule_overrides` に書く。共通ルールは繰り返さない。
- 仮説1つにつきB枠1回のPM再合成。ペルソナdebate（Round 1/2）は共有する（効率化のため）。
- `note_prefix` は paper_portfolio.csv の note フィールドに付与される。
"""

PAPER_HYPOTHESES: dict[str, dict] = {
    # ------------------------------------------------------------------
    # H-3: Small capital satellite portfolio
    # 検証: 20万円規模・同一銘柄2株上限・高キャッシュ稼働の別軸運用は、
    # A枠の集中/分散ルールより機会損失を減らしつつ期待値を維持できるか
    # A枠: 100万円予算、最大5銘柄、1銘柄25%上限、Kelly + VIX乗数
    # B枠: 20万円予算、同一銘柄2株上限、品質ゲート通過銘柄で高稼働
    # 判定期間: 2026-06-20 〜 2026-09-20
    # ------------------------------------------------------------------
    "H-3": {
        "active": False,
        "description": "Small Capital Satellite — 正式な20万円デフォルトポートフォリオへ昇格済み",
        "pm_rule_overrides": """\
## B枠 H-3 PMルール上書き（Small Capital Satellite）

**状態:**
この仮説は正式な20万円デフォルトポートフォリオへ昇格したため、B枠では実行しない。
20万円枠のルールは `.claude/skills/decision/reference/pm-synthesis.md` と `investor/config.py` を参照する。

**資産制約:**
- 総予算: 200,000円（A枠の為替前提 ¥1,000,000 ≒ $6,700 に合わせ、概算 $1,340）
- `position_size_usd` は B枠全体の残り予算を超えてはならない
- 同一銘柄の同時保有は最大2株。既存B枠保有 + 新規提案後で2株を超える場合はBUY禁止
- 1銘柄への集中上限は「2株」かつ「B枠予算の50%」の小さい方を目安にする。ただし高単価銘柄で1株が50%を超える場合は、A枠品質ゲートをすべて満たし、リスクリワードが2.0以上なら1株だけ許可

**採用品質ゲート（A枠より緩めない）:**
- A枠の catalyst_quality gate / score gate / sector LAGGING block / timeframe alignment / RSI gate はすべて維持
- `catalyst_quality == WEAK`、score < 7.0、stop_loss未設定、data_gap_flagがCRITICALの場合はBUY禁止
- MEDIUM採用は score ≥ 7.5、または score 7.0–7.4 + STRONG catalyst の場合のみ
- 不安の残る銘柄でキャッシュを埋めることは禁止。基準未達ならHOLD_CASHを明示する

**キャッシュ稼働ルール:**
- 採用品質ゲートを満たす候補がある場合、目標キャッシュ稼働率は85%以上
- ただし、基準を満たす候補がない場合はHOLD_CASHを優先し、稼働率目標は適用しない
- 稼働率85%未満で終える場合、rationale に「なぜ現金を残すか」を明記する

**銘柄選択の優先順位:**
1. A枠でBUYになった銘柄のうち、2株上限・予算制約内で買えるもの
2. A枠でWAITだが、H-3制約では1株/2株の小口でリスクが許容でき、全品質ゲートを満たすもの
3. 高単価で1株しか買えない銘柄は、同じ期待値なら低単価で分散できる候補を優先

**B枠proposal出力ルール:**
- BUY proposal には必ず `note` に `[H-3]` を含める
- `position_size_usd` は実際に使う金額（概算 $1,340 以内）を明示する
- `shares_suggested` は整数株で、同一ticker合計2株以下にする
- `rationale` には「H-3: 20万円枠 / 稼働率 / 2株上限 / 現金を残す理由」を含める

**記録の目的:**
小口・高稼働の別軸ポートフォリオが、A枠の分散モメンタム運用に対して
機会損失を減らしつつ、ルール遵守後のリターン/ドローダウンで優位かを比較する。
結果は `python skills/paper_portfolio.py compare` と hypothesis_id=H-3 の個別集計で確認する。
""",
        "note_prefix": "[H-3]",
    },

    # ------------------------------------------------------------------
    # H-2: RSI WAIT strict variant
    # 検証: RSI 70-84 × SECTOR_LEADING 縮小エントリーは常時WAITより優れるか
    # A枠: SECTOR_LEADING特例あり（縮小エントリー可）
    # B枠: 特例なし（RSI≥70は常時WAIT）
    # 判定期間: 2026-05-10 〜 2026-07-10
    # ------------------------------------------------------------------
    "H-2": {
        "active": True,
        "description": "RSI WAIT strict — RSI≥70で常時WAIT（SECTOR_LEADING特例なし）",
        "pm_rule_overrides": """\
## B枠 H-2 PMルール上書き（A枠との差分のみ）

**OVERRIDE — RSI過熱エントリーゲート（H-2 strict mode）:**
- RSI ≥ 85 → WAIT無条件（A枠と同じ）
- RSI 70–84 かつ 52W高値3%以内 → WAIT無条件（A枠と同じ）
- RSI 70–84 かつ 52W高値3%超 → **WAIT無条件。SECTOR_LEADING特例を適用しない。**
  （A枠では縮小エントリー可だが、B枠ではWAITとして記録する）

他のルール（確信度フロア・Kellyサイジング・レジーム乗数・スコア優先枠）はA枠と同一。

**記録の目的:**
A枠でSECTOR_LEADING特例を使ってエントリーした銘柄が、B枠（WAIT）と比べて
期待値が高いかを8週後に比較する。結果は `python skills/paper_portfolio.py compare` で確認。
""",
        "note_prefix": "[H-2]",
    },

    # ------------------------------------------------------------------
    # H-1: signal_type別優位性 → B枠不要（A枠データで測定可能）
    # 代わりに measurement_only フラグで管理する
    # ------------------------------------------------------------------
    "H-1": {
        "active": False,
        "description": "Watchlist ESCALATE vs market-scan 勝率比較（B枠不要・A枠データで測定）",
        "measurement_only": True,
        "pm_rule_overrides": "",
        "note_prefix": "[H-1]",
    },
}


def get_active_hypotheses() -> list[dict]:
    """B枠並走が必要なアクティブ仮説を返す（measurement_onlyは除外）。"""
    return [
        {"id": hid, **hdef}
        for hid, hdef in PAPER_HYPOTHESES.items()
        if hdef.get("active") and not hdef.get("measurement_only")
    ]


def format_active_hypotheses_for_claude() -> str:
    """decision.md Step 10 でClaudeが読む仮説一覧テキストを生成する。"""
    active = get_active_hypotheses()
    if not active:
        return "アクティブ仮説なし — B枠スキップ"

    lines = [
        "## アクティブB枠仮説一覧",
        "",
        f"以下の {len(active)} 件の仮説について、A枠ディベートのRound 1/2ログを使い、",
        "PMルールだけ差し替えてB枠合成を実行し、paper_portfolio.csv に記録すること。",
        "",
    ]
    for h in active:
        lines += [
            f"### {h['id']}: {h['description']}",
            "",
            h["pm_rule_overrides"].strip(),
            "",
            f"note_prefix: `{h['note_prefix']}`",
            "",
            "---",
            "",
        ]
    return "\n".join(lines)

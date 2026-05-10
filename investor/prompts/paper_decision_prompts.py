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

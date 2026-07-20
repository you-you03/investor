#!/usr/bin/env python3
"""
Create the Metabase dashboard for score reliability monitoring.

Required env:
  METABASE_URL                         e.g. http://localhost:3000
  METABASE_API_KEY                     preferred

Alternative auth env:
  METABASE_USER
  METABASE_PASSWORD

Optional env:
  METABASE_DB_ID                       use this database id directly
  METABASE_DB_NAME                     default: investor-score-validation
  METABASE_COLLECTION_ID               collection id for created cards/dashboard

Usage:
  METABASE_URL=http://localhost:3000 \
  METABASE_USER='you@example.com' \
  METABASE_PASSWORD='...' \
  METABASE_DB_NAME='investor-score-validation' \
  .venv/bin/python scripts/setup_metabase_score_dashboard.py
"""

from __future__ import annotations

import os
import sys
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


DEFAULT_DB_NAME = "investor-score-validation"
DASHBOARD_NAME = "スコア信頼性モニター"
SNAPSHOTS_PATH = Path(__file__).parent.parent / "data" / "score_snapshots.json"


@dataclass(frozen=True)
class CardSpec:
    name: str
    query: str
    display: str
    row: int
    col: int
    size_x: int
    size_y: int
    description: str = ""
    visualization_settings: dict[str, Any] | None = None


CARD_SPECS = [
    CardSpec(
        name="01. 総合結論: このスコアは使えるか",
        query="""
with h as (
  select *
  from bi_score_health_latest
),
judged as (
  select
    snapshot_count,
    week4_ic,
    week8_ic,
    week4_threshold_spread,
    week8_threshold_spread,
    case
      when week4_ic >= 0.20 and week4_threshold_spread > 0 then '使える: 4週目線の候補選別に有効'
      when week8_ic >= 0.20 and week8_threshold_spread > 0 then '条件付きで使える: 長めの保有期間では有効'
      when week4_threshold_spread > 0 then '足切りには使える: ランキング精度は弱い'
      else '要見直し: スコア閾値または配点の再検証が必要'
    end as overall_judgement
  from h
)
select *
from (
  select
    1 as "重要度",
    '総合判定' as "見るもの",
    overall_judgement as "現在の結論",
    '最初にここを見る。使える/条件付き/要見直しを判断する。' as "見方"
  from judged
  union all
  select
    2,
    '検証データ数',
    snapshot_count::text || ' 件',
    '30件未満のホライゾンは判断保留。全体件数が増えるほど信頼度が上がる。'
  from judged
  union all
  select
    3,
    '4週後IC',
    coalesce(round(week4_ic::numeric, 2)::text, 'N/A'),
    '0.20以上なら候補ランキングとして使える。0.40以上なら強い。'
  from judged
  union all
  select
    4,
    '8週後IC',
    coalesce(round(week8_ic::numeric, 2)::text, 'N/A'),
    '長めの保有でスコアが効くかを見る。サンプル数が少ない時は保留。'
  from judged
  union all
  select
    5,
    '4週後 7.0閾値差',
    coalesce(round(week4_threshold_spread::numeric, 1)::text || '%', 'N/A'),
    'score>=7.0 が score<7.0 をどれだけ上回ったか。プラスなら足切りが有効。'
  from judged
) rows
order by "重要度"
""".strip(),
        display="table",
        row=0,
        col=0,
        size_x=24,
        size_y=7,
        description="初見の人が最初に見るカード。スコア全体を運用に使えるかを判定する。",
    ),
    CardSpec(
        name="02. 何週後にスコアが効いているか",
        query="""
select
  horizon_weeks as "週",
  horizon as "ホライゾン",
  sample_count as "サンプル数",
  round(spearman_rho::numeric, 2) as "IC",
  round(p_value::numeric, 4) as "p値",
  case
    when sample_count < 30 then '判断保留: N<30'
    when spearman_rho >= 0.40 then '強い: 主要判断に使える'
    when spearman_rho >= 0.20 then '使える: ただし過信しない'
    when spearman_rho >= 0.05 then '弱い: 補助材料'
    else '効いていない'
  end as "判定",
  case
    when sample_count < 30 then 'データ蓄積を待つ'
    when spearman_rho >= 0.20 then 'この保有期間ではスコアを候補順位付けに使う'
    else 'この保有期間ではスコア単独判断を避ける'
  end as "運用アクション"
from bi_horizon_reliability
where validation_date = (select max(validation_date) from bi_horizon_reliability)
order by horizon_weeks
""".strip(),
        display="table",
        row=7,
        col=0,
        size_x=12,
        size_y=8,
        description="スコアが短期・中期・長期のどこで効くかを見る。",
    ),
    CardSpec(
        name="03. IC推移: 信頼性は改善しているか",
        query="""
select validation_date, horizon, horizon_weeks, sample_count, spearman_rho
from bi_horizon_reliability
where sample_count >= 30
order by validation_date, horizon_weeks
""".strip(),
        display="line",
        row=7,
        col=12,
        size_x=12,
        size_y=8,
        description="検証日ごとのIC推移。右肩上がりならスコア設計が改善している。",
        visualization_settings={
            "graph.dimensions": ["validation_date"],
            "graph.metrics": ["spearman_rho"],
            "graph.series_order": ["week1", "week2", "week3", "week4", "week5", "week6", "week7", "week8"],
        },
    ),
    CardSpec(
        name="04. 7.0閾値は有効か",
        query="""
select
  horizon_weeks as "週",
  horizon as "ホライゾン",
  round(passed_avg_return_pct::numeric, 1) as "score>=7.0 平均リターン%",
  round(rejected_avg_return_pct::numeric, 1) as "score<7.0 平均リターン%",
  round(spread_return_pct::numeric, 1) as "差分%",
  case
    when spread_return_pct > 10 then '強く有効: 閾値維持'
    when spread_return_pct > 0 then '有効: 閾値維持'
    when spread_return_pct = 0 then '中立: 継続監視'
    else '無効: 閾値見直し候補'
  end as "判定",
  'プラスなら score>=7.0 の足切りが機能している' as "見方"
from bi_threshold_performance
where validation_date = (select max(validation_date) from bi_threshold_performance)
order by horizon_weeks
""".strip(),
        display="table",
        row=15,
        col=0,
        size_x=12,
        size_y=8,
        description="score>=7.0 の足切りが本当に機能しているかを見る。",
    ),
    CardSpec(
        name="05. 閾値差分グラフ",
        query="""
select validation_date, horizon, horizon_weeks, spread_return_pct
from bi_threshold_performance
where validation_date = (select max(validation_date) from bi_threshold_performance)
order by horizon_weeks
""".strip(),
        display="bar",
        row=15,
        col=12,
        size_x=12,
        size_y=8,
        description="score>=7.0 と score<7.0 の平均リターン差。大きいほど閾値が効いている。",
        visualization_settings={
            "graph.dimensions": ["horizon_weeks"],
            "graph.metrics": ["spread_return_pct"],
        },
    ),
    CardSpec(
        name="06. どの採点項目が効いているか",
        query="""
select
  case factor
    when 'momentum' then 'モメンタム'
    when 'fundamentals' then 'ファンダメンタルズ'
    when 'catalyst' then 'カタリスト'
    when 'technical' then 'テクニカル'
    when 'sentiment' then 'センチメント'
    else factor
  end as "ファクター",
  horizon_weeks as "週",
  sample_count as "サンプル数",
  round(spearman_rho::numeric, 2) as "IC",
  case
    when sample_count < 30 then '判断保留'
    when spearman_rho >= 0.30 then '強い: 配点引き上げ候補'
    when spearman_rho >= 0.15 then '有効: 配点維持'
    when spearman_rho > 0 then '弱い: 補助扱い'
    else '弱い/逆効果: 配点引き下げ候補'
  end as "判定",
  case
    when factor = 'fundamentals' and spearman_rho >= 0.20 then 'BUY根拠として重視'
    when factor in ('technical', 'catalyst') and spearman_rho < 0.10 then '単独の買い理由にしない'
    when factor = 'sentiment' and spearman_rho >= 0.15 then '補助材料として使う'
    else '継続監視'
  end as "運用アクション"
from bi_factor_reliability
where validation_date = (select max(validation_date) from bi_factor_reliability)
order by
  case factor
    when 'fundamentals' then 1
    when 'momentum' then 2
    when 'sentiment' then 3
    when 'catalyst' then 4
    when 'technical' then 5
    else 9
  end,
  horizon_weeks
""".strip(),
        display="table",
        row=23,
        col=0,
        size_x=24,
        size_y=9,
        description="配点を変える根拠。ファンダが効くか、カタリスト/テクニカルが弱いかを見る。",
    ),
    CardSpec(
        name="07. データ成熟度: 判断してよい件数か",
        query="""
select
  horizon_weeks as "週",
  horizon as "ホライゾン",
  total_observations as "全観測数",
  matured_count as "満期到達数",
  fetched_count as "取得済み数",
  fetched_pct as "取得率%",
  case
    when fetched_count >= 50 then '十分'
    when fetched_count >= 30 then '最低限OK'
    else '判断保留'
  end as "判定"
from bi_data_maturity
order by horizon_weeks
""".strip(),
        display="table",
        row=32,
        col=0,
        size_x=24,
        size_y=7,
        description="ICを見る前に、サンプル数が十分か確認する。",
    ),
    CardSpec(
        name="08. ホライゾンとリターンの散布図",
        query="""
with observations as (
  select
    1 as horizon_weeks,
    (week1->>'return_pct')::numeric as return_pct
  from score_snapshots
  union all
  select
    2 as horizon_weeks,
    (week2->>'return_pct')::numeric as return_pct
  from score_snapshots
  union all
  select
    3 as horizon_weeks,
    (week3->>'return_pct')::numeric as return_pct
  from score_snapshots
  union all
  select
    4 as horizon_weeks,
    (week4->>'return_pct')::numeric as return_pct
  from score_snapshots
  union all
  select
    5 as horizon_weeks,
    (week5->>'return_pct')::numeric as return_pct
  from score_snapshots
  union all
  select
    6 as horizon_weeks,
    (week6->>'return_pct')::numeric as return_pct
  from score_snapshots
  union all
  select
    7 as horizon_weeks,
    (week7->>'return_pct')::numeric as return_pct
  from score_snapshots
  union all
  select
    8 as horizon_weeks,
    (week8->>'return_pct')::numeric as return_pct
  from score_snapshots
)
select
  horizon_weeks as "ホライゾン週",
  round(return_pct, 2) as "リターン%"
from observations
where return_pct is not null
  and abs(return_pct) <= 100
order by "ホライゾン週", "リターン%"
""".strip(),
        display="boxplot",
        row=39,
        col=0,
        size_x=12,
        size_y=8,
        description="保有週数ごとにリターンがどう分布するかを見る。短期で荒く、中期で収束するかの確認用。",
    ),
    CardSpec(
        name="09. スコアとリターンの散布図",
        query="""
select
  round(score::numeric, 2) as "Score",
  round((week4->>'return_pct')::numeric, 2) as "4週後リターン%"
from score_snapshots
where score is not null
  and score > 6
  and (week4->>'return_pct') is not null
  and abs((week4->>'return_pct')::numeric) <= 100
order by "Score", "4週後リターン%"
""".strip(),
        display="scatter",
        row=39,
        col=12,
        size_x=12,
        size_y=8,
        description="高スコアほど実リターンが伸びているかを見る。右上に点群が寄るほど望ましい。",
    ),
]


class MetabaseClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=30.0)

    def authenticate(self) -> None:
        api_key = os.getenv("METABASE_API_KEY")
        if api_key:
            self.client.headers["x-api-key"] = api_key
            return

        user = os.getenv("METABASE_USER")
        password = os.getenv("METABASE_PASSWORD")
        if not user or not password:
            raise RuntimeError("Set METABASE_API_KEY or METABASE_USER/METABASE_PASSWORD.")

        response = self.client.post("/api/session", json={"username": user, "password": password})
        if response.status_code == 401:
            raise RuntimeError(
                "Metabase login failed with 401 Unauthorized. "
                "Use your Metabase login email/password, not the Supabase database password. "
                "Alternatively create a Metabase API key and set METABASE_API_KEY."
            )
        response.raise_for_status()
        session_id = response.json()["id"]
        self.client.headers["X-Metabase-Session"] = session_id

    def get(self, path: str) -> Any:
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def put(self, path: str, payload: dict[str, Any]) -> Any:
        response = self.client.put(path, json=payload)
        response.raise_for_status()
        return response.json()


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    return []


def _collection_id() -> int | None:
    raw = os.getenv("METABASE_COLLECTION_ID")
    return int(raw) if raw else None


def _load_score_snapshots() -> list[dict[str, Any]]:
    if not SNAPSHOTS_PATH.exists():
        return []
    try:
        payload = json.loads(SNAPSHOTS_PATH.read_text())
    except Exception:
        return []
    return payload.get("snapshots", [])


def _score_return_avg_goal_value() -> float | None:
    returns: list[float] = []
    for snapshot in _load_score_snapshots():
        score = snapshot.get("score")
        week4 = snapshot.get("week4") or {}
        ret = week4.get("return_pct")
        try:
            score_val = float(score)
            ret_val = float(ret)
        except (TypeError, ValueError):
            continue
        if score_val <= 6 or abs(ret_val) > 100:
            continue
        returns.append(ret_val)
    if not returns:
        return None
    return round(sum(returns) / len(returns), 2)


def _resolved_visualization_settings(spec: CardSpec) -> dict[str, Any]:
    settings = dict(spec.visualization_settings or {})
    if spec.name == "09. スコアとリターンの散布図":
        goal_value = _score_return_avg_goal_value()
        if goal_value is not None:
            settings.update(
                {
                    "graph.show_goal": True,
                    "graph.goal_value": goal_value,
                    "graph.goal_label": f"平均 {goal_value:+.2f}%",
                }
            )
    return settings


def find_database_id(mb: MetabaseClient) -> int:
    raw_db_id = os.getenv("METABASE_DB_ID")
    if raw_db_id:
        return int(raw_db_id)

    target_name = os.getenv("METABASE_DB_NAME", DEFAULT_DB_NAME)
    databases = mb.get("/api/database")
    data = databases.get("data", databases if isinstance(databases, list) else [])
    for database in data:
        if database.get("name") == target_name:
            return int(database["id"])
    names = ", ".join(sorted(str(item.get("name")) for item in data if item.get("name")))
    raise RuntimeError(
        f"Metabase database named {target_name!r} was not found. "
        f"Set METABASE_DB_ID or create/connect the database first. Available: {names}"
    )


def _card_payload(db_id: int, spec: CardSpec) -> dict[str, Any]:
    visualization_settings = _resolved_visualization_settings(spec)
    payload: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
        "display": spec.display,
        "dataset_query": {
            "type": "native",
            "database": db_id,
            "native": {"query": spec.query},
        },
        "visualization_settings": visualization_settings,
    }
    collection_id = _collection_id()
    if collection_id is not None:
        payload["collection_id"] = collection_id
    return payload


def _dashboard_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": DASHBOARD_NAME,
        "description": "スコアの信頼性、閾値の有効性、ファクター別予測力、データ成熟度を重要度順に確認するダッシュボード。",
    }
    collection_id = _collection_id()
    if collection_id is not None:
        payload["collection_id"] = collection_id
    return payload


def find_card_by_name(mb: MetabaseClient, name: str) -> dict[str, Any] | None:
    for card in _as_list(mb.get("/api/card")):
        if card.get("name") == name:
            return card
    return None


def upsert_card(mb: MetabaseClient, db_id: int, spec: CardSpec) -> tuple[dict[str, Any], str]:
    existing = find_card_by_name(mb, spec.name)
    payload = _card_payload(db_id, spec)
    if existing:
        card = mb.put(f"/api/card/{existing['id']}", payload)
        return card, "updated"
    card = mb.post("/api/card", payload)
    return card, "created"


def find_dashboard_by_name(mb: MetabaseClient, name: str) -> dict[str, Any] | None:
    for dashboard in _as_list(mb.get("/api/dashboard")):
        if dashboard.get("name") == name:
            return dashboard
    return None


def upsert_dashboard(mb: MetabaseClient) -> tuple[dict[str, Any], str]:
    existing = find_dashboard_by_name(mb, DASHBOARD_NAME)
    payload = _dashboard_payload()
    if existing:
        dashboard = mb.put(f"/api/dashboard/{existing['id']}", payload)
        return dashboard, "updated"
    dashboard = mb.post("/api/dashboard", payload)
    return dashboard, "created"


def sync_dashboard_cards(mb: MetabaseClient, dashboard_id: int, cards: list[tuple[dict[str, Any], CardSpec]]) -> None:
    dashboard = mb.get(f"/api/dashboard/{dashboard_id}")
    existing_dashcards = dashboard.get("dashcards", []) or []
    by_card_id = {dashcard.get("card_id"): dashcard for dashcard in existing_dashcards if dashcard.get("card_id")}
    synced_dashcards: list[dict[str, Any]] = []

    for card, spec in cards:
        existing = by_card_id.get(card["id"])
        if existing:
            synced_dashcards.append(
                {
                    "id": existing["id"],
                    "card_id": card["id"],
                    "row": spec.row,
                    "col": spec.col,
                    "size_x": spec.size_x,
                    "size_y": spec.size_y,
                    "parameter_mappings": existing.get("parameter_mappings", []),
                    "visualization_settings": _resolved_visualization_settings(spec),
                }
            )
        else:
            synced_dashcards.append(
                {
                    "id": -len(synced_dashcards) - 1,
                    "card_id": card["id"],
                    "row": spec.row,
                    "col": spec.col,
                    "size_x": spec.size_x,
                    "size_y": spec.size_y,
                    "parameter_mappings": [],
                    "visualization_settings": _resolved_visualization_settings(spec),
                }
            )

    mb.put(f"/api/dashboard/{dashboard_id}/cards", {"cards": synced_dashcards})


def main() -> int:
    base_url = os.getenv("METABASE_URL")
    if not base_url:
        print("ERROR: METABASE_URL is required.", file=sys.stderr)
        return 2

    mb = MetabaseClient(base_url)
    mb.authenticate()
    db_id = find_database_id(mb)
    print(f"Using Metabase database id: {db_id}")

    cards = []
    for spec in CARD_SPECS:
        card, status = upsert_card(mb, db_id, spec)
        cards.append((card, spec))
        print(f"{status.title()} card: {spec.name} (id={card['id']})")

    dashboard, status = upsert_dashboard(mb)
    dashboard_id = int(dashboard["id"])
    print(f"{status.title()} dashboard: {DASHBOARD_NAME} (id={dashboard_id})")

    sync_dashboard_cards(mb, dashboard_id, cards)
    print(f"Synchronized dashboard cards: {len(cards)}")

    print(f"\nDone: {base_url.rstrip('/')}/dashboard/{dashboard_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

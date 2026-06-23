"""Best-effort local-file to Supabase synchronization helpers."""

from __future__ import annotations

from collections.abc import Callable

from investor.supabase_store import get_store
from investor.utils.logger import get_logger

logger = get_logger(__name__)

SyncName = str


def sync_local_to_supabase(*names: SyncName) -> dict[str, int | tuple[int, ...]]:
    """Run selected backfill syncs after local JSON/CSV files are saved.

    This is intentionally best-effort: local persistence is the source of
    truth for command completion, and Supabase sync failures should not corrupt
    or roll back a completed local save.
    """
    if not names:
        return {}

    try:
        from scripts import backfill_supabase
    except Exception as exc:
        logger.warning("Supabase sync unavailable: %s", exc)
        return {}

    store = get_store()
    if not store:
        return {}

    syncers: dict[SyncName, Callable] = {
        "positions": backfill_supabase.backfill_positions,
        "watchlist": backfill_supabase.backfill_watchlist,
        "research": backfill_supabase.backfill_research,
        "decisions": backfill_supabase.backfill_decisions,
        "score_snapshots": backfill_supabase.backfill_score_snapshots,
        "trade_journal": backfill_supabase.backfill_trade_journal,
        "market_news": backfill_supabase.backfill_market_news,
        "daily_lite": backfill_supabase.backfill_daily_lite,
        "watchlist_research": backfill_supabase.backfill_watchlist_research,
        "report_artifacts": backfill_supabase.backfill_report_artifacts,
        "workflow_tasks": backfill_supabase.backfill_workflow_tasks,
        "position_events": backfill_supabase.backfill_position_events,
        "lineage": backfill_supabase.backfill_lineage,
    }

    results: dict[str, int | tuple[int, ...]] = {}
    for name in names:
        syncer = syncers.get(name)
        if syncer is None:
            logger.warning("Unknown Supabase sync target: %s", name)
            continue
        try:
            results[name] = syncer(store)
        except Exception as exc:
            logger.warning("Supabase sync skipped for %s: %s", name, exc)
    return results


def sync_all_local_to_supabase() -> dict[str, int | tuple[int, ...]]:
    """Sync all local file-backed datasets that have Supabase backfills."""
    return sync_local_to_supabase(
        "positions",
        "watchlist",
        "research",
        "decisions",
        "score_snapshots",
        "trade_journal",
        "market_news",
        "daily_lite",
        "watchlist_research",
        "report_artifacts",
        "workflow_tasks",
        "position_events",
        "lineage",
    )

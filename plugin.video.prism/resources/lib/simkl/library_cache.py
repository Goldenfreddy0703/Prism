"""Otaku-style watchlist cache: Simkl API membership + local DB metadata."""
from __future__ import annotations

import time

from resources.lib.indexers.simkl import SimklAPI
from resources.lib.modules.meta_enrichment_queue import MetaEnrichmentQueue, meta_enrichment_background

ACTIVITY_CHECK_SECONDS = 120
CACHE_HOURS_FALLBACK = 24

_CATALOG_ACTIVITY_SECTION = {
    "movie": "movies",
    "tv": "shows",
    "anime": "anime",
}


def ensure_library_cache_tables(db=None) -> None:
    from resources.lib.database.simkl_sync.database import SimklSyncDatabase

    db = db or SimklSyncDatabase()
    db.execute_sql(
        """
        CREATE TABLE IF NOT EXISTS library_status_cache (
            catalog TEXT NOT NULL,
            status TEXT NOT NULL,
            simkl_id INTEGER NOT NULL,
            item_order INTEGER NOT NULL,
            last_updated INTEGER NOT NULL,
            PRIMARY KEY (catalog, status, simkl_id)
        )
        """
    )
    db.execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_library_status_cache_list
        ON library_status_cache(catalog, status, item_order)
        """
    )
    db.execute_sql(
        """
        CREATE TABLE IF NOT EXISTS library_status_activity (
            catalog TEXT PRIMARY KEY NOT NULL,
            activity_timestamp TEXT,
            last_checked INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def invalidate_library_cache(catalog: str | None = None) -> None:
    """Drop cached membership lists after a local status change."""
    from resources.lib.database.simkl_sync.database import SimklSyncDatabase

    db = SimklSyncDatabase()
    ensure_library_cache_tables(db)
    if catalog:
        db.execute_sql("DELETE FROM library_status_cache WHERE catalog=?", (catalog,))
    else:
        db.execute_sql("DELETE FROM library_status_cache")


def _cache_is_fresh(last_updated: int | None, hours: float = CACHE_HOURS_FALLBACK) -> bool:
    if not last_updated:
        return False
    return (time.time() - int(last_updated)) < (hours * 3600)


def _get_cached_last_updated(catalog: str, status: str) -> int | None:
    from resources.lib.database.simkl_sync.database import SimklSyncDatabase

    db = SimklSyncDatabase()
    ensure_library_cache_tables(db)
    row = db.fetchone(
        """
        SELECT MIN(last_updated) AS last_updated
        FROM library_status_cache
        WHERE catalog=? AND status=?
        """,
        (catalog, status),
    )
    if not row or row.get("last_updated") is None:
        return None
    return int(row["last_updated"])


def _get_cached_refs(catalog: str, status: str) -> list[dict]:
    from resources.lib.database.simkl_sync.database import SimklSyncDatabase

    db = SimklSyncDatabase()
    ensure_library_cache_tables(db)
    rows = db.fetchall(
        """
        SELECT simkl_id
        FROM library_status_cache
        WHERE catalog=? AND status=?
        ORDER BY item_order ASC
        """,
        (catalog, status),
    )
    return [{"simkl_id": int(row["simkl_id"]), "catalog": catalog} for row in rows]


def _save_cached_refs(catalog: str, status: str, refs: list[dict]) -> None:
    from resources.lib.database.simkl_sync.database import SimklSyncDatabase

    db = SimklSyncDatabase()
    ensure_library_cache_tables(db)
    now = int(time.time())
    rows = [
        (catalog, status, int(ref["simkl_id"]), order, now)
        for order, ref in enumerate(refs)
        if ref.get("simkl_id") is not None
    ]
    db.execute_sql(
        "DELETE FROM library_status_cache WHERE catalog=? AND status=?",
        (catalog, status),
    )
    if rows:
        db.execute_sql(
            """
            INSERT INTO library_status_cache
                (catalog, status, simkl_id, item_order, last_updated)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )


def _stored_activity(catalog: str) -> dict | None:
    from resources.lib.database.simkl_sync.database import SimklSyncDatabase

    db = SimklSyncDatabase()
    ensure_library_cache_tables(db)
    return db.fetchone(
        "SELECT activity_timestamp, last_checked FROM library_status_activity WHERE catalog=?",
        (catalog,),
    )


def _save_activity_check(catalog: str, activity_timestamp: str | None) -> None:
    from resources.lib.database.simkl_sync.database import SimklSyncDatabase

    db = SimklSyncDatabase()
    ensure_library_cache_tables(db)
    db.execute_sql(
        """
        INSERT INTO library_status_activity (catalog, activity_timestamp, last_checked)
        VALUES (?, ?, ?)
        ON CONFLICT(catalog) DO UPDATE SET
            activity_timestamp=excluded.activity_timestamp,
            last_checked=excluded.last_checked
        """,
        (catalog, activity_timestamp, int(time.time())),
    )


def _remote_library_activity_timestamp(catalog: str) -> str | None:
    api = SimklAPI()
    if not api.is_authenticated():
        return None
    payload = api.get_activities()
    if not isinstance(payload, dict):
        return None
    section_key = _CATALOG_ACTIVITY_SECTION.get(catalog, "shows")
    section = payload.get(section_key) or {}
    if not isinstance(section, dict):
        return None
    timestamps = [
        value
        for value in (
            section.get("all"),
            section.get("rated_at"),
            section.get("watchlist"),
            section.get("collected_at"),
            section.get("dropped_at"),
            section.get("hold_at"),
            section.get("completed_at"),
        )
        if value
    ]
    return max(timestamps) if timestamps else None


def _activity_requires_refresh(catalog: str) -> bool:
    stored = _stored_activity(catalog)
    if stored and stored.get("last_checked"):
        if time.time() - int(stored["last_checked"]) < ACTIVITY_CHECK_SECONDS:
            return False

    remote_ts = _remote_library_activity_timestamp(catalog)
    _save_activity_check(catalog, remote_ts)

    if not remote_ts:
        return False

    if not stored or not stored.get("activity_timestamp"):
        return True

    return str(stored["activity_timestamp"]) != str(remote_ts)


def should_refresh_library_cache(catalog: str, status: str) -> bool:
    cached_refs = _get_cached_refs(catalog, status)
    if not cached_refs:
        return True
    if _activity_requires_refresh(catalog):
        return True
    return not _cache_is_fresh(_get_cached_last_updated(catalog, status))


def _schedule_library_refresh(catalog: str, status: str) -> None:
    import xbmc

    from resources.lib.common import tools
    from resources.lib.modules.globals import g

    url = g.create_url(
        g.BASE_URL,
        {
            "action": "refreshLibraryCache",
            "action_args": tools.construct_action_args({"catalog": catalog, "status": status}),
        },
    )
    xbmc.executebuiltin(f'RunPlugin("{url}")')


def refresh_library_cache_background(catalog: str | None, status: str | None) -> None:
    """Background refresh of library membership cache after stale-while-revalidate paint."""
    from resources.lib.modules.global_lock import global_lock_running
    from resources.lib.modules.globals import g
    from resources.lib.simkl.library import fetch_library_refs
    from resources.lib.simkl.library_sort import sort_library_refs
    from resources.lib.simkl.library_status import stamp_library_list_status

    if not catalog or not status:
        return

    sync_running = global_lock_running("simkl.sync")
    refs = fetch_library_refs(catalog, status=status, skip_persist=sync_running)
    if refs and not sync_running:
        _save_cached_refs(catalog, status, refs)
    if refs:
        stamp_library_list_status(catalog, status, sort_library_refs(refs, catalog))
        movie_refs = [{"simkl_id": ref["simkl_id"]} for ref in refs if ref.get("catalog") == "movie"]
        show_refs = [
            {"simkl_id": ref["simkl_id"]}
            for ref in refs
            if ref.get("catalog") in ("tv", "anime")
        ]
        if movie_refs:
            MetaEnrichmentQueue.schedule_run_plugin(movie_refs, "movie", reason="library", catalog="movie")
        if show_refs:
            MetaEnrichmentQueue.schedule_run_plugin(show_refs, "tvshow", reason="library", catalog=catalog)


def load_library_list_refs(catalog: str, status: str) -> list[dict]:
    """
    Return list-builder refs for a My Library status list.

    Simkl ``/sync/all-items/...`` is the source of truth for membership.
    Cached simklSync.db rows supply metadata when rendering the list.
    """
    from resources.lib.modules.global_lock import global_lock_running
    from resources.lib.modules.globals import g
    from resources.lib.modules.widget_loader import mark_widget_session_loaded
    from resources.lib.simkl.library import fetch_library_refs
    from resources.lib.simkl.library_sort import sort_library_refs
    from resources.lib.simkl.library_status import stamp_library_list_status

    sync_running = global_lock_running("simkl.sync")

    if g.FROM_WIDGET and mark_widget_session_loaded(f"library.{catalog}.{status}"):
        cached = _get_cached_refs(catalog, status)
        if cached:
            refs = sort_library_refs(cached, catalog)
            stamp_library_list_status(catalog, status, refs)
            return refs

    if sync_running:
        cached = _get_cached_refs(catalog, status)
        if cached:
            refs = sort_library_refs(cached, catalog)
            stamp_library_list_status(catalog, status, refs)
            return refs

    if should_refresh_library_cache(catalog, status):
        cached = _get_cached_refs(catalog, status)
        if cached and meta_enrichment_background():
            _schedule_library_refresh(catalog, status)
            refs = sort_library_refs(cached, catalog)
            stamp_library_list_status(catalog, status, refs)
            return refs
        refs = fetch_library_refs(catalog, status=status, skip_persist=sync_running)
        if refs:
            stamp_library_list_status(catalog, status, refs)
        if refs and not sync_running:
            _save_cached_refs(catalog, status, refs)
        return refs

    refs = _get_cached_refs(catalog, status)
    if refs:
        refs = sort_library_refs(refs, catalog)
        stamp_library_list_status(catalog, status, refs)
        return refs

    refs = fetch_library_refs(catalog, status=status, skip_persist=sync_running)
    if refs:
        stamp_library_list_status(catalog, status, refs)
    if refs and not sync_running:
        _save_cached_refs(catalog, status, refs)
    return refs

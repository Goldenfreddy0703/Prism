"""Keep addon_data cache databases compact."""

from __future__ import annotations

import os

import xbmcvfs

from resources.lib.common import tools
from resources.lib.database.cache import Cache
from resources.lib.modules.globals import g

# Tighter defaults — user prefers smaller on-disk caches.
API_CACHE_MAX_ROWS = 2000
API_CACHE_MAX_AGE_HOURS = 18
SYNC_META_PREFETCH_LIMIT = 200
PROVIDER_BLOB_TYPES = ("tmdb", "tvdb", "fanart")


def trim_api_cache(max_rows: int = API_CACHE_MAX_ROWS) -> int:
    """Drop oldest API cache rows when over the row cap."""
    if max_rows <= 0:
        return 0
    try:
        cache = Cache()
        removed = cache.trim_disk_rows(max_rows)
        cache.close()
        if removed:
            g.log(f"Trimmed {removed} rows from cache.db", "debug")
        return removed
    except Exception:
        g.log_stacktrace()
        return 0


def purge_stale_api_cache(max_age_hours: int = API_CACHE_MAX_AGE_HOURS) -> int:
    """Delete API cache rows older than max_age_hours even if not yet expired."""
    if max_age_hours <= 0:
        return 0
    try:
        import datetime

        cache = Cache()
        cutoff = Cache._get_timestamp(datetime.timedelta(hours=-max_age_hours))
        removed = cache.purge_disk_older_than(cutoff)
        cache.close()
        if removed:
            g.log(f"Purged {removed} stale rows from cache.db", "debug")
        return removed
    except Exception:
        g.log_stacktrace()
        return 0


def vacuum_sqlite_if_large(path: str, min_bytes: int = 4 * 1024 * 1024) -> bool:
    """Run VACUUM on a SQLite file when it exceeds min_bytes."""
    if not path or not xbmcvfs.exists(path):
        return False
    try:
        stat = xbmcvfs.Stat(path)
        size = stat.st_size() if hasattr(stat, "st_size") else 0
        if size < min_bytes:
            return False
        import sqlite3

        conn = sqlite3.connect(tools.translate_path(path))
        conn.execute("VACUUM")
        conn.close()
        g.log(f"Vacuumed {os.path.basename(path)}", "debug")
        return True
    except Exception:
        g.log_stacktrace()
        return False


def prune_non_library_provider_blobs() -> int:
    """Drop TMDB/TVDB/Fanart blobs for browse-only titles (no library engagement)."""
    removed = 0
    try:
        from resources.lib.database.session import get_sync_database

        db = get_sync_database()
        provider_types = ",".join(f"'{name}'" for name in PROVIDER_BLOB_TYPES)
        prune_specs = (
            (
                "movies_meta",
                """
                id IN (
                    SELECT m.tmdb_id FROM movies AS m
                    WHERE m.tmdb_id IS NOT NULL
                      AND COALESCE(m.collected, 0) = 0
                      AND COALESCE(m.watched, 0) = 0
                      AND m.simkl_id NOT IN (SELECT simkl_id FROM bookmarks WHERE simkl_id IS NOT NULL)
                )
                OR id IN (
                    SELECT m.tvdb_id FROM movies AS m
                    WHERE m.tvdb_id IS NOT NULL
                      AND COALESCE(m.collected, 0) = 0
                      AND COALESCE(m.watched, 0) = 0
                      AND m.simkl_id NOT IN (SELECT simkl_id FROM bookmarks WHERE simkl_id IS NOT NULL)
                )
                """,
            ),
            (
                "shows_meta",
                """
                id IN (
                    SELECT s.tmdb_id FROM shows AS s
                    WHERE s.tmdb_id IS NOT NULL
                      AND COALESCE(s.watched_episodes, 0) = 0
                      AND NOT EXISTS (
                          SELECT 1 FROM episodes AS e
                          WHERE e.simkl_show_id = s.simkl_id AND COALESCE(e.collected, 0) != 0
                      )
                      AND s.simkl_id NOT IN (SELECT simkl_id FROM bookmarks WHERE simkl_id IS NOT NULL)
                )
                OR id IN (
                    SELECT s.tvdb_id FROM shows AS s
                    WHERE s.tvdb_id IS NOT NULL
                      AND COALESCE(s.watched_episodes, 0) = 0
                      AND NOT EXISTS (
                          SELECT 1 FROM episodes AS e
                          WHERE e.simkl_show_id = s.simkl_id AND COALESCE(e.collected, 0) != 0
                      )
                      AND s.simkl_id NOT IN (SELECT simkl_id FROM bookmarks WHERE simkl_id IS NOT NULL)
                )
                """,
            ),
        )
        for meta_table, where in prune_specs:
            before = db.fetchone(f"SELECT COUNT(*) AS count FROM {meta_table} WHERE type IN ({provider_types})")
            db.execute_sql(f"DELETE FROM {meta_table} WHERE type IN ({provider_types}) AND ({where})")
            after = db.fetchone(f"SELECT COUNT(*) AS count FROM {meta_table} WHERE type IN ({provider_types})")
            if before and after:
                removed += max(0, int(before.get("count") or 0) - int(after.get("count") or 0))
        if removed:
            g.log(f"Pruned {removed} non-library provider blob rows", "debug")
    except Exception:
        g.log_stacktrace()
    return removed


def run_cache_maintenance() -> None:
    """Entry point for periodic cache size management."""
    purge_stale_api_cache()
    trim_api_cache()
    prune_non_library_provider_blobs()
    vacuum_sqlite_if_large(g.CACHE_DB_PATH)
    vacuum_sqlite_if_large(g.SIMKL_SYNC_DB_PATH)
    vacuum_sqlite_if_large(g.PRISM_META_DB_PATH)

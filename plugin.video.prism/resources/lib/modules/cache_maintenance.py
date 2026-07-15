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


def run_cache_maintenance() -> None:
    """Entry point for periodic cache size management."""
    purge_stale_api_cache()
    trim_api_cache()
    vacuum_sqlite_if_large(g.CACHE_DB_PATH)

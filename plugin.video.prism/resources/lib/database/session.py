"""Session-scoped database accessors (one init per Kodi session)."""
from __future__ import annotations

import threading

_DB_LOCK = threading.Lock()
_SYNC_DB = None
_SIMKL_REBUILD_KEY = "simkl_sync.database_rebuilding"


def simkl_database_rebuilding() -> bool:
    """True while simklSync.db schema is being torn down/recreated (rebuild or integrity repair)."""
    from resources.lib.modules.globals import g

    return g.get_bool_runtime_setting(_SIMKL_REBUILD_KEY, False)


def set_simkl_database_rebuilding(active: bool) -> None:
    from resources.lib.modules.globals import g

    if active:
        g.set_runtime_setting(_SIMKL_REBUILD_KEY, True)
    else:
        g.clear_runtime_setting(_SIMKL_REBUILD_KEY)


def get_sync_database():
    """Return a shared SimklSyncDatabase for the current Kodi session."""
    global _SYNC_DB
    if _SYNC_DB is None:
        with _DB_LOCK:
            if _SYNC_DB is None:
                from resources.lib.database.simkl_sync import SimklSyncDatabase

                _SYNC_DB = SimklSyncDatabase()
    return _SYNC_DB


def ensure_browse_db_read_mode() -> None:
    """Re-assert read-friendly pragmas before browse batch SQL (Otaku SQL pattern)."""
    from resources.lib.modules.globals import g

    if not g.get_bool_setting("general.db.wal_mode", False):
        return
    db = get_sync_database()
    try:
        db.execute_sql("PRAGMA mmap_size = 268435456")
    except Exception:
        pass


def reset_sync_database() -> None:
    """Drop the session singleton (tests / rebuild)."""
    global _SYNC_DB
    with _DB_LOCK:
        _SYNC_DB = None

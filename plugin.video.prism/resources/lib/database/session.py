"""Session-scoped database accessors (one init per Kodi session)."""
from __future__ import annotations

import threading

_DB_LOCK = threading.Lock()
_SYNC_DB = None


def get_sync_database():
    """Return a shared SimklSyncDatabase for the current Kodi session."""
    global _SYNC_DB
    if _SYNC_DB is None:
        with _DB_LOCK:
            if _SYNC_DB is None:
                from resources.lib.database.simkl_sync import SimklSyncDatabase

                _SYNC_DB = SimklSyncDatabase()
    return _SYNC_DB


def reset_sync_database() -> None:
    """Drop the session singleton (tests / rebuild)."""
    global _SYNC_DB
    with _DB_LOCK:
        _SYNC_DB = None

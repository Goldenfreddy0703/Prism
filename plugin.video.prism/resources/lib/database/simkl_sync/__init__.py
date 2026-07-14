"""Simkl user sync database."""
from resources.lib.database.simkl_sync.activities import SimklSyncDatabase
from resources.lib.database.simkl_sync.database import SimklSyncDatabase as SimklSyncDatabaseBase

# activities extends shows (episode/season formatting); base schema in database.py.
SimklSyncDatabaseBase  # re-export for internal submodule imports

__all__ = ["SimklSyncDatabase"]

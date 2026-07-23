"""Simkl user sync database."""
from resources.lib.database.simkl_sync import activities
from resources.lib.database.simkl_sync import movies
from resources.lib.database.simkl_sync.database import SimklSyncDatabase as SimklSyncDatabaseBase


class SimklSyncDatabase(activities.SimklSyncDatabase, movies.SimklSyncDatabase):
    """Activities + shows + movies mixins for session singleton and router imports."""


SimklSyncDatabaseBase  # re-export for internal submodule imports

__all__ = ["SimklSyncDatabase"]

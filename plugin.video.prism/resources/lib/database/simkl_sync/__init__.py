"""Simkl user sync database."""
from resources.lib.database.simkl_sync import activities
from resources.lib.database.simkl_sync import bookmark
from resources.lib.database.simkl_sync import movies
from resources.lib.database.simkl_sync import playback_history_db
from resources.lib.database.simkl_sync.database import SimklSyncDatabase as SimklSyncDatabaseBase


class SimklSyncDatabase(
    activities.SimklSyncDatabase,
    movies.SimklSyncDatabase,
    bookmark.SimklSyncDatabase,
    playback_history_db.SimklSyncDatabase,
):
    """Activities + shows + movies + bookmark + playback history mixins."""


SimklSyncDatabaseBase  # re-export for internal submodule imports

__all__ = ["SimklSyncDatabase"]

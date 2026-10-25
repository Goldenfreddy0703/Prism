"""Simkl user sync database."""
from resources.lib.database.simkl_sync import activities
from resources.lib.database.simkl_sync import anime
from resources.lib.database.simkl_sync import bookmark
from resources.lib.database.simkl_sync import movies
from resources.lib.database.simkl_sync import hidden
from resources.lib.database.simkl_sync import playback_history_db
from resources.lib.database.simkl_sync.database import SimklSyncDatabase as SimklSyncDatabaseBase


class SimklSyncDatabase(
    activities.SimklSyncDatabase,
    movies.SimklSyncDatabase,
    anime.AnimeSyncDatabase,
    bookmark.SimklSyncDatabase,
    playback_history_db.SimklSyncDatabase,
    hidden.SimklSyncDatabase,
):
    """Activities + shows + movies + anime + bookmark + playback history + hidden mixins."""


SimklSyncDatabaseBase  # re-export for internal submodule imports

__all__ = ["SimklSyncDatabase"]

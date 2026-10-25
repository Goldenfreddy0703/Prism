"""Anime series sync DB API (parallel to TV ``shows`` stack)."""
from __future__ import annotations

from resources.lib.database.simkl_sync import shows
from resources.lib.modules.guard_decorators import guard_against_none


class AnimeSyncDatabase(shows.SimklSyncDatabase):
    """Anime serial content — ``shows`` / ``seasons`` / ``episodes`` with ``catalog='anime'``."""

    def anime_catalog(self) -> str:
        return "anime"

    @guard_against_none(list)
    def get_anime_list(self, media_list, **params):
        params["_serial_profile"] = "anime"
        return self.get_show_list(media_list, **params)

    @guard_against_none(list, 1)
    def get_anime_season_list(self, simkl_show_id, simkl_id=None, season=None, **params):
        params["_serial_profile"] = "anime"
        return self.get_season_list(simkl_show_id, simkl_id=simkl_id, season=season, **params)

    @guard_against_none(list, 1, 2, 4)
    def get_anime_episode_list(
        self,
        simkl_show_id,
        simkl_season_id=None,
        simkl_id=None,
        season=None,
        **params,
    ):
        params["_serial_profile"] = "anime"
        return self.get_episode_list(
            simkl_show_id,
            simkl_season_id=simkl_season_id,
            simkl_id=simkl_id,
            season=season,
            **params,
        )

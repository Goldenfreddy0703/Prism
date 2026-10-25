"""Anime menu season/episode coordinates (TVDB buckets from Simkl episode meta)."""
from __future__ import annotations

from typing import Any

from resources.lib.simkl.ids import season_key


def menu_season_from_episode(episode: dict[str, Any] | None) -> int | None:
    if not isinstance(episode, dict):
        return None
    from resources.lib.simkl.field_map import anime_menu_season

    try:
        return int(anime_menu_season(episode))
    except (TypeError, ValueError):
        return None


def menu_episode_number_from_episode(episode: dict[str, Any] | None) -> int | None:
    if not isinstance(episode, dict):
        return None
    from resources.lib.simkl.field_map import anime_menu_episode_number

    try:
        return int(anime_menu_episode_number(episode))
    except (TypeError, ValueError):
        return None


def season_row_id(show_id: int, menu_season: int) -> int:
    return season_key(int(show_id), int(menu_season))


def episode_history_coords(info: dict[str, Any]) -> tuple[int, int]:
    """Simkl history API season/number for an anime episode menu row."""
    season = info.get("season")
    episode = info.get("episode") or info.get("number")
    if info.get("tvdb_season") is not None:
        tvdb_season = int(info["tvdb_season"])
        season = 1 if tvdb_season == 0 else tvdb_season
    if info.get("tvdb_episode") is not None:
        episode = info.get("tvdb_episode")
    return int(season or 1), int(episode or 0)

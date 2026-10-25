"""Anime torrent scraper context for a4kScrapers."""
from __future__ import annotations

from typing import Any

from resources.lib.discover.normalize import _int_or_none
from resources.lib.simkl.field_map import (
    anime_menu_episode_number,
    anime_menu_season,
    tvdb_from_episode,
)


def is_anime_item(ep_info: dict[str, Any], item_info: dict[str, Any] | None) -> bool:
    """True when the episode should use anime torrent scraper filters."""
    item_info = item_info or {}
    if ep_info.get("catalog") == "anime" or item_info.get("catalog") == "anime":
        return True
    for key in ("mal_id", "mal_show_id", "anidb_id", "anilist_id", "kitsu_id"):
        if ep_info.get(key):
            return True
    genres = ep_info.get("genre", [])
    if not isinstance(genres, list):
        genres = [genres] if genres else []
    for genre in genres:
        genre_lower = str(genre).lower()
        if "anime" in genre_lower:
            return True
        if "animation" in genre_lower:
            country = (ep_info.get("country_origin") or "").upper()
            if country in ("JP", "JPN", "JAPAN", "CN", "CHN", "CHINA"):
                return True
    return False


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _status_value(ep_info: dict[str, Any], show_info: dict[str, Any] | None) -> str:
    for source in (ep_info, show_info or {}):
        status = source.get("status")
        if status:
            return str(status)
    return ""


def build_anime_simple_info_fields(
    ep_info: dict[str, Any],
    item_info: dict[str, Any] | None,
    show_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return extra simple_info keys for anime scrapers (empty dict for non-anime)."""
    item_info = item_info or {}
    if not is_anime_item(ep_info, item_info):
        return {}

    show_info = show_info or {}
    show_ids = show_info.get("ids") if isinstance(show_info.get("ids"), dict) else {}
    ep_ids = ep_info.get("ids") if isinstance(ep_info.get("ids"), dict) else {}

    fields: dict[str, Any] = {}

    for flat_key, sources in (
        ("mal_id", (ep_info, show_info, ep_ids, show_ids)),
        ("anidb_id", (ep_info, show_info, ep_ids, show_ids)),
        ("anilist_id", (ep_info, show_info, ep_ids, show_ids)),
        ("kitsu_id", (ep_info, show_info, ep_ids, show_ids)),
        ("tvdb_id", (ep_info, show_info, ep_ids, show_ids)),
        ("simkl_id", (ep_info, show_info, ep_ids, show_ids)),
    ):
        value = None
        for source in sources:
            if not isinstance(source, dict):
                continue
            if flat_key == "mal_id":
                value = source.get("mal_id") or source.get("mal") or source.get("mal_show_id")
            elif flat_key == "simkl_id":
                value = source.get("simkl_id") or source.get("simkl")
            else:
                value = source.get(flat_key)
            if value is not None:
                break
        if value is not None:
            fields[flat_key] = value

    status = _status_value(ep_info, show_info)
    if status:
        fields["status"] = status

    duration = ep_info.get("duration") or show_info.get("duration")
    if duration is not None:
        fields["duration"] = duration

    menu_season = anime_menu_season(ep_info)
    fallback_ep = _first_int(ep_info.get("episode"), ep_info.get("number"))
    menu_episode = anime_menu_episode_number(ep_info, menu_season, fallback_ep)

    simkl_season = _first_int(ep_info.get("season"))
    simkl_episode = _first_int(ep_info.get("episode"), ep_info.get("number"))
    if simkl_season is not None:
        fields["alternative_season"] = str(simkl_season)
    if simkl_episode is not None:
        fields["alternative_episode"] = str(simkl_episode)
        fields["simkl_episode_number"] = str(simkl_episode)

    tvdb_bucket, tvdb_ep = tvdb_from_episode(ep_info)
    if tvdb_bucket is not None:
        fields["thetvdb_season"] = str(tvdb_bucket)
    if tvdb_ep is not None:
        fields["thetvdb_part"] = str(tvdb_ep)

    if menu_season is not None and "alternative_season" not in fields:
        fields["alternative_season"] = str(menu_season)
    if menu_episode is not None and "alternative_episode" not in fields:
        fields["alternative_episode"] = str(menu_episode)

    return fields


__all__ = ["build_anime_simple_info_fields", "is_anime_item"]

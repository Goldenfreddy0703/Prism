"""Resolve artwork settings profile and provider fetch type from sync/list rows."""
from __future__ import annotations

from typing import Any

PROFILE_MOVIE = "movie"
PROFILE_TVSHOW = "tvshow"
PROFILE_ANIME_MOVIE = "anime_movie"
PROFILE_ANIME_SERIES = "anime_series"

_ANIME_PROFILES = frozenset({PROFILE_ANIME_MOVIE, PROFILE_ANIME_SERIES})


def _row_info(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    info = row.get("info")
    if isinstance(info, dict):
        return info
    simkl_object = row.get("simkl_object")
    if isinstance(simkl_object, dict) and isinstance(simkl_object.get("info"), dict):
        return simkl_object["info"]
    return {}


def _is_anime_catalog(info: dict[str, Any], row: dict[str, Any] | None = None) -> bool:
    if info.get("catalog") == "anime":
        return True
    if row and row.get("catalog") == "anime":
        return True
    if str(info.get("type") or "").lower() == "anime":
        return True
    ids = info.get("ids")
    if isinstance(ids, dict) and ids.get("mal"):
        return True
    if info.get("mal_id") or info.get("anime_type"):
        return True
    return False


def artwork_profile_for_row(row: dict[str, Any] | None, default_media_type: str = "tvshow") -> str:
    """Return movie | tvshow | anime_movie | anime_series for artwork settings."""
    if not isinstance(row, dict):
        return PROFILE_MOVIE if default_media_type == "movie" else PROFILE_TVSHOW

    info = dict(_row_info(row))
    from resources.lib.simkl.ids import canonicalize_info_identity

    canonicalize_info_identity(info)

    if _is_anime_catalog(info, row):
        from resources.lib.simkl.catalog import is_anime_movie_info, simkl_anime_type

        merged = dict(row)
        merged["info"] = info
        if is_anime_movie_info(info) or simkl_anime_type(merged) == "movie" or simkl_anime_type(info) == "movie":
            return PROFILE_ANIME_MOVIE
        return PROFILE_ANIME_SERIES

    mediatype = info.get("mediatype") or row.get("mediatype") or default_media_type
    if mediatype == "movie":
        return PROFILE_MOVIE
    return PROFILE_TVSHOW


def settings_prefix_for_profile(profile: str) -> str:
    if profile in _ANIME_PROFILES:
        return "anime"
    if profile == PROFILE_MOVIE:
        return "movies"
    return "tvshows"


def provider_media_type(profile: str) -> str:
    if profile in (PROFILE_MOVIE, PROFILE_ANIME_MOVIE):
        return "movie"
    return "tvshow"


def art_limits_media_type(profile: str) -> str:
    """Media type key for meta_storage._art_limits()."""
    if profile in _ANIME_PROFILES:
        return profile
    if profile == PROFILE_MOVIE:
        return "movie"
    return "tvshow"


def preferred_art_scope(profile: str) -> str:
    """Scope for metadata_providers.advanced_artwork_enabled / art_option_enabled."""
    if profile in _ANIME_PROFILES:
        return "anime"
    if profile == PROFILE_MOVIE:
        return "movie"
    return "tvshow"

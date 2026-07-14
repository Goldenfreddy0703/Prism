"""Slim metadata for SQLite storage — Kodi display fields only, no duplicate API payloads."""
from __future__ import annotations

import copy
from typing import Any

# Info keys used by Kodi list items, info tags, scrapers, and merge logic.
_DISPLAY_INFO_KEYS = frozenset(
    {
        "title",
        "originaltitle",
        "tvshowtitle",
        "sorttitle",
        "plot",
        "overview",
        "tagline",
        "genre",
        "genres",
        "year",
        "duration",
        "runtime",
        "rating",
        "votes",
        "rating.tmdb",
        "rating.tvdb",
        "rating.imdb",
        "rating.trakt",
        "rating.simkl",
        "rating.mal",
        "rating.mdblist",
        "ratings",
        "mediatype",
        "catalog",
        "type",
        "anime_type",
        "simkl_id",
        "tmdb_id",
        "tvdb_id",
        "imdb_id",
        "imdbnumber",
        "mal_id",
        "tmdb_show_id",
        "tvdb_show_id",
        "simkl_show_id",
        "simkl_season_id",
        "season",
        "episode",
        "episode_count",
        "season_count",
        "status",
        "mpaa",
        "certification",
        "trailer",
        "studio",
        "director",
        "writer",
        "country",
        "country_origin",
        "aired",
        "premiered",
        "release_date",
        "dateadded",
        "aliases",
        "set",
        "network",
        "slug",
        "ids",
        "thumb",
        "poster",
        "fanart",
        "simkl_img",
        "img",
        "is_airing",
        "playcount",
        "simkl_status",
        "user_rating",
        "score",
        "rank",
        "mdblist_score",
        "collected",
        "watched",
        "uniqueid",
        "dbid",
    }
)

_SIMKL_EXTRA_INFO_KEYS = frozenset(
    {
        "mal_id",
        "anidb_id",
        "anilist_id",
        "kitsu_id",
        "simkl_img",
        "img",
        "anime_type",
        "catalog",
    }
)

_ART_LIST_TYPES = (
    "poster",
    "fanart",
    "thumb",
    "icon",
    "clearlogo",
    "banner",
    "landscape",
    "clearart",
    "discart",
    "characterart",
    "keyart",
)

_CAST_MEMBER_KEYS = frozenset(
    {"name", "character", "role", "order", "thumb", "thumbnail", "profile", "profile_path"}
)

_MAX_RELEASE_COUNTRIES = 4


def _user_region_code() -> str:
    from resources.lib.modules.globals import g

    code = g.get_language_code(True).split("-")[-1]
    return code.upper() if code else "US"


def _art_limits(media_type: str | None) -> dict[str, int]:
    from resources.lib.modules.globals import g

    if media_type == "movie":
        return {
            "poster": g.get_int_setting("movies.poster_limit", 1),
            "fanart": g.get_int_setting("movies.fanart_limit", 1),
            "characterart": g.get_int_setting("movies.characterart_limit", 1),
            "keyart": g.get_int_setting("movies.keyart_limit", 1),
            "thumb": 1,
            "icon": 1,
            "clearlogo": 1 if g.get_bool_setting("movies.clearlogo", True) else 0,
            "banner": 1 if g.get_bool_setting("movies.banner", True) else 0,
            "landscape": 1 if g.get_bool_setting("movies.landscape", True) else 0,
            "clearart": 1 if g.get_bool_setting("movies.clearart", True) else 0,
            "discart": 1 if g.get_bool_setting("movies.discart", True) else 0,
        }
    return {
        "poster": g.get_int_setting("tvshows.poster_limit", 1),
        "fanart": g.get_int_setting("tvshows.fanart_limit", 1),
        "characterart": g.get_int_setting("tvshows.characterart_limit", 1),
        "keyart": g.get_int_setting("tvshows.keyart_limit", 1),
        "thumb": 1,
        "icon": 1,
        "clearlogo": 1 if g.get_bool_setting("tvshows.clearlogo", True) else 0,
        "banner": 1 if g.get_bool_setting("tvshows.banner", True) else 0,
        "landscape": 1 if g.get_bool_setting("tvshows.landscape", True) else 0,
        "clearart": 1 if g.get_bool_setting("tvshows.clearart", True) else 0,
    }


def _slim_releases(releases: Any) -> dict | None:
    if not isinstance(releases, dict) or not releases:
        return None
    region = _user_region_code()
    keep: dict = {}
    for code in (region, "US", "GB", "CA"):
        if code in releases and releases[code] is not None:
            keep[code] = releases[code]
        if len(keep) >= _MAX_RELEASE_COUNTRIES:
            break
    if not keep and releases:
        first_key = next(iter(releases))
        keep[first_key] = releases[first_key]
    return keep or None


def slim_info_dict(info: dict[str, Any] | None, *, simkl: bool = False) -> dict[str, Any]:
    if not isinstance(info, dict):
        return {}
    allowed = _DISPLAY_INFO_KEYS | (_SIMKL_EXTRA_INFO_KEYS if simkl else frozenset())
    out: dict[str, Any] = {}
    for key, value in info.items():
        if key not in allowed or value is None or value == "":
            continue
        if key == "releases":
            slimmed = _slim_releases(value)
            if slimmed:
                out[key] = slimmed
            continue
        if key == "ids" and isinstance(value, dict):
            out[key] = {k: v for k, v in value.items() if v is not None}
            continue
        out[key] = value
    return out


def _slim_art_entry(entry: Any) -> Any:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        slim = {
            k: entry[k]
            for k in ("url", "rating", "size")
            if k in entry and entry[k] is not None
        }
        if "language" in entry:
            slim["language"] = entry["language"]
        elif slim.get("url"):
            slim["language"] = None
        return slim if slim else entry
    return entry


def slim_art_dict(art: dict[str, Any] | None, media_type: str | None = None) -> dict[str, Any]:
    if not isinstance(art, dict) or not art:
        return {}
    limits = _art_limits(media_type)
    out: dict[str, Any] = {}
    for key, value in art.items():
        if not value:
            continue
        base_key = key.rstrip("0123456789")
        if base_key not in _ART_LIST_TYPES and key not in _ART_LIST_TYPES:
            if isinstance(value, str):
                out[key] = value
            continue
        limit = limits.get(base_key, limits.get(key, 1))
        if isinstance(value, str):
            out[key] = value
            continue
        if isinstance(value, list):
            trimmed = [_slim_art_entry(item) for item in value[: max(limit, 1)] if item]
            if trimmed:
                out[key] = trimmed
            continue
        if isinstance(value, dict):
            out[key] = _slim_art_entry(value)
    return out


def slim_cast_list(cast: list | None) -> list:
    if not isinstance(cast, list) or not cast:
        return []
    out = []
    for member in cast:
        if isinstance(member, dict):
            slim = {k: member[k] for k in _CAST_MEMBER_KEYS if k in member and member[k] is not None}
            if slim:
                out.append(slim)
        elif member:
            out.append(member)
    return out


def slim_provider_blob(
    blob: dict[str, Any] | None,
    provider_type: str | None = None,
    media_type: str | None = None,
) -> dict[str, Any] | None:
    """Reduce a provider {info, art, cast} blob before writing to *_meta tables."""
    if not isinstance(blob, dict) or not blob:
        return None

    info = blob.get("info") if isinstance(blob.get("info"), dict) else {}
    mediatype = info.get("mediatype") or media_type

    if provider_type in ("tmdb", "tvdb", "fanart") and mediatype in ("season", "episode"):
        from resources.lib.simkl.field_map import simkl_child_external_patch

        return simkl_child_external_patch(blob) or None

    simkl = provider_type == "simkl"
    result = {
        "info": slim_info_dict(info, simkl=simkl),
        "art": slim_art_dict(blob.get("art"), mediatype if mediatype in ("movie", "tvshow") else "tvshow"),
    }
    if provider_type in ("tmdb", "tvdb") and not simkl:
        cast = slim_cast_list(blob.get("cast"))
        if cast:
            result["cast"] = cast
    elif simkl and blob.get("cast"):
        cast = slim_cast_list(blob.get("cast"))
        if cast:
            result["cast"] = cast

    if not result["info"] and not result["art"] and not result.get("cast"):
        return None
    return result


def slim_formatted_item(item: dict[str, Any]) -> dict[str, Any]:
    """Slim a post-merge Kodi menu/playback row before writing to movies/shows tables."""
    if not isinstance(item, dict):
        return item
    info = item.get("info")
    if not isinstance(info, dict):
        return item
    mediatype = info.get("mediatype")
    slimmed = copy.copy(item)
    slimmed["info"] = slim_info_dict(info, simkl=True)
    slimmed["art"] = slim_art_dict(item.get("art"), mediatype)
    if item.get("cast"):
        slimmed["cast"] = slim_cast_list(item.get("cast"))
    return slimmed


def slim_db_row(row: dict[str, Any]) -> dict[str, Any]:
    """Slim info/art/cast on a sync DB list row."""
    if not isinstance(row, dict):
        return row
    out = dict(row)
    info = row.get("info")
    if isinstance(info, dict):
        out["info"] = slim_info_dict(info, simkl=True)
    if isinstance(row.get("art"), dict):
        mediatype = (info or {}).get("mediatype") if isinstance(info, dict) else None
        out["art"] = slim_art_dict(row.get("art"), mediatype)
    if row.get("cast"):
        out["cast"] = slim_cast_list(row.get("cast"))
    return out

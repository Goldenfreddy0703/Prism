"""Browse helpers — Simkl discover, genres, TMDB year/discover, Simkl airing."""
from __future__ import annotations

import copy
import time
from typing import Any, NamedTuple

from resources.lib.simkl.media_ref import normalize_simkl_item
from resources.lib.discover.renderer import DiscoverRenderer
from resources.lib.database.cache import use_cache
from resources.lib.indexers.simkl import SimklAPI
from resources.lib.indexers.tmdb import TMDBAPI
from resources.lib.modules.globals import g
from resources.lib.simkl.enrich import _simkl_detail_sync_dict
from resources.lib.simkl.menu_helpers import genre_sort_segment


def _tmdb_runtime_enabled() -> bool:
    from resources.lib.meta.provider_settings import tmdb_features_enabled

    return tmdb_features_enabled()

DISCOVER_ENDPOINTS: dict[str, dict[str, str]] = {
    "movie": {
        "trending": "movie_week",
        "popular": "movies_popular",
        "played": "movies_most_watched",
        "watched": "movies_most_watched",
        "anticipated": "movies_anticipated",
        "collected": "movies_top_simkl",
        "updated": "movies_new",
    },
    "tv": {
        "trending": "tv_week",
        "popular": "tv_popular",
        "played": "tv_most_watched",
        "watched": "tv_most_watched",
        "anticipated": "tv_anticipated",
        "collected": "tv_top_simkl",
        "new": "tv_new",
        "updated": "tv_month",
    },
    "anime": {
        "trending": "anime_week",
        "popular": "anime_popular",
        "played": "anime_most_watched",
        "watched": "anime_most_watched",
        "anticipated": "anime_anticipated",
        "collected": "anime_completed",
        "new": "anime_new",
        "popular_recent": "anime_new_year",
        "trending_recent": "anime_week",
    },
}


SIMKL_MOVIE_GENRE_SLUGS = (
    "action",
    "adventure",
    "animation",
    "comedy",
    "crime",
    "documentary",
    "drama",
    "erotica",
    "family",
    "fantasy",
    "history",
    "horror",
    "music",
    "mystery",
    "romance",
    "science-fiction",
    "thriller",
    "tv-movie",
    "war",
    "western",
)

SIMKL_TV_GENRE_SLUGS = (
    "action",
    "adventure",
    "animation",
    "awards-show",
    "children",
    "comedy",
    "crime",
    "documentary",
    "drama",
    "erotica",
    "family",
    "fantasy",
    "food",
    "game-show",
    "history",
    "home-and-garden",
    "horror",
    "indie",
    "korean-drama",
    "martial-arts",
    "mini-series",
    "musical",
    "mystery",
    "news",
    "podcast",
    "reality",
    "romance",
    "science-fiction",
    "soap",
    "special-interest",
    "sport",
    "suspense",
    "talk-show",
    "thriller",
    "travel",
    "video-game-play",
    "war",
    "western",
)

SIMKL_ANIME_GENRE_SLUGS = (
    "action",
    "adventure",
    "comedy",
    "drama",
    "ecchi",
    "educational",
    "fantasy",
    "gag-humor",
    "gore",
    "harem",
    "historical",
    "horror",
    "idol",
    "isekai",
    "josei",
    "kids",
    "magic",
    "martial-arts",
    "mecha",
    "military",
    "music",
    "mystery",
    "mythology",
    "parody",
    "psychological",
    "racing",
    "reincarnation",
    "romance",
    "samurai",
    "school",
    "sci-fi",
    "seinen",
    "shoujo",
    "shoujo-ai",
    "shounen",
    "shounen-ai",
    "slice-of-life",
    "space",
    "sports",
    "strategy-game",
    "super-power",
    "supernatural",
    "thriller",
    "vampire",
    "yaoi",
    "yuri",
)

SIMKL_GENRE_SLUGS = {
    "movie": SIMKL_MOVIE_GENRE_SLUGS,
    "tv": SIMKL_TV_GENRE_SLUGS,
    "anime": SIMKL_ANIME_GENRE_SLUGS,
}

ADULT_BLOCKED_SIMKL_GENRE_SLUGS = frozenset({"erotica"})

# Simkl genre browse wildcards (``all`` in docs; API expects these literal segments).
SIMKL_GENRE_ALL_TYPES = "all-types"
SIMKL_GENRE_ALL_COUNTRIES = "all-countries"
SIMKL_GENRE_ALL_NETWORKS = "all-networks"
SIMKL_GENRE_ALL_YEARS = "all-years"

TENRAI_ANIME_GENRE_BUCKET_FILTERS = ("genres",)
TENRAI_ANIME_TAG_BUCKET_FILTERS = ("themes", "demographics")
TENRAI_ANIME_EXPLICIT_GENRE_FILTER = "explicit_genres"


def adult_content_enabled() -> bool:
    return g.get_bool_setting("general.adult.enabled")


def _visible_simkl_genre_slugs(catalog: str) -> tuple[str, ...]:
    slugs = SIMKL_GENRE_SLUGS.get(catalog, ())
    if adult_content_enabled():
        return slugs
    return tuple(slug for slug in slugs if slug not in ADULT_BLOCKED_SIMKL_GENRE_SLUGS)


class GenreBrowsePage(NamedTuple):
    items: list[dict]
    has_next_page: bool
    next_tmdb_page: int = 1
    next_tmdb_offset: int = 0


def _slug_to_label(slug: str) -> str:
    return slug.replace("-", " ").title()


def get_simkl_genres(catalog: str) -> list[dict[str, str]]:
    """Return ``[{slug, label}]`` for Simkl genre browse pickers."""
    slugs = _visible_simkl_genre_slugs(catalog)
    if not slugs:
        return []
    return [{"slug": slug, "label": _slug_to_label(slug)} for slug in slugs]


GENRE_ICON_FOLDERS = {
    "movie": "movies",
    "tv": "tv",
    "anime": "Anime",
}


def genre_icons_path(catalog: str) -> str:
    """Per-catalog genre art folder; anime uses shared pack-agnostic assets when present."""
    import xbmcvfs

    folder = GENRE_ICON_FOLDERS.get(catalog, catalog)
    pack_path = f"{g.GENRES_PATH}{folder}/"
    if catalog == "anime":
        shared_path = f"{g.SHARED_GENRES_PATH}{folder}/"
        if xbmcvfs.exists(shared_path):
            return shared_path
    return pack_path


def genre_icon_art_path(catalog: str, slug: str) -> str:
    """Resolve a genre image path, allowing per-pack anime overrides over shared art."""
    import xbmcvfs

    filename = f"{slug}.png"
    if catalog == "anime":
        pack_path = f"{g.GENRES_PATH}{GENRE_ICON_FOLDERS['anime']}/{filename}"
        if xbmcvfs.exists(pack_path):
            return pack_path
        shared_path = f"{g.SHARED_GENRES_PATH}{GENRE_ICON_FOLDERS['anime']}/{filename}"
        if xbmcvfs.exists(shared_path):
            return shared_path
    return f"{genre_icons_path(catalog)}{filename}"


def genre_icon_dict(catalog: str, slug: str) -> dict:
    """Genre menu art from ``genres/{movies|tv|Anime}/{slug}.png``."""
    art_path = genre_icon_art_path(catalog, slug)
    return {"art": dict.fromkeys(["icon", "poster", "thumb"], art_path)}


def discover_genre_menu_icon(catalog: str) -> dict:
    """Discover submenu ``Genres`` row — prefer catalog icons pack, else list fallback."""
    icon_slug = {
        "movie": "movies_genres",
        "tv": "shows_genres",
        "anime": "anime_genres",
    }.get(catalog, "list")
    icon_path = f"{g.ICONS_PATH}{icon_slug}.png"
    import xbmcvfs

    if xbmcvfs.exists(icon_path):
        return g.create_icon_dict(icon_slug, g.ICONS_PATH)
    return g.create_icon_dict("list", g.ICONS_PATH)


def _simkl_genre_row_to_sync(row: dict, catalog: str) -> dict | None:
    if not isinstance(row, dict):
        return None
    from resources.lib.simkl.media_ref import _simkl_api_list_row_to_item

    item = _simkl_api_list_row_to_item(row)
    normalized = normalize_simkl_item(item, catalog)
    if normalized:
        info = normalized.get("simkl_object", {}).get("info", {})
        if row.get("rank") is not None:
            info["score"] = row.get("rank")
    return normalized


def _simkl_genre_browse_path(catalog: str, genre_slug: str, sort: str) -> str:
    """Build Simkl genre browse path with documented wildcard segment names."""
    if catalog == "movie":
        return (
            f"/movies/genres/{genre_slug}/movies/"
            f"{SIMKL_GENRE_ALL_TYPES}/{SIMKL_GENRE_ALL_COUNTRIES}/{SIMKL_GENRE_ALL_YEARS}/{sort}"
        )
    if catalog == "anime":
        return (
            f"/anime/genres/{genre_slug}/"
            f"{SIMKL_GENRE_ALL_TYPES}/{SIMKL_GENRE_ALL_NETWORKS}/{SIMKL_GENRE_ALL_YEARS}/{sort}"
        )
    return (
        f"/tv/genres/{genre_slug}/"
        f"{SIMKL_GENRE_ALL_TYPES}/{SIMKL_GENRE_ALL_COUNTRIES}/{SIMKL_GENRE_ALL_YEARS}/{sort}"
    )


def _simkl_genre_browse_page(
    catalog: str,
    genre_slug: str,
    page: int,
    page_limit: int,
) -> GenreBrowsePage:
    from resources.lib.simkl.menu_helpers import genre_page_has_next, genre_sort_segment, simkl_pagination_has_next

    sort = genre_sort_segment(catalog)
    api = SimklAPI()
    path = _simkl_genre_browse_path(catalog, genre_slug, sort)

    request_limit = min(page_limit, 60)
    payload, pagination = api.get_public_json_with_pagination(
        path,
        page=page,
        limit=request_limit,
    )
    if payload is None:
        return GenreBrowsePage([], False)
    if not isinstance(payload, list):
        return GenreBrowsePage([], False)

    results = []
    for row in payload:
        normalized = _simkl_genre_row_to_sync(row, catalog)
        if normalized:
            results.append(normalized)
        if len(results) >= page_limit:
            break

    has_next = simkl_pagination_has_next(
        pagination,
        fallback_page=page,
        fallback_count=len(payload),
        fallback_limit=request_limit,
    )
    if not has_next and not pagination:
        has_next = genre_page_has_next(page, len(payload), request_limit)

    return GenreBrowsePage(results, has_next)


def discover_by_genre_slug(catalog: str, genre_slug: str, page: int, page_limit: int) -> GenreBrowsePage:
    """Fetch one page of Simkl genre browse for a single slug."""
    slug = str(genre_slug or "").strip().lower()
    if not slug or slug not in SIMKL_GENRE_SLUGS.get(catalog, ()):
        return GenreBrowsePage([], False)
    if slug in ADULT_BLOCKED_SIMKL_GENRE_SLUGS and not adult_content_enabled():
        return GenreBrowsePage([], False)
    return _simkl_genre_browse_page(catalog, slug, page, page_limit)


TMDB_GENRE_POPULARITY_SORTS = frozenset(
    {
        "popular-this-week",
        "popular-all-time",
        "popular-this-month",
        "watched",
    }
)


@use_cache(cache_hours=24)
def get_tmdb_genres(catalog: str) -> list[dict[str, Any]]:
    """Return ``[{id, name}]`` from TMDB genre list endpoints."""
    if not _tmdb_runtime_enabled():
        return []
    if catalog not in ("movie", "tv"):
        return []
    tmdb = TMDBAPI()
    media_type = "movie" if catalog == "movie" else "tv"
    payload = tmdb.get_json_cached(
        f"genre/{media_type}/list",
        raw=True,
        language=tmdb.lang_full_code,
    )
    if not payload:
        return []
    genres: list[dict[str, Any]] = []
    for row in payload.get("genres") or []:
        genre_id = row.get("id")
        name = row.get("name")
        if genre_id is None or not name:
            continue
        genres.append({"id": int(genre_id), "name": str(name)})
    if not adult_content_enabled():
        genres = [genre for genre in genres if genre["name"].strip().lower() != "erotica"]
    return sorted(genres, key=lambda item: item["name"].lower())


def tmdb_sort_for_genre_setting(catalog: str) -> str:
    """Map general.genres.endpoint.* to TMDB discover ``sort_by``."""
    segment = genre_sort_segment(catalog)
    if segment == "release-date":
        return "primary_release_date.desc" if catalog == "movie" else "first_air_date.desc"
    if segment == "rank":
        return "vote_average.desc"
    if segment == "voted":
        return "vote_count.desc"
    if segment in TMDB_GENRE_POPULARITY_SORTS:
        return "popularity.desc"
    return "popularity.desc"


def _should_exclude_anime_from_genre_browse(item: dict, _browse_catalog: str) -> bool:
    """Drop Simkl anime rows from movie/TV multi-genre TMDB discover."""
    from resources.lib.simkl.catalog import is_anime_movie_info, resolve_item_catalog

    blob = item.get("simkl_object") or item
    info = (blob.get("info") or {}) if isinstance(blob, dict) else {}
    catalog = item.get("catalog") or info.get("catalog")

    if catalog == "anime":
        return True

    ids = info.get("ids") or (blob.get("ids") if isinstance(blob, dict) else {}) or {}
    if ids.get("mal") or info.get("mal_id"):
        return True

    if (blob.get("anime_type") if isinstance(blob, dict) else None) or info.get("anime_type"):
        return True

    if is_anime_movie_info(info):
        return True

    if isinstance(blob, dict) and resolve_item_catalog(blob, "") == "anime":
        return True

    return False


def _resolve_tmdb_discover_id(tmdb_id: int, catalog: str) -> dict | None:
    """Parallel-safe TMDB id → thin SyncRow via GET /redirect."""
    from resources.lib.indexers.simkl import thread_simkl_api
    from resources.lib.simkl.id_resolve import thin_sync_from_redirect

    lookup_type = "movie" if catalog == "movie" else "tv"
    match = thread_simkl_api().redirect_simkl_id(tmdb=int(tmdb_id), type=lookup_type)
    if match:
        simkl_id, resolved_catalog = match
    else:
        simkl_id = _simkl_id_from_db(tmdb_id, catalog)
        if simkl_id is None:
            return None
        resolved_catalog = catalog
    normalized = thin_sync_from_redirect(simkl_id, resolved_catalog, tmdb_id=int(tmdb_id))
    if _should_exclude_anime_from_genre_browse(normalized, catalog):
        return None
    return normalized


def _parallel_resolve_tmdb_discover_rows(rows: list[dict], catalog: str) -> dict[int, dict]:
    tmdb_ids: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("id")
        if value is None:
            continue
        try:
            tmdb_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    unique_ids = list(dict.fromkeys(tmdb_ids))
    if not unique_ids:
        return {}
    from resources.lib.simkl.id_resolve import parallel_map_resolve

    resolved = parallel_map_resolve(unique_ids, lambda tid: _resolve_tmdb_discover_id(tid, catalog), parallel=True)
    return {
        tmdb_id: row
        for tmdb_id, row in zip(unique_ids, resolved)
        if isinstance(row, dict) and row.get("simkl_id") is not None
    }


_TMDM_MULTI_GROW_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}


def _grow_tmdb_multi_genre_stream(
    catalog: str,
    with_genres: str,
    sort_by: str,
    min_items: int,
) -> list[dict]:
    """Grow TMDB multiselect results (parallel /redirect per TMDB page) until min_items or exhaust."""
    if not _tmdb_runtime_enabled() or catalog not in ("movie", "tv"):
        return []

    key = (catalog, with_genres, sort_by)
    state = _TMDM_MULTI_GROW_CACHE.get(key)
    if state is None:
        state = {
            "items": [],
            "tmdb_page": 1,
            "total_pages": 1,
            "seen_simkl_ids": set(),
            "exhausted": False,
        }
        _TMDM_MULTI_GROW_CACHE[key] = state

    items: list[dict] = state["items"]
    if len(items) >= min_items or state["exhausted"]:
        return items

    tmdb = TMDBAPI()
    media_type = "movie" if catalog == "movie" else "tv"
    seen_simkl_ids: set[int] = state["seen_simkl_ids"]
    current_page = int(state["tmdb_page"])
    total_pages = int(state["total_pages"])
    started = time.time()

    while len(items) < min_items and current_page <= total_pages:
        response = tmdb.get_json(
            f"discover/{media_type}",
            raw=True,
            page=current_page,
            language=tmdb.lang_full_code,
            sort_by=sort_by,
            with_genres=with_genres,
            include_adult=False,
        )
        if not response:
            state["exhausted"] = True
            break
        total_pages = int(response.get("total_pages") or 1)
        rows = response.get("results") or []
        if not rows:
            state["exhausted"] = True
            break
        resolved_by_tmdb = _parallel_resolve_tmdb_discover_rows(rows, catalog)
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get("id")
            if value is None:
                continue
            try:
                tmdb_id = int(value)
            except (TypeError, ValueError):
                continue
            normalized = resolved_by_tmdb.get(tmdb_id)
            if not normalized:
                continue
            simkl_id = normalized.get("simkl_id")
            if simkl_id is not None:
                sid = int(simkl_id)
                if sid in seen_simkl_ids:
                    continue
                seen_simkl_ids.add(sid)
            items.append(normalized)
            if len(items) >= min_items:
                break
        current_page += 1
        if current_page > total_pages:
            state["exhausted"] = True
            break

    state["tmdb_page"] = current_page
    state["total_pages"] = total_pages
    elapsed_ms = int((time.time() - started) * 1000)
    g.log(
        f"TMDB multi-genre grow catalog={catalog} genres={with_genres} "
        f"items={len(items)} need={min_items} tmdb_page={current_page} grow_ms={elapsed_ms}",
        "debug",
    )
    return items


def _tmdb_multi_grow_exhausted(catalog: str, with_genres: str, sort_by: str) -> bool:
    state = _TMDM_MULTI_GROW_CACHE.get((catalog, with_genres, sort_by))
    if not state:
        return False
    return bool(state.get("exhausted"))


def _multi_genre_menu_has_next(
    stream: list[dict],
    chunk: list[dict],
    page_limit: int,
    end: int,
    *,
    grow_exhausted: bool,
) -> bool:
    if end < len(stream):
        return True
    return not grow_exhausted and len(chunk) >= page_limit


def discover_by_tmdb_genres(
    catalog: str,
    genre_ids: str,
    page_limit: int,
    *,
    menu_page: int = 1,
    tmdb_page: int = 1,
    tmdb_offset: int = 0,
) -> GenreBrowsePage:
    """TMDB multiselect: cached parallel redirect stream, sliced by Kodi menu page."""
    if not _tmdb_runtime_enabled():
        return GenreBrowsePage([], False)
    if catalog not in ("movie", "tv"):
        return GenreBrowsePage([], False)

    parsed_ids: list[int] = []
    for part in str(genre_ids or "").split(","):
        part = part.strip()
        if part.isdigit():
            parsed_ids.append(int(part))
    if not parsed_ids:
        return GenreBrowsePage([], False)

    with_genres = ",".join(str(genre_id) for genre_id in parsed_ids)
    sort_by = tmdb_sort_for_genre_setting(catalog)
    page_index = max(1, int(menu_page))
    stream = _grow_tmdb_multi_genre_stream(catalog, with_genres, sort_by, page_index * page_limit)
    start = (page_index - 1) * page_limit
    end = start + page_limit
    chunk = stream[start:end]
    has_next = _multi_genre_menu_has_next(
        stream,
        chunk,
        page_limit,
        end,
        grow_exhausted=_tmdb_multi_grow_exhausted(catalog, with_genres, sort_by),
    )
    return GenreBrowsePage(chunk, has_next, page_index + 1 if has_next else page_index, 0)


def _merge_tenrai_genre_rows(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for rows in lists:
        for row in rows:
            mal_id = row.get("mal_id")
            if mal_id is None:
                continue
            merged[int(mal_id)] = row
    return sorted(merged.values(), key=lambda item: str(item.get("name") or "").lower())


def get_tenrai_anime_picker_items() -> dict[str, list[dict[str, Any]]]:
    return _get_tenrai_anime_picker_items_cached(adult_content_enabled())


@use_cache(cache_hours=24)
def _get_tenrai_anime_picker_items_cached(include_adult: bool) -> dict[str, list[dict[str, Any]]]:
    """MAL genres + themes/demographics (+ explicit_genres when adult is enabled)."""
    from resources.lib.indexers.tenrai import TenraiAPI

    tenrai = TenraiAPI()
    genre_filter_names = list(TENRAI_ANIME_GENRE_BUCKET_FILTERS)
    if include_adult:
        genre_filter_names.append(TENRAI_ANIME_EXPLICIT_GENRE_FILTER)

    genre_sources = [tenrai.get_anime_genres_cached(name) for name in genre_filter_names]
    tag_sources = [tenrai.get_anime_genres_cached(name) for name in TENRAI_ANIME_TAG_BUCKET_FILTERS]

    for filter_name, rows in zip(genre_filter_names, genre_sources):
        if not rows:
            g.log(f"Tenrai genres/anime filter={filter_name} returned no rows", "warning")

    for filter_name, rows in zip(TENRAI_ANIME_TAG_BUCKET_FILTERS, tag_sources):
        if not rows:
            g.log(f"Tenrai genres/anime filter={filter_name} returned no rows", "warning")

    return {
        "genres": _merge_tenrai_genre_rows(*genre_sources),
        "tags": _merge_tenrai_genre_rows(*tag_sources),
    }


def tenrai_sort_for_genre_setting() -> tuple[str, str]:
    """Map general.genres.endpoint.anime to Tenrai ``order_by`` + ``sort``.

    MAL ``popularity`` and ``rank`` are rank indices (1 = best) — use ``asc``.
    ``members``, ``score``, and ``scored_by`` use ``desc`` for highest-first.
    """
    segment = genre_sort_segment("anime")
    mapping: dict[str, tuple[str, str]] = {
        "popular-this-week": ("members", "desc"),
        "popular-all-time": ("popularity", "asc"),
        "popular-this-month": ("members", "desc"),
        "rank": ("rank", "asc"),
        "release-date": ("start_date", "desc"),
        "voted": ("score", "desc"),
        "watched": ("members", "desc"),
    }
    return mapping.get(segment, ("popularity", "asc"))


def _resolve_mal_discover_id(mal_id: int) -> dict | None:
    from resources.lib.indexers.simkl import thread_simkl_api
    from resources.lib.simkl.id_resolve import thin_sync_from_redirect

    match = thread_simkl_api().redirect_simkl_id(mal=int(mal_id))
    if not match:
        return None
    simkl_id, resolved_catalog = match
    return thin_sync_from_redirect(simkl_id, resolved_catalog, mal_id=int(mal_id))


def _parallel_resolve_mal_rows(rows: list[dict]) -> dict[int, dict]:
    mal_ids: list[int] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("mal_id") is None:
            continue
        try:
            mal_ids.append(int(row["mal_id"]))
        except (TypeError, ValueError):
            continue
    unique_ids = list(dict.fromkeys(mal_ids))
    if not unique_ids:
        return {}
    from resources.lib.simkl.id_resolve import parallel_map_resolve

    resolved = parallel_map_resolve(unique_ids, _resolve_mal_discover_id, parallel=True)
    return {
        mal_id: row
        for mal_id, row in zip(unique_ids, resolved)
        if isinstance(row, dict) and row.get("simkl_id") is not None
    }


def _append_tenrai_resolved_rows(
    results: list[dict],
    rows: list[dict],
    resolved_by_mal: dict[int, dict],
    seen_simkl_ids: set[int],
) -> None:
    for row in rows:
        if not isinstance(row, dict) or row.get("mal_id") is None:
            continue
        try:
            mal_id = int(row["mal_id"])
        except (TypeError, ValueError):
            continue
        normalized = resolved_by_mal.get(mal_id)
        if not normalized:
            continue
        simkl_id = normalized.get("simkl_id")
        if simkl_id is not None:
            key = int(simkl_id)
            if key in seen_simkl_ids:
                continue
            seen_simkl_ids.add(key)
        results.append(normalized)


_TENRAI_MULTI_GROW_CACHE: dict[tuple[str, str, str, bool, bool], dict[str, Any]] = {}


def _grow_tenrai_multi_genre_stream(
    with_genres: str,
    order_by: str,
    sort: str,
    sfw: bool,
    *,
    or_mode: bool,
    min_items: int,
) -> list[dict]:
    from resources.lib.indexers.tenrai import TenraiAPI, TENRAI_PAGE_SIZE

    key = (with_genres, order_by, sort, sfw, or_mode)
    state = _TENRAI_MULTI_GROW_CACHE.get(key)
    if state is None:
        parsed_ids: list[int] = []
        for part in str(with_genres or "").split(","):
            part = part.strip()
            if part.isdigit():
                parsed_ids.append(int(part))
        state = {
            "items": [],
            "seen_simkl_ids": set(),
            "exhausted": False,
            "or_mode": or_mode,
            "parsed_ids": parsed_ids,
            "and_page": 1,
            "or_index": 0,
            "or_page": 1,
        }
        _TENRAI_MULTI_GROW_CACHE[key] = state

    items: list[dict] = state["items"]
    if len(items) >= min_items or state["exhausted"]:
        return items

    tenrai = TenraiAPI()
    seen_simkl_ids: set[int] = state["seen_simkl_ids"]
    started = time.time()

    if not state["or_mode"]:
        current_page = int(state["and_page"])
        while len(items) < min_items:
            response = tenrai.search_anime(
                page=current_page,
                limit=TENRAI_PAGE_SIZE,
                genres=with_genres,
                order_by=order_by,
                sort=sort,
                sfw=sfw,
            )
            if not response:
                state["exhausted"] = True
                break
            pagination = response.get("pagination") or {}
            rows = response.get("data") or []
            if not rows:
                state["exhausted"] = True
                break
            resolved_by_mal = _parallel_resolve_mal_rows(rows)
            _append_tenrai_resolved_rows(items, rows, resolved_by_mal, seen_simkl_ids)
            if len(items) >= min_items:
                break
            if not pagination.get("has_next_page"):
                state["exhausted"] = True
                break
            current_page += 1
        state["and_page"] = current_page
    else:
        parsed_ids: list[int] = state["parsed_ids"]
        or_index = int(state["or_index"])
        or_page = int(state["or_page"])
        while len(items) < min_items and or_index < len(parsed_ids):
            genre_id = parsed_ids[or_index]
            response = tenrai.search_anime(
                page=or_page,
                limit=TENRAI_PAGE_SIZE,
                genres=str(genre_id),
                order_by=order_by,
                sort=sort,
                sfw=sfw,
            )
            if not response:
                or_index += 1
                or_page = 1
                continue
            pagination = response.get("pagination") or {}
            rows = response.get("data") or []
            if not rows:
                or_index += 1
                or_page = 1
                continue
            resolved_by_mal = _parallel_resolve_mal_rows(rows)
            _append_tenrai_resolved_rows(items, rows, resolved_by_mal, seen_simkl_ids)
            if len(items) >= min_items:
                break
            if pagination.get("has_next_page"):
                or_page += 1
            else:
                or_index += 1
                or_page = 1
        state["or_index"] = or_index
        state["or_page"] = or_page
        if or_index >= len(parsed_ids):
            state["exhausted"] = True

    elapsed_ms = int((time.time() - started) * 1000)
    g.log(
        f"Tenrai multi-genre grow genres={with_genres} or_mode={or_mode} "
        f"items={len(items)} need={min_items} grow_ms={elapsed_ms}",
        "debug",
    )
    return items


def discover_by_tenrai_genres(
    genre_ids: str,
    page_limit: int,
    *,
    menu_page: int = 1,
    tenrai_page: int = 1,
    row_offset: int = 0,
) -> GenreBrowsePage:
    """Tenrai multiselect: cached parallel redirect stream, sliced by Kodi menu page."""
    parsed_ids: list[int] = []
    for part in str(genre_ids or "").split(","):
        part = part.strip()
        if part.isdigit():
            parsed_ids.append(int(part))
    if not parsed_ids:
        return GenreBrowsePage([], False)

    with_genres = ",".join(str(genre_id) for genre_id in parsed_ids)
    order_by, sort = tenrai_sort_for_genre_setting()
    sfw = not adult_content_enabled()
    g.log(
        f"Tenrai anime discover genres={with_genres} order_by={order_by} sort={sort} "
        f"sfw={sfw} (base list={genre_sort_segment('anime')})",
        "debug",
    )

    page_index = max(1, int(menu_page))
    min_items = page_index * page_limit
    or_mode_used = False
    stream = _grow_tenrai_multi_genre_stream(
        with_genres,
        order_by,
        sort,
        sfw,
        or_mode=False,
        min_items=min_items,
    )
    if not stream and len(parsed_ids) > 1:
        g.log(
            f"Tenrai AND genre query returned no rows for {with_genres}; retrying with OR",
            "debug",
        )
        or_mode_used = True
        stream = _grow_tenrai_multi_genre_stream(
            with_genres,
            order_by,
            sort,
            sfw,
            or_mode=True,
            min_items=min_items,
        )

    start = (page_index - 1) * page_limit
    end = start + page_limit
    chunk = stream[start:end]
    tenrai_key = (with_genres, order_by, sort, sfw, or_mode_used)
    tenrai_state = _TENRAI_MULTI_GROW_CACHE.get(tenrai_key) or {}
    has_next = _multi_genre_menu_has_next(
        stream,
        chunk,
        page_limit,
        end,
        grow_exhausted=bool(tenrai_state.get("exhausted")),
    )
    return GenreBrowsePage(chunk, has_next, page_index + 1 if has_next else page_index, 0)


def render_discover_endpoint(catalog: str, endpoint: str) -> bool:
    list_id = DISCOVER_ENDPOINTS.get(catalog, {}).get(endpoint)
    if not list_id:
        g.log(f"No Simkl discover mapping for {catalog}/{endpoint}", "warning")
        return False
    DiscoverRenderer().render_list(catalog, list_id)
    return True


def _simkl_id_from_db(tmdb_id: int, catalog: str) -> int | None:
    from resources.lib.database.session import get_sync_database

    db = get_sync_database()
    if catalog == "movie":
        row = db.fetchone("SELECT simkl_id FROM movies WHERE tmdb_id = ?", (int(tmdb_id),))
    elif catalog == "anime":
        row = db.fetchone(
            "SELECT simkl_id FROM shows WHERE catalog = 'anime' AND tmdb_id = ?",
            (int(tmdb_id),),
        )
    else:
        row = db.fetchone(
            "SELECT simkl_id FROM shows WHERE catalog = 'tv' AND tmdb_id = ?",
            (int(tmdb_id),),
        )
    if row and row.get("simkl_id") is not None:
        return int(row["simkl_id"])
    return None


def _simkl_redirect_tmdb_match(tmdb_id: int, catalog: str) -> tuple[int, str] | None:
    """Resolve TMDB id via GET /redirect (Location header only)."""
    lookup_type = "movie" if catalog == "movie" else "tv"
    return SimklAPI().redirect_simkl_id(tmdb=int(tmdb_id), type=lookup_type)


def _simkl_redirect_mal_match(mal_id: int) -> tuple[int, str] | None:
    return SimklAPI().redirect_simkl_id(mal=int(mal_id))


def _attach_tmdb_id(sync: dict, tmdb_id: int) -> dict:
    sync["tmdb_id"] = int(tmdb_id)
    info = sync.setdefault("simkl_object", {}).setdefault("info", {})
    info["tmdb_id"] = int(tmdb_id)
    if not sync.get("catalog"):
        sync["catalog"] = "movie" if info.get("mediatype") == "movie" else "tv"
    return sync


def _simkl_lookup_by_tmdb_api(tmdb_id: int, catalog: str, *, with_detail: bool = True) -> dict | None:
    from resources.lib.simkl.id_resolve import thin_sync_from_redirect

    match = _simkl_redirect_tmdb_match(tmdb_id, catalog)
    if match:
        simkl_id, resolved_catalog = match
    else:
        simkl_id = _simkl_id_from_db(tmdb_id, catalog)
        if simkl_id is None:
            return None
        resolved_catalog = catalog
        g.log(
            f"Simkl /redirect miss for tmdb={tmdb_id} ({catalog}); using local simkl_id={simkl_id}",
            "debug",
        )
    if not with_detail:
        return thin_sync_from_redirect(simkl_id, resolved_catalog, tmdb_id=int(tmdb_id))
    sync = _simkl_detail_sync_dict(simkl_id, resolved_catalog)
    if not sync:
        g.log(
            f"Simkl detail fetch failed for tmdb={tmdb_id} ({catalog}) simkl_id={simkl_id}",
            "debug",
        )
        return None
    return _attach_tmdb_id(sync, tmdb_id)


@use_cache(cache_hours=24)
def _simkl_lookup_by_tmdb_cached(tmdb_id: int, catalog: str, with_detail: bool = True) -> dict | None:
    return _simkl_lookup_by_tmdb_api(tmdb_id, catalog, with_detail=with_detail)


def _simkl_lookup_by_tmdb(tmdb_id: int, catalog: str) -> dict | None:
    return _simkl_lookup_by_tmdb_cached(int(tmdb_id), catalog)


def resolve_tmdb_to_simkl(tmdb_id: int, catalog: str, *, with_detail: bool = True) -> dict | None:
    normalized = _simkl_lookup_by_tmdb_cached(tmdb_id, catalog, with_detail=with_detail)
    if not normalized:
        return None
    normalized = copy.deepcopy(normalized)
    if not normalized.get("catalog"):
        normalized["catalog"] = catalog
    return normalized


def search_people(query: str, limit: int = 20) -> list[dict]:
    if not _tmdb_runtime_enabled():
        return []
    tmdb = TMDBAPI()
    response = tmdb.get_json("search/person", raw=True, query=query, page=1, language=tmdb.lang_full_code)
    results = (response or {}).get("results") or []
    if not results:
        g.log(f"TMDB person search returned no results for {query!r}", "debug")
    return [row for row in results if isinstance(row, dict)][:limit]


def get_person_combined_cast(person_id: int) -> list[dict]:
    return _fetch_person_combined_cast(int(person_id))


@use_cache(cache_hours=24)
def _fetch_person_combined_cast(person_id: int) -> list[dict]:
    if not _tmdb_runtime_enabled():
        return []
    tmdb = TMDBAPI()
    response = tmdb.get_json(
        f"person/{person_id}/combined_credits",
        raw=True,
        language=tmdb.lang_full_code,
    )
    if not response:
        return []
    cast = [
        row
        for row in (response.get("cast") or [])
        if isinstance(row, dict) and row.get("media_type") in ("movie", "tv")
    ]
    cast.sort(key=lambda c: c.get("popularity") or 0, reverse=True)
    return cast


def credit_catalog(credit: dict) -> str:
    return "movie" if credit.get("media_type") == "movie" else "tv"


def _tmdb_id_from_credit(credit: dict) -> int | None:
    for key in ("id", "tmdb_id"):
        value = credit.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _dedupe_person_credits(cast: list[dict]) -> list[dict]:
    seen: set[tuple[str, int]] = set()
    results: list[dict] = []
    for credit in cast:
        if not isinstance(credit, dict):
            continue
        tmdb_id = _tmdb_id_from_credit(credit)
        media_type = credit.get("media_type")
        if tmdb_id is None or media_type not in ("movie", "tv"):
            continue
        key = (media_type, tmdb_id)
        if key in seen:
            continue
        seen.add(key)
        results.append(credit)
    return results


@use_cache(cache_hours=24)
def get_person_details(person_id: int) -> dict:
    tmdb = TMDBAPI()
    response = tmdb.get_json(
        f"person/{int(person_id)}",
        raw=True,
        language=tmdb.lang_full_code,
    )
    return response if isinstance(response, dict) else {}


def _resolve_person_credit_redirect(credit: dict) -> dict | None:
    """Parallel-safe TMDB credit → thin SyncRow via GET /redirect (per-thread Simkl client)."""
    from resources.lib.indexers.simkl import thread_simkl_api
    from resources.lib.simkl.id_resolve import thin_sync_from_redirect

    tmdb_id = _tmdb_id_from_credit(credit)
    if tmdb_id is None:
        return None
    catalog = credit_catalog(credit)
    lookup_type = "movie" if catalog == "movie" else "tv"
    match = thread_simkl_api().redirect_simkl_id(tmdb=int(tmdb_id), type=lookup_type)
    if match:
        simkl_id, resolved_catalog = match
    else:
        simkl_id = _simkl_id_from_db(tmdb_id, catalog)
        if simkl_id is None:
            return None
        resolved_catalog = catalog
    normalized = thin_sync_from_redirect(simkl_id, resolved_catalog, tmdb_id=int(tmdb_id))
    role = credit.get("character") or credit.get("job")
    if role:
        normalized["_credit_role"] = str(role)
    return normalized


@use_cache(cache_hours=24)
def _person_filmography_resolved_stream(person_id: int) -> list[dict | None]:
    """TMDB popularity-ordered filmography rows (parallel /redirect), cached per person."""
    cast = _dedupe_person_credits(get_person_combined_cast(person_id))
    if not cast:
        return []
    from resources.lib.simkl.id_resolve import parallel_map_resolve

    started = time.time()
    parallel = len(cast) > 1
    rows = parallel_map_resolve(cast, _resolve_person_credit_redirect, parallel=parallel)
    elapsed_ms = int((time.time() - started) * 1000)
    hits = sum(1 for row in rows if isinstance(row, dict) and row.get("simkl_id") is not None)
    g.log(
        f"Actor filmography person={person_id}: parallel redirect resolve "
        f"credits={len(cast)} hits={hits} parallel={parallel} resolve_ms={elapsed_ms}",
        "debug",
    )
    return rows


def _paginate_person_filmography_stream(
    stream: list,
    *,
    page: int,
    page_limit: int,
) -> tuple[list[dict], int, int]:
    """Slice a cached resolve stream (mapped-index pagination, same as legacy sequential scan)."""
    skip = max(0, (page - 1) * page_limit)
    results: list[dict] = []
    mapped = 0
    seen_simkl: set[int] = set()
    cast_len = len(stream)

    for normalized in stream:
        if not isinstance(normalized, dict):
            continue
        simkl_id = normalized.get("simkl_id")
        if simkl_id is None:
            continue
        simkl_id = int(simkl_id)
        if simkl_id in seen_simkl:
            continue
        seen_simkl.add(simkl_id)
        mapped += 1
        if skip > 0:
            skip -= 1
            continue
        if normalized.get("_credit_role"):
            results.append(normalized)
        if len(results) >= page_limit:
            break

    return results, mapped, cast_len


def combined_credits_by_person(person_id: int, page: int, page_limit: int) -> list[dict]:
    """Page TMDB filmography; Simkl IDs from cached parallel /redirect stream."""
    stream = _person_filmography_resolved_stream(int(person_id))
    results, mapped, cast_len = _paginate_person_filmography_stream(
        stream,
        page=page,
        page_limit=page_limit,
    )
    g.log(
        f"Actor filmography person={person_id} page={page}: "
        f"{len(results)} Simkl titles ({mapped} mapped in scan, {cast_len} TMDB credits total)",
        "debug",
    )
    return results


def _attach_mal_id(sync: dict, mal_id: int) -> dict:
    sync["mal_id"] = int(mal_id)
    info = sync.setdefault("simkl_object", {}).setdefault("info", {})
    info["mal_id"] = int(mal_id)
    ids = info.setdefault("ids", {})
    ids["mal"] = int(mal_id)
    if not sync.get("catalog"):
        sync["catalog"] = "anime"
    return sync


def _simkl_lookup_by_mal_api(mal_id: int, *, with_detail: bool = True) -> dict | None:
    from resources.lib.simkl.id_resolve import thin_sync_from_redirect

    match = _simkl_redirect_mal_match(mal_id)
    if not match:
        return None
    simkl_id, resolved_catalog = match
    if not with_detail:
        return thin_sync_from_redirect(simkl_id, resolved_catalog, mal_id=int(mal_id))
    sync = _simkl_detail_sync_dict(simkl_id, resolved_catalog)
    if not sync:
        g.log(
            f"Simkl detail fetch failed for mal={mal_id} simkl_id={simkl_id}",
            "debug",
        )
        return None
    return _attach_mal_id(sync, mal_id)


@use_cache(cache_hours=24)
def _simkl_lookup_by_mal_cached(mal_id: int, with_detail: bool = True) -> dict | None:
    return _simkl_lookup_by_mal_api(mal_id, with_detail=with_detail)


def resolve_mal_to_simkl(mal_id: int, *, with_detail: bool = True) -> dict | None:
    normalized = _simkl_lookup_by_mal_cached(int(mal_id), with_detail=with_detail)
    if not normalized:
        return None
    normalized = copy.deepcopy(normalized)
    if not normalized.get("catalog"):
        normalized["catalog"] = "anime"
    return normalized


def tmdb_discover_page(catalog: str, page: int, page_limit: int, **filters) -> list[dict]:
    if not _tmdb_runtime_enabled():
        return []
    tmdb = TMDBAPI()
    media_type = "movie" if catalog == "movie" else "tv"
    params: dict[str, Any] = {
        "page": page,
        "language": tmdb.lang_full_code,
        "sort_by": filters.pop("sort_by", "popularity.desc"),
        "include_adult": False,
    }
    params.update(filters)
    response = tmdb.get_json(f"discover/{media_type}", raw=True, **params)
    if not response:
        return []
    results = []
    for row in response.get("results") or []:
        tmdb_id = row.get("id")
        if not tmdb_id:
            continue
        normalized = _simkl_lookup_by_tmdb(int(tmdb_id), catalog)
        if normalized:
            results.append(normalized)
        if len(results) >= page_limit:
            break
    return results


def discover_by_year(catalog: str, year: int, page: int, page_limit: int) -> list[dict]:
    if catalog == "movie":
        return tmdb_discover_page(
            catalog,
            page,
            page_limit,
            primary_release_year=year,
            sort_by="popularity.desc",
        )
    return tmdb_discover_page(
        catalog,
        page,
        page_limit,
        first_air_date_year=year,
        sort_by="popularity.desc",
    )


def airing_episodes(date: str = "today") -> list[dict]:
    """Return mixed-episode shaped rows from Simkl /tv/airing."""
    api = SimklAPI()
    rows = api.get_catalog_json("/tv/airing", date=date, sort="time")
    if not rows:
        return []

    episodes = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ids = row.get("ids") or {}
        simkl_id = ids.get("simkl_id") or ids.get("simkl")
        ep = row.get("episode") or {}
        if simkl_id is None or ep.get("season") is None or ep.get("episode") is None:
            continue
        show_id = int(simkl_id)
        season = int(ep["season"])
        episode_num = int(ep["episode"])
        from resources.lib.simkl.ids import attach_tv_context, season_key

        season_id = season_key(show_id, season)
        ep_id = ep.get("ids", {}).get("simkl_id") or (show_id * 1000000 + season * 1000 + episode_num)
        show_slug = ids.get("slug")
        info = {
            "simkl_id": int(ep_id),
            "mediatype": "episode",
            "season": season,
            "episode": episode_num,
            "title": row.get("title"),
            "aired": row.get("date"),
            "first_aired": row.get("date"),
            "tvshowtitle": row.get("title"),
            "score": row.get("rank") or 1.0,
        }
        attach_tv_context(info, show_id, season_num=season, season_row_id=season_id, slug=show_slug)
        episodes.append(
            {
                "simkl_id": int(ep_id),
                "simkl_show_id": show_id,
                "simkl_season_id": season_id,
                "season": season,
                "episode": episode_num,
                "first_aired": row.get("date"),
                "simkl_object": {"info": info},
            }
        )
    return episodes

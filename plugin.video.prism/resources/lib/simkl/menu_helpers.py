"""Shared menu helpers for Simkl-backed browse and general settings."""
from __future__ import annotations

from resources.lib.modules.globals import g

GENRE_SORT_SEGMENTS = (
    "popular-this-week",
    "popular-all-time",
    "popular-this-month",
    "rank",
    "release-date",
    "voted",
    "watched",
)

GENRE_SORT_SETTING_KEYS = {
    "movie": "general.genres.endpoint.movies",
    "tv": "general.genres.endpoint.tv",
    "anime": "general.genres.endpoint.anime",
}

SIMKL_GENRE_MAX_PAGE = 20


def paginate_simkl_lists() -> bool:
    return g.get_bool_setting("general.paginatesimkllists")


def library_list_page(refs: list) -> tuple[list, bool]:
    """
    Apply Paginate Simkl Lists to a pre-sorted ref list.

    Returns (page_refs, no_paging). When pagination is off, or the list fits one
    page, behavior matches loading the full list with no Next Page row.
    """
    if not paginate_simkl_lists():
        return refs, True

    page_limit = g.get_int_setting("item.limit")
    start = (g.PAGE - 1) * page_limit
    return refs[start : start + page_limit], False


def list_filter_kwargs(**overrides) -> dict:
    """
    General-tab hide filters for sync DB list queries.
    Callers may override individual keys (e.g. discover keeps skip_mill separate).
    """
    defaults = {
        "hide_unaired": g.get_bool_setting("general.hideUnAired"),
        "hide_watched": g.get_bool_setting("general.hideWatched"),
        "hide_specials": g.get_bool_setting("general.hideSpecials"),
    }
    defaults.update(overrides)
    return defaults


def genre_sort_segment(catalog: str) -> str:
    """Simkl genre browse sort path segment from general.genres.endpoint.* settings."""
    key = GENRE_SORT_SETTING_KEYS.get(catalog, GENRE_SORT_SETTING_KEYS["movie"])
    index = g.get_int_setting(key, 1)
    if index < 0 or index >= len(GENRE_SORT_SEGMENTS):
        index = 1
    return GENRE_SORT_SEGMENTS[index]


def genre_page_has_next(page: int, result_count: int, page_limit: int) -> bool:
    """Fallback when Simkl pagination headers are missing."""
    if result_count < page_limit:
        return False
    return int(page) < SIMKL_GENRE_MAX_PAGE


def simkl_pagination_has_next(
    pagination: dict[str, int],
    *,
    fallback_page: int,
    fallback_count: int,
    fallback_limit: int,
) -> bool:
    """True when Simkl reports another page via ``X-Pagination-*`` headers."""
    current_page = pagination.get("page", int(fallback_page))
    page_count = pagination.get("page_count")
    if page_count is not None:
        return current_page < page_count
    return genre_page_has_next(fallback_page, fallback_count, fallback_limit)

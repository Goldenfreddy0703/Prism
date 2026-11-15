"""Mixed lists for skin widgets. Tools → Widgets."""
from __future__ import annotations

from resources.lib.modules.globals import g

_CATALOGS = ("movie", "tv", "anime")
_PER_CATALOG = 100
_TRENDING = {
    "today": 31447,
    "week": 31448,
    "month": 31449,
}
# Same discover queries, run on each catalog and mixed together.
# Movies call "in theaters" ongoing_movies; TV and anime call it ongoing.
# IMDb is the external rating for movies and TV. Anime uses MAL.
_DISCOVER = (
    ("popular", 31450, {"movie": "popular", "tv": "popular", "anime": "popular"}),
    ("most_watched", 31451, {"movie": "most_watched", "tv": "most_watched", "anime": "most_watched"}),
    ("anticipated", 31452, {"movie": "anticipated", "tv": "anticipated", "anime": "anticipated"}),
    ("top_simkl", 31453, {"movie": "top_simkl", "tv": "top_simkl", "anime": "top_simkl"}),
    ("top_external", 31454, {"movie": "top_imdb", "tv": "top_imdb", "anime": "top_mal"}),
    ("new_year", 31455, {"movie": "new_year", "tv": "new_year", "anime": "new_year"}),
    ("new_releases", 31456, {"movie": "new_releases", "tv": "new_releases", "anime": "new_releases"}),
    ("low_drop", 31457, {"movie": "low_drop", "tv": "low_drop", "anime": "low_drop"}),
    ("ongoing", 31458, {"movie": "ongoing_movies", "tv": "ongoing", "anime": "ongoing"}),
    ("ended", 31459, {"movie": "ended", "tv": "ended", "anime": "ended"}),
)
_DISCOVER_QUERIES = {key: queries for key, _label, queries in _DISCOVER}
_MENU = [("today", 31447), ("week", 31448), ("month", 31449), *_DISCOVER]


def show_widget_menu() -> None:
    for key, label_id, *_rest in _MENU:
        g.add_directory_item(
            g.get_language_string(label_id),
            action="widgetMixedList",
            action_args=key,
            description=g.get_language_string(31446),
            menu_item=g.create_icon_dict("list", g.ICONS_PATH),
        )
    g.close_directory(g.CONTENT_MENU)


def render_mixed_trending(window: str | None) -> None:
    key = str(window or "today").strip().lower()
    if key not in _TRENDING and key not in _DISCOVER_QUERIES:
        key = "today"
    if g.FROM_WIDGET:
        from resources.lib.modules.widget_loader import mark_widget_session_loaded

        mark_widget_session_loaded(f"widget.mixed.{key}")

    mixed = _trending_items(key) if key in _TRENDING else _discover_items(key)
    limit = g.get_int_setting("item.limit") or 20
    start = max(g.PAGE - 1, 0) * limit
    page = mixed[start : start + limit]
    from resources.lib.simkl.media_ref import render_mixed_sync_list

    render_mixed_sync_list(
        page,
        list_id=f"widget_mixed_{key}",
        no_paging=False,
        has_next_page=start + limit < len(mixed),
        next_action="widgetMixedList",
        next_args=key,
        hide_unaired=g.get_bool_setting("general.hideUnAired"),
        hide_watched=True if g.FROM_WIDGET else g.get_bool_setting("general.hideWatched"),
        paint_profile="browse",
        menu_action="widgetMixedList",
        enrichment_reason="discover",
    )


def _interleave(columns: list[list[dict]]) -> list[dict]:
    mixed: list[dict] = []
    longest = max((len(column) for column in columns), default=0)
    for index in range(longest):
        for column in columns:
            if index < len(column):
                mixed.append(column[index])
    return mixed


def _trending_items(window: str) -> list[dict]:
    from resources.lib.indexers.simkl_cdn import SimklCDN
    from resources.lib.simkl.media_ref import normalize_simkl_item

    payload = SimklCDN().trending_combined(window, _PER_CATALOG)
    if not isinstance(payload, dict):
        return []
    columns = []
    for field, catalog in (("movies", "movie"), ("tv", "tv"), ("anime", "anime")):
        rows = payload.get(field) or []
        if not isinstance(rows, list):
            rows = []
        column = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = normalize_simkl_item(row, catalog)
            if item:
                column.append(item)
        columns.append(column)
    return _interleave(columns)


def _discover_items(key: str) -> list[dict]:
    from resources.lib.discover.cdn_store import rows_for_catalog
    from resources.lib.discover.query_engine import query_all_rows
    from resources.lib.discover.renderer import DiscoverRenderer, _POST_FILTER_QUERIES
    from resources.lib.simkl.media_ref import normalize_discover_db_row

    queries = _DISCOVER_QUERIES[key]
    renderer = DiscoverRenderer()
    columns = []
    for catalog in _CATALOGS:
        query_name = queries[catalog]
        rows = query_all_rows(rows_for_catalog(catalog), query_name, catalog=catalog)
        if query_name in _POST_FILTER_QUERIES:
            rows = renderer._post_filter(query_name, rows, catalog)
        column = []
        for row in rows[:_PER_CATALOG]:
            item = normalize_discover_db_row(row, catalog)
            if item:
                column.append(item)
        columns.append(column)
    return _interleave(columns)

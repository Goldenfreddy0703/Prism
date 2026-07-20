"""Render discover lists into Kodi directories."""
from __future__ import annotations

import json

import xbmcgui

from resources.lib.discover.definitions import Catalog, DiscoverList, get_list
from resources.lib.discover.normalize import runtime_minutes
from resources.lib.discover.cdn_store import rows_for_catalog
from resources.lib.discover.query_engine import query_rows
from resources.lib.indexers.simkl_cdn import SimklCDN
from resources.lib.modules.globals import g
from resources.lib.simkl.media_ref import (
    enrich_and_persist,
    normalize_discover_db_rows,
    normalize_simkl_items,
    paginate_items,
)
from resources.lib.simkl.menu_helpers import list_filter_kwargs


# Discover lists honor general-tab hide filters; skip_mill avoids sync milling on browse refs.
DISCOVER_LIST_KWARGS = {**list_filter_kwargs(), "skip_mill": True}


def discover_list_kwargs() -> dict:
    """Shared list-builder kwargs for all fast hybrid menus (discover, search, library, etc.)."""
    kwargs = dict(DISCOVER_LIST_KWARGS)
    from resources.lib.modules.meta_enrichment_queue import meta_enrichment_background, hybrid_foreground_first_page

    if meta_enrichment_background() and not hybrid_foreground_first_page():
        kwargs["skip_update"] = True
    if g.get_bool_setting("general.menucaching", True):
        kwargs.setdefault("menu_cache", True)
    else:
        kwargs.setdefault("menu_cache", False)
    return kwargs

# DB lists that load a candidate pool in SQL, rank/filter in Python, then paginate in memory.
_POST_FILTER_QUERIES = frozenset(
    {"top_simkl", "top_imdb", "top_mal", "hidden_gems", "completed", "quick_watch"}
)

# Icon filenames use the "shows" prefix for the tv catalog.
_ICON_PREFIX = {"movie": "movies", "tv": "shows", "anime": "anime"}

_CALENDAR_MENU = {
    "movie": ("movieAiringCalendar", "Weekly Movie Calendar", "movies_calendar"),
    "tv": ("tvAiringCalendar", "Weekly Show Calendar", "shows_calendar"),
    "anime": ("animeAiringCalendar", "Weekly Anime Calendar", "anime_calendar"),
}

_GENRE_MENU = {
    "movie": "movieGenres",
    "tv": "tvGenres",
    "anime": "animeGenres",
}

def _discover_genre_menu_icon(catalog: Catalog):
    from resources.lib.simkl import browse

    return browse.discover_genre_menu_icon(catalog)

# Map a discover list's trailing token to an icon suffix shared by all three catalogs.
_LIST_ICON_KIND = {
    "today": "trending",
    "week": "trending",
    "month": "trending",
    "popular": "popular",
    "most_watched": "watched",
    "anticipated": "anticipated",
    "top_simkl": "simkl",
    "top_imdb": "simkl",
    "top_mal": "simkl",
    "top_mdblist": "simkl",
    "hidden_gems": "recommended",
    "awards": "recommended",
    "completed": "collected",
    "ended": "collected",
    "binge": "progress",
    "new_year": "new",
    "new": "new",
    "quick_watch": "recent",
    "short": "recent",
    "dvd": "recent",
    "low_drop": "played",
    "ongoing": "calendar",
    "tba": "calendar",
}


def _discover_list_icon(item: DiscoverList) -> str:
    """Resolve a discover list to an icon slug, falling back to the base catalog icon."""
    prefix = _ICON_PREFIX.get(item.catalog, "movies")
    token = item.list_id.split("_", 1)[1] if "_" in item.list_id else item.list_id
    kind = _LIST_ICON_KIND.get(token)
    return f"{prefix}_{kind}" if kind else prefix


class DiscoverRenderer:
    def __init__(self):
        self.page_size = g.get_int_setting("item.limit", 25)
        self.cdn = SimklCDN()

    @staticmethod
    def show_discover_menu(catalog: Catalog):
        from resources.lib.discover.definitions import CATALOG_LISTS
        from resources.lib.modules.metadata_providers import filter_discover_lists, provider_enabled

        search_actions = {
            "movie": ("moviesSearch", "moviesSearchHistory"),
            "tv": ("showsSearch", "showsSearchHistory"),
            "anime": ("animeSearch", "animeSearchHistory"),
        }
        search_labels = {
            "movie": 30025,
            "tv": 30026,
            "anime": 30769,
        }
        actor_action = "actorSearchHistory" if g.get_bool_setting("searchHistory") else "searchByActor"

        cal_action, cal_label, cal_icon = _CALENDAR_MENU[catalog]
        g.add_directory_item(
            cal_label,
            action=cal_action,
            catalog=catalog,
            description=cal_label,
            menu_item=g.create_icon_dict(cal_icon, g.ICONS_PATH),
        )

        for item in filter_discover_lists(CATALOG_LISTS[catalog]):
            g.add_directory_item(
                item.label,
                action="simklDiscoverList",
                catalog=catalog,
                list_id=item.list_id,
                description=item.label,
                menu_item=g.create_icon_dict(_discover_list_icon(item), g.ICONS_PATH),
            )

        g.add_directory_item(
            g.get_language_string(30042),
            action=_GENRE_MENU[catalog],
            catalog=catalog,
            description=g.get_language_string(30042),
            menu_item=_discover_genre_menu_icon(catalog),
        )

        if catalog in search_actions:
            if provider_enabled("tmdb"):
                g.add_directory_item(
                    g.get_language_string(30327),
                    action=actor_action,
                    catalog=catalog,
                    description=g.get_language_string(30776),
                    menu_item=g.create_icon_dict(f"{_ICON_PREFIX.get(catalog, 'movies')}_actor", g.ICONS_PATH),
                )
            direct_action, history_action = search_actions[catalog]
            action = history_action if g.get_bool_setting("searchHistory") else direct_action
            g.add_directory_item(
                g.get_language_string(search_labels[catalog]),
                action=action,
                description=g.get_language_string(30770 if catalog == "anime" else (30371 if catalog == "movie" else 30372)),
                menu_item=g.create_icon_dict(f"{_ICON_PREFIX.get(catalog, 'movies')}_search", g.ICONS_PATH),
            )
        g.close_directory(g.CONTENT_MENU)

    def _collect_page_items(self, discover_list: DiscoverList, catalog: Catalog, page: int) -> tuple[list, bool]:
        if discover_list.source == "cdn":
            raw_items = self._fetch_cdn(discover_list, catalog)
            sync_items = normalize_simkl_items(raw_items, catalog)
            page_items = paginate_items(sync_items, page, self.page_size)
            has_next = page * self.page_size < len(sync_items)
            return page_items, has_next

        query_name = discover_list.db_query or ""
        sync_items = self._fetch_db(discover_list, catalog, page=page)
        if query_name in _POST_FILTER_QUERIES:
            page_items = paginate_items(sync_items, page, self.page_size)
            has_next = page * self.page_size < len(sync_items)
        else:
            page_items = sync_items
            has_next = len(sync_items) >= self.page_size
        return page_items, has_next

    def prefetch_page(self, catalog: Catalog, list_id: str, page: int) -> None:
        """Warm sync DB + background enrichment for a discover page (no Kodi UI)."""
        discover_list = get_list(catalog, list_id)
        if discover_list is None:
            return
        from resources.lib.modules.metadata_providers import discover_list_visible

        if not discover_list_visible(discover_list):
            return

        page_items, _has_next = self._collect_page_items(discover_list, catalog, int(page))
        if not page_items:
            return

        refs = enrich_and_persist(catalog, page_items, force_simkl_meta=True, enrich=False)
        from resources.lib.modules.page_prefetch import enrich_refs_blocking

        enrich_refs_blocking(refs, catalog, reason="prefetch_discover")

    def render_list(self, catalog: Catalog, list_id: str):
        discover_list = get_list(catalog, list_id)
        if discover_list is None:
            xbmcgui.Dialog().ok(g.ADDON_NAME, f"Unknown discover list: {list_id}")
            g.cancel_directory()
            return

        from resources.lib.modules.metadata_providers import discover_list_visible

        if not discover_list_visible(discover_list):
            xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30964))
            g.cancel_directory()
            return

        page_items, has_next = self._collect_page_items(discover_list, catalog, g.PAGE)

        if not page_items:
            empty_msg = (
                "No upcoming items found."
                if discover_list.cdn_path and discover_list.cdn_path.startswith("/calendar/")
                else "No items found."
            )
            xbmcgui.Dialog().ok(g.ADDON_NAME, empty_msg)
            g.cancel_directory()
            return

        from resources.lib.modules.meta_enrichment_queue import hybrid_enrich_on_insert

        blocking_enrich = hybrid_enrich_on_insert()
        show_busy = blocking_enrich and not g.FROM_WIDGET
        if show_busy:
            g.show_busy_dialog()
        try:
            refs = enrich_and_persist(
                catalog,
                page_items,
                force_simkl_meta=True,
                enrich=blocking_enrich,
            )

            from resources.lib.modules.list_builder import ListBuilder
            from resources.lib.simkl.field_map import display_rating_priority_for_discover

            builder_kwargs = discover_list_kwargs()
            builder_kwargs["display_rating_priority"] = display_rating_priority_for_discover(
                catalog,
                discover_list.db_query if discover_list.source == "db" else None,
            )
            if has_next:
                builder_kwargs["next_action"] = "simklDiscoverList"
                builder_kwargs["has_next_page"] = True
                builder_kwargs["list_id"] = list_id

            builder = ListBuilder()
            if catalog == "anime":
                builder.anime_discover_builder(refs, **builder_kwargs)
            elif catalog == "movie":
                builder.movie_discover_builder(refs, **builder_kwargs)
            else:
                builder.show_discover_builder(refs, **builder_kwargs)
        finally:
            if show_busy:
                g.close_busy_dialog()

    def _fetch_cdn(self, discover_list: DiscoverList, catalog: Catalog) -> list:
        if not discover_list.cdn_path:
            return []
        data = self.cdn.fetch_json(discover_list.cdn_path)
        if not isinstance(data, list):
            return []
        if discover_list.cdn_path.startswith("/calendar/"):
            from resources.lib.calendar.simkl_calendar import filter_coming_soon_rows

            return filter_coming_soon_rows(data, catalog=catalog)
        return data

    def _fetch_db(self, discover_list: DiscoverList, catalog: Catalog, *, page: int | None = None) -> list[dict]:
        if not discover_list.db_query:
            return []

        page_num = g.PAGE if page is None else int(page)
        query_name = discover_list.db_query
        catalog_rows = rows_for_catalog(catalog)
        if not catalog_rows:
            return []

        offset = 0 if query_name in _POST_FILTER_QUERIES else (page_num - 1) * self.page_size
        rows = query_rows(
            catalog_rows,
            query_name,
            catalog=catalog,
            limit=self.page_size if query_name not in _POST_FILTER_QUERIES else 500,
            offset=offset,
        )
        rows = self._post_filter(query_name, rows, catalog)
        return normalize_discover_db_rows(rows, catalog)

    def _post_filter(self, query_name: str, rows: list[dict], catalog: str) -> list[dict]:
        if query_name == "top_simkl":
            return self._sort_ratings(rows, "simkl", min_votes=50)[:100]
        if query_name == "top_imdb":
            return self._sort_ratings(rows, "imdb", min_votes=1000)[:100]
        if query_name == "top_mal":
            return self._sort_ratings(rows, "mal", min_votes=500)[:100]
        if query_name == "hidden_gems":
            return self._hidden_gems(rows)[:100]
        if query_name == "completed":
            return self._sort_ratings(rows, "imdb" if catalog != "anime" else "mal", min_votes=100, min_rating=7.5)[:100]
        if query_name == "quick_watch":
            return self._quick_watch(rows)[:100]
        return rows

    @staticmethod
    def _parse_ratings(row: dict) -> dict:
        raw = row.get("ratings_json")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _sort_ratings(self, rows, source: str, min_votes: int, min_rating: float = 0.0, limit: int = 100):
        scored = []
        for row in rows:
            ratings = self._parse_ratings(row)
            src = ratings.get(source) or {}
            rating = src.get("rating")
            votes = src.get("votes") or 0
            if rating is None or votes < min_votes or rating < min_rating:
                continue
            scored.append((float(rating), int(votes), row))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [row for _, _, row in scored[:limit]]

    def _hidden_gems(self, rows: list[dict]) -> list[dict]:
        watched_values = [r.get("watched") or 0 for r in rows if self._row_quality_score(r) > 0]
        if not watched_values:
            return rows
        median = sorted(watched_values)[len(watched_values) // 2]
        gems = [r for r in rows if (r.get("watched") or 0) <= median]
        gems.sort(key=self._row_quality_score, reverse=True)
        return gems

    def _row_quality_score(self, row: dict) -> float:
        mdblist_score = row.get("mdblist_score")
        if mdblist_score:
            try:
                return float(mdblist_score)
            except (TypeError, ValueError):
                pass
        ratings = self._parse_ratings(row)
        simkl = ratings.get("simkl") or {}
        try:
            return float(simkl.get("rating") or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _quick_watch(rows: list[dict]) -> list[dict]:
        result = []
        for row in rows:
            runtime = row.get("runtime") or ""
            minutes = runtime_minutes(runtime)
            if minutes is not None and minutes <= 90:
                result.append(row)
        result.sort(key=lambda r: DiscoverRenderer._row_quality_score_static(r), reverse=True)
        return result

    @staticmethod
    def _row_quality_score_static(row: dict) -> float:
        mdblist_score = row.get("mdblist_score")
        if mdblist_score:
            try:
                return float(mdblist_score)
            except (TypeError, ValueError):
                pass
        raw = row.get("ratings_json")
        if not raw:
            return 0.0
        try:
            ratings = json.loads(raw)
        except json.JSONDecodeError:
            return 0.0
        simkl = ratings.get("simkl") or {}
        try:
            return float(simkl.get("rating") or 0)
        except (TypeError, ValueError):
            return 0.0

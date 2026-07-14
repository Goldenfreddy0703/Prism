"""Anime browse menus — backed by Simkl discover lists."""
from functools import cached_property

from resources.lib.indexers import simkl_auth_guard
from resources.lib.modules.globals import g


class Menus:
    def __init__(self):
        self.page_limit = g.get_int_setting("item.limit")
        self.page_start = (g.PAGE - 1) * self.page_limit
        self.page_end = g.PAGE * self.page_limit

    @cached_property
    def shows_database(self):
        from resources.lib.database.simkl_sync.shows import SimklSyncDatabase

        return SimklSyncDatabase()

    @cached_property
    def search_history(self):
        from resources.lib.database.searchHistory import SearchHistory

        return SearchHistory()

    @cached_property
    def list_builder(self):
        from resources.lib.modules.list_builder import ListBuilder

        return ListBuilder()

    def discover_anime(self):
        from resources.lib.discover.renderer import DiscoverRenderer

        DiscoverRenderer.show_discover_menu("anime")

    def anime_search_history(self):
        from resources.lib.simkl.search_menus import render_search_history

        render_search_history(
            "anime",
            new_search_action="animeSearch",
            new_search_label_id=30771,
            new_search_description_id=30770,
            results_action="animeSearchResults",
            clear_mediatype="anime",
        )

    def anime_search(self, query=None):
        from resources.lib.simkl.search_menus import normalize_search_query, persist_search_pagination

        query = normalize_search_query(query)
        if query is None:
            query = g.get_keyboard_input(heading=g.get_language_string(30013))
            if not query:
                g.cancel_directory()
                return

        if g.get_bool_setting("searchHistory"):
            self.search_history.add_search_history("anime", query)

        persist_search_pagination(query)
        self.anime_search_results(query)

    def anime_search_results(self, query):
        from resources.lib.simkl.search_menus import (
            filter_search_results,
            normalize_search_query,
            notify_empty_search,
            persist_search_pagination,
        )

        query = normalize_search_query(query)
        if not query:
            g.cancel_directory()
            return

        persist_search_pagination(query)
        from resources.lib.discover.renderer import discover_list_kwargs
        from resources.lib.simkl.media_ref import persist_search_results
        from resources.lib.simkl.search import search_page

        media_list = search_page(
            "search/anime",
            "shows",
            g.PAGE,
            self.page_limit,
            query,
        )

        filtered = filter_search_results(media_list)
        if not filtered:
            notify_empty_search(30766)
            return
        refs = persist_search_results("anime", filtered)
        self.list_builder.anime_discover_builder(refs, **discover_list_kwargs())

    def anime_genres(self):
        from resources.lib.simkl.genre_menus import show_genre_picker

        show_genre_picker("anime")

    def anime_genre_list(self, args):
        from resources.lib.simkl.genre_menus import render_genre_list

        render_genre_list("anime", args, self.page_limit, self.list_builder)

    def anime_genres_multi(self):
        from resources.lib.simkl.genre_menus import show_tenrai_anime_multiselect

        show_tenrai_anime_multiselect(self.page_limit, self.list_builder)

    def anime_genres_multi_list(self, args):
        from resources.lib.simkl.genre_menus import render_anime_multi_genre_list

        render_anime_multi_genre_list(args, self.page_limit, self.list_builder)

    def _render_discover(self, list_id: str):
        from resources.lib.discover.renderer import DiscoverRenderer

        DiscoverRenderer().render_list("anime", list_id)

    def anime_shows_popular(self):
        self._render_discover("anime_popular")

    def anime_shows_trending(self):
        self._render_discover("anime_week")

    def anime_shows_popular_recent(self):
        self._render_discover("anime_new_year")

    def anime_shows_trending_recent(self):
        self._render_discover("anime_week")

    def anime_shows_new(self):
        self._render_discover("anime_new")

    def anime_shows_played(self):
        self._render_discover("anime_most_watched")

    def anime_shows_watched(self):
        self._render_discover("anime_most_watched")

    def anime_shows_collected(self):
        self._render_discover("anime_completed")

    def anime_shows_anticipated(self):
        self._render_discover("anime_anticipated")

    def anime_movies_popular(self):
        self._render_discover("anime_popular")

    def anime_movies_trending(self):
        self._render_discover("anime_week")

    def anime_movies_popular_recent(self):
        self._render_discover("anime_new_year")

    def anime_movies_trending_recent(self):
        self._render_discover("anime_week")

    def anime_movies_new(self):
        self._render_discover("anime_new")

    def anime_movies_played(self):
        self._render_discover("anime_most_watched")

    def anime_movies_watched(self):
        self._render_discover("anime_most_watched")

    def anime_movies_collected(self):
        self._render_discover("anime_completed")

    def anime_movies_anticipated(self):
        self._render_discover("anime_anticipated")

    @staticmethod
    @simkl_auth_guard
    def my_anime():
        from resources.lib.simkl.library_menus import my_anime_hub

        my_anime_hub()

    @simkl_auth_guard
    def on_deck_anime(self):
        from resources.lib.simkl.library_menus import render_continue_watching_episodes

        render_continue_watching_episodes("anime")

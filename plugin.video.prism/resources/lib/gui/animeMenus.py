"""Anime browse menus — discover, search, genres, and library (mirrors movie/tv menu layout)."""
from functools import cached_property

from resources.lib.indexers import simkl_auth_guard
from resources.lib.modules.globals import g
from resources.lib.simkl import browse


class Menus:
    def __init__(self):
        self.page_limit = g.get_int_setting("item.limit")
        self.page_start = (g.PAGE - 1) * self.page_limit
        self.page_end = g.PAGE * self.page_limit

    @cached_property
    def search_history(self):
        from resources.lib.database.searchHistory import SearchHistory

        return SearchHistory()

    @cached_property
    def list_builder(self):
        from resources.lib.modules.list_builder import ListBuilder

        return ListBuilder()

    ######################################################
    # DISCOVER
    ######################################################

    @staticmethod
    def discover_anime():
        from resources.lib.discover.renderer import DiscoverRenderer

        DiscoverRenderer.show_discover_menu("anime")

    def generic_endpoint(self, endpoint):
        if not browse.render_discover_endpoint("anime", endpoint):
            g.cancel_directory()

    def anime_popular_recent(self):
        browse.render_discover_endpoint("anime", "popular_recent")

    def anime_trending_recent(self):
        browse.render_discover_endpoint("anime", "trending_recent")

    ######################################################
    # SEARCH
    ######################################################

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
            normalize_search_query,
            persist_search_pagination,
            render_search_results_list,
        )

        query = normalize_search_query(query)
        if not query:
            g.cancel_directory()
            return

        persist_search_pagination(query)
        render_search_results_list("anime", query, self.page_limit, self.list_builder)

    ######################################################
    # GENRES
    ######################################################

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

    ######################################################
    # LIBRARY
    ######################################################

    @staticmethod
    @simkl_auth_guard
    def my_anime():
        from resources.lib.simkl.library_menus import my_anime_hub

        my_anime_hub()

    @simkl_auth_guard
    def on_deck_anime(self):
        from resources.lib.simkl.library_menus import render_continue_watching_episodes

        render_continue_watching_episodes("anime")

"""Simkl unified title search (movies + TV + anime)."""

from __future__ import annotations

from functools import cached_property

from resources.lib.modules.globals import g


class SearchAllMenus:
    def __init__(self):
        self.page_limit = g.get_int_setting("item.limit")

    @cached_property
    def search_history(self):
        from resources.lib.database.searchHistory import SearchHistory

        return SearchHistory()

    @cached_property
    def list_builder(self):
        from resources.lib.modules.list_builder import ListBuilder

        return ListBuilder()

    def all_search_history(self):
        from resources.lib.simkl.search_menus import render_search_history

        render_search_history(
            "all",
            new_search_action="allSearch",
            new_search_label_id=31239,
            new_search_description_id=31237,
            results_action="allSearchResults",
            clear_mediatype="all",
        )

    def all_search(self, query=None):
        from resources.lib.simkl.search_menus import normalize_search_query, persist_search_pagination

        query = normalize_search_query(query)
        if query is None:
            query = g.get_keyboard_input(heading=g.get_language_string(30013))
            if not query:
                g.cancel_directory()
                return

        if g.get_bool_setting("searchHistory"):
            self.search_history.add_search_history("all", query)

        persist_search_pagination(query)
        self.all_search_results(query)

    def all_search_results(self, query):
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
        render_search_results_list("all", query, self.page_limit, self.list_builder)

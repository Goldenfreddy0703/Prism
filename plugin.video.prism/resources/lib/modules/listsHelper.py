import xbmcgui

from resources.lib.discover.renderer import discover_list_kwargs
from resources.lib.modules.globals import g
from resources.lib.modules.list_builder import ListBuilder
from resources.lib.simkl.library_cache import load_library_list_refs
from resources.lib.simkl.menu_helpers import library_list_page


class ListsHelper:
    WATCHLIST_STATUSES = [
        ("plantowatch", 30732),
        ("watching", 30733),
        ("completed", 30736),
        ("hold", 30734),
        ("dropped", 30735),
    ]

    def __init__(self):
        self.title_appends = g.get_setting("general.appendListTitles")
        self.builder = ListBuilder()

    def my_simkl_lists(self, media_type):
        """Legacy folder — prefer flat hubs in library_menus."""
        catalog = self._catalog_for_media_type(media_type)
        for status, string_id in self.WATCHLIST_STATUSES:
            if status == "watching" and catalog == "movie":
                continue
            if status == "hold" and catalog == "movie":
                continue
            g.add_directory_item(
                g.get_language_string(string_id),
                action="simklLibraryList",
                catalog=catalog,
                status=status,
            )
        g.close_directory(g.CONTENT_MENU)

    def get_list_items(self):
        media_type = g.REQUEST_PARAMS.get("mediatype", "shows")
        status = g.REQUEST_PARAMS.get("status", "plantowatch")
        catalog = self._catalog_for_media_type(media_type)

        refs = load_library_list_refs(catalog, status)
        if not refs:
            g.cancel_directory()
            return
        refs, no_paging = library_list_page(refs)
        list_kwargs = discover_list_kwargs()
        if catalog == "movie":
            self.builder.movie_menu_builder(refs, no_paging=no_paging, library_status=status, **list_kwargs)
        else:
            self.builder.show_list_builder(
                refs,
                no_paging=no_paging,
                library_status=status,
                catalog=catalog,
                **list_kwargs,
            )

    def my_liked_lists(self, media_type):
        xbmcgui.Dialog().ok(g.ADDON_NAME, "Simkl does not expose liked public lists in this addon yet.")
        g.cancel_directory()

    def trending_lists(self, media_type):
        xbmcgui.Dialog().ok(g.ADDON_NAME, "Use Discover menus for Simkl trending lists.")
        g.cancel_directory()

    def popular_lists(self, media_type):
        xbmcgui.Dialog().ok(g.ADDON_NAME, "Use Discover menus for Simkl popular lists.")
        g.cancel_directory()

    @staticmethod
    def _catalog_for_media_type(media_type):
        if media_type in ("movie", "movies"):
            return "movie"
        if media_type == "anime":
            return "anime"
        return "tv"

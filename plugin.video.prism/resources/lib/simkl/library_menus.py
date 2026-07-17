"""Simkl My Library hub menus — flat status lists for movies, TV, and anime."""
from __future__ import annotations

from resources.lib.indexers import simkl_auth_guard
from resources.lib.modules.globals import g
from resources.lib.simkl.menu_helpers import (
    library_list_page,
    list_filter_kwargs,
    paginate_simkl_lists,
)
from resources.lib.simkl.statuses import MOVIE_STATUS_OPTIONS, SHOW_STATUS_OPTIONS

_MOVIE_META = {
    "plantowatch": ("movies_watched", 30740),
    "completed": ("movies_watched", 30741),
    "dropped": ("movies_watched", 30742),
}
_SHOW_META = {
    "watching": ("shows_progress", 30743),
    "plantowatch": ("shows_watched", 30744),
    "hold": ("shows_collected", 30745),
    "completed": ("shows_watched", 30746),
    "dropped": ("shows_watched", 30747),
}

_MOVIE_STATUSES = tuple((s, lid, *_MOVIE_META[s]) for s, lid in MOVIE_STATUS_OPTIONS)
_SHOW_STATUSES = tuple((s, lid, *_SHOW_META[s]) for s, lid in SHOW_STATUS_OPTIONS)


def _add_library_item(label_id: int, action: str, icon: str, desc_id: int, **params) -> None:
    g.add_directory_item(
        g.get_language_string(label_id),
        action=action,
        description=g.get_language_string(desc_id),
        menu_item=g.create_icon_dict(icon, g.ICONS_PATH),
        **params,
    )


def _add_status_item(catalog: str, status: str, label_id: int, icon: str, desc_id: int) -> None:
    _add_library_item(
        label_id,
        "simklLibraryList",
        icon,
        desc_id,
        catalog=catalog,
        status=status,
    )


@simkl_auth_guard
def my_movies_hub() -> None:
    _add_library_item(30731, "onDeckMovies", "movies_progress", 30748)
    for status, label_id, icon, desc_id in _MOVIE_STATUSES:
        _add_status_item("movie", status, label_id, icon, desc_id)
    _add_library_item(30326, "myWatchedMovies", "movies_watched", 30415)
    g.close_directory(g.CONTENT_MENU)


@simkl_auth_guard
def my_shows_hub() -> None:
    _add_library_item(30731, "onDeckShows", "shows_progress", 30433)
    for status, label_id, icon, desc_id in _SHOW_STATUSES:
        _add_status_item("tv", status, label_id, icon, desc_id)
    _add_library_item(30210, "showsNextUp", "shows_nextup", 30436, catalog="tv")
    _add_library_item(30090, "showsRecentlyWatched", "shows_recent", 30479, catalog="tv")
    _add_library_item(30325, "myWatchedEpisodes", "shows_watched", 30442, catalog="tv")
    g.close_directory(g.CONTENT_MENU)


@simkl_auth_guard
def my_anime_hub() -> None:
    _add_library_item(30731, "onDeckAnime", "shows_progress", 30749)
    for status, label_id, icon, desc_id in _SHOW_STATUSES:
        _add_status_item("anime", status, label_id, icon, desc_id)
    _add_library_item(30210, "animeNextUp", "shows_nextup", 30750)
    _add_library_item(30090, "animeRecentlyWatched", "shows_recent", 30751)
    _add_library_item(30325, "animeWatchedEpisodes", "shows_watched", 30752)
    g.close_directory(g.CONTENT_MENU)


def render_status_list(catalog: str, status: str) -> None:
    from resources.lib.discover.renderer import discover_list_kwargs
    from resources.lib.modules.list_builder import ListBuilder
    from resources.lib.simkl.library_cache import load_library_list_refs

    list_kwargs = discover_list_kwargs()
    list_kwargs.update(list_filter_kwargs(hide_unaired=False, hide_watched=False))

    refs = load_library_list_refs(catalog, status)

    if not refs:
        g.cancel_directory()
        return

    refs, no_paging = library_list_page(refs)

    if catalog == "movie":
        ListBuilder().movie_menu_builder(refs, no_paging=no_paging, library_status=status, **list_kwargs)
        return

    ListBuilder().show_list_builder(
        refs,
        no_paging=no_paging,
        library_status=status,
        catalog=catalog,
        **list_kwargs,
    )


def render_recently_watched_shows(catalog: str) -> None:
    from resources.lib.database.simkl_sync.shows import SimklSyncDatabase
    from resources.lib.discover.renderer import discover_list_kwargs
    from resources.lib.modules.list_builder import ListBuilder

    items = SimklSyncDatabase().get_recently_watched_shows(g.PAGE, catalog=catalog)
    if not items:
        g.cancel_directory()
        return
    list_kwargs = discover_list_kwargs()
    list_kwargs["catalog"] = catalog
    ListBuilder().show_list_builder(
        items,
        no_paging=not paginate_simkl_lists(),
        **list_kwargs,
    )


def render_watched_episodes(catalog: str) -> None:
    from resources.lib.database.simkl_sync.shows import SimklSyncDatabase
    from resources.lib.modules.list_builder import ListBuilder

    items = SimklSyncDatabase().get_watched_episodes(g.PAGE, catalog=catalog)
    if not items:
        g.cancel_directory()
        return
    ListBuilder().mixed_episode_builder(items, no_paging=not paginate_simkl_lists())


def render_next_up(catalog: str) -> None:
    from resources.lib.database.simkl_sync.shows import SimklSyncDatabase
    from resources.lib.modules.list_builder import ListBuilder

    episodes = SimklSyncDatabase().get_nextup_episodes(
        g.get_int_setting("nextup.sort") == 1,
        catalog=catalog,
    )
    if g.get_bool_setting("limit.nextup"):
        episodes = episodes[: g.get_int_setting("item.limit")]
    if not episodes:
        g.cancel_directory()
        return
    ListBuilder().mixed_episode_builder(episodes, no_paging=True)


def render_continue_watching_movies() -> None:
    from resources.lib.database.simkl_sync.bookmark import SimklSyncDatabase as BookmarkDatabase
    from resources.lib.database.simkl_sync.hidden import SimklSyncDatabase as HiddenDatabase
    from resources.lib.discover.renderer import discover_list_kwargs
    from resources.lib.modules.list_builder import ListBuilder

    page_limit = g.get_int_setting("item.limit")
    page_start = (g.PAGE - 1) * page_limit
    page_end = g.PAGE * page_limit
    hidden = HiddenDatabase().get_hidden_items("progress_watched", "movies")
    items = [
        i for i in BookmarkDatabase().get_all_bookmark_items("movie") if i["simkl_id"] not in hidden
    ][page_start:page_end]
    if not items:
        g.cancel_directory()
        return
    ListBuilder().movie_menu_builder(items, **discover_list_kwargs())


def render_continue_watching_episodes(catalog: str) -> None:
    from resources.lib.database.simkl_sync.bookmark import SimklSyncDatabase as BookmarkDatabase
    from resources.lib.database.simkl_sync.hidden import SimklSyncDatabase as HiddenDatabase
    from resources.lib.database.simkl_sync.shows import SimklSyncDatabase
    from resources.lib.modules.list_builder import ListBuilder
    from resources.lib.simkl.ids import show_id_from_item

    page_limit = g.get_int_setting("item.limit")
    page_start = (g.PAGE - 1) * page_limit
    page_end = g.PAGE * page_limit
    hidden = HiddenDatabase().get_hidden_items("progress_watched", "tvshow")
    show_db = SimklSyncDatabase()
    items = []
    for item in BookmarkDatabase().get_all_bookmark_items("episode"):
        show_id = show_id_from_item(item)
        if not show_id or show_id in hidden:
            continue
        if show_db.show_catalog(show_id) != catalog:
            continue
        items.append(item)
    items = items[page_start:page_end]
    if not items:
        g.cancel_directory()
        return
    ListBuilder().mixed_episode_builder(items)

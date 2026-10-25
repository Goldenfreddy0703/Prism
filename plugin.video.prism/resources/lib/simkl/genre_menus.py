"""Shared Simkl genre browse menu handlers."""
from __future__ import annotations

from urllib import parse

import xbmcgui

from resources.lib.discover.renderer import discover_list_kwargs
from resources.lib.modules.globals import g
from resources.lib.simkl import browse
from resources.lib.simkl.search_menus import notify_empty_search, persist_search_pagination
from resources.lib.meta.list_pipeline import make_list_id

GENRE_GET_ACTIONS = {
    "movie": "movieGenresGet",
    "tv": "showGenresGet",
    "anime": "animeGenresGet",
}

MULTI_GENRE_ACTIONS = {
    "movie": ("movieGenresMulti", "movieGenresMultiGet"),
    "tv": ("showGenresMulti", "showGenresMultiGet"),
    "anime": ("animeGenresMulti", "animeGenresMultiGet"),
}


def _render_genre_browse_page(
    catalog: str,
    page,
    list_builder,
    *,
    next_action: str,
    next_args,
    list_id: str | None = None,
    merge_source: str = "genre",
) -> None:
    """Paint genre browse via CatalogPagePipeline."""
    from resources.lib.pipeline.catalog_page import CatalogPagePipeline

    menu_page = max(1, int(g.PAGE or 1))
    resolved_list_id = list_id or make_list_id(next_action, next_args, menu_page)

    CatalogPagePipeline.open_genre(
        catalog,
        page,
        list_builder,
        next_action=next_action,
        next_args=next_args,
        list_id=resolved_list_id,
        browse_source=merge_source,
    )


def show_genre_picker(catalog: str) -> None:
    genres = browse.get_simkl_genres(catalog)
    if not genres:
        g.cancel_directory()
        return

    if catalog in MULTI_GENRE_ACTIONS:
        multi_action, _ = MULTI_GENRE_ACTIONS[catalog]
        from resources.lib.meta.provider_settings import tmdb_features_enabled

        if catalog == "anime" or tmdb_features_enabled():
            g.add_directory_item(
                g.get_language_string(30940),
                action=multi_action,
                menu_item=browse.genre_icon_dict(catalog, "multi-select"),
            )

    for genre in genres:
        g.add_directory_item(
            genre["label"],
            action=GENRE_GET_ACTIONS[catalog],
            action_args=genre["slug"],
            catalog=catalog,
            menu_item=browse.genre_icon_dict(catalog, genre["slug"]),
        )
    g.close_directory(g.CONTENT_MENU)


def show_tmdb_genre_multiselect(catalog: str, page_limit: int, list_builder) -> None:
    from resources.lib.meta.provider_settings import notify_tmdb_required, tmdb_features_enabled

    if not tmdb_features_enabled():
        notify_tmdb_required()
        g.cancel_directory()
        return
    if catalog not in MULTI_GENRE_ACTIONS:
        g.cancel_directory()
        return

    genres = browse.get_tmdb_genres(catalog)
    if not genres:
        g.cancel_directory()
        return

    labels = [genre["name"] for genre in genres]
    selected = xbmcgui.Dialog().multiselect(g.get_language_string(30941), labels)
    if not selected:
        g.cancel_directory()
        return

    genre_ids = ",".join(str(genres[index]["id"]) for index in selected)
    render_multi_genre_list(catalog, {"genres": genre_ids}, page_limit, list_builder)


def show_tenrai_anime_multiselect(page_limit: int, list_builder) -> None:
    picker = browse.get_tenrai_anime_picker_items()
    genres = picker.get("genres") or []
    tags = picker.get("tags") or []
    if not genres and not tags:
        g.cancel_directory()
        return

    labels = [item["name"] for item in genres] + [item["name"] for item in tags]
    selected = xbmcgui.Dialog().multiselect(g.get_language_string(30941), labels)
    if not selected:
        g.cancel_directory()
        return

    genre_count = len(genres)
    mal_ids: list[str] = []
    for index in selected:
        if index < genre_count:
            mal_ids.append(str(genres[index]["mal_id"]))
        elif index - genre_count < len(tags):
            mal_ids.append(str(tags[index - genre_count]["mal_id"]))

    if not mal_ids:
        g.cancel_directory()
        return

    render_anime_multi_genre_list({"genres": ",".join(mal_ids)}, page_limit, list_builder)


def _parse_tmdb_multi_genre_action_args(action_args) -> tuple[str | None, int, int]:
    if isinstance(action_args, dict):
        value = action_args.get("genres")
        genre_ids = str(value).strip() if value else None
        try:
            page = max(1, int(action_args.get("tmdb_page") or 1))
        except (TypeError, ValueError):
            page = 1
        try:
            offset = max(0, int(action_args.get("tmdb_offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        return genre_ids, page, offset
    text = str(action_args or "").strip()
    return (text or None), 1, 0


def _parse_tenrai_multi_genre_action_args(action_args) -> tuple[str | None, int, int]:
    if isinstance(action_args, dict):
        value = action_args.get("genres")
        genre_ids = str(value).strip() if value else None
        try:
            page = max(1, int(action_args.get("tenrai_page") or 1))
        except (TypeError, ValueError):
            page = 1
        try:
            offset = max(0, int(action_args.get("tenrai_offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        return genre_ids, page, offset
    text = str(action_args or "").strip()
    return (text or None), 1, 0


def render_multi_genre_list(catalog: str, action_args, page_limit: int, list_builder) -> None:
    genre_ids, _tmdb_page, _tmdb_offset = _parse_tmdb_multi_genre_action_args(action_args)
    if not genre_ids:
        g.cancel_directory()
        return

    persist_search_pagination({"genres": genre_ids})

    menu_page = max(1, int(g.PAGE or 1))
    tmdb_list_id = make_list_id("tmdb", catalog, genre_ids)

    def _tmdb_loader() -> list:
        result = browse.discover_by_tmdb_genres(
            catalog,
            genre_ids,
            page_limit,
            menu_page=menu_page,
        )
        return list(result.items or [])

    thin = _genre_thin_page(catalog, tmdb_list_id, menu_page, page_limit, _tmdb_loader)
    if not thin or not thin.items:
        notify_empty_search(30766)
        return
    page = thin

    _, get_action = MULTI_GENRE_ACTIONS[catalog]
    next_args: dict[str, str | int] = {"genres": genre_ids}

    _render_genre_browse_page(
        catalog,
        page,
        list_builder,
        next_action=get_action,
        next_args=next_args,
        list_id=make_list_id("tmdb", catalog, genre_ids, menu_page),
        merge_source=f"tmdb_genre:{genre_ids}",
    )


def render_anime_multi_genre_list(action_args, page_limit: int, list_builder) -> None:
    genre_ids, _tenrai_page, _tenrai_offset = _parse_tenrai_multi_genre_action_args(action_args)
    if not genre_ids:
        g.cancel_directory()
        return

    persist_search_pagination({"genres": genre_ids})

    menu_page = max(1, int(g.PAGE or 1))
    tenrai_list_id = make_list_id("tenrai", genre_ids)

    def _tenrai_loader() -> list:
        result = browse.discover_by_tenrai_genres(
            genre_ids,
            page_limit,
            menu_page=menu_page,
        )
        return list(result.items or [])

    thin = _genre_thin_page("anime", tenrai_list_id, menu_page, page_limit, _tenrai_loader)
    if not thin or not thin.items:
        notify_empty_search(30766)
        return
    page = thin

    _, get_action = MULTI_GENRE_ACTIONS["anime"]
    next_args: dict[str, str | int] = {"genres": genre_ids}

    _render_genre_browse_page(
        "anime",
        page,
        list_builder,
        next_action=get_action,
        next_args=next_args,
        list_id=make_list_id("tenrai", genre_ids, menu_page),
        merge_source=f"tenrai_genre:{genre_ids}",
    )


def _genre_thin_page(
    catalog: str,
    list_id: str,
    page: int,
    page_limit: int,
    loader,
) -> browse.GenreBrowsePage | None:
    from resources.lib.meta.list_pipeline import get_list_store

    store = get_list_store("genre")
    items = store.load_thin_page_items(
        catalog,
        list_id,
        page,
        loader,
        disk_namespace="genre",
    )
    if not items:
        return None
    return browse.GenreBrowsePage(items, len(items) >= page_limit)


def render_genre_list(catalog: str, args, page_limit: int, list_builder) -> None:
    slug = parse.unquote(str(args or "")).strip().lower()
    if not slug:
        g.cancel_directory()
        return

    menu_page = max(1, int(g.PAGE or 1))
    list_id = make_list_id("slug", catalog, slug)
    page = _genre_thin_page(
        catalog,
        list_id,
        menu_page,
        page_limit,
        lambda: list(
            browse.discover_by_genre_slug(catalog, slug, menu_page, page_limit).items or []
        ),
    )
    if not page or not page.items:
        g.cancel_directory()
        return

    _render_genre_browse_page(
        catalog,
        page,
        list_builder,
        next_action=GENRE_GET_ACTIONS[catalog],
        next_args=slug,
        list_id=make_list_id("slug", catalog, slug),
        merge_source=f"genre_slug:{slug}",
    )

"""Background prefetch for the next paginated list page (Otaku-style)."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Callable

from resources.lib.modules.globals import g

_DONE_KEY = "page_prefetch.done_keys"
_IN_FLIGHT_KEY = "page_prefetch.in_flight"
_MAX_DONE_KEYS = 256
_prefetch_events: dict[str, threading.Event] = {}
_prefetch_events_lock = threading.Lock()


def prefetch_next_page_enabled() -> bool:
    return True


def _prefetch_key(page_params: dict[str, Any]) -> str:
    stable = {
        key: page_params[key]
        for key in sorted(page_params)
        if key not in ("special_sort", "reload")
    }
    return hashlib.md5(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()


def _done_keys() -> set[str]:
    raw = g.get_runtime_setting(_DONE_KEY)
    if isinstance(raw, list):
        return {str(key) for key in raw}
    return set()


def _mark_done(key: str) -> None:
    done = list(_done_keys())
    if key in done:
        return
    done.append(key)
    if len(done) > _MAX_DONE_KEYS:
        done = done[-_MAX_DONE_KEYS:]
    g.set_runtime_setting(_DONE_KEY, done)


def _in_flight_keys() -> set[str]:
    raw = g.get_runtime_setting(_IN_FLIGHT_KEY)
    if isinstance(raw, list):
        return {str(key) for key in raw}
    return set()


def _set_in_flight(key: str, active: bool) -> None:
    keys = _in_flight_keys()
    if active:
        keys.add(key)
    else:
        keys.discard(key)
    g.set_runtime_setting(_IN_FLIGHT_KEY, sorted(keys))


def schedule_refs_enrichment(
    refs: list[dict],
    catalog: str,
    *,
    reason: str = "prefetch",
    blocking: bool = False,
) -> None:
    if not refs:
        return
    from resources.lib.meta.enrichment import MetaEnrichmentQueue

    if blocking:
        _blocking_enrich_refs(refs, default_catalog=catalog, reason=reason)
        return

    movie_ids = sorted(
        {
            int(ref["simkl_id"])
            for ref in refs
            if ref.get("simkl_id") is not None and ref.get("catalog") == "movie"
        }
    )
    show_ids = sorted(
        {
            int(ref["simkl_id"])
            for ref in refs
            if ref.get("simkl_id") is not None and ref.get("catalog") in ("tv", "anime")
        }
    )
    if catalog == "movie" and not movie_ids:
        movie_ids = sorted({int(ref["simkl_id"]) for ref in refs if ref.get("simkl_id") is not None})
    elif catalog in ("tv", "anime") and not show_ids and not movie_ids:
        show_ids = sorted({int(ref["simkl_id"]) for ref in refs if ref.get("simkl_id") is not None})

    if movie_ids:
        MetaEnrichmentQueue.schedule_run_plugin(
            [{"simkl_id": simkl_id, "needs_update": True} for simkl_id in movie_ids],
            "movie",
            reason=reason,
            catalog="movie",
        )
    if show_ids:
        MetaEnrichmentQueue.schedule_run_plugin(
            [{"simkl_id": simkl_id, "needs_update": True} for simkl_id in show_ids],
            "tvshow",
            reason=reason,
            catalog=catalog if catalog in ("tv", "anime") else "tv",
        )


def enrich_refs_blocking(
    refs: list[dict],
    catalog: str,
    *,
    reason: str = "prefetch",
) -> None:
    schedule_refs_enrichment(refs, catalog, reason=reason, blocking=True)


def current_page_prefetch_params() -> dict[str, Any] | None:
    params = getattr(g, "REQUEST_PARAMS", None) or {}
    action = params.get("action")
    if not action:
        return None
    page_params: dict[str, Any] = {"action": action}
    for key in ("catalog", "list_id", "page", "action_args", "status", "mediatype"):
        if key in params and params[key] not in (None, ""):
            page_params[key] = params[key]
    if "page" not in page_params:
        try:
            page_params["page"] = int(g.PAGE or 1)
        except (TypeError, ValueError):
            page_params["page"] = 1
    return page_params


def _prefetch_event(key: str) -> threading.Event:
    with _prefetch_events_lock:
        event = _prefetch_events.get(key)
        if event is None:
            event = threading.Event()
            _prefetch_events[key] = event
        return event


def _signal_prefetch_done(key: str) -> None:
    event = _prefetch_event(key)
    event.set()
    with _prefetch_events_lock:
        if len(_prefetch_events) > _MAX_DONE_KEYS:
            for stale_key in list(_prefetch_events.keys())[:-_MAX_DONE_KEYS]:
                _prefetch_events.pop(stale_key, None)


def _prefetch_discover(page_params: dict[str, Any]) -> None:
    from resources.lib.discover.renderer import DiscoverRenderer

    catalog = page_params.get("catalog")
    list_id = page_params.get("list_id")
    page = int(page_params.get("page") or 1)
    if not catalog or not list_id:
        return
    DiscoverRenderer().prefetch_page(catalog, list_id, page)


def _prefetch_search(page_params: dict[str, Any]) -> None:
    from resources.lib.simkl.media_ref import persist_search_results
    from resources.lib.simkl.search import search_page
    from resources.lib.simkl.search_menus import filter_search_results, normalize_search_query

    action = page_params.get("action")
    search_map = {
        "moviesSearchResults": ("movie", "search/movie", "movies"),
        "showsSearchResults": ("tv", "search/show", "shows"),
        "animeSearchResults": ("anime", "search/anime", "shows"),
    }
    mapped = search_map.get(action)
    if not mapped:
        return
    catalog, url, media_type = mapped
    query = normalize_search_query(page_params.get("action_args"))
    if not query:
        return
    page = int(page_params.get("page") or 1)
    page_limit = g.get_int_setting("item.limit", 25)
    items = search_page(url, media_type, page, page_limit, query)
    filtered = filter_search_results(items)
    if not filtered:
        return
    refs = persist_search_results(catalog, filtered, enrich=False)
    enrich_refs_blocking(refs, catalog, reason="prefetch_search")


def _prefetch_genre_slug(page_params: dict[str, Any]) -> None:
    from urllib import parse

    from resources.lib.simkl import browse
    from resources.lib.simkl.media_ref import persist_genre_page

    action = page_params.get("action")
    catalog_map = {
        "movieGenresGet": "movie",
        "showGenresGet": "tv",
        "animeGenresGet": "anime",
    }
    catalog = catalog_map.get(action)
    if not catalog:
        return
    slug = parse.unquote(str(page_params.get("action_args") or "")).strip().lower()
    if not slug:
        return
    page = int(page_params.get("page") or 1)
    page_limit = g.get_int_setting("item.limit", 25)
    result = browse.discover_by_genre_slug(catalog, slug, page, page_limit)
    if not result.items:
        return
    persist_genre_page(catalog, result.items, blocking_enrich=True, enrich_reason="prefetch_genre")


def _prefetch_multi_genre(page_params: dict[str, Any]) -> None:
    from resources.lib.simkl import browse
    from resources.lib.simkl.genre_menus import (
        _parse_tenrai_multi_genre_action_args,
        _parse_tmdb_multi_genre_action_args,
    )
    from resources.lib.simkl.media_ref import persist_genre_page

    action = page_params.get("action")
    action_args = page_params.get("action_args")
    page_limit = g.get_int_setting("item.limit", 25)

    if action == "animeGenresMultiGet":
        genre_ids, tenrai_page, tenrai_offset = _parse_tenrai_multi_genre_action_args(action_args)
        if not genre_ids:
            return
        result = browse.discover_by_tenrai_genres(
            genre_ids,
            page_limit,
            tenrai_page=tenrai_page,
            row_offset=tenrai_offset,
        )
        catalog = "anime"
    elif action in ("movieGenresMultiGet", "showGenresMultiGet"):
        genre_ids, tmdb_page, tmdb_offset = _parse_tmdb_multi_genre_action_args(action_args)
        if not genre_ids:
            return
        catalog = "movie" if action == "movieGenresMultiGet" else "tv"
        result = browse.discover_by_tmdb_genres(
            catalog,
            genre_ids,
            page_limit,
            tmdb_page=tmdb_page,
            tmdb_offset=tmdb_offset,
        )
    else:
        return

    if not result.items:
        return
    persist_genre_page(catalog, result.items, blocking_enrich=True, enrich_reason="prefetch_genre")


def _library_catalog_status(page_params: dict[str, Any]) -> tuple[str | None, str | None]:
    catalog = page_params.get("catalog")
    status = page_params.get("status")
    if catalog and status:
        return str(catalog), str(status)
    media_type = page_params.get("mediatype")
    if not media_type:
        return None, None
    if media_type in ("movie", "movies"):
        catalog = "movie"
    elif media_type == "anime":
        catalog = "anime"
    else:
        catalog = "tv"
    return catalog, str(status or "plantowatch")


def _blocking_enrich_simkl_ids(
    simkl_ids: list[int],
    media_type: str,
    *,
    catalog: str | None,
    reason: str,
) -> None:
    if not simkl_ids:
        return
    from resources.lib.meta.enrichment import MetaEnrichmentQueue

    MetaEnrichmentQueue.enrich_simkl_ids_blocking(simkl_ids, media_type, reason=reason, catalog=catalog)


def _blocking_enrich_refs(refs: list[dict], *, default_catalog: str, reason: str) -> None:
    movie_ids = sorted(
        {
            int(ref["simkl_id"])
            for ref in refs
            if ref.get("simkl_id") is not None and ref.get("catalog") == "movie"
        }
    )
    show_ids = sorted(
        {
            int(ref["simkl_id"])
            for ref in refs
            if ref.get("simkl_id") is not None and ref.get("catalog") in ("tv", "anime")
        }
    )
    if not movie_ids and default_catalog == "movie":
        movie_ids = sorted({int(ref["simkl_id"]) for ref in refs if ref.get("simkl_id") is not None})
    if not show_ids and default_catalog in ("tv", "anime"):
        show_ids = sorted({int(ref["simkl_id"]) for ref in refs if ref.get("simkl_id") is not None})
    if movie_ids:
        _blocking_enrich_simkl_ids(movie_ids, "movie", catalog="movie", reason=reason)
    if show_ids:
        _blocking_enrich_simkl_ids(show_ids, "tvshow", catalog=default_catalog, reason=reason)


def _prefetch_library(page_params: dict[str, Any]) -> None:
    catalog, status = _library_catalog_status(page_params)
    if not catalog or not status:
        return
    from resources.lib.simkl.library_cache import load_library_list_refs
    from resources.lib.simkl.menu_helpers import paginate_refs_for_page

    refs = load_library_list_refs(catalog, status)
    if not refs:
        return
    page = int(page_params.get("page") or 1)
    page_refs = paginate_refs_for_page(refs, page)
    if not page_refs:
        return
    _blocking_enrich_refs(page_refs, default_catalog=catalog, reason="prefetch_library")


def _prefetch_actor(page_params: dict[str, Any]) -> None:
    from resources.lib.simkl.enrich import enrich_sync_items
    from resources.lib.simkl.media_ref import enrich_and_persist
    from resources.lib.simkl.person_ref import fetch_filmography_page, normalize_person_ref

    args = normalize_person_ref(page_params.get("action_args"))
    person_id = args.get("person_id")
    if person_id is None:
        return
    catalog_hint = args.get("catalog") or "movie"
    page = int(page_params.get("page") or 1)
    page_limit = g.get_int_setting("item.limit", 25)
    items = fetch_filmography_page(int(person_id), page, page_limit)
    if not items:
        return
    items = enrich_sync_items(items, fast=True)
    refs = enrich_and_persist(
        catalog_hint,
        items,
        force_simkl_meta=True,
        enrich=False,
    )
    _blocking_enrich_refs(refs, default_catalog=catalog_hint, reason="prefetch_actor")


def _prefetch_year(page_params: dict[str, Any]) -> None:
    from resources.lib.simkl import browse
    from resources.lib.simkl.media_ref import enrich_and_persist

    action = page_params.get("action")
    catalog = "movie" if action == "movieYearsMovies" else "tv"
    try:
        year = int(page_params.get("action_args") or 0)
    except (TypeError, ValueError):
        return
    if year <= 0:
        return
    page = int(page_params.get("page") or 1)
    page_limit = g.get_int_setting("item.limit", 25)
    items = browse.discover_by_year(catalog, year, page, page_limit)
    if not items:
        return
    refs = enrich_and_persist(catalog, items, enrich=False)
    _blocking_enrich_refs(refs, default_catalog=catalog, reason="prefetch_year")


def _prefetch_db_movie_page(page_params: dict[str, Any], *, method: str, reason: str) -> None:
    page = int(page_params.get("page") or 1)
    from resources.lib.database.session import get_sync_database

    rows = getattr(get_sync_database(), method)(page) or []
    simkl_ids = sorted({int(row["simkl_id"]) for row in rows if row.get("simkl_id") is not None})
    _blocking_enrich_simkl_ids(simkl_ids, "movie", catalog="movie", reason=reason)


def _prefetch_db_show_page(
    page_params: dict[str, Any],
    *,
    method: str,
    reason: str,
    catalog: str | None = None,
) -> None:
    page = int(page_params.get("page") or 1)
    catalog = catalog or page_params.get("catalog") or "tv"
    from resources.lib.database.session import get_sync_database

    db = get_sync_database()
    if method == "get_recently_watched_shows":
        rows = db.get_recently_watched_shows(page, catalog=catalog) or []
    else:
        rows = getattr(db, method)(page) or []
    simkl_ids = sorted({int(row["simkl_id"]) for row in rows if row.get("simkl_id") is not None})
    _blocking_enrich_simkl_ids(simkl_ids, "tvshow", catalog=catalog, reason=reason)


def _prefetch_continue_watching(page_params: dict[str, Any]) -> None:
    from resources.lib.simkl.playback import prefetch_continue_watching

    catalog = page_params.get("catalog") or "tv"
    prefetch_continue_watching(catalog, page_params)


def _prefetch_watched_episodes(page_params: dict[str, Any]) -> None:
    catalog = page_params.get("catalog") or "tv"
    page = int(page_params.get("page") or 1)
    from resources.lib.database.session import get_sync_database
    from resources.lib.simkl.ids import show_id_from_item

    items = get_sync_database().get_watched_episodes(page, catalog=catalog) or []
    show_ids = sorted({int(show_id_from_item(item)) for item in items if show_id_from_item(item) is not None})
    _blocking_enrich_simkl_ids(show_ids, "tvshow", catalog=catalog, reason="prefetch_watched")


def _library_prefetch_handler(route: str, catalog: str):
    if route == "on_deck":
        return lambda p, cat=catalog: _prefetch_continue_watching({**p, "catalog": cat})
    if route in ("watched_movies", "recently_watched") and catalog == "movie":
        return lambda p: _prefetch_db_movie_page(p, method="get_watched_movies", reason="prefetch_watched")
    if route == "watched_episodes":
        return lambda p, cat=catalog: _prefetch_watched_episodes({**p, "catalog": cat})
    if route == "recently_watched":
        return lambda p, cat=catalog: _prefetch_db_show_page(
            p, method="get_recently_watched_shows", reason="prefetch_watched", catalog=cat
        )
    return None


def _build_library_prefetch_handlers() -> dict[str, Callable[[dict[str, Any]], None]]:
    from resources.lib.simkl.library_routes import _CANONICAL_ROUTES

    handlers: dict[str, Callable[[dict[str, Any]], None]] = {}
    for action, route in _CANONICAL_ROUTES.items():

        def _canonical(route_name: str = route):
            def _handler(page_params: dict[str, Any]) -> None:
                catalog = page_params.get("catalog") or ("movie" if route_name == "watched_movies" else "tv")
                bound = _library_prefetch_handler(route_name, catalog)
                if bound is not None:
                    bound(page_params)

            return _handler

        handlers[action] = _canonical()
    return handlers


_PREFETCH_HANDLERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "simklDiscoverList": _prefetch_discover,
    "moviesSearchResults": _prefetch_search,
    "showsSearchResults": _prefetch_search,
    "animeSearchResults": _prefetch_search,
    "movieGenresGet": _prefetch_genre_slug,
    "showGenresGet": _prefetch_genre_slug,
    "animeGenresGet": _prefetch_genre_slug,
    "movieGenresMultiGet": _prefetch_multi_genre,
    "showGenresMultiGet": _prefetch_multi_genre,
    "animeGenresMultiGet": _prefetch_multi_genre,
    "simklLibraryList": _prefetch_library,
    "actorCredits": _prefetch_actor,
    "movieYearsMovies": _prefetch_year,
    "showYears": _prefetch_year,
    "moviesMyCollection": lambda p: _prefetch_db_movie_page(p, method="get_collected_movies", reason="prefetch_collection"),
    "showsMyCollection": lambda p: _prefetch_db_show_page(p, method="get_collected_shows", reason="prefetch_collection"),
    "showsMyProgress": lambda p: _prefetch_db_show_page(
        p, method="get_unfinished_collected_shows", reason="prefetch_collection"
    ),
    **_build_library_prefetch_handlers(),
}


def prefetch_threads_active() -> bool:
    """True while a background prefetch thread is still running."""
    return bool(_in_flight_keys())


def foreground_browse_busy() -> bool:
    """True while prefetch, meta-enrich, or playback pipeline is active."""
    if prefetch_threads_active():
        return True
    if g.get_bool_runtime_setting("meta_enrich.in_flight"):
        return True
    if g.get_bool_runtime_setting("playback.pipeline_busy"):
        return True
    try:
        import xbmc

        if xbmc.Player().isPlayingVideo():
            return True
    except Exception:
        pass
    return False


def run_page_prefetch(page_params: dict[str, Any]) -> None:
    if not prefetch_next_page_enabled() or not isinstance(page_params, dict):
        return
    g.ensure_addon()
    action = page_params.get("action")
    if not action:
        return
    handler = _PREFETCH_HANDLERS.get(str(action))
    if handler is None:
        return
    start = time.time()
    try:
        handler(page_params)
        g.log(
            f"page_prefetch_ms={(time.time() - start) * 1000:.0f} action={action} page={page_params.get('page')}",
            "debug",
        )
    except Exception:
        g.log_stacktrace()


class PagePrefetch:
    @staticmethod
    def schedule(page_params: dict[str, Any] | None) -> None:
        if not prefetch_next_page_enabled() or not isinstance(page_params, dict):
            return
        if not page_params.get("action"):
            return
        key = _prefetch_key(page_params)
        if key in _done_keys() or key in _in_flight_keys():
            return

        def _run() -> None:
            event = _prefetch_event(key)
            event.clear()
            _set_in_flight(key, True)
            try:
                run_page_prefetch(page_params)
                _mark_done(key)
            except Exception:
                g.log_stacktrace()
            finally:
                _set_in_flight(key, False)
                _signal_prefetch_done(key)

        threading.Thread(target=_run, daemon=True, name=f"prism-prefetch-{key[:8]}").start()

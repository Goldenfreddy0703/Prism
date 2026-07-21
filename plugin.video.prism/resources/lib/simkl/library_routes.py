"""Central routing for Simkl My Library actions (movies, TV, anime).

Canonical actions accept a ``catalog`` query param:
  libraryOnDeck, libraryNextUp, libraryRecentlyWatched,
  libraryWatchedEpisodes, libraryWatchedMovies

Legacy per-catalog action names remain aliases (widgets, shortcuts).
"""
from __future__ import annotations

from typing import Any

# route name -> (legacy action, catalog)
_LEGACY_LIBRARY_ACTIONS: dict[str, tuple[str, str]] = {
    "onDeckMovies": ("on_deck", "movie"),
    "onDeckShows": ("on_deck", "tv"),
    "onDeckAnime": ("on_deck", "anime"),
    "showsNextUp": ("next_up", "tv"),
    "animeNextUp": ("next_up", "anime"),
    "showsRecentlyWatched": ("recently_watched", "tv"),
    "animeRecentlyWatched": ("recently_watched", "anime"),
    "myWatchedEpisodes": ("watched_episodes", "tv"),
    "animeWatchedEpisodes": ("watched_episodes", "anime"),
    "myWatchedMovies": ("watched_movies", "movie"),
    "moviesRecentlyWatched": ("recently_watched", "movie"),
}

_ROUTE_DEFAULT_CATALOG: dict[str, str] = {
    "watched_movies": "movie",
}

_CANONICAL_ROUTES: dict[str, str] = {
    "libraryOnDeck": "on_deck",
    "libraryNextUp": "next_up",
    "libraryRecentlyWatched": "recently_watched",
    "libraryWatchedEpisodes": "watched_episodes",
    "libraryWatchedMovies": "watched_movies",
}

_HUB_ACTIONS = frozenset({"myMovies", "myShows", "myAnime"})


def resolve_library_route(action: str, params: dict[str, Any] | None = None) -> tuple[str, str] | None:
    """Return ``(route, catalog)`` when *action* is a library submenu, else None."""
    params = params or {}
    legacy = _LEGACY_LIBRARY_ACTIONS.get(action)
    if legacy:
        return legacy
    route = _CANONICAL_ROUTES.get(action)
    if route:
        catalog = params.get("catalog") or _ROUTE_DEFAULT_CATALOG.get(route, "tv")
        return route, catalog
    return None


def prefetch_catalog(action: str, params: dict[str, Any] | None = None, *, default: str = "tv") -> str | None:
    """Catalog hint for page prefetch, or None if not a library route."""
    resolved = resolve_library_route(action, params)
    if resolved:
        return resolved[1]
    return None


def dispatch_library_action(action: str, params: dict[str, Any] | None = None) -> bool:
    """Handle library routes. Returns True when *action* was dispatched."""
    if action in _HUB_ACTIONS:
        from resources.lib.gui import animeMenus, movieMenus, tvshowMenus

        if action == "myMovies":
            movieMenus.Menus().my_movies()
        elif action == "myAnime":
            animeMenus.Menus().my_anime()
        else:
            tvshowMenus.Menus().my_shows()
        return True

    if action == "simklLibraryList":
        from resources.lib.simkl.library_menus import render_status_list

        params = params or {}
        render_status_list(params.get("catalog", "tv"), params.get("status", "plantowatch"))
        return True

    resolved = resolve_library_route(action, params)
    if not resolved:
        return False

    route, catalog = resolved
    _run_library_route(route, catalog)
    return True


def _run_library_route(route: str, catalog: str) -> None:
    from resources.lib.simkl import library_menus as lm

    if route == "on_deck":
        lm.render_continue_watching(catalog)
        return

    if catalog == "movie":
        if route == "recently_watched":
            lm.render_recently_watched_movies()
        elif route == "watched_movies":
            lm.render_watched_movies()
        return

    if route == "next_up":
        lm.render_next_up(catalog)
    elif route == "recently_watched":
        lm.render_recently_watched_shows(catalog)
    elif route == "watched_episodes":
        lm.render_watched_episodes(catalog)

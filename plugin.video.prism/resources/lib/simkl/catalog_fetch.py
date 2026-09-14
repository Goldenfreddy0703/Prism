"""Cloudflare-cached Simkl catalog detail and episode-list fetches (no client_id)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Tuple

from resources.lib.indexers.simkl import thread_simkl_api
from resources.lib.simkl.ids import (
    anime_api_path,
    anime_episodes_api_path,
    movie_api_path,
    show_api_path,
    tv_episodes_api_path,
)

CatalogDetailKey = Tuple[str, int]
EpisodeListKey = Tuple[str, int]


def _detail_paths(catalog: str, simkl_id: int, *, prefer_anime: bool = False) -> list[str]:
    if catalog == "movie":
        return [movie_api_path(simkl_id)]
    if catalog == "anime" or prefer_anime:
        return [anime_api_path(simkl_id), show_api_path(simkl_id)]
    return [show_api_path(simkl_id), anime_api_path(simkl_id)]


def fetch_catalog_detail(
    catalog: str,
    simkl_id: int,
    *,
    prefer_anime: bool = False,
    api=None,
) -> dict[str, Any] | None:
    """GET /movies|tv|anime/{id} without client_id."""
    client = api or thread_simkl_api()
    for path in _detail_paths(catalog, int(simkl_id), prefer_anime=prefer_anime):
        data = client.get_catalog_json(path)
        if isinstance(data, dict) and not data.get("error"):
            return data
    return None


def _fetch_one_detail(
    request: dict[str, Any],
    *,
    api=None,
) -> tuple[CatalogDetailKey, dict[str, Any] | None]:
    catalog = str(request["catalog"])
    simkl_id = int(request["simkl_id"])
    prefer_anime = bool(request.get("prefer_anime"))
    detail = fetch_catalog_detail(catalog, simkl_id, prefer_anime=prefer_anime, api=api)
    return (catalog, simkl_id), detail


def fetch_catalog_details_parallel(
    requests: list[dict[str, Any]],
    *,
    max_workers: int | None = None,
    api=None,
) -> dict[CatalogDetailKey, dict[str, Any]]:
    """Batch parallel catalog detail fetches; pool is scoped and joined before return."""
    if not requests:
        return {}

    unique: list[dict[str, Any]] = []
    seen: set[CatalogDetailKey] = set()
    for request in requests:
        if not isinstance(request, dict):
            continue
        catalog = request.get("catalog")
        simkl_id = request.get("simkl_id")
        if catalog not in ("movie", "tv", "anime") or simkl_id is None:
            continue
        key = (str(catalog), int(simkl_id))
        if key in seen:
            continue
        seen.add(key)
        unique.append(request)

    if not unique:
        return {}

    workers = max_workers if max_workers is not None else min(len(unique), 32)
    workers = max(1, workers)
    out: dict[CatalogDetailKey, dict[str, Any]] = {}

    def _run_batch() -> None:
        for request in unique:
            key, detail = _fetch_one_detail(request, api=api)
            if detail:
                out[key] = detail

    if api is not None or len(unique) <= 32:
        _run_batch()
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for key, detail in pool.map(lambda req: _fetch_one_detail(req), unique):
                if detail:
                    out[key] = detail
    return out


def fetch_episode_list(
    catalog: str,
    show_id: int,
    slug: str | None = None,
    *,
    api=None,
    extended: str | None = None,
) -> list[dict[str, Any]]:
    """GET /tv|anime/episodes/{id} (catalog path, parallel-safe)."""
    client = api or thread_simkl_api()
    sid = int(show_id)
    if catalog == "anime":
        params: dict[str, str] = {}
        if extended:
            params["extended"] = extended
        data = client.get_catalog_json(anime_episodes_api_path(sid, slug), **params)
    else:
        data = client.get_catalog_json(tv_episodes_api_path(sid, slug))
    if isinstance(data, list):
        return [episode for episode in data if isinstance(episode, dict)]
    return []


def _fetch_one_episode_list(
    request: dict[str, Any],
    *,
    api=None,
) -> tuple[EpisodeListKey, list[dict[str, Any]]]:
    catalog = str(request["catalog"])
    show_id = int(request["show_id"])
    slug = request.get("slug")
    extended = request.get("extended")
    episodes = fetch_episode_list(
        catalog,
        show_id,
        slug,
        api=api,
        extended=extended,
    )
    return (catalog, show_id), episodes


def fetch_episode_lists_parallel(
    requests: list[dict[str, Any]],
    *,
    max_workers: int | None = None,
    api=None,
) -> dict[EpisodeListKey, list[dict[str, Any]]]:
    """Batch parallel episode-list fetches; pool is scoped and joined before return."""
    if not requests:
        return {}

    unique: list[dict[str, Any]] = []
    seen: set[EpisodeListKey] = set()
    for request in requests:
        if not isinstance(request, dict):
            continue
        catalog = request.get("catalog")
        show_id = request.get("show_id")
        if catalog not in ("tv", "anime") or show_id is None:
            continue
        key = (str(catalog), int(show_id))
        if key in seen:
            continue
        seen.add(key)
        unique.append(request)

    if not unique:
        return {}

    workers = max_workers if max_workers is not None else min(len(unique), 32)
    workers = max(1, workers)
    out: dict[EpisodeListKey, list[dict[str, Any]]] = {}

    def _run_batch() -> None:
        for request in unique:
            key, episodes = _fetch_one_episode_list(request, api=api)
            if episodes:
                out[key] = episodes

    if api is not None or len(unique) <= 32:
        _run_batch()
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for key, episodes in pool.map(lambda req: _fetch_one_episode_list(req), unique):
                if episodes:
                    out[key] = episodes

    return out

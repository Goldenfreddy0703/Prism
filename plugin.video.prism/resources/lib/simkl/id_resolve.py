"""Resolve external IDs to Simkl SyncRows (redirect lookup vs full detail)."""
from __future__ import annotations

import re
from typing import Callable

_SIMKL_LOCATION_RE = re.compile(r"/(movies|tv|anime)/(\d+)", re.IGNORECASE)
_SEGMENT_TO_CATALOG = {"movies": "movie", "tv": "tv", "anime": "anime"}


def parse_simkl_location(location: str) -> tuple[int, str] | None:
    """Parse simkl_id + catalog from a Simkl redirect Location URL."""
    if not location:
        return None
    match = _SIMKL_LOCATION_RE.search(location)
    if not match:
        return None
    segment, simkl_id = match.group(1).lower(), int(match.group(2))
    catalog = _SEGMENT_TO_CATALOG.get(segment, "tv")
    return simkl_id, catalog


def thin_sync_from_redirect(
    simkl_id: int,
    catalog: str,
    *,
    tmdb_id: int | None = None,
    mal_id: int | None = None,
) -> dict:
    """Minimal SyncRow after GET /redirect (detail filled later on menu open)."""
    sync: dict = {
        "simkl_id": int(simkl_id),
        "catalog": catalog,
        "simkl_object": {"info": {}, "art": {}},
    }
    return attach_external_ids(sync, tmdb_id=tmdb_id, mal_id=mal_id)


def attach_external_ids(sync: dict, *, tmdb_id: int | None = None, mal_id: int | None = None) -> dict:
    if tmdb_id is not None:
        sync["tmdb_id"] = int(tmdb_id)
        info = sync.setdefault("simkl_object", {}).setdefault("info", {})
        info["tmdb_id"] = int(tmdb_id)
        ids = info.setdefault("ids", {})
        ids["tmdb"] = int(tmdb_id)
    if mal_id is not None:
        sync["mal_id"] = int(mal_id)
        info = sync.setdefault("simkl_object", {}).setdefault("info", {})
        info["mal_id"] = int(mal_id)
        ids = info.setdefault("ids", {})
        ids["mal"] = int(mal_id)
        if not sync.get("catalog"):
            sync["catalog"] = "anime"
    return sync


def parallel_map_resolve(
    items: list,
    resolver: Callable,
    *,
    parallel: bool = True,
) -> list:
    """Run external-id resolvers concurrently for page-sized batches."""
    if not items:
        return []
    if not parallel or len(items) == 1:
        return [resolver(item) for item in items]

    from resources.lib.common.thread_pool import get_shared_executor

    from resources.lib.modules.globals import g

    try:
        return list(get_shared_executor().map(resolver, items))
    except Exception:
        g.log_stacktrace()
        return [resolver(item) for item in items]

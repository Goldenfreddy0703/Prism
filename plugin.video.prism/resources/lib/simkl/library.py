"""Fetch Simkl user library buckets and normalize for sync DB insertion."""
from __future__ import annotations

from resources.lib.indexers.simkl import SimklAPI
from resources.lib.modules.globals import g
from resources.lib.simkl.library_sort import sort_sync_items
from resources.lib.simkl.media_ref import normalize_library_entry, persist_library_entries

_CATALOG_TO_SIMKL_TYPE = {
    "movie": "movies",
    "tv": "shows",
    "anime": "anime",
}

_SIMKL_SINGULAR = {
    "movies": "movie",
    "shows": "show",
    "anime": "anime",
}


def _unwrap_sync_items(payload, media_key: str) -> list[dict]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if media_key in payload and isinstance(payload[media_key], list):
            return payload[media_key]
        for key in ("movies", "shows", "anime", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def simkl_entry_to_sync_dict(entry: dict, catalog: str) -> dict | None:
    """Backward-compatible alias — prefer :func:`normalize_library_entry`."""
    return normalize_library_entry(entry, catalog)


def fetch_library_refs(catalog: str, status: str = "plantowatch", *, skip_persist: bool = False) -> list[dict]:
    """Return [{simkl_id, catalog}, ...] refs for list_builder after sync insert."""
    from resources.lib.discover.sync_bridge import simkl_refs

    simkl_type = _CATALOG_TO_SIMKL_TYPE.get(catalog)
    if not simkl_type:
        return []

    api = SimklAPI()
    if not api.is_authenticated():
        g.log("Simkl library: not authenticated", "warning")
        return []

    payload = api.get_json(
        f"/sync/all-items/{simkl_type}/{status}",
        extended="full",
        episode_watched_at="yes",
    )
    entries = _unwrap_sync_items(payload, _SIMKL_SINGULAR.get(simkl_type, "show"))

    sync_items = []
    for entry in entries:
        normalized = normalize_library_entry(entry, catalog)
        if normalized:
            sync_items.append(normalized)

    sync_items = sort_sync_items(sync_items, catalog)

    if not sync_items:
        return []

    if skip_persist:
        return simkl_refs(sync_items)

    return persist_library_entries(catalog, entries, sync_items)

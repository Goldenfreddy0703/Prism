"""Page-first library list loading (thin refs, hydrate current page only)."""
from __future__ import annotations

import time

from resources.lib.meta.list_pipeline import get_list_store, make_list_id
from resources.lib.modules.globals import g
from resources.lib.simkl.library_cache import _attach_library_watch_fields, load_library_list_refs


def load_library_status_refs(catalog: str, status: str) -> list[dict]:
    """Ordered membership refs for one library bucket (no full sync-row hydrate)."""
    store = get_list_store("library")
    list_id = make_list_id(status)
    return store.get_refs(
        catalog,
        list_id,
        lambda: load_library_list_refs(catalog, status),
    )


def library_status_page_sync_items(
    catalog: str,
    status: str,
    page_refs: list[dict],
) -> list[dict]:
    """Hydrate SyncRows for one library page slice (POV-style page-first)."""
    if not page_refs:
        return []

    from resources.lib.meta.list_paint import rows_to_sync_items
    from resources.lib.simkl.media_ref import sync_db_rows_for_refs

    started = time.time()
    rows = sync_db_rows_for_refs(catalog, page_refs)
    sync_items = rows_to_sync_items(rows, catalog) or list(rows)
    items = _attach_library_watch_fields(sync_items, rows)
    page_ms = int((time.time() - started) * 1000)
    g.log(
        f"ListPipeline: namespace=library list={status} page_resolve source=sync_db "
        f"page_rows={len(items)} page_ms={page_ms}",
        "debug",
    )
    return items

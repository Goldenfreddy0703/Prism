"""Deferred catalog_items upsert for Seren-mode browse (foreground simkl_sync only)."""
from __future__ import annotations

from resources.lib.modules.globals import g

_PENDING_KEY = "browse_catalog_seed.pending"
_WAKE_KEY = "browse_catalog_seed.service_wake"
_MAX_PENDING = 12


def defer_browse_catalog_seed(catalog: str, items: list[dict]) -> None:
    if not items or not catalog:
        return
    try:
        from resources.lib.discover.catalog_store import upsert_sync_items

        upsert_sync_items(items, catalog_hint=str(catalog))
    except Exception:
        g.log_stacktrace()


def browse_catalog_seed_wake_pending() -> bool:
    return g.get_bool_runtime_setting(_WAKE_KEY)


def clear_browse_catalog_seed_wake() -> None:
    g.set_runtime_setting(_WAKE_KEY, False)


def process_idle_browse_catalog_seed() -> bool:
    return False

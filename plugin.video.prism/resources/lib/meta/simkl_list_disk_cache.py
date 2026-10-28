"""Optional disk TTL cache for Simkl browse list page JSON (Fen lists_cache pattern)."""
from __future__ import annotations

import json
import time
from typing import Any

_TABLE = "simkl_list_page_cache"
_GENRE_TTL_SEC = 96 * 3600.0
_SEARCH_TTL_SEC = 6 * 3600.0
_DEFAULT_TTL_SEC = 24 * 3600.0


def _ensure_table(db) -> None:
    db.execute_sql(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            cache_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )


def _ttl_for_namespace(namespace: str) -> float:
    if namespace == "search":
        return _SEARCH_TTL_SEC
    if namespace == "drilldown":
        return 6 * 3600.0
    if namespace in ("genre", "year", "actor"):
        return _GENRE_TTL_SEC
    return _DEFAULT_TTL_SEC


def get_cached_page(namespace: str, cache_key: str) -> list[dict[str, Any]] | None:
    from resources.lib.database.session import get_sync_database
    from resources.lib.meta.list_window_cache import get_window_page_items
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled():
        return None
    window_items = get_window_page_items(cache_key)
    if window_items is not None:
        return window_items
    db = get_sync_database()
    _ensure_table(db)
    row = db.fetchone(
        f"SELECT payload, expires_at FROM {_TABLE} WHERE cache_key = ?",
        (cache_key,),
    )
    if not row:
        return None
    expires_at = float(row.get("expires_at") or 0)
    if time.time() >= expires_at:
        db.execute_sql(f"DELETE FROM {_TABLE} WHERE cache_key = ?", (cache_key,))
        return None
    try:
        payload = json.loads(row.get("payload") or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    from resources.lib.meta.list_window_cache import set_window_page_items

    set_window_page_items(cache_key, payload)
    return payload


def set_cached_page(namespace: str, cache_key: str, items: list[dict[str, Any]]) -> None:
    from resources.lib.database.session import get_sync_database
    from resources.lib.meta.list_window_cache import set_window_page_items
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled() or not items:
        return
    set_window_page_items(cache_key, items)
    db = get_sync_database()
    _ensure_table(db)
    ttl = _ttl_for_namespace(namespace)
    expires_at = time.time() + ttl
    db.execute_sql(
        f"INSERT OR REPLACE INTO {_TABLE} (cache_key, payload, expires_at) VALUES (?, ?, ?)",
        (cache_key, json.dumps(items, separators=(",", ":")), expires_at),
    )

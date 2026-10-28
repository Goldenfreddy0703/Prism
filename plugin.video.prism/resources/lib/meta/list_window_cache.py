"""Session RAM list page cache via Kodi window properties (Otaku _mem_get pattern)."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

_SESSION_TTL_SEC = 30 * 60
_MAX_PAYLOAD_BYTES = 180000
_PROP_PREFIX = "prism_list_cache_"
_EXPIRE_PREFIX = "prism_list_cache_exp_"


def page_list_window_key(
    catalog: str,
    refs: list[dict],
    *,
    mixed_list: bool,
    paint_profile: str,
    hide_unaired: bool,
    hide_watched: bool,
    prefer_rich_payload: bool = False,
) -> str:
    """Stable key for Otaku-style Kodi window list cache (survives plugin invoker exit)."""
    from resources.lib.meta.paint_cache import page_cache_catalog, page_paint_cache_key

    cache_catalog = page_cache_catalog(catalog, refs, mixed_list=mixed_list)
    key_tuple = page_paint_cache_key(
        cache_catalog,
        refs,
        hide_unaired=hide_unaired,
        hide_watched=hide_watched,
        paint_profile=paint_profile,
        prefer_rich_payload=prefer_rich_payload,
    )
    return hashlib.sha1(repr(key_tuple).encode("utf-8")).hexdigest()


def serialize_page_rows_for_window(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Slim rows for window property storage (pre-built list payloads, no cast blobs)."""
    from resources.lib.meta.profiles import MetaProfile
    from resources.lib.meta.storage import slim_db_row

    packed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slim = slim_db_row(row, profile=MetaProfile.LIST, slim_art=False)
        slim.pop("simkl_object", None)
        slim["_menu_display_ready"] = True
        packed.append(slim)
    return packed


def _cache_key(disk_key: str) -> str:
    digest = hashlib.sha1(disk_key.encode("utf-8")).hexdigest()[:20]
    return digest


def _home_window():
    import xbmcgui

    return xbmcgui.Window(10000)


def get_window_page_items(disk_key: str) -> list[dict[str, Any]] | None:
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled():
        return None
    key = _cache_key(disk_key)
    expire_raw = _home_window().getProperty(_EXPIRE_PREFIX + key)
    if not expire_raw:
        return None
    try:
        expires = float(expire_raw)
    except (TypeError, ValueError):
        return None
    if time.time() >= expires:
        clear_window_page(disk_key)
        return None
    raw = _home_window().getProperty(_PROP_PREFIX + key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    return payload


def set_window_page_items(disk_key: str, items: list[dict[str, Any]]) -> None:
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled() or not items:
        return
    try:
        encoded = json.dumps(items, separators=(",", ":"))
    except (TypeError, ValueError):
        return
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        return
    key = _cache_key(disk_key)
    win = _home_window()
    win.setProperty(_PROP_PREFIX + key, encoded)
    win.setProperty(_EXPIRE_PREFIX + key, str(time.time() + _SESSION_TTL_SEC))


def clear_window_page(disk_key: str) -> None:
    key = _cache_key(disk_key)
    win = _home_window()
    win.clearProperty(_PROP_PREFIX + key)
    win.clearProperty(_EXPIRE_PREFIX + key)

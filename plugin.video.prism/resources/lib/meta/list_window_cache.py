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
_BROWSE_MAT_PREFIX = "prism_browse_mat_"
_BROWSE_MAT_EXPIRE = "prism_browse_mat_exp_"
_EPISODE_PAGE_PREFIX = "prism_episode_page_"
_EPISODE_PAGE_EXPIRE = "prism_episode_page_exp_"


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


def serialize_episode_page_rows_for_window(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Slim episode rows for window cache; only stamp display-ready when plot is present."""
    from resources.lib.database.sync_meta_cache import row_has_plot_meta
    from resources.lib.meta.profiles import MetaProfile
    from resources.lib.meta.storage import slim_db_row

    packed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slim = slim_db_row(row, profile=MetaProfile.LIST, slim_art=False)
        slim.pop("simkl_object", None)
        if row.get("_menu_display_ready") and row_has_plot_meta(slim):
            slim["_menu_display_ready"] = True
        packed.append(slim)
    return packed


def _cache_key(disk_key: str) -> str:
    digest = hashlib.sha1(disk_key.encode("utf-8")).hexdigest()[:20]
    return digest


def _home_window():
    import xbmcgui

    return xbmcgui.Window(10000)


def _read_window_payload(
    disk_key: str,
    *,
    prop_prefix: str,
    expire_prefix: str,
) -> list[dict[str, Any]] | None:
    key = _cache_key(disk_key)
    expire_raw = _home_window().getProperty(expire_prefix + key)
    if not expire_raw:
        return None
    try:
        expires = float(expire_raw)
    except (TypeError, ValueError):
        return None
    if time.time() >= expires:
        _clear_window_payload(disk_key, prop_prefix=prop_prefix, expire_prefix=expire_prefix)
        return None
    raw = _home_window().getProperty(prop_prefix + key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    return payload


def _write_window_payload(
    disk_key: str,
    items: list[dict[str, Any]],
    *,
    prop_prefix: str,
    expire_prefix: str,
) -> None:
    if not items:
        return
    try:
        encoded = json.dumps(items, separators=(",", ":"))
    except (TypeError, ValueError):
        return
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        return
    key = _cache_key(disk_key)
    win = _home_window()
    win.setProperty(prop_prefix + key, encoded)
    win.setProperty(expire_prefix + key, str(time.time() + _SESSION_TTL_SEC))


def _clear_window_payload(
    disk_key: str,
    *,
    prop_prefix: str,
    expire_prefix: str,
) -> None:
    key = _cache_key(disk_key)
    win = _home_window()
    win.clearProperty(prop_prefix + key)
    win.clearProperty(expire_prefix + key)


def get_window_page_items(disk_key: str) -> list[dict[str, Any]] | None:
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled():
        return None
    return _read_window_payload(
        disk_key,
        prop_prefix=_PROP_PREFIX,
        expire_prefix=_EXPIRE_PREFIX,
    )


def set_window_page_items(disk_key: str, items: list[dict[str, Any]]) -> None:
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled() or not items:
        return
    _write_window_payload(
        disk_key,
        items,
        prop_prefix=_PROP_PREFIX,
        expire_prefix=_EXPIRE_PREFIX,
    )


def clear_window_page(disk_key: str) -> None:
    _clear_window_payload(
        disk_key,
        prop_prefix=_PROP_PREFIX,
        expire_prefix=_EXPIRE_PREFIX,
    )


def browse_materialize_window_key(
    source: str,
    catalog: str,
    list_id: str | None,
    page: int | None,
) -> str:
    """Stable key for materialized browse pages (survives plugin invoker exit)."""
    return "bmat|{0}|{1}|{2}|{3}".format(
        str(source or ""),
        str(catalog or ""),
        str(list_id or ""),
        max(1, int(page or 1)),
    )


def get_browse_materialized_items(disk_key: str) -> list[dict[str, Any]] | None:
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled():
        return None
    return _read_window_payload(
        disk_key,
        prop_prefix=_BROWSE_MAT_PREFIX,
        expire_prefix=_BROWSE_MAT_EXPIRE,
    )


def set_browse_materialized_items(disk_key: str, items: list[dict[str, Any]]) -> None:
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled() or not items:
        return
    slim = serialize_page_rows_for_window(items)
    _write_window_payload(
        disk_key,
        slim,
        prop_prefix=_BROWSE_MAT_PREFIX,
        expire_prefix=_BROWSE_MAT_EXPIRE,
    )


def episode_page_window_disk_key(
    catalog: str,
    episode_rows: list[dict],
    *,
    paint_profile: str,
    menu_action: str,
    page: int,
) -> str:
    """Stable key for painted episode pages (Next Up, Continue Watching, Watched Episodes)."""
    from resources.lib.meta.list_paint import episode_row_simkl_ids
    from resources.lib.meta.paint_cache import episode_page_paint_cache_key

    episode_ids = episode_row_simkl_ids(episode_rows)
    paint_key = episode_page_paint_cache_key(catalog, episode_ids, paint_profile=paint_profile)
    paint_digest = hashlib.sha1(repr(paint_key).encode("utf-8")).hexdigest()[:20]
    return "epwin|{0}|{1}|{2}|{3}|{4}".format(
        str(menu_action or "episodes"),
        str(catalog or ""),
        max(1, int(page or 1)),
        str(paint_profile or ""),
        paint_digest,
    )


def get_episode_page_window_items(disk_key: str) -> list[dict[str, Any]] | None:
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled():
        return None
    return _read_window_payload(
        disk_key,
        prop_prefix=_EPISODE_PAGE_PREFIX,
        expire_prefix=_EPISODE_PAGE_EXPIRE,
    )


def set_episode_page_window_items(disk_key: str, items: list[dict[str, Any]]) -> None:
    from resources.lib.modules.globals import g

    if not g.kodi_menu_caching_enabled() or not items:
        return
    slim = serialize_episode_page_rows_for_window(items)
    _write_window_payload(
        disk_key,
        slim,
        prop_prefix=_EPISODE_PAGE_PREFIX,
        expire_prefix=_EPISODE_PAGE_EXPIRE,
    )

"""Per menu-open snapshot of hot settings (Otaku bool_cache pattern)."""
from __future__ import annotations

from typing import Any

_SNAPSHOT: dict[str, Any] | None = None


def begin_browse_menu_snapshot() -> dict[str, Any]:
    global _SNAPSHOT
    from resources.lib.modules.globals import g

    _SNAPSHOT = {
        "page_limit": max(1, g.get_int_setting("item.limit", 25)),
        "menu_caching": g.kodi_menu_caching_enabled(),
        "wal_mode": g.get_bool_setting("general.db.wal_mode", False),
    }
    return dict(_SNAPSHOT)


def browse_menu_snapshot() -> dict[str, Any]:
    if _SNAPSHOT is None:
        return begin_browse_menu_snapshot()
    return dict(_SNAPSHOT)


def clear_browse_menu_snapshot() -> None:
    global _SNAPSHOT
    _SNAPSHOT = None

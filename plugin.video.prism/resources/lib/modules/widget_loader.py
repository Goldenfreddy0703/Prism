"""Serialize skin widget directory loads so multiple widgets do not hammer Simkl/DB at once."""
from __future__ import annotations

import time

from resources.lib.modules.global_lock import GlobalLock
from resources.lib.modules.globals import g

_LAST_LOAD_MS_KEY = "widget.last_load_ms"
_SESSION_PREFIX = "widget.session."


def widget_stagger_enabled() -> bool:
    if g.IS_SERVICE or not g.FROM_WIDGET:
        return False
    if not g.get_bool_setting("general.widget.stagger", True):
        return False
    return True


def widget_request_key() -> str:
    action = g.REQUEST_PARAMS.get("action", "")
    parts = [action]
    for key in ("catalog", "status", "mediatype", "endpoint", "list_id"):
        value = g.REQUEST_PARAMS.get(key)
        if value:
            parts.append(f"{key}={value}")
    action_args = g.REQUEST_PARAMS.get("action_args")
    if isinstance(action_args, dict):
        for key in ("simkl_id", "catalog", "status"):
            value = action_args.get(key)
            if value is not None:
                parts.append(f"args.{key}={value}")
    return "|".join(parts) or action or "widget"


def mark_widget_session_loaded(request_key: str | None = None) -> bool:
    """
    Return True when this widget URL has not been loaded yet this Kodi session.

    First load can prefer warm caches; later refreshes may bypass them.
    """
    if not g.FROM_WIDGET:
        return False
    key = f"{_SESSION_PREFIX}{request_key or widget_request_key()}"
    if g.get_bool_runtime_setting(key):
        return False
    g.set_runtime_setting(key, True)
    return True


def clear_widget_session_flags() -> None:
    """Clear per-session widget markers (e.g. before a forced home refresh)."""
    prefix = f"{g.ADDON_ID}.{g.VERSION}.runtime.{_SESSION_PREFIX}"
    try:
        for key in g.HOME_WINDOW.getProperties().keys():
            if key.startswith(prefix):
                g.HOME_WINDOW.clearProperty(key)
    except Exception:
        pass


class WidgetLoadGate:
    """Context manager: one widget directory request at a time + optional inter-load delay."""

    def __init__(self):
        self._lock: GlobalLock | None = None

    def _apply_delay(self) -> None:
        delay_ms = max(0, g.get_int_setting("general.widget.delay", 1000))
        if delay_ms <= 0:
            return
        last_ms = g.get_int_runtime_setting(_LAST_LOAD_MS_KEY, 0)
        wait_ms = delay_ms - (int(time.time() * 1000) - last_ms)
        if wait_ms > 0:
            g.log(f"Widget stagger waiting {wait_ms}ms before {widget_request_key()}", "debug")
            g.wait_for_abort(wait_ms / 1000.0)

    def __enter__(self):
        if not widget_stagger_enabled():
            return self
        self._lock = GlobalLock("widget.load")
        self._lock.__enter__()
        self._apply_delay()
        g.log(f"Widget load started: {widget_request_key()}", "debug")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self._lock:
            return False
        try:
            return self._lock.__exit__(exc_type, exc_val, exc_tb)
        finally:
            g.set_runtime_setting(_LAST_LOAD_MS_KEY, int(time.time() * 1000))
            g.log(f"Widget load finished: {widget_request_key()}", "debug")
            self._lock = None

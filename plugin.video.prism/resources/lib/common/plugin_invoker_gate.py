"""Serialize Kodi prism.py invocations and pace interpreter spawns at cold start."""

from __future__ import annotations

import os
import sys
import threading
import time

import xbmc

from resources.lib.modules.globals import g

_PLUGIN_SLOT_LOCK_KEY = "prism.plugin_slot.owner"
_PLUGIN_SLOT_FINISHED_KEY = "prism.plugin_slot.last_finished"
_MIN_INVOKER_GAP_SEC = 2.0
_LOCK_STALE_SEC = 90.0
_runtime_settings_cache = None


def _runtime_settings():
    global _runtime_settings_cache
    if _runtime_settings_cache is None:
        from resources.lib.modules.settings_cache import RuntimeSettingsCache

        _runtime_settings_cache = RuntimeSettingsCache()
    return _runtime_settings_cache


def _get_runtime_setting(setting_id: str, default_value=None):
    cache = getattr(g, "RUNTIME_SETTINGS_CACHE", None)
    if cache is not None:
        return g.get_runtime_setting(setting_id, default_value)
    return _runtime_settings().get_setting(setting_id, default_value)


def _set_runtime_setting(setting_id: str, value) -> None:
    cache = getattr(g, "RUNTIME_SETTINGS_CACHE", None)
    if cache is not None:
        g.set_runtime_setting(setting_id, value)
        return
    _runtime_settings().set_setting(setting_id, value)


def _clear_runtime_setting(setting_id: str) -> None:
    cache = getattr(g, "RUNTIME_SETTINGS_CACHE", None)
    if cache is not None:
        g.clear_runtime_setting(setting_id)
        return
    _runtime_settings().clear_setting(setting_id)


def _get_float_runtime_setting(setting_id: str, default_value=0.0) -> float:
    cache = getattr(g, "RUNTIME_SETTINGS_CACHE", None)
    if cache is not None:
        return g.get_float_runtime_setting(setting_id, default_value)
    return _runtime_settings().get_float_setting(setting_id, default_value)


def _abort_requested() -> bool:
    try:
        return g.abort_requested()
    except Exception:
        return xbmc.Monitor().abortRequested()


def _wait_abort(seconds: float) -> None:
    try:
        g.wait_for_abort(seconds)
    except Exception:
        xbmc.Monitor().waitForAbort(seconds)


def should_hold_plugin_slot_from_argv() -> bool:
    """Reserved for long-running invokers only — normal menu browse is Seren-like (no slot)."""
    from resources.lib.common.thread_pool import _peek_plugin_action_from_argv, plugin_action_allows_threads

    try:
        handle = int(sys.argv[1])
    except (IndexError, ValueError, TypeError):
        return False
    if handle <= 0:
        return False
    action = _peek_plugin_action_from_argv()
    if not plugin_action_allows_threads(action):
        return False
    plugin_name = xbmc.getInfoLabel("Container.PluginName")
    if plugin_name and plugin_name != "plugin.video.prism":
        return False
    return True


def _slot_token() -> str:
    return f"{os.getpid()}:{threading.get_ident()}:{time.time()}"


def _lock_owner_stale(owner: str | None) -> bool:
    if not owner:
        return True
    try:
        issued = float(str(owner).rsplit(":", 1)[-1])
    except (ValueError, IndexError):
        return True
    return time.time() - issued > _LOCK_STALE_SEC


def _try_acquire_slot(token: str) -> bool:
    owner = _get_runtime_setting(_PLUGIN_SLOT_LOCK_KEY)
    if owner and owner != token and not _lock_owner_stale(owner):
        return False
    if owner and owner != token and _lock_owner_stale(owner):
        _clear_runtime_setting(_PLUGIN_SLOT_LOCK_KEY)
        owner = None
    if not owner:
        _set_runtime_setting(_PLUGIN_SLOT_LOCK_KEY, token)
        owner = _get_runtime_setting(_PLUGIN_SLOT_LOCK_KEY)
    return owner == token


def _wait_invoker_gap() -> None:
    last_finished = _get_float_runtime_setting(_PLUGIN_SLOT_FINISHED_KEY, 0)
    if not last_finished:
        return
    while not _abort_requested():
        remaining = _MIN_INVOKER_GAP_SEC - (time.time() - last_finished)
        if remaining <= 0:
            return
        _wait_abort(min(0.05, remaining))


def acquire_prism_plugin_slot(max_wait_sec: float = 45.0) -> str:
    """Hold a cross-process slot so only one prism.py invoker runs at a time."""
    token = _slot_token()
    deadline = time.time() + max_wait_sec
    while not _abort_requested():
        if _try_acquire_slot(token):
            _wait_invoker_gap()
            return token
        if time.time() >= deadline:
            try:
                g.log("PRISM: Plugin slot timeout — continuing without exclusive lock", "warning")
            except Exception:
                pass
            return token
        _wait_abort(0.05)
    return token


def release_prism_plugin_slot(token: str | None) -> None:
    if not token:
        return
    if _get_runtime_setting(_PLUGIN_SLOT_LOCK_KEY) == token:
        _clear_runtime_setting(_PLUGIN_SLOT_LOCK_KEY)
    _set_runtime_setting(_PLUGIN_SLOT_FINISHED_KEY, time.time())


def prepare_foreground_plugin_invoke() -> bool:
    """Menus are never blocked on service startup (Seren parity)."""
    return True


def ensure_startup_ready_for_foreground(max_wait_sec: float = 45.0) -> bool:
    """No-op — kept for callers; never blocks menus on service startup."""
    _ = max_wait_sec
    return True

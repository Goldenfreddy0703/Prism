"""Gate Prism background work so it does not contend with playback (Seren-aligned service)."""
from __future__ import annotations

import time

import xbmc

from resources.lib.modules.globals import g

_BACKGROUND_BUSY_KEY = "background.maintenance_busy"
_DEFAULT_THROTTLE_SEC = 86400.0


def playback_session_busy() -> bool:
    """True while PrismPlayer owns an active playback session (binge / smart play)."""
    if g.get_bool_runtime_setting("playback.session_busy"):
        return True
    if g.get_bool_runtime_setting("playback.pipeline_busy"):
        return True
    try:
        if xbmc.Player().isPlaying():
            return True
    except Exception:
        pass
    return False


def idle_ok_for_background_work() -> bool:
    """True when heavy idle maintenance may start (not playing, not scraping pipeline)."""
    if playback_session_busy():
        return False
    if g.get_bool_runtime_setting(_BACKGROUND_BUSY_KEY):
        return False
    try:
        from resources.lib.modules.page_prefetch import foreground_browse_busy

        if foreground_browse_busy():
            return False
    except Exception:
        pass
    return True


def throttle_elapsed(setting_key: str, interval_sec: float = _DEFAULT_THROTTLE_SEC) -> bool:
    last = float(g.get_float_runtime_setting(setting_key, 0) or 0)
    if last <= 0:
        return True
    return (time.time() - last) >= float(interval_sec)


def mark_throttle(setting_key: str) -> None:
    g.set_runtime_setting(setting_key, time.time())


class background_work_guard:
    """Context manager: set background.maintenance_busy for idle maintenance runs."""

    def __enter__(self):
        g.set_runtime_setting(_BACKGROUND_BUSY_KEY, True)
        return self

    def __exit__(self, *args):
        g.clear_runtime_setting(_BACKGROUND_BUSY_KEY)

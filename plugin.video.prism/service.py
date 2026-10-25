from __future__ import annotations

import sqlite3
import sys
import threading
import time
from random import randint

import xbmc

from resources.lib.common import tools

if tools.is_stub():
    # noinspection PyUnresolvedReferences
    from mock_kodi import MOCK

from resources.lib.modules.globals import g

from resources.lib.modules.prism_version import do_version_change
from resources.lib.modules.prismMonitor import PrismMonitor
from resources.lib.modules.update_news import do_update_news
from resources.lib.modules.manual_timezone import validate_timezone_detected

_PLUGIN_BASE = "plugin://plugin.video.prism/"

# Seren service.py: one housekeeping batch, then sleep 60 * randint(13, 17) minutes before the next.
_MAINTENANCE_BATCH_INTERVAL_MIN = (13, 17)
# Simkl activity sync is throttled to 5 minutes in simkl_sync; poll during the long sleep only.
_SIMKL_SYNC_POLL_SEC = 5 * 60


def _service_shutdown() -> None:
    """Service exit hook."""
    try:
        from resources.lib.common.thread_pool import release_global_executors

        release_global_executors(wait=False, cancel_futures=True)
    except Exception:
        pass


def _run_long_life_manager() -> None:
    try:
        from resources.lib.modules.providers.service_manager import ProvidersServiceManager

        ProvidersServiceManager().run_long_life_manager()
    except Exception:
        g.log_stacktrace()


def _run_kodi_watched_bridge_poller(monitor: PrismMonitor) -> None:
    """Poll MyVideos for Kodi native watched toggles on Prism URLs (independent of maintenance cycle)."""
    try:
        from resources.lib.simkl.kodi_watched_bridge import bridge_enabled, scan_kodi_watched_bridge

        while not monitor.abortRequested():
            if bridge_enabled():
                try:
                    from resources.lib.common.background_coordinator import idle_ok_for_background_work

                    if idle_ok_for_background_work():
                        scan_kodi_watched_bridge(trigger="poller")
                except Exception:
                    g.log_stacktrace()
            if monitor.waitForAbort(2):
                break
    except Exception:
        g.log_stacktrace()


def _run_parent_folder_refresh_poller(monitor: PrismMonitor) -> None:
    """Repaint deferred parent TV lists when the user backs out of drilldown."""
    try:
        from resources.lib.simkl.menu_parent_refresh import poll_pending_parent_folder_refresh

        while not monitor.abortRequested():
            try:
                from resources.lib.common.background_coordinator import idle_ok_for_background_work

                if idle_ok_for_background_work():
                    poll_pending_parent_folder_refresh()
            except Exception:
                g.log_stacktrace()
            if monitor.waitForAbort(0.5):
                break
    except Exception:
        g.log_stacktrace()


def _run_plugin(action: str) -> None:
    xbmc.executebuiltin(f'RunPlugin("{_PLUGIN_BASE}?action={action}")')


g.init_globals(sys.argv)
from resources.lib.common.backup_restore import apply_deferred_db_restore

apply_deferred_db_restore()
do_version_change()

_migration_skip_release_notes = False
try:
    from resources.lib.common.maintenance import consume_deferred_wipe_at_startup

    if consume_deferred_wipe_at_startup():
        _migration_skip_release_notes = True
    else:
        from resources.lib.modules.release_migration import maybe_show_migration_wipe_dialog

        _migration_skip_release_notes = maybe_show_migration_wipe_dialog()
except Exception:
    g.log_stacktrace()

g.log("##################  STARTING SERVICE  ######################")
g.log(f"### {g.ADDON_ID} {g.VERSION}")
g.log(f"### Platform: {g.PLATFORM}")
g.log(f"### Python: {sys.version.split(' ', 1)[0]}")
g.log(f"### SQLite: {sqlite3.sqlite_version}")  # pylint: disable=no-member
g.log(f"### Detected Kodi Version: {g.KODI_VERSION}")
g.log(f"### Detected timezone: {repr(g.LOCAL_TIMEZONE.zone)}")
g.log("#############  SERVICE ENTERED KEEP ALIVE  #################")

g.set_runtime_setting("cache_maintenance.service_started_at", time.time())

try:
    from resources.lib.database.session import get_sync_database
    from resources.lib.modules.cache_maintenance import mark_service_migrations_ready

    get_sync_database()
    mark_service_migrations_ready()
except Exception:
    g.log_stacktrace()

monitor = PrismMonitor()
_long_life_thread: threading.Thread | None = None
_bridge_poller_thread: threading.Thread | None = None
_parent_refresh_poller_thread: threading.Thread | None = None
try:
    _long_life_thread = threading.Thread(
        target=_run_long_life_manager,
        daemon=True,
        name="prism-long-life",
    )
    _long_life_thread.start()
    _bridge_poller_thread = threading.Thread(
        target=_run_kodi_watched_bridge_poller,
        args=(monitor,),
        daemon=True,
        name="prism-kodi-watched-bridge",
    )
    _bridge_poller_thread.start()
    _parent_refresh_poller_thread = threading.Thread(
        target=_run_parent_folder_refresh_poller,
        args=(monitor,),
        daemon=True,
        name="prism-parent-folder-refresh",
    )
    _parent_refresh_poller_thread.start()

    if not _migration_skip_release_notes:
        do_update_news()
    validate_timezone_detected()
    try:
        g.clear_kodi_bookmarks()
    except TypeError:
        g.log(
            "Unable to clear bookmarks on service init. This is not a problem if it occurs immediately after install.",
            "warning",
        )

    _run_plugin("torrentCacheCleanup")

    while not monitor.abortRequested():
        _run_plugin("runMaintenance")
        if not g.wait_for_abort(15):
            _run_plugin("syncSimklActivities")
        if not g.wait_for_abort(15):
            _run_plugin("cleanOrphanedMetadata")
        if not g.wait_for_abort(15):
            _run_plugin("updateLocalTimezone")
        try:
            from resources.lib.common.background_coordinator import idle_ok_for_background_work

            if idle_ok_for_background_work():
                _run_plugin("runPrismIdleMaintenance")
        except Exception:
            g.log_stacktrace()
            break

        maintenance_sleep_sec = 60 * randint(*_MAINTENANCE_BATCH_INTERVAL_MIN)
        g.log(
            f"Prism service: next maintenance batch in {maintenance_sleep_sec // 60} minutes",
            "debug",
        )
        slept = 0
        while not monitor.abortRequested() and slept < maintenance_sleep_sec:
            chunk = min(_SIMKL_SYNC_POLL_SEC, maintenance_sleep_sec - slept)
            if g.wait_for_abort(chunk):
                break
            slept += chunk
            _run_plugin("syncSimklActivities")
finally:
    _service_shutdown()
    if _long_life_thread is not None and _long_life_thread.is_alive():
        _long_life_thread.join(timeout=3.0)
    del monitor
    g.deinit()

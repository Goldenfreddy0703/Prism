import sqlite3
import sys
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

g.init_globals(sys.argv)
do_version_change()

g.log("##################  STARTING SERVICE  ######################")
g.log(f"### {g.ADDON_ID} {g.VERSION}")
g.log(f"### Platform: {g.PLATFORM}")
g.log(f"### Python: {sys.version.split(' ', 1)[0]}")
g.log(f"### SQLite: {sqlite3.sqlite_version}")  # pylint: disable=no-member
g.log(f"### Detected Kodi Version: {g.KODI_VERSION}")
g.log(f"### Detected timezone: {repr(g.LOCAL_TIMEZONE.zone)}")
g.log("#############  SERVICE ENTERED KEEP ALIVE  #################")

monitor = PrismMonitor()
try:
    xbmc.executebuiltin('RunPlugin("plugin://plugin.video.prism/?action=longLifeServiceManager")')

    do_update_news()
    validate_timezone_detected()
    try:
        g.clear_kodi_bookmarks()
    except TypeError:
        g.log(
            "Unable to clear bookmarks on service init. This is not a problem if it occurs immediately after install.",
            "warning",
        )

    xbmc.executebuiltin('RunPlugin("plugin://plugin.video.prism/?action=torrentCacheCleanup")')
    xbmc.executebuiltin('RunPlugin("plugin://plugin.video.prism/?action=prefetchCalendars")')

    def _service_db_idle() -> bool:
        try:
            from resources.lib.modules.page_prefetch import foreground_browse_busy

            return not foreground_browse_busy()
        except Exception:
            return True

    while not monitor.abortRequested():
        if _service_db_idle():
            xbmc.executebuiltin('RunPlugin("plugin://plugin.video.prism/?action=runMaintenance")')
        if not g.wait_for_abort(15):  # Sleep to make sure tokens refreshed during maintenance
            if _service_db_idle():
                xbmc.executebuiltin('RunPlugin("plugin://plugin.video.prism/?action=syncSimklActivities")')
        if not g.wait_for_abort(15):  # Sleep to make sure we don't possibly clobber settings
            if _service_db_idle():
                xbmc.executebuiltin('RunPlugin("plugin://plugin.video.prism/?action=cleanOrphanedMetadata")')
        if not g.wait_for_abort(15):  # Sleep to make sure we don't possibly clobber settings
            xbmc.executebuiltin('RunPlugin("plugin://plugin.video.prism/?action=updateLocalTimezone")')
        if g.wait_for_abort(60 * randint(13, 17)):
            break
finally:
    del monitor
    g.deinit()

import xbmc
import xbmcaddon

properties = [
    "context.prism.quickResume",
    "context.prism.shuffle",
    "context.prism.playFromRandomPoint",
    "context.prism.rescrape",
    "context.prism.rescrape_ss",
    "context.prism.sourceSelect",
    "context.prism.findRecommendations",
    "context.prism.findRelations",
    "context.prism.simklManager",
]


class PropertiesUpdater(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.addon = xbmcaddon.Addon()
        self._update_window_properties()

    def __del__(self):
        del self.addon

    def onSettingsChanged(self):
        self._update_window_properties()

    def _update_window_properties(self):
        for prop in properties:
            setting = self.addon.getSetting(prop)
            if setting == "false":
                xbmc.executebuiltin(f"SetProperty({prop},{setting},home)")
            else:
                xbmc.executebuiltin(f"ClearProperty({prop},home)")
            xbmc.log(f'Context menu item {"disabled" if setting == "false" else "enabled"}: {prop}')


xbmc.log("context.prism service: starting", xbmc.LOGINFO)

try:
    # start monitoring settings changes events
    properties_monitor = PropertiesUpdater()

    # wait until abort is requested
    properties_monitor.waitForAbort()
except Exception as e:
    xbmc.log(f"context.prism service: error - {e}", xbmc.LOGERROR)
finally:
    del properties_monitor

xbmc.log("context.prism service: stopped", xbmc.LOGINFO)

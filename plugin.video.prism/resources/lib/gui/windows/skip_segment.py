import threading

import xbmc

from resources.lib.gui.windows.base_window import BaseWindow
from resources.lib.modules.globals import g

SEGMENT_LABELS = {
    "intro": 30801,
    "recap": 30802,
    "credits": 30803,
    "preview": 30804,
}


class SkipSegment(BaseWindow):
    """
    Overlay providing a button to skip a media segment (intro/recap/credits/preview).
    """

    def __init__(self, xml_file, xml_location, item_information=None, segment_type="intro", segment_end=0):
        try:
            super().__init__(xml_file, xml_location, item_information=item_information)
            self.player = xbmc.Player()
            self.segment_type = segment_type if segment_type in SEGMENT_LABELS else "intro"
            self.segment_end = self._safe_float(segment_end)
            self.offset = g.get_int_setting("introdb.offset")
            self.display_time = max(g.get_int_setting("introdb.displaytime"), 1)
            self.closed = False
            self.playing_file = self._get_playing_file()
        except Exception:
            g.log_stacktrace()

    def __del__(self):
        self.player = None
        del self.player

    @staticmethod
    def _safe_float(value):
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _get_playing_file(self):
        try:
            return self.player.getPlayingFile()
        except RuntimeError:
            return None

    def onInit(self):
        self.setProperty("skip.segment", self.segment_type)
        self.setProperty("skip.label", g.get_language_string(SEGMENT_LABELS.get(self.segment_type, 30801)))
        self._start_watcher()
        super().onInit()

    def _start_watcher(self):
        thread = threading.Thread(target=self._watch)
        thread.daemon = True
        thread.start()

    def _watch(self):
        """Auto-close once the segment ends, playback changes, or the display time elapses."""
        try:
            elapsed = 0.0
            while not self.closed and not g.abort_requested():
                if not self.player.isPlaying() or self.playing_file != self._get_playing_file():
                    break
                try:
                    current = self.player.getTime()
                except RuntimeError:
                    break
                if self.segment_end and current >= self.segment_end:
                    break
                if elapsed >= self.display_time:
                    break
                xbmc.sleep(500)
                elapsed += 0.5
        except Exception:
            g.log_stacktrace()

        if not self.closed:
            self.close()

    def _seek_skip(self):
        if not self.player.isPlaying():
            return
        try:
            total = self.player.getTotalTime()
        except RuntimeError:
            total = 0

        target = (self.segment_end + self.offset) if self.segment_end else (total - 5 if total else 0)
        if total and target >= total:
            target = total - 5
        if target > 0:
            self.player.seekTime(target)

    def close(self):
        self.closed = True
        super().close()

    def handle_action(self, action_id, control_id=None):
        if action_id == 7:
            if control_id == 3001:
                self._seek_skip()
                self.close()
            elif control_id == 3002:
                self.close()

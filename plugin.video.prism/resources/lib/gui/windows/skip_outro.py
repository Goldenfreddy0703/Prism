from resources.lib.gui.windows.playing_next import PlayingNext
from resources.lib.modules.globals import g


class SkipOutro(PlayingNext):
    """
    Playing Next dialog variant that also offers a Skip Outro button (id 3004).

    Shown in place of the standard Playing Next dialog when IntroDB reports a
    credits/outro segment for the current item. Kept as its own window/skin file
    so theme authors can style it independently of playing_next.xml.
    """

    def __init__(self, xml_file, xml_location, item_information=None):
        super().__init__(xml_file, xml_location, item_information=item_information)
        self.outro_end = self._get_outro_end()
        self.offset = g.get_int_setting("introdb.offset")

    @staticmethod
    def _get_outro_end():
        """Outro end (seconds) published by the player, or None when unavailable.

        0 is a valid value meaning "credits run to the end of the media".
        """
        value = g.HOME_WINDOW.getProperty("prism.outro.end")
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _skip_outro(self):
        if not self.isPlaying():
            return
        total = self.getTotalTime()
        if self.outro_end and self.outro_end > 0:
            target = self.outro_end + self.offset
        else:
            target = (total - 5) if total else 0
        if total and target >= total:
            target = total - 5
        if target > 0:
            self.seekTime(target)

    def handle_action(self, action, control_id=None):
        if action == 7 and control_id == 3004:
            self._skip_outro()
            self.close()
            return
        super().handle_action(action, control_id)

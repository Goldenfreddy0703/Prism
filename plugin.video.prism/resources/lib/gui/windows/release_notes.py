from resources.lib.gui.windows.base_window import BaseWindow
from resources.lib.modules import release_notes
from resources.lib.modules.globals import g


class ReleaseNotesWindow(BaseWindow):
    CLOSE_CONTROL = 5003
    CHANGELOG_SCROLL = 5101
    NEWS_SCROLL = 5102

    def __init__(self, xml_file, xml_location):
        super().__init__(xml_file, xml_location)

    def onInit(self):
        changelog = release_notes.read_release_file("changelog.txt")
        news = release_notes.read_release_file("news.txt")
        if not news.strip():
            news = g.get_language_string(31233)
        self.setProperty("prism.release.changelog", changelog)
        self.setProperty("prism.release.news", news)
        self.setProperty("prism.release.version", g.CLEAN_VERSION or g.VERSION or "")
        self.set_default_focus(control_id=self.CLOSE_CONTROL)
        super().onInit()

    def handle_action(self, action_id, control_id=None):
        # BaseWindow forwards every non-back key while a control is focused.
        # Only Select/Enter (action 7, also sent from onClick) should close.
        if control_id == self.CLOSE_CONTROL and action_id == 7:
            self.close()

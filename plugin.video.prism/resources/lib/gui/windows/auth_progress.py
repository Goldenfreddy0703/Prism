import xbmcgui

from resources.lib.modules.globals import g
from resources.lib.modules.qr_auth import delete_qr_png

_CLOSING_ACTIONS = {
    xbmcgui.ACTION_PARENT_DIR,
    xbmcgui.ACTION_PREVIOUS_MENU,
    xbmcgui.ACTION_STOP,
    xbmcgui.ACTION_NAV_BACK,
}


class AuthProgressDialog(xbmcgui.WindowXMLDialog):
    """Device-code auth dialog with QR image, instructions, and progress bar."""

    def __init__(self, xml_file, location, heading="", text="", qr_code="", percent=100):
        super().__init__(xml_file, location)
        self._percent = percent
        self._cancelled = False
        self._qr_path = (qr_code or "").replace("\\", "/")
        self.setProperty("texture.white", f"{g.IMAGES_PATH}white.png")
        self.setProperty("settings.color", g.get_user_text_color())
        self.setProperty("auth.heading", heading or " ")
        self.setProperty("auth.text", text or " ")
        self.setProperty("qr_code", self._qr_path)

    def onInit(self):
        self.getControl(3003).setPercent(self._percent)
        self.setFocusId(4001)

    def onAction(self, action):
        if action.getId() in _CLOSING_ACTIONS:
            self._cancelled = True
            self.close()

    def onClick(self, control_id):
        if control_id == 4001:
            self._cancelled = True
            self.close()

    def close(self):
        delete_qr_png(self._qr_path or None)
        super().close()

    def update(self, percent=None, text=None):
        if percent is not None:
            self.getControl(3003).setPercent(percent)
        if text is not None:
            self.setProperty("auth.text", text)

    def iscanceled(self):
        return self._cancelled

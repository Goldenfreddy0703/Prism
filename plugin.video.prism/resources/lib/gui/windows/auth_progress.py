import xbmcgui

from resources.lib.modules.globals import g

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92


class AuthProgressDialog(xbmcgui.WindowXMLDialog):
    """Device-code auth dialog with QR image, instructions, and progress bar."""

    def __init__(self, xml_file, location, heading="", text="", qr_code="", percent=100):
        super().__init__(xml_file, location)
        self._percent = percent
        self._cancelled = False
        self.setProperty("texture.white", f"{g.IMAGES_PATH}white.png")
        self.setProperty("settings.color", g.get_user_text_color())
        self.setProperty("auth.heading", heading or " ")
        self.setProperty("auth.text", text or " ")
        self.setProperty("qr_code", (qr_code or "").replace("\\", "/"))

    def onInit(self):
        self.getControl(3003).setPercent(self._percent)

    def onAction(self, action):
        if action.getId() in {ACTION_PREVIOUS_MENU, ACTION_NAV_BACK}:
            self._cancelled = True
            self.close()

    def onClick(self, control_id):
        if control_id == 4001:
            self._cancelled = True
            self.close()

    def update(self, percent=None, text=None):
        if percent is not None:
            self.getControl(3003).setPercent(percent)
        if text is not None:
            self.setProperty("auth.text", text)

    def iscanceled(self):
        return self._cancelled

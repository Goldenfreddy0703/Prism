"""QR code helpers for device / PIN account authentication."""
from __future__ import annotations

import os

from resources.lib.common import tools
from resources.lib.modules.globals import g


def qr_png_path() -> str:
    return os.path.join(g.ADDON_USERDATA_PATH, "qr_code.png")


def generate_qr_png(url: str) -> str:
    import pyqrcode

    path = qr_png_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pyqrcode.create(url).png(path, scale=20)
    return path.replace("\\", "/")


def build_auth_message(verification_url: str, user_code: str | None = None) -> str:
    parts = [g.get_language_string(30018).format(g.color_string(verification_url))]
    if user_code:
        parts.append(g.get_language_string(30019).format(g.color_string(user_code)))
        if tools.copy2clip(user_code):
            parts.append(g.get_language_string(30047))
    return "[CR]".join(parts)


def auth_progress_percent(remaining: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, int(float(remaining * 100) / total)))


def open_auth_dialog(heading: str, verification_url: str, user_code: str | None = None, percent: int = 100):
    from resources.lib.database.skinManager import SkinManager
    from resources.lib.gui.windows.auth_progress import AuthProgressDialog

    dialog = AuthProgressDialog(
        *SkinManager().confirm_skin_path("auth_progress.xml"),
        heading=heading,
        text=build_auth_message(verification_url, user_code),
        qr_code=generate_qr_png(verification_url),
        percent=percent,
    )
    dialog.show()
    return dialog

"""Load addon settings.xml into a single window-property JSON blob (POV-style)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import xbmcvfs

from resources.lib.common import tools
from resources.lib.modules.globals import g

_SETTINGS_PROPERTY = "prism.settings_dict"
_EMPTY = "__EMPTY__"


def _property_key() -> str:
    return f"{g.ADDON_ID}.{_SETTINGS_PROPERTY}"


def _settings_xml_path() -> str:
    path = getattr(g, "SETTINGS_PATH", None)
    if path:
        return path
    addon_id = getattr(g, "ADDON_ID", None) or "plugin.video.prism"
    return tools.translate_path(f"special://profile/addon_data/{addon_id}/settings.xml")


def warm_settings_dict() -> dict[str, str] | None:
    """Parse profile settings.xml once and store all values in a window property."""
    settings_path = _settings_xml_path()
    if not xbmcvfs.exists(settings_path):
        return None
    try:
        with xbmcvfs.File(tools.validate_path(settings_path)) as handle:
            root = ET.fromstring(handle.read())
        settings_dict = {
            item.get("id"): (item.text or "")
            for item in root.iter("setting")
            if item.get("id")
        }
        g.HOME_WINDOW.setProperty(_property_key(), json.dumps(settings_dict))
        return settings_dict
    except Exception:
        g.log_stacktrace()
        return None


def clear_settings_dict() -> None:
    g.HOME_WINDOW.clearProperty(_property_key())


def get_hot_setting(setting_id: str, default_value=None):
    """Return a setting from the hot dict, or None if the dict is unavailable."""
    try:
        raw = g.HOME_WINDOW.getProperty(_property_key())
        if not raw:
            return None
        value = json.loads(raw).get(setting_id)
        if value is None:
            return None
        if value == "":
            return default_value
        return value
    except Exception:
        return None


def patch_hot_setting(setting_id: str, value) -> None:
    """Update one key in the hot dict after a programmatic settings write."""
    try:
        raw = g.HOME_WINDOW.getProperty(_property_key())
        settings_dict = json.loads(raw) if raw else {}
        if isinstance(value, bool):
            settings_dict[setting_id] = str(value).lower()
        else:
            settings_dict[setting_id] = "" if value is None else str(value)
        g.HOME_WINDOW.setProperty(_property_key(), json.dumps(settings_dict))
    except Exception:
        warm_settings_dict()

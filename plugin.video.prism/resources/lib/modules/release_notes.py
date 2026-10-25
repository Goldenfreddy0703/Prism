"""Changelog and news viewer (changelog.txt + news.txt)."""
from __future__ import annotations

import os

from resources.lib.common import tools
from resources.lib.modules.globals import g

_SETTING_SHOW_ON_UPDATE = "general.releaseNotes.showOnUpdate"
_SETTING_LAST_SHOWN = "general.releaseNotes.lastShownVersion"
_LEGACY_LAST_SHOWN = "update.news.version"
_CHANGELOG_FILE = "changelog.txt"
_NEWS_FILE = "news.txt"
_MAX_TEXT_CHARS = 120_000
_TRUNCATION_FOOTER = "\n\n[... truncated for Kodi; see the full changelog on GitHub ...]"


def migrate_last_shown_version() -> None:
    if g.get_setting(_SETTING_LAST_SHOWN):
        return
    legacy = g.get_setting(_LEGACY_LAST_SHOWN)
    if legacy:
        g.set_setting(_SETTING_LAST_SHOWN, legacy)


def read_release_file(filename: str) -> str:
    path = os.path.join(g.ADDON_PATH, filename)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        g.log(f"Release notes: could not read {filename}", "debug")
        return ""
    if filename == _CHANGELOG_FILE and len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS] + _TRUNCATION_FOOTER
    return text


def show_release_notes_window() -> None:
    from resources.lib.gui.windows.release_notes import ReleaseNotesWindow

    try:
        window = ReleaseNotesWindow("release_notes.xml", g.ADDON_PATH)
        window.doModal()
    finally:
        try:
            del window
        except UnboundLocalError:
            pass


def maybe_show_on_update() -> None:
    migrate_last_shown_version()
    if not g.get_bool_setting(_SETTING_SHOW_ON_UPDATE, True):
        return

    last_shown = (g.get_setting(_SETTING_LAST_SHOWN) or "").strip()
    current = (g.VERSION or "").strip()
    if not current:
        return

    if not last_shown and not g.get_setting(_LEGACY_LAST_SHOWN):
        g.set_setting(_SETTING_LAST_SHOWN, current)
        return

    if not tools.compare_version_numbers(last_shown, current):
        return

    show_release_notes_window()
    g.set_setting(_SETTING_LAST_SHOWN, current)

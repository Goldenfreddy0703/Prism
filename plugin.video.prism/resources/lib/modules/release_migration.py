"""One-shot major-upgrade prompts (e.g. 5.0.57 full addon_data wipe)."""
from __future__ import annotations

import xbmcgui

from resources.lib.common import tools
from resources.lib.modules.globals import g

MIGRATION_WIPE_SINCE = "5.0.57"
_SETTING_PENDING = "prism.migration557.pending"


def migration_wipe_pending() -> bool:
    return g.get_bool_setting(_SETTING_PENDING)


def flag_migration_wipe_on_version_cross(old_version: str | None, new_version: str) -> None:
    """Set pending wipe when upgrading from below MIGRATION_WIPE_SINCE to that version or newer."""
    old = (old_version or "").strip()
    new = (new_version or "").strip()
    if not old or not new:
        return
    if not tools.compare_version_numbers(old, MIGRATION_WIPE_SINCE):
        return
    if not tools.compare_version_numbers(MIGRATION_WIPE_SINCE, new, include_same=True):
        return
    g.set_setting(_SETTING_PENDING, "true")
    g.log(f"Migration {MIGRATION_WIPE_SINCE}: wipe pending (from {old} to {new})", "info")


def maybe_show_migration_wipe_dialog() -> bool:
    """
    Show migration UI when pending. Returns True to skip automatic release notes this service start.
    """
    if not migration_wipe_pending():
        return False

    title = g.get_language_string(31265).format(g.CLEAN_VERSION or g.VERSION or MIGRATION_WIPE_SINCE)
    body = g.get_language_string(31266)
    # Param order: customlabel, nolabel, yeslabel — returns 2 / 0 / 1 respectively
    choice = xbmcgui.Dialog().yesnocustom(
        title,
        body,
        g.get_language_string(31269),
        g.get_language_string(31268),
        g.get_language_string(31267),
    )
    g.log(f"Migration dialog choice={choice} (-1=cancel,0=later,1=wipe,2=changelog)", "info")

    if choice == 1:
        from resources.lib.common.maintenance import perform_migration_wipe

        perform_migration_wipe()
        return True

    if choice == 2:
        from resources.lib.modules.release_notes import show_release_notes_window

        show_release_notes_window()
        return True

    # Later (0) or cancelled (-1) — allow automatic release notes this start
    return False

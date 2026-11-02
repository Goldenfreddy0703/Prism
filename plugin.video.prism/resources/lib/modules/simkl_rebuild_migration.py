"""One-shot Simkl library rebuild when crossing to 5.0.64 (season composite schema)."""
from __future__ import annotations

from resources.lib.common import tools
from resources.lib.modules.globals import g

SIMKL_REBUILD_SINCE = "5.0.64"
_SETTING_PENDING = "prism.simklRebuild564.pending"


def simkl_rebuild_pending() -> bool:
    return g.get_bool_setting(_SETTING_PENDING)


def flag_simkl_rebuild_on_version_cross(old_version: str | None, new_version: str) -> None:
    """Schedule rebuild when upgrading from below 5.0.64 to 5.0.64+ (not fresh install)."""
    old = (old_version or "").strip()
    new = (new_version or "").strip()
    if not old:
        return
    if not tools.compare_version_numbers(old, SIMKL_REBUILD_SINCE):
        return
    if not tools.compare_version_numbers(SIMKL_REBUILD_SINCE, new, include_same=True):
        return
    g.set_setting(_SETTING_PENDING, "true")
    g.log(
        f"Simkl {SIMKL_REBUILD_SINCE}: library rebuild pending (from {old} to {new})",
        "info",
    )


def maybe_run_pending_simkl_rebuild() -> None:
    if not simkl_rebuild_pending():
        return
    g.log(f"Simkl {SIMKL_REBUILD_SINCE}: rebuilding simklSync.db after upgrade", "notice")
    try:
        from resources.lib.database.session import get_sync_database

        get_sync_database().re_build_database(silent=True)
        g.set_setting(_SETTING_PENDING, "false")
        g.log(f"Simkl {SIMKL_REBUILD_SINCE}: library rebuild finished", "info")
    except Exception:
        g.log_stacktrace()

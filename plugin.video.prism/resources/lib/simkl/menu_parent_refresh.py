"""Refresh Kodi-cached parent lists after drilldown watch edits (TV and anime)."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import xbmc

from resources.lib.modules.globals import g

_SHOW_PARENT_KEY = "show_parent_folder_{show_id}"
_SEASON_LIST_PARENT_KEY = "show_season_list_folder_{show_id}"
_PENDING_SHOW_REFRESH_KEY = "pending_parent_folder_refresh_path"
_PENDING_SEASON_LIST_REFRESH_KEY = "pending_season_list_refresh_path"

# Folder actions that are drilldown levels, not the show/anime hub parent list.
_DRILLDOWN_FOLDER_ACTIONS = frozenset(
    {
        "showSeasons",
        "showEpisodes",
        "flatEpisodes",
        "seasonEpisodes",
    }
)


def _show_parent_key(show_id: int) -> str:
    return _SHOW_PARENT_KEY.format(show_id=int(show_id))


def _season_list_parent_key(show_id: int) -> str:
    return _SEASON_LIST_PARENT_KEY.format(show_id=int(show_id))


def _normalize_folder_path(path: str) -> str:
    parsed = urlparse(path.strip())
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in ("prism_reload", "_cb"):
        query.pop(key, None)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _folder_action(path: str) -> str:
    if not path.startswith("plugin://plugin.video.prism"):
        return ""
    query = dict(parse_qsl(urlparse(path).query, keep_blank_values=True))
    return str(query.get("action") or "")


def capture_parent_folder_for_show(show_id: int) -> None:
    """Remember the TV/anime hub list the user drilled in from."""
    try:
        show_id = int(show_id)
    except (TypeError, ValueError):
        return
    path = (xbmc.getInfoLabel("Container.FolderPath") or "").strip()
    if not path.startswith("plugin://plugin.video.prism"):
        return
    if _folder_action(path) in _DRILLDOWN_FOLDER_ACTIONS:
        return
    g.set_runtime_setting(_show_parent_key(show_id), path)
    g.log(f"Captured show parent folder for {show_id}: {path[:120]}", "debug")


def capture_season_list_folder_for_show(show_id: int) -> None:
    """Remember the season menu when opening seasonEpisodes (TV or anime)."""
    try:
        show_id = int(show_id)
    except (TypeError, ValueError):
        return
    path = (xbmc.getInfoLabel("Container.FolderPath") or "").strip()
    if not path.startswith("plugin://plugin.video.prism"):
        return
    if _folder_action(path) != "showSeasons":
        return
    g.set_runtime_setting(_season_list_parent_key(show_id), path)
    g.log(f"Captured season-list parent for show {show_id}: {path[:120]}", "debug")


def _schedule_pending_refresh(path: str, pending_key: str, label: str, show_id: int) -> bool:
    if not path.startswith("plugin://plugin.video.prism"):
        return False
    g.set_runtime_setting(pending_key, path)
    g.log(f"Scheduled {label} refresh for show {show_id}", "debug")
    return True


def schedule_parent_folder_refresh(show_id: int) -> bool:
    """Defer show/anime hub list repaint until the user navigates back to that folder."""
    try:
        show_id = int(show_id)
    except (TypeError, ValueError):
        return False
    path = (g.get_runtime_setting(_show_parent_key(show_id)) or "").strip()
    return _schedule_pending_refresh(path, _PENDING_SHOW_REFRESH_KEY, "show parent", show_id)


def schedule_season_list_folder_refresh(show_id: int) -> bool:
    """Defer season menu repaint until the user backs out of seasonEpisodes."""
    try:
        show_id = int(show_id)
    except (TypeError, ValueError):
        return False
    path = (g.get_runtime_setting(_season_list_parent_key(show_id)) or "").strip()
    return _schedule_pending_refresh(path, _PENDING_SEASON_LIST_REFRESH_KEY, "season list", show_id)


def schedule_drilldown_parent_refreshes(show_id: int) -> None:
    """Queue deferred refreshes for hub + season list (if captured)."""
    schedule_parent_folder_refresh(show_id)
    schedule_season_list_folder_refresh(show_id)


def _apply_pending_refresh(pending_key: str) -> bool:
    pending = (g.get_runtime_setting(pending_key) or "").strip()
    if not pending:
        return False
    if not g.is_addon_visible():
        return False
    current = (xbmc.getInfoLabel("Container.FolderPath") or "").strip()
    if not current.startswith("plugin://plugin.video.prism"):
        return False
    if _normalize_folder_path(current) != _normalize_folder_path(pending):
        return False
    g.clear_runtime_setting(pending_key)
    if not g.refresh_visible_container():
        g.container_refresh()
    return True


def poll_pending_parent_folder_refresh() -> None:
    """Service poller: refresh parent folders when the user lands on them after Back."""
    if _apply_pending_refresh(_PENDING_SEASON_LIST_REFRESH_KEY):
        g.log("Applied deferred season-list refresh", "debug")
        return
    if _apply_pending_refresh(_PENDING_SHOW_REFRESH_KEY):
        g.log("Applied deferred show/anime hub refresh", "debug")

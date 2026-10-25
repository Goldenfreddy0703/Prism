"""Shared mark watched / unwatched logic for Simkl Manager and Kodi native menu bridge."""
from __future__ import annotations

import time

from resources.lib.database.session import get_sync_database
from resources.lib.modules.globals import g
from resources.lib.simkl.library_status import (
    _library_info,
    apply_local_library_status,
    apply_local_status_after_watch,
)
from resources.lib.simkl.payloads import info_to_history_payload
from resources.lib.simkl.statuses import resolved_watched_status_from_response


def _set_show_watch_edit_cooldown(show_id: int) -> None:
    """Skip immediate Simkl /sync/watched reconcile after a local watch edit."""
    g.set_runtime_setting(f"episode_watch_refresh_cooldown_{int(show_id)}", str(int(time.time())))


def finish_library_action(
    item_information: dict,
    *,
    refresh_container: bool = True,
    refresh_show_hub: bool = True,
    refresh_season_menu: bool = True,
) -> None:
    """Refresh visible lists after a watch-state edit."""
    from resources.lib.meta.paint_cache import clear_session_page_paint_for_item, clear_session_page_paint_for_show
    from resources.lib.simkl.library_list_sync import mark_library_catalog_verified
    from resources.lib.simkl.statuses import library_hub_catalog

    info = _library_info(item_information)
    hub_catalog = library_hub_catalog(info)
    mark_library_catalog_verified(hub_catalog)
    if refresh_show_hub and hub_catalog in ("tv", "anime", "movie"):
        from resources.lib.meta.list_pipeline import get_list_store

        get_list_store("library").forget_items(hub_catalog if hub_catalog != "movie" else "movie")
    show_id = _get_show_id(item_information)
    mediatype = (info.get("mediatype") or "").lower()
    if show_id is not None and mediatype in ("tvshow", "season", "episode"):
        clear_session_page_paint_for_show(int(show_id))
        try:
            from resources.lib.pipeline.drilldown_page import clear_drilldown_cache_for_show

            clear_drilldown_cache_for_show(int(show_id))
        except Exception:
            pass
    if info.get("simkl_id") is not None:
        clear_session_page_paint_for_item(int(info["simkl_id"]), info.get("mediatype"))
        from resources.lib.meta.display_store import get_display_meta_store

        display_store = get_display_meta_store()
        if mediatype in ("movie", "movies"):
            display_store.delete_row("movie", int(info["simkl_id"]))
        elif show_id is not None and mediatype in ("tvshow", "season", "episode"):
            display_store.delete_row("show", int(show_id))
    if show_id is not None and mediatype in ("tvshow", "season", "episode"):
        from resources.lib.simkl.menu_parent_refresh import (
            schedule_parent_folder_refresh,
            schedule_season_list_folder_refresh,
        )

        if refresh_show_hub:
            schedule_parent_folder_refresh(int(show_id))
        if refresh_season_menu:
            schedule_season_list_folder_refresh(int(show_id))
    if refresh_container:
        refreshed = g.refresh_visible_container()
        if not refreshed:
            g.container_refresh()
    g.trigger_widget_refresh(if_playing=False)


def _simkl_api():
    from resources.lib.indexers.simkl import SimklAPI

    return SimklAPI()


def _history_success(response, key: str) -> bool:
    if not response:
        return False
    added = response.get("added") or {}
    if isinstance(added.get(key), int) and added[key] > 0:
        return True
    if isinstance(added.get(key), list) and added[key]:
        return True
    if added.get("statuses"):
        return True
    return bool(added.get("episodes") or added.get("shows") or added.get("movies"))


def _remove_success(response, key: str) -> bool:
    if not response:
        return False
    deleted = response.get("deleted") or response.get("removed") or {}
    if not isinstance(deleted, dict):
        return False
    if isinstance(deleted.get(key), int) and deleted[key] > 0:
        return True
    for bucket in ("episodes", "shows", "movies", "anime"):
        val = deleted.get(bucket)
        if isinstance(val, int) and val > 0:
            return True
        if isinstance(val, list) and val:
            return True
    return False


def _episode_mark_coords(item_information: dict) -> tuple[int, int, int] | None:
    """Resolve (show_id, season, episode) for local DB watch columns (anime TVDB buckets)."""
    info = _watch_info(item_information)
    show_id = _get_show_id(item_information)
    if show_id is None:
        return None
    db = get_sync_database()
    from resources.lib.simkl.watch_coords import resolve_db_episode_coords

    coords = resolve_db_episode_coords(db, int(show_id), info)
    if coords:
        return int(show_id), int(coords[0]), int(coords[1])
    season = info.get("season")
    episode = info.get("episode")
    if episode is None:
        episode = info.get("number")
    if season is None or episode is None:
        return None
    return int(show_id), int(season), int(episode)


def _get_show_id(item_information: dict) -> int | None:
    from resources.lib.simkl.ids import parent_show_simkl_id, show_id_from_info, show_id_from_item

    if isinstance(item_information, dict):
        sid = show_id_from_item(item_information)
        if sid is not None:
            return int(sid)
    info = _watch_info(item_information)
    if not isinstance(info, dict):
        return None
    mediatype = (info.get("mediatype") or "").lower()
    if mediatype == "tvshow":
        raw = info.get("simkl_id")
        return int(raw) if raw is not None else None
    sid = parent_show_simkl_id(info)
    if sid is not None:
        return int(sid)
    return show_id_from_info(info)


def _season_mark_coords(item_information: dict) -> tuple[int, int] | None:
    info = _watch_info(item_information)
    show_id = _get_show_id(item_information)
    if show_id is None:
        return None
    db = get_sync_database()
    from resources.lib.simkl.watch_coords import resolve_db_season_number

    season = resolve_db_season_number(db, int(show_id), info)
    if season is None and info.get("season") is not None:
        season = int(info["season"])
    if season is None and info.get("tvdb_season") is not None:
        season = int(info["tvdb_season"]) or 1
    if season is None:
        return None
    return int(show_id), int(season)


def _watch_info(item_or_full: dict) -> dict:
    return _library_info(item_or_full)


def _capture_watch_snapshots(item_information: dict, mediatype: str) -> tuple[int | None, int | None, dict | None, dict | None]:
    """Return (show_id, season, show_snapshot, season_snapshot) before a watch edit."""
    from resources.lib.simkl.watch_refresh_policy import season_watch_snapshot, show_watch_snapshot

    show_id = _get_show_id(item_information)
    if show_id is None:
        return None, None, None, None
    show_id = int(show_id)
    mediatype = (mediatype or "").lower()
    if mediatype == "episode":
        coords = _episode_mark_coords(item_information)
        if coords is None:
            return show_id, None, show_watch_snapshot(show_id), None
        _, season, _number = coords
        return show_id, season, show_watch_snapshot(show_id), season_watch_snapshot(show_id, season)
    if mediatype == "season":
        season_coords = _season_mark_coords(item_information)
        if season_coords is None:
            return show_id, None, show_watch_snapshot(show_id), None
        _, season = season_coords
        return show_id, season, show_watch_snapshot(show_id), season_watch_snapshot(show_id, season)
    if mediatype == "tvshow":
        return show_id, None, show_watch_snapshot(show_id), None
    return show_id, None, None, None


def _deferred_refresh_flags_after_edit(
    item_information: dict,
    mediatype: str,
    show_before: dict | None,
    season_before: dict | None,
    season: int | None,
) -> tuple[bool, bool]:
    from resources.lib.simkl.watch_refresh_policy import (
        deferred_drilldown_refresh_flags,
        season_watch_snapshot,
        show_watch_snapshot,
    )

    show_id = _get_show_id(item_information)
    if show_id is None:
        return True, True
    show_after = show_watch_snapshot(int(show_id))
    season_after = None
    if season is not None:
        season_after = season_watch_snapshot(int(show_id), int(season))
    return deferred_drilldown_refresh_flags(
        mediatype=mediatype,
        show_before=show_before,
        show_after=show_after,
        season_before=season_before,
        season_after=season_after,
    )


def apply_mark_watched(
    item_information: dict,
    *,
    silent: bool = False,
    refresh: bool = True,
) -> bool:
    """
    Mark item watched via Simkl API and local sync DB.
    Returns True when the local DB was updated successfully.
    """
    info = _watch_info(item_information)
    mediatype = (info.get("mediatype") or "").lower()
    if not mediatype or info.get("simkl_id") is None:
        return False

    _show_id_pre, season_pre, show_before, season_before = _capture_watch_snapshots(item_information, mediatype)

    season_local_marked = False
    season_coords: tuple[int, int] | None = None
    if mediatype == "season":
        season_coords = _season_mark_coords(item_information)
        if season_coords is None:
            return False
        get_sync_database().mark_season_watched(season_coords[0], season_coords[1], 1)
        season_local_marked = True

    payload = info_to_history_payload(info)
    response = _simkl_api().add_to_history(payload)
    api_ok = (
        _history_success(response, "shows")
        or _history_success(response, "anime")
        or _history_success(response, "movies")
    )

    if mediatype == "movie":
        if not _history_success(response, "movies"):
            if not silent:
                g.notification(
                    f"{g.ADDON_NAME}: {g.get_language_string(30286)}",
                    g.get_language_string(30287),
                )
            return False
        from resources.lib.simkl.library_status import ensure_library_row

        ensure_library_row(info)
        get_sync_database().mark_movie_watched(info["simkl_id"])
    elif mediatype == "season":
        if not api_ok:
            g.log(
                "Simkl history did not confirm season watch; local episode flags were updated",
                "info",
            )
        if not season_local_marked:
            return False
    else:
        if not api_ok:
            if not silent:
                g.notification(
                    f"{g.ADDON_NAME}: {g.get_language_string(30286)}",
                    g.get_language_string(30287),
                )
            return False
        if mediatype == "episode":
            coords = _episode_mark_coords(item_information)
            if coords is None:
                return False
            show_id, season, episode = coords
            get_sync_database().mark_episode_watched(show_id, season, episode)
        elif mediatype == "tvshow":
            get_sync_database().mark_show_watched(info["simkl_id"], 1)

    resolved = resolved_watched_status_from_response(response, info)
    if resolved:
        apply_local_library_status(item_information, resolved, touch_last_watched=True)
    else:
        apply_local_status_after_watch(item_information)

    show_id = _get_show_id(item_information)
    if show_id is not None and mediatype in ("tvshow", "episode", "season"):
        _set_show_watch_edit_cooldown(int(show_id))
        if mediatype in ("tvshow", "episode"):
            try:
                get_sync_database().refresh_show_episode_watch_state(int(show_id), force=True)
            except Exception:
                g.log_stacktrace()

    refresh_show_hub, refresh_season_menu = _deferred_refresh_flags_after_edit(
        item_information,
        mediatype,
        show_before,
        season_before,
        season_pre,
    )

    if not silent:
        g.notification(
            f"{g.ADDON_NAME}: {g.get_language_string(30286)}",
            g.get_language_string(30288),
        )
        if refresh:
            finish_library_action(
                item_information,
                refresh_container=refresh,
                refresh_show_hub=refresh_show_hub,
                refresh_season_menu=refresh_season_menu,
            )
    elif refresh:
        finish_library_action(
            item_information,
            refresh_container=refresh,
            refresh_show_hub=refresh_show_hub,
            refresh_season_menu=refresh_season_menu,
        )

    return True


def apply_mark_unwatched(
    item_information: dict,
    *,
    silent: bool = False,
    refresh: bool = True,
) -> bool:
    """Mark item unwatched via Simkl API and local sync DB."""
    info = _watch_info(item_information)
    mediatype = (info.get("mediatype") or "").lower()
    if not mediatype or info.get("simkl_id") is None:
        return False

    show_id_pre, season_pre, show_before, season_before = _capture_watch_snapshots(item_information, mediatype)

    season_local_marked = False
    if mediatype == "season":
        season_coords = _season_mark_coords(item_information)
        if season_coords is None:
            return False
        get_sync_database().mark_season_watched(season_coords[0], season_coords[1], 0)
        season_local_marked = True

    payload = info_to_history_payload(info)
    response = _simkl_api().remove_from_history(payload)

    if mediatype == "movie":
        if not _remove_success(response, "movies"):
            if not silent:
                g.notification(
                    f"{g.ADDON_NAME}: {g.get_language_string(30286)}",
                    g.get_language_string(30287),
                )
            return False
        get_sync_database().mark_movie_unwatched(info["simkl_id"])
    elif mediatype == "season":
        if not _remove_success(response, "episodes") and not season_local_marked:
            if not silent:
                g.notification(
                    f"{g.ADDON_NAME}: {g.get_language_string(30286)}",
                    g.get_language_string(30287),
                )
            return False
    else:
        if not _remove_success(response, "episodes"):
            if not silent:
                g.notification(
                    f"{g.ADDON_NAME}: {g.get_language_string(30286)}",
                    g.get_language_string(30287),
                )
            return False
        if mediatype == "episode":
            coords = _episode_mark_coords(item_information)
            if coords is None:
                return False
            show_id, season, episode = coords
            get_sync_database().mark_episode_unwatched(show_id, season, episode)
        elif mediatype == "tvshow":
            get_sync_database().mark_show_watched(info["simkl_id"], 0)

    get_sync_database().remove_bookmark(info["simkl_id"])
    show_id = _get_show_id(item_information)
    if show_id is not None and mediatype in ("tvshow", "episode", "season"):
        _set_show_watch_edit_cooldown(int(show_id))
    refresh_show_hub, refresh_season_menu = _deferred_refresh_flags_after_edit(
        item_information,
        mediatype,
        show_before,
        season_before,
        season_pre,
    )

    if not silent:
        g.notification(
            f"{g.ADDON_NAME}: {g.get_language_string(30286)}",
            g.get_language_string(30289),
        )
    if refresh:
        finish_library_action(
            item_information,
            refresh_container=refresh,
            refresh_show_hub=refresh_show_hub,
            refresh_season_menu=refresh_season_menu,
        )
    return True

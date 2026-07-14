"""Simkl watchlist status keys and labels shared by library menus and context menu."""
from __future__ import annotations

from typing import Any

from resources.lib.modules.globals import g
from resources.lib.simkl.ids import show_id_from_info

# (status_key, label_string_id) — label IDs match My Library hubs
MOVIE_STATUS_OPTIONS = (
    ("plantowatch", 30732),
    ("completed", 30736),
    ("dropped", 30735),
)

SHOW_STATUS_OPTIONS = (
    ("watching", 30733),
    ("plantowatch", 30732),
    ("hold", 30734),
    ("completed", 30736),
    ("dropped", 30735),
)

STATUS_LABEL_IDS = {status: label_id for status, label_id in MOVIE_STATUS_OPTIONS + SHOW_STATUS_OPTIONS}


def status_label(status: str) -> str:
    label_id = STATUS_LABEL_IDS.get(status)
    return g.get_language_string(label_id) if label_id else status


def _catalog_for_info(info: dict[str, Any]) -> str:
    if info.get("mediatype") == "movie":
        return "movie"
    ids = info.get("ids") or {}
    if info.get("catalog") == "anime" or info.get("mal_id") or ids.get("mal"):
        return "show"
    return "show"


def status_options_for_info(info: dict[str, Any], *, exclude_current: bool = True) -> list[tuple[str, int]]:
    options = MOVIE_STATUS_OPTIONS if info.get("mediatype") == "movie" else SHOW_STATUS_OPTIONS
    if exclude_current:
        current = current_simkl_status(info)
        if current:
            options = tuple((s, lid) for s, lid in options if s != current)
    return list(options)


def in_simkl_library(item: dict[str, Any]) -> bool:
    """True when the item is on a Simkl list or has local watch history."""
    info = item.get("info") if isinstance(item.get("info"), dict) else item
    if current_simkl_status(info):
        return True
    try:
        if int(item.get("play_count") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    mediatype = (info.get("mediatype") or "").lower()
    if mediatype in ("tvshow", "season") and item.get("unwatched_episodes") is not None:
        return True
    return False


def current_simkl_status(info: dict[str, Any]) -> str | None:
    status = info.get("simkl_status")
    if status:
        return status

    mediatype = (info.get("mediatype") or "").lower()
    if mediatype == "movie":
        simkl_id = info.get("simkl_id")
        if not simkl_id:
            return None
        from resources.lib.database.simkl_sync.movies import SimklSyncDatabase

        row = SimklSyncDatabase().fetchone(
            "SELECT simkl_status, info FROM movies WHERE simkl_id=?",
            (int(simkl_id),),
        )
    else:
        show_id = show_id_from_info(info) if mediatype != "tvshow" else info.get("simkl_id")
        if not show_id:
            return None
        from resources.lib.database.simkl_sync.shows import SimklSyncDatabase

        row = SimklSyncDatabase().fetchone(
            "SELECT simkl_status, info FROM shows WHERE simkl_id=?",
            (int(show_id),),
        )

    if not row:
        return None
    if row.get("simkl_status"):
        return row.get("simkl_status")
    stored = row.get("info")
    if isinstance(stored, dict):
        return stored.get("simkl_status")
    return None


def resolved_list_status_from_response(
    response: dict[str, Any] | None,
    *,
    requested: str | None = None,
) -> str | None:
    """Status after add-to-list; prefer API resolution, then the status the user picked."""
    if response:
        for entry in (response.get("added") or {}).get("statuses") or []:
            if not isinstance(entry, dict):
                continue
            resolved = (entry.get("response") or {}).get("status")
            if resolved:
                return resolved
            req_to = (entry.get("request") or {}).get("to")
            if req_to:
                return req_to
    return requested


def resolved_watched_status_from_response(
    response: dict[str, Any] | None,
    info: dict[str, Any],
) -> str | None:
    """Status after mark-watched; movies default to completed when the API is silent."""
    status = resolved_list_status_from_response(response)
    if status:
        return status
    if info.get("mediatype") == "movie":
        return "completed"
    return None


def resolved_status_from_response(response: dict[str, Any] | None, info: dict[str, Any]) -> str | None:
    """Backward-compatible alias for mark-watched flows."""
    return resolved_watched_status_from_response(response, info)


def library_row_id(info: dict[str, Any]) -> int | None:
    """Simkl row id used in movies/shows table for list status updates."""
    mediatype = (info.get("mediatype") or "").lower()
    if mediatype == "movie":
        return int(info["simkl_id"]) if info.get("simkl_id") else None
    if mediatype == "tvshow":
        return int(info["simkl_id"]) if info.get("simkl_id") else None
    show_id = show_id_from_info(info)
    return int(show_id) if show_id else None


def library_catalog(info: dict[str, Any]) -> str:
    return "movie" if info.get("mediatype") == "movie" else _catalog_for_info(info)

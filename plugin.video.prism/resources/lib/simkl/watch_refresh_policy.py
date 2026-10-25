"""Decide when watch toggles should repaint parent TV/anime hub lists."""
from __future__ import annotations

from typing import Any

from resources.lib.database.session import get_sync_database


def _int_field(row: dict | None, key: str, default: int = 0) -> int:
    if not row:
        return default
    try:
        return int(row.get(key) if row.get(key) is not None else default)
    except (TypeError, ValueError):
        return default


def show_watch_snapshot(show_id: int) -> dict[str, Any]:
    db = get_sync_database()
    row = db.fetchone(
        f"""
        SELECT episode_count, watched_episodes, unwatched_episodes, simkl_status
        FROM {db._st().show}
        WHERE simkl_id=?
        """,
        (int(show_id),),
    )
    return dict(row or {})


def season_watch_snapshot(show_id: int, season: int) -> dict[str, Any]:
    db = get_sync_database()
    row = db.fetchone(
        f"""
        SELECT episode_count, watched_episodes, unwatched_episodes
        FROM {db._st().season}
        WHERE simkl_show_id=? AND season=?
        """,
        (int(show_id), int(season)),
    )
    return dict(row or {})


def _is_fully_watched(snap: dict[str, Any]) -> bool:
    episode_count = _int_field(snap, "episode_count")
    if episode_count <= 0:
        return False
    unwatched = snap.get("unwatched_episodes")
    if unwatched is not None:
        return _int_field(snap, "unwatched_episodes") <= 0
    watched = _int_field(snap, "watched_episodes")
    return watched >= episode_count


def show_hub_refresh_needed(
    *,
    mediatype: str,
    show_before: dict[str, Any] | None,
    show_after: dict[str, Any] | None,
) -> bool:
    """True when the show/anime hub row would change (completion checkmark, library status)."""
    mediatype = (mediatype or "").lower()
    if mediatype == "tvshow":
        return True
    if mediatype not in ("episode", "season"):
        return True

    if show_before is None or show_after is None:
        return True

    if _is_fully_watched(show_before) != _is_fully_watched(show_after):
        return True

    status_before = str(show_before.get("simkl_status") or "").strip().lower()
    status_after = str(show_after.get("simkl_status") or "").strip().lower()
    if status_before != status_after and {status_before, status_after} & {"completed", "watching"}:
        return True

    return False


def season_menu_refresh_needed(
    *,
    season_before: dict[str, Any] | None,
    season_after: dict[str, Any] | None,
) -> bool:
    """True when the season list would show a different per-season completion checkmark."""
    if season_before is None or season_after is None:
        return False
    if _is_fully_watched(season_before) != _is_fully_watched(season_after):
        return True
    return False


def deferred_drilldown_refresh_flags(
    *,
    mediatype: str,
    show_before: dict[str, Any] | None,
    show_after: dict[str, Any] | None,
    season_before: dict[str, Any] | None = None,
    season_after: dict[str, Any] | None = None,
) -> tuple[bool, bool]:
    """Return (refresh_show_hub, refresh_season_menu)."""
    show_hub = show_hub_refresh_needed(
        mediatype=mediatype,
        show_before=show_before,
        show_after=show_after,
    )
    season_menu = season_menu_refresh_needed(
        season_before=season_before,
        season_after=season_after,
    )
    return show_hub, season_menu

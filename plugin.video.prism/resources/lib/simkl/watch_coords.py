"""Map menu/Simkl item info to local sync DB season + episode coordinates (anime TVDB buckets)."""
from __future__ import annotations

from typing import Any


def resolve_db_episode_coords(db, show_id: int, info: dict[str, Any]) -> tuple[int, int] | None:
    """Return (season, number) columns in unified ``episodes`` for this item (catalog from show)."""
    if not info:
        return None
    try:
        show_id = int(show_id)
    except (TypeError, ValueError):
        return None

    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope
    from resources.lib.simkl.ids import entity_simkl_id, is_synthetic_episode_id, split_synthetic_episode_id

    catalog = db.show_catalog(show_id) or "tv"
    profile = "anime" if catalog == "anime" else "tv"

    with serial_profile_scope(db, profile):
        ep_table = db._st().episode
        mediatype = (info.get("mediatype") or "").lower()
        ep_id = entity_simkl_id(info) if mediatype == "episode" else None
        if ep_id is not None:
            try:
                ep_id = int(ep_id)
            except (TypeError, ValueError):
                ep_id = None
        if ep_id is not None and is_synthetic_episode_id(ep_id):
            sid, season, number = split_synthetic_episode_id(ep_id)
            if sid == show_id:
                row = db.fetchone(
                    f"SELECT season, number FROM {ep_table} WHERE simkl_show_id=? AND season=? AND number=?",
                    (show_id, int(season), int(number)),
                )
                if row:
                    return int(row["season"]), int(row["number"])
        elif ep_id is not None:
            row = db.fetchone(
                f"SELECT season, number FROM {ep_table} WHERE simkl_show_id=? AND simkl_id=?",
                (show_id, ep_id),
            )
            if row:
                return int(row["season"]), int(row["number"])

        season_raw = info.get("season")
        ep_raw = info.get("episode") if info.get("episode") is not None else info.get("number")
        if season_raw is not None and ep_raw is not None:
            season, number = int(season_raw), int(ep_raw)
            row = db.fetchone(
                f"SELECT season, number FROM {ep_table} WHERE simkl_show_id=? AND season=? AND number=?",
                (show_id, season, number),
            )
            if row:
                return int(row["season"]), int(row["number"])

        if catalog == "anime":
            tvdb_season = info.get("tvdb_season")
            tvdb_episode = info.get("tvdb_episode")
            if tvdb_season is not None:
                menu_season = 1 if int(tvdb_season) == 0 else int(tvdb_season)
                ep_num = tvdb_episode if tvdb_episode is not None else ep_raw
                if ep_num is not None:
                    row = db.fetchone(
                        f"""
                        SELECT season, number FROM {ep_table}
                        WHERE simkl_show_id=? AND season=? AND number=?
                        """,
                        (show_id, menu_season, int(ep_num)),
                    )
                    if row:
                        return int(row["season"]), int(row["number"])

    return None


def resolve_db_season_number(db, show_id: int, info: dict[str, Any]) -> int | None:
    """Season bucket for mark-season-watched (menu / TVDB season for anime)."""
    if not info:
        return None
    try:
        show_id = int(show_id)
    except (TypeError, ValueError):
        return None

    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope
    from resources.lib.simkl.ids import season_row_id_from_info, split_synthetic_season_id, is_synthetic_season_id

    season_num = info.get("season")
    if season_num is not None:
        try:
            candidate = int(season_num)
        except (TypeError, ValueError):
            candidate = None
    else:
        candidate = None

    if candidate is None:
        row_id = season_row_id_from_info(info)
        if row_id is not None and is_synthetic_season_id(row_id):
            _, candidate = split_synthetic_season_id(int(row_id))

    if candidate is None and (db.show_catalog(show_id) or "tv") == "anime":
        tvdb_season = info.get("tvdb_season")
        if tvdb_season is not None:
            candidate = 1 if int(tvdb_season) == 0 else int(tvdb_season)

    if candidate is None:
        return None

    catalog = db.show_catalog(show_id) or "tv"
    profile = "anime" if catalog == "anime" else "tv"
    with serial_profile_scope(db, profile):
        st = db._st()
        has_season = db.fetchone(
            f"SELECT 1 AS ok FROM {st.season} WHERE simkl_show_id=? AND season=? LIMIT 1",
            (show_id, int(candidate)),
        )
        has_eps = db.fetchone(
            f"SELECT 1 AS ok FROM {st.episode} WHERE simkl_show_id=? AND season=? LIMIT 1",
            (show_id, int(candidate)),
        )
        if has_season or has_eps:
            return int(candidate)
    return int(candidate)

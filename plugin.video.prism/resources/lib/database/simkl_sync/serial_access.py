"""Catalog-scoped helpers for TV vs anime serial tables (simkl_sync)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from resources.lib.database.simkl_sync.database import SimklSyncDatabase


def profile_for_catalog(catalog: str | None) -> str:
    return "anime" if (catalog or "").lower() == "anime" else "tv"


def paint_cache_type_for_catalog(catalog: str | None) -> str:
    """display_meta.media_type bucket: movie | show | anime."""
    cat = (catalog or "").lower()
    if cat == "movie":
        return "movie"
    if cat == "anime":
        return "anime"
    return "show"


def paint_cache_type_for_media_type(media_type: str, catalog: str | None = None) -> str:
    mt = (media_type or "").lower()
    if mt == "movie" or mt == "movies":
        return "movie"
    if catalog:
        return paint_cache_type_for_catalog(catalog)
    if mt == "anime":
        return "anime"
    return "show"


def sync_show_table_for_catalog(catalog: str | None) -> str:
    return "shows"


def catalog_for_profile(profile: str | None) -> str:
    return "anime" if (profile or "").lower() == "anime" else "tv"


def partition_simkl_ids(
    items: list[dict[str, Any]] | None,
) -> tuple[list[int], list[int], list[int]]:
    """Split refs/sync rows into (movie_ids, tv_show_ids, anime_ids)."""
    movie_ids: list[int] = []
    tv_ids: list[int] = []
    anime_ids: list[int] = []
    seen_m: set[int] = set()
    seen_tv: set[int] = set()
    seen_an: set[int] = set()

    for item in items or []:
        if not isinstance(item, dict):
            continue
        raw = item.get("simkl_id")
        if raw is None:
            continue
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        catalog = (item.get("catalog") or "").lower()
        if not catalog:
            info = item.get("info")
            if isinstance(info, dict):
                catalog = (info.get("catalog") or "").lower()
        if catalog == "movie":
            if sid not in seen_m:
                seen_m.add(sid)
                movie_ids.append(sid)
        elif catalog == "anime":
            if sid not in seen_an:
                seen_an.add(sid)
                anime_ids.append(sid)
        elif catalog == "tv":
            if sid not in seen_tv:
                seen_tv.add(sid)
                tv_ids.append(sid)
        else:
            if sid not in seen_tv:
                seen_tv.add(sid)
                tv_ids.append(sid)
    return movie_ids, tv_ids, anime_ids


def fetch_show_row(
    db: SimklSyncDatabase,
    catalog: str,
    simkl_id: int,
    columns: str = "simkl_id, info, art, [cast]",
) -> dict[str, Any] | None:
    from resources.lib.database.simkl_sync.serial_sync import catalog_filter_sql, serial_profile_scope

    profile = profile_for_catalog(catalog)
    with serial_profile_scope(db, profile):
        st = db._st()
        cat_sql, cat_params = catalog_filter_sql(st)
        return db.fetchone(
            f"SELECT {columns} FROM {st.show} WHERE simkl_id=?{cat_sql}",
            (int(simkl_id),) + cat_params,
        )


def episode_table_for_catalog(catalog: str | None) -> str:
    return "episodes"


def fetch_episode_watched_row(
    db: SimklSyncDatabase,
    catalog: str,
    *,
    episode_id: int | None = None,
    show_id: int | None = None,
    season: int | None = None,
    episode: int | None = None,
) -> dict[str, Any] | None:
    from resources.lib.database.simkl_sync.serial_sync import catalog_filter_sql, serial_tables

    st = serial_tables(profile_for_catalog(catalog))
    cat_sql, cat_params = catalog_filter_sql(st)
    if show_id is not None and season is not None and episode is not None:
        return db.fetchone(
            f"SELECT watched FROM {st.episode} WHERE simkl_show_id = ? AND season = ? AND number = ?{cat_sql}",
            (int(show_id), int(season), int(episode)) + cat_params,
        )
    if episode_id is not None:
        return db.fetchone(
            f"SELECT watched FROM {st.episode} WHERE simkl_id = ?{cat_sql}",
            (int(episode_id),) + cat_params,
        )
    return None


def fetch_show_rows_by_ids(
    db: SimklSyncDatabase,
    catalog: str,
    simkl_ids: list[int],
    columns: str = "simkl_id, info, art, [cast], tmdb_id, tvdb_id",
) -> list[dict[str, Any]]:
    if not simkl_ids:
        return []
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope

    profile = profile_for_catalog(catalog)
    ids_sql = ",".join(str(int(sid)) for sid in simkl_ids)
    with serial_profile_scope(db, profile):
        from resources.lib.database.simkl_sync.serial_sync import catalog_filter_sql

        st = db._st()
        cat_sql, cat_params = catalog_filter_sql(st)
        return list(
            db.fetchall(
                f"SELECT {columns} FROM {st.show} WHERE simkl_id IN ({ids_sql}){cat_sql}",
                cat_params,
            )
            or []
        )

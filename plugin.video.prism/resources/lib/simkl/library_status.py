"""Immediate local Simkl library status updates for My Library lists."""
from __future__ import annotations

import xbmc

from resources.lib.modules.globals import g
from resources.lib.simkl.statuses import library_catalog, library_row_id


def _library_db(catalog: str):
    """Return the sync DB subclass with movie/show watch helpers."""
    if catalog == "movie":
        from resources.lib.database.simkl_sync.movies import SimklSyncDatabase
    else:
        from resources.lib.database.simkl_sync.shows import SimklSyncDatabase
    return SimklSyncDatabase()


def _library_info(item_or_info: dict) -> dict:
    if not isinstance(item_or_info, dict):
        return {}
    info = item_or_info.get("info")
    if isinstance(info, dict):
        merged = dict(info)
        for key in ("mediatype", "simkl_id", "season", "episode", "catalog", "play_count"):
            if item_or_info.get(key) is not None and merged.get(key) is None:
                merged[key] = item_or_info[key]
        return merged
    return item_or_info


def queue_library_sync(*, user_initiated: bool = True) -> None:
    force = "1" if user_initiated else "0"
    xbmc.executebuiltin(
        f'RunPlugin("plugin://plugin.video.prism/?action=syncSimklActivities&force={force}")'
    )


def _sync_dict_from_info(info: dict, catalog: str) -> dict | None:
    from resources.lib.discover.normalize import cdn_item_to_sync_dict

    row_id = library_row_id(info)
    if row_id is None:
        return None

    ids = dict(info.get("ids") or {})
    ids.setdefault("simkl_id", int(row_id))
    for provider in ("tmdb", "tvdb", "imdb", "mal"):
        flat = f"{provider}_id"
        if info.get(flat) is not None and provider not in ids:
            ids[provider] = info.get(flat)

    mediatype = (info.get("mediatype") or "").lower()
    if mediatype == "episode":
        title = info.get("tvshowtitle") or info.get("title")
    else:
        title = info.get("title") or info.get("name")

    art = info.get("art") if isinstance(info.get("art"), dict) else {}
    raw = {
        "title": title,
        "overview": info.get("plot") or info.get("overview"),
        "release_date": info.get("aired") or info.get("premiered") or info.get("release_date"),
        "poster": art.get("poster") or info.get("poster"),
        "fanart": art.get("fanart") or info.get("fanart"),
        "ids": ids,
        "type": info.get("type"),
        "anime_type": info.get("anime_type"),
        "catalog": info.get("catalog") or catalog,
    }
    return cdn_item_to_sync_dict(raw, catalog)


def ensure_library_row(item_or_info: dict) -> int | None:
    """Ensure a movies/shows row exists; fetch or insert if missing."""
    info = _library_info(item_or_info)
    row_id = library_row_id(info)
    if row_id is None:
        return None

    catalog = library_catalog(info)
    table = "movies" if catalog == "movie" else "shows"
    db = _library_db(catalog)
    simkl_id = int(row_id)
    if db.fetchone(f"SELECT simkl_id FROM {table} WHERE simkl_id=?", (simkl_id,)):
        return simkl_id

    media_type = "movies" if catalog == "movie" else "shows"
    db._get_single_meta(simkl_id, media_type)
    if db.fetchone(f"SELECT simkl_id FROM {table} WHERE simkl_id=?", (simkl_id,)):
        return simkl_id

    sync_item = _sync_dict_from_info(info, catalog)
    if not sync_item:
        return None

    if catalog == "movie":
        db.insert_simkl_movies([sync_item], force_meta=True)
    else:
        db.insert_simkl_shows([sync_item], force_meta=True)

    if db.fetchone(f"SELECT simkl_id FROM {table} WHERE simkl_id=?", (simkl_id,)):
        return simkl_id
    return None


def resolve_status_after_watch(item_or_info: dict) -> str | None:
    info = _library_info(item_or_info)
    mediatype = (info.get("mediatype") or "").lower()
    if mediatype == "movie":
        return "completed"

    show_id = library_row_id(info)
    if show_id is None:
        return "watching"

    from resources.lib.database.simkl_sync.shows import SimklSyncDatabase

    row = SimklSyncDatabase().fetchone(
        "SELECT unwatched_episodes FROM shows WHERE simkl_id=?",
        (int(show_id),),
    )
    if not row:
        return "watching"
    try:
        unwatched = int(row.get("unwatched_episodes") or 0)
    except (TypeError, ValueError):
        return "watching"
    return "completed" if unwatched <= 0 else "watching"


def apply_local_library_status(
    item_or_info: dict,
    status: str | None,
    *,
    touch_last_watched: bool = False,
    queue_sync: bool = False,
) -> bool:
    info = _library_info(item_or_info)
    simkl_id = ensure_library_row(item_or_info)
    if simkl_id is None:
        g.log("apply_local_library_status: unable to ensure library row", "debug")
        return False

    catalog = library_catalog(info)
    db = _library_db(catalog)
    db.set_simkl_status(simkl_id, catalog, status)

    from resources.lib.simkl.library_cache import invalidate_library_cache

    invalidate_library_cache(catalog)

    if status == "completed":
        if catalog == "movie":
            db.mark_movie_watched(simkl_id)
        else:
            db.mark_show_watched(simkl_id, 1)

    if touch_last_watched:
        now = str(db._get_datetime_now())
        table = "movies" if catalog == "movie" else "shows"
        row = db.fetchone(f"SELECT info FROM {table} WHERE simkl_id=?", (simkl_id,))
        info_blob = dict(row["info"]) if row and isinstance(row.get("info"), dict) else {}
        info_blob["last_watched_at"] = now
        if status:
            info_blob["simkl_status"] = status
        db.execute_sql(
            f"UPDATE {table} SET last_watched_at=?, info=? WHERE simkl_id=?",
            (now, info_blob, simkl_id),
        )

    if queue_sync:
        queue_library_sync()

    return True


def apply_local_status_after_watch(item_or_info: dict, *, queue_sync: bool = False) -> bool:
    status = resolve_status_after_watch(item_or_info)
    return apply_local_library_status(
        item_or_info,
        status,
        touch_last_watched=True,
        queue_sync=queue_sync,
    )

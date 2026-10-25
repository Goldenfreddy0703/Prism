"""Fast drilldown menus: one Simkl episode-tree fetch, in-memory rows, deferred DB mill."""
from __future__ import annotations

import time
from typing import Any

from resources.lib.modules.globals import g

_RAM_TTL_SEC = 6 * 3600.0
_DRILLDOWN_ROW_RAM: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]] = {}


def drilldown_fast_open_enabled() -> bool:
    return g.get_bool_setting("general.drilldown.fast_open", default_value=True)


def load_raw_episode_tree(
    show_id: int,
    catalog: str,
    slug: str | None = None,
    *,
    db=None,
) -> list[dict[str, Any]]:
    from resources.lib.database.simkl_sync.milling import fetch_raw_show_episodes

    if db is None:
        from resources.lib.database.session import get_sync_database

        db = get_sync_database()
    api = db.simkl_api if db is not None else None
    return fetch_raw_show_episodes(int(show_id), str(catalog), slug=slug, api=api) or []


def _resolve_slug(db, show_id: int) -> str | None:
    try:
        return db._meta_slug(int(show_id), "shows")
    except Exception:
        return None


def _parent_show_fields(
    db,
    show_id: int,
    show_ctx: dict[str, Any] | None,
) -> tuple[dict | None, dict | None, list | None]:
    show_info = (show_ctx or {}).get("show_info") if show_ctx else None
    show_art = (show_ctx or {}).get("show_art") if show_ctx else None
    show_cast = (show_ctx or {}).get("show_cast") if show_ctx else None
    if isinstance(show_info, dict) and show_info:
        return show_info, show_art, show_cast
    meta = db._get_single_show_meta(int(show_id))
    if not isinstance(meta, dict):
        return show_info, show_art, show_cast
    from resources.lib.modules.metadataHandler import MetadataHandler

    return (
        MetadataHandler.simkl_info(meta) or show_info,
        meta.get("art") or show_art,
        meta.get("cast") or show_cast,
    )


def _format_milled_row(
    db,
    stub: dict[str, Any],
    *,
    show_info: dict | None,
    show_art: dict | None,
    show_cast: list | None,
    season_info: dict | None = None,
    season_art: dict | None = None,
) -> dict[str, Any]:
    simkl_object = stub.get("simkl_object")
    if not isinstance(simkl_object, dict):
        simkl_object = {"info": {}}
    db_object: dict[str, Any] = {
        "simkl_id": stub.get("simkl_id"),
        "simkl_object": simkl_object,
        "show_info": show_info,
        "show_art": show_art,
        "show_cast": show_cast,
        "season_info": season_info,
        "season_art": season_art,
    }
    formatted = db.metadataHandler.format_meta(db_object)
    info = formatted.get("info") or {}
    row: dict[str, Any] = {
        "simkl_id": stub.get("simkl_id"),
        "simkl_show_id": stub.get("simkl_show_id"),
        "season": stub.get("season", info.get("season")),
        "info": info,
        "art": formatted.get("art"),
        "cast": formatted.get("cast"),
        "args": formatted.get("args") or db._create_args(formatted),
    }
    if stub.get("episode") is not None:
        row["episode"] = stub.get("episode")
    if stub.get("simkl_season_id") is not None:
        row["simkl_season_id"] = stub.get("simkl_season_id")
    aired = stub.get("aired_episodes")
    if aired is not None:
        row["episode_count"] = int(aired)
        row.setdefault("info", {})["episode_count"] = int(aired)
        row["info"].setdefault("aired_episodes", int(aired))
    return row


def _cache_get(key: tuple[Any, ...]) -> list[dict[str, Any]] | None:
    hit = _DRILLDOWN_ROW_RAM.get(key)
    if not hit:
        from resources.lib.meta.simkl_list_disk_cache import get_cached_page

        disk_key = ":".join(str(part) for part in key)
        cached = get_cached_page("drilldown", disk_key)
        if cached:
            return [dict(row) for row in cached if isinstance(row, dict)]
        return None
    expires_at, rows = hit
    if time.time() >= expires_at:
        _DRILLDOWN_ROW_RAM.pop(key, None)
        return None
    return [dict(row) for row in rows]


def _cache_put(key: tuple[Any, ...], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    _DRILLDOWN_ROW_RAM[key] = (time.time() + _RAM_TTL_SEC, [dict(row) for row in rows])
    from resources.lib.meta.simkl_list_disk_cache import set_cached_page

    disk_key = ":".join(str(part) for part in key)
    set_cached_page("drilldown", disk_key, rows)


def _filter_episode_rows(rows: list[dict], paint_kwargs: dict) -> list[dict]:
    hide_specials = bool(paint_kwargs.get("hide_specials", False))
    hide_unaired = bool(paint_kwargs.get("hide_unaired", False))
    hide_watched = bool(paint_kwargs.get("hide_watched", False))
    from resources.lib.meta.paint_cache import _apply_list_filters

    filtered: list[dict] = []
    for row in rows:
        if hide_specials and int(row.get("season") or (row.get("info") or {}).get("season") or 0) == 0:
            continue
        if _apply_list_filters(row, "tvshow", hide_unaired=hide_unaired, hide_watched=hide_watched):
            continue
        filtered.append(row)
    return filtered


def _filter_season_rows(rows: list[dict], paint_kwargs: dict) -> list[dict]:
    hide_specials = bool(paint_kwargs.get("hide_specials", False))
    hide_unaired = bool(paint_kwargs.get("hide_unaired", False))
    hide_watched = bool(paint_kwargs.get("hide_watched", False))
    from resources.lib.meta.paint_cache import _apply_list_filters

    filtered: list[dict] = []
    for row in rows:
        if hide_specials and int(row.get("season") or 0) == 0:
            continue
        if _apply_list_filters(row, "tvshow", hide_unaired=hide_unaired, hide_watched=hide_watched):
            continue
        filtered.append(row)
    return filtered


def _sync_season_row_watch_playcount(row: dict) -> None:
    """Drop stale playcount from cached drilldown rows; align with live watch counters."""
    from resources.lib.simkl.watch_counters import is_caught_up, not_aired_count, total_for_watch_math

    info = row.get("info")
    if not isinstance(info, dict):
        info = {}
        row["info"] = info
    try:
        ep_count = int(row.get("episode_count") or info.get("episode_count") or 0)
        watched = int(row.get("watched_episodes") or info.get("watched_episodes_count") or 0)
    except (TypeError, ValueError):
        ep_count = 0
        watched = 0
    unwatched = row.get("unwatched_episodes", info.get("unwatched_episodes"))
    if ep_count <= 0:
        row.pop("play_count", None)
        info.pop("playcount", None)
        return
    caught = is_caught_up(
        watched,
        total_for_watch_math(row, info) or ep_count,
        not_aired=not_aired_count(info),
        unwatched=unwatched,
        aired_episode_count=ep_count,
    )
    if caught:
        info["playcount"] = 1
        row["play_count"] = 1
    else:
        info["playcount"] = 0
        row.pop("play_count", None)


def _drilldown_serial_profile(db, show_id: int) -> str:
    return "anime" if (db.show_catalog(int(show_id)) or "tv") == "anime" else "tv"


def clear_drilldown_cache_for_show(show_id: int) -> None:
    """Invalidate fast drilldown RAM/disk rows after local watch toggles."""
    sid = int(show_id)
    for key in list(_DRILLDOWN_ROW_RAM):
        if isinstance(key, tuple) and key and int(key[0]) == sid:
            _DRILLDOWN_ROW_RAM.pop(key, None)
    try:
        from resources.lib.database.session import get_sync_database
        from resources.lib.meta.simkl_list_disk_cache import _TABLE

        db = get_sync_database()
        db.execute_sql(
            f"DELETE FROM {_TABLE} WHERE cache_key LIKE ?",
            (f"{sid}:%",),
        )
    except Exception:
        pass


def _season_watch_paint_snapshot(db, show_id: int) -> dict[str, int]:
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope

    with serial_profile_scope(db, _drilldown_serial_profile(db, show_id)):
        st = db._st()
        show_row = db.fetchone(
            f"SELECT watched_episodes FROM {st.show} WHERE simkl_id=?",
            (int(show_id),),
        ) or {}
        ep_row = db.fetchone(
            f"""
            SELECT COUNT(*) AS ep_rows,
                   SUM(CASE WHEN COALESCE(watched, 0) > 0 THEN 1 ELSE 0 END) AS ep_watched
            FROM {st.episode}
            WHERE simkl_show_id = ? AND season > 0
            """,
            (int(show_id),),
        ) or {}
    try:
        show_watched = int(show_row.get("watched_episodes") or 0)
    except (TypeError, ValueError):
        show_watched = 0
    try:
        ep_rows = int(ep_row.get("ep_rows") or 0)
        ep_watched = int(ep_row.get("ep_watched") or 0)
    except (TypeError, ValueError):
        ep_rows = 0
        ep_watched = 0
    return {"show_watched": show_watched, "ep_rows": ep_rows, "ep_watched": ep_watched}


def _season_watch_paint_ready(snapshot: dict[str, int]) -> bool:
    """Episode tree present and show-level watched total matches per-episode flags."""
    ep_rows = int(snapshot.get("ep_rows") or 0)
    if ep_rows <= 0:
        return False
    show_watched = int(snapshot.get("show_watched") or 0)
    ep_watched = int(snapshot.get("ep_watched") or 0)
    if show_watched > 0:
        return ep_watched == show_watched
    if ep_watched > 0:
        return True
    # Episode rows exist but counters are still zero — Simkl reconcile may not have run yet.
    return False


def _ensure_season_watch_state_for_paint(db, show_id: int, catalog: str) -> None:
    """
    Fast drilldown can paint before background persist finishes (fresh install / first open).

    Season checkmarks need per-episode watched flags. Reconcile may run after the menu if
    shows.watched_episodes is still 0 or episode rows are not milled yet.
    """
    show_id = int(show_id)
    before = _season_watch_paint_snapshot(db, show_id)
    if int(before.get("show_watched") or 0) > 0 or int(before.get("ep_watched") or 0) > 0:
        try:
            from resources.lib.simkl.all_items_sync import ensure_show_episode_watch_aligned_for_paint

            if ensure_show_episode_watch_aligned_for_paint(db, show_id, catalog=catalog):
                clear_drilldown_cache_for_show(show_id)  # reconciled before paint
            before = _season_watch_paint_snapshot(db, show_id)
        except Exception:
            g.log_stacktrace()
    if _season_watch_paint_ready(before):
        return

    g.log(
        f"Menu perf: drilldown sync watch hydrate show={show_id} "
        f"show_watched={before['show_watched']} ep_rows={before['ep_rows']} "
        f"ep_watched={before['ep_watched']}",
        "info",
    )
    show_meta = db._get_single_show_meta(show_id) or {"simkl_id": show_id, "catalog": catalog}
    if int(before.get("ep_rows") or 0) == 0:
        db.force_mill_shows(
            show_meta,
            mill_episodes=True,
            skip_provider_episode_updates=True,
            catalog=catalog,
        )
        db._format_seasons_local(show_id)
    try:
        db.refresh_show_episode_watch_state(show_id)
    except Exception:
        g.log_stacktrace()
    db._refresh_show_and_season_statistics(show_id)


def merge_watch_state_light(db, show_id: int, rows: list[dict]) -> list[dict]:
    """Season watch badges from local episode rows when the tree already exists."""
    if not rows:
        return rows
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope

    with serial_profile_scope(db, _drilldown_serial_profile(db, show_id)):
        enriched = db._enrich_season_episode_counts(rows)
        merged = db._enrich_season_watch_counts(int(show_id), enriched) or rows
        for row in merged:
            if isinstance(row, dict):
                _sync_season_row_watch_playcount(row)
        return merged


def _episode_watch_paint_snapshot(
    db,
    show_id: int,
    *,
    season_num: int | None = None,
    flat_all: bool = False,
) -> dict[str, int]:
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope

    with serial_profile_scope(db, _drilldown_serial_profile(db, show_id)):
        st = db._st()
        show_row = db.fetchone(
            f"SELECT watched_episodes FROM {st.show} WHERE simkl_id=?",
            (int(show_id),),
        ) or {}
        where = "simkl_show_id = ? AND season > 0"
        params: list[int] = [int(show_id)]
        if not flat_all and season_num is not None:
            where += " AND season = ?"
            params.append(int(season_num))
        ep_row = db.fetchone(
            f"""
            SELECT COUNT(*) AS ep_rows,
                   SUM(CASE WHEN COALESCE(watched, 0) > 0 THEN 1 ELSE 0 END) AS ep_watched
            FROM {st.episode}
            WHERE {where}
            """,
            tuple(params),
        ) or {}
    try:
        show_watched = int(show_row.get("watched_episodes") or 0)
    except (TypeError, ValueError):
        show_watched = 0
    try:
        ep_rows = int(ep_row.get("ep_rows") or 0)
        ep_watched = int(ep_row.get("ep_watched") or 0)
    except (TypeError, ValueError):
        ep_rows = 0
        ep_watched = 0
    return {"show_watched": show_watched, "ep_rows": ep_rows, "ep_watched": ep_watched}


def _episode_watch_paint_ready(snapshot: dict[str, int], expected_count: int | None) -> bool:
    """Episode rows for this menu scope exist and watch flags are present when the show has history."""
    ep_rows = int(snapshot.get("ep_rows") or 0)
    if expected_count is not None and ep_rows < int(expected_count):
        return False
    if ep_rows <= 0:
        return False
    show_watched = int(snapshot.get("show_watched") or 0)
    ep_watched = int(snapshot.get("ep_watched") or 0)
    if show_watched > 0 and ep_watched <= 0:
        return False
    return True


def _ensure_episode_watch_state_for_paint(
    db,
    show_id: int,
    catalog: str,
    *,
    season_num: int | None = None,
    flat_all: bool = False,
    expected_count: int | None = None,
) -> None:
    """Block fast episode paint until anime/TV episode rows and watch flags match the menu scope."""
    show_id = int(show_id)
    before = _episode_watch_paint_snapshot(
        db, show_id, season_num=season_num, flat_all=flat_all
    )
    if int(before.get("show_watched") or 0) > 0 or int(before.get("ep_watched") or 0) > 0:
        try:
            from resources.lib.simkl.all_items_sync import ensure_show_episode_watch_aligned_for_paint

            if ensure_show_episode_watch_aligned_for_paint(db, show_id, catalog=catalog):
                clear_drilldown_cache_for_show(show_id)
            before = _episode_watch_paint_snapshot(
                db, show_id, season_num=season_num, flat_all=flat_all
            )
        except Exception:
            g.log_stacktrace()
    if _episode_watch_paint_ready(before, expected_count):
        return

    g.log(
        f"Menu perf: drilldown sync episode watch hydrate show={show_id} "
        f"expected={expected_count} ep_rows={before['ep_rows']} ep_watched={before['ep_watched']}",
        "info",
    )
    show_meta = db._get_single_show_meta(show_id) or {"simkl_id": show_id, "catalog": catalog}
    mill_filter = None
    if not flat_all and season_num is not None:
        mill_filter = frozenset({int(season_num)})
    db.force_mill_shows(
        show_meta,
        mill_episodes=True,
        skip_provider_episode_updates=True,
        mill_season_filter=mill_filter,
        catalog=catalog,
    )
    from resources.lib.simkl.ids import season_key

    if flat_all:
        db._format_episodes_local(show_id)
    elif season_num is not None:
        db._format_episodes_local(show_id, season_key(show_id, int(season_num)))
    try:
        db.refresh_show_episode_watch_state(show_id)
    except Exception:
        g.log_stacktrace()
    try:
        from resources.lib.simkl.all_items_sync import ensure_show_episode_watch_aligned_for_paint

        if ensure_show_episode_watch_aligned_for_paint(db, show_id, catalog=catalog):
            clear_drilldown_cache_for_show(show_id)
    except Exception:
        g.log_stacktrace()
    db._refresh_show_and_season_statistics(show_id)


def _row_episode_coord(row: dict) -> tuple[int, int] | None:
    info = row.get("info") if isinstance(row.get("info"), dict) else {}
    season_raw = row.get("season", info.get("season"))
    ep_raw = row.get("episode")
    if ep_raw is None:
        ep_raw = info.get("episode") if info.get("episode") is not None else info.get("number")
    try:
        if season_raw is None or ep_raw is None:
            return None
        return int(season_raw), int(ep_raw)
    except (TypeError, ValueError):
        return None


def merge_episode_watch_state_light(
    db,
    show_id: int,
    rows: list[dict],
    *,
    season_num: int | None = None,
) -> list[dict]:
    if not rows:
        return rows
    ids = [int(row["simkl_id"]) for row in rows if row.get("simkl_id") is not None]
    if not ids:
        return rows
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope

    profile = _drilldown_serial_profile(db, show_id)
    with serial_profile_scope(db, profile):
        st = db._st()
        placeholders = ",".join("?" * len(ids))
        watch_rows = db.fetchall(
            f"""
            SELECT e.simkl_id,
                   e.watched AS play_count,
                   b.resume_time AS resume_time,
                   b.percent_played AS percent_played,
                   e.user_rating
            FROM {st.episode} AS e
            LEFT JOIN bookmarks AS b ON e.simkl_id = b.simkl_id
            WHERE e.simkl_show_id = ? AND e.simkl_id IN ({placeholders})
            """,
            (int(show_id), *ids),
        ) or []
        by_id = {int(row["simkl_id"]): row for row in watch_rows if row.get("simkl_id") is not None}
        if len(by_id) < len(ids):
            where = "e.simkl_show_id = ? AND e.season > 0"
            scope_params: list[int] = [int(show_id)]
            if season_num is not None:
                where += " AND e.season = ?"
                scope_params.append(int(season_num))
            scope_rows = db.fetchall(
                f"""
                SELECT e.simkl_id,
                       e.season,
                       e.number,
                       e.watched AS play_count,
                       b.resume_time AS resume_time,
                       b.percent_played AS percent_played,
                       e.user_rating
                FROM {st.episode} AS e
                LEFT JOIN bookmarks AS b ON e.simkl_id = b.simkl_id
                WHERE {where}
                """,
                tuple(scope_params),
            ) or []
            for row in scope_rows:
                if row.get("simkl_id") is not None:
                    by_id[int(row["simkl_id"])] = row
    by_coord = {
        (int(row["season"]), int(row["number"])): row
        for row in by_id.values()
        if row.get("season") is not None and row.get("number") is not None
    }
    if not by_id:
        return rows
    merged: list[dict] = []
    for row in rows:
        simkl_id = row.get("simkl_id")
        if simkl_id is None:
            merged.append(row)
            continue
        watch = by_id.get(int(simkl_id))
        if not watch:
            coord = _row_episode_coord(row)
            if coord:
                watch = by_coord.get(coord)
        if not watch:
            merged.append(row)
            continue
        item = dict(row)
        play_count = watch.get("play_count")
        if play_count is not None:
            item["play_count"] = play_count
            info = item.setdefault("info", {})
            if isinstance(info, dict):
                info["playcount"] = play_count
        if watch.get("resume_time") is not None:
            item["resume_time"] = watch.get("resume_time")
        if watch.get("percent_played") is not None:
            item["percent_played"] = watch.get("percent_played")
        if watch.get("user_rating") is not None:
            item["user_rating"] = watch.get("user_rating")
        merged.append(item)
    return merged


def build_season_menu_rows(
    show_id: int,
    catalog: str,
    *,
    db=None,
    show_ctx: dict | None = None,
    slug: str | None = None,
    paint_kwargs: dict | None = None,
) -> list[dict] | None:
    from resources.lib.database.simkl_sync.milling import pull_show_seasons

    if db is None:
        from resources.lib.database.session import get_sync_database

        db = get_sync_database()
    paint_kwargs = paint_kwargs or {}
    cache_key = (int(show_id), catalog, "seasons")
    cached = _cache_get(cache_key)
    if cached is not None:
        g.log(f"Menu perf: drilldown cache hit show={show_id} mode=seasons rows={len(cached)}", "debug")
        _ensure_season_watch_state_for_paint(db, int(show_id), catalog)
        return _filter_season_rows(merge_watch_state_light(db, show_id, cached), paint_kwargs)

    if slug is None:
        slug = _resolve_slug(db, show_id)
    raw = load_raw_episode_tree(show_id, catalog, slug=slug, db=db)
    if not raw:
        return None

    milled = pull_show_seasons(int(show_id), catalog, mill_episodes=False, slug=slug)
    if not milled:
        return None

    show_info, show_art, show_cast = _parent_show_fields(db, show_id, show_ctx)
    rows = [_format_milled_row(db, season, show_info=show_info, show_art=show_art, show_cast=show_cast) for season in milled]
    if rows:
        _cache_put(cache_key, rows)
    _ensure_season_watch_state_for_paint(db, int(show_id), catalog)
    rows = merge_watch_state_light(db, show_id, rows)
    rows = _filter_season_rows(rows, paint_kwargs)
    g.log(
        f"Menu perf: drilldown_fast build seasons show={show_id} catalog={catalog} rows={len(rows or [])}",
        "debug",
    )
    return rows or None


def build_episode_menu_rows(
    show_id: int,
    catalog: str,
    season_num: int | None,
    *,
    flat_all: bool = False,
    db=None,
    show_ctx: dict | None = None,
    season_ctx: dict | None = None,
    slug: str | None = None,
    paint_kwargs: dict | None = None,
) -> list[dict] | None:
    from resources.lib.database.simkl_sync.milling import pull_show_seasons

    if db is None:
        from resources.lib.database.session import get_sync_database

        db = get_sync_database()
    paint_kwargs = paint_kwargs or {}
    mode = "flat" if flat_all else f"s{int(season_num) if season_num is not None else 0}"
    cache_key = (int(show_id), catalog, "episodes", mode)
    cached = _cache_get(cache_key)
    if cached is not None:
        g.log(f"Menu perf: drilldown cache hit show={show_id} mode={mode} rows={len(cached)}", "debug")
        _ensure_episode_watch_state_for_paint(
            db,
            int(show_id),
            catalog,
            season_num=season_num,
            flat_all=flat_all,
            expected_count=len(cached),
        )
        return _filter_episode_rows(
            merge_episode_watch_state_light(db, show_id, cached, season_num=season_num),
            paint_kwargs,
        )

    if slug is None:
        slug = _resolve_slug(db, show_id)
    raw = load_raw_episode_tree(show_id, catalog, slug=slug, db=db)
    if not raw:
        return None

    mill_filter = None
    if not flat_all and season_num is not None:
        mill_filter = frozenset({int(season_num)})
    milled = pull_show_seasons(
        int(show_id),
        catalog,
        mill_episodes=True,
        slug=slug,
        mill_season_filter=mill_filter,
    )
    if not milled:
        return None

    show_info, show_art, show_cast = _parent_show_fields(db, show_id, show_ctx)
    season_info = (season_ctx or {}).get("season_info") if season_ctx else None
    season_art = (season_ctx or {}).get("season_art") if season_ctx else None

    stubs: list[dict[str, Any]] = []
    if flat_all:
        for season in milled:
            stubs.extend(season.get("episodes") or [])
        stubs.sort(key=lambda ep: (ep.get("season") or 0, ep.get("episode") or 0))
    else:
        target = int(season_num) if season_num is not None else None
        for season in milled:
            if target is not None and int(season.get("season") or 0) != target:
                continue
            stubs.extend(season.get("episodes") or [])
        stubs.sort(key=lambda ep: ep.get("episode") or 0)

    if not stubs:
        return None

    rows = [
        _format_milled_row(
            db,
            stub,
            show_info=show_info,
            show_art=show_art,
            show_cast=show_cast,
            season_info=season_info,
            season_art=season_art,
        )
        for stub in stubs
    ]
    if rows:
        _cache_put(cache_key, rows)
    _ensure_episode_watch_state_for_paint(
        db,
        int(show_id),
        catalog,
        season_num=season_num,
        flat_all=flat_all,
        expected_count=len(rows),
    )
    rows = merge_episode_watch_state_light(db, show_id, rows, season_num=season_num)
    rows = _filter_episode_rows(rows, paint_kwargs)
    g.log(
        f"Menu perf: drilldown_fast build episodes show={show_id} catalog={catalog} mode={mode} rows={len(rows)}",
        "debug",
    )
    return rows


class DrilldownPagePipeline:
    """Symmetry with CatalogPagePipeline for season/episode drilldown."""

    @staticmethod
    def fast_open_enabled() -> bool:
        return drilldown_fast_open_enabled()

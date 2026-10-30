"""Post-sync episode catalog warm for library episode menus (Next Up, Continue Watching, etc.)."""
from __future__ import annotations

import datetime
import time
from typing import TYPE_CHECKING, Callable

from resources.lib.modules.globals import g
from resources.lib.simkl.library import _unwrap_sync_items, sync_entry_media_blob

if TYPE_CHECKING:
    from resources.lib.database.simkl_sync.activities import SimklSyncDatabase

EPISODE_WARM_BATCH_SIZE = 8
CHANGES_POLL_INTERVAL_SEC = 24 * 60 * 60
RECENT_WATCHED_SHOW_LIMIT = 100
WATCHING_WARM_CAP = 50
LAZY_WARM_SHOW_CAP = 10

BUCKET_NEXT_UP = "next_up"
BUCKET_CONTINUE = "continue_watching"
BUCKET_WATCHED = "watched_episodes"
BUCKET_CATALOG = "catalog_update"
BUCKET_DELTA = "sync_delta"

_BUCKET_STRING_IDS = {
    BUCKET_NEXT_UP: 31005,
    BUCKET_CONTINUE: 31006,
    BUCKET_WATCHED: 31007,
    BUCKET_CATALOG: 31008,
    BUCKET_DELTA: 31009,
}

_BUCKET_PROGRESS_STRING_IDS = {
    BUCKET_NEXT_UP: 31005,
    BUCKET_CONTINUE: 31014,
    BUCKET_WATCHED: 31015,
    BUCKET_CATALOG: 31016,
    BUCKET_DELTA: 31017,
}


def bucket_label(bucket: str) -> str:
    string_id = _BUCKET_STRING_IDS.get(bucket, 31008)
    return g.get_language_string(string_id)


def bucket_progress_label(bucket: str) -> str:
    """Short menu label for the sync progress dialog (limited width)."""
    string_id = _BUCKET_PROGRESS_STRING_IDS.get(bucket, 31005)
    return g.get_language_string(string_id)


def episode_warm_enabled() -> bool:
    return g.get_bool_setting("simkl.syncEpisodeWarm", True)


def episode_warm_uses_raw_endpoint() -> bool:
    return g.get_bool_setting("simkl.syncEpisodeWarmFast", True)


def library_parent_warm_enabled() -> bool:
    return g.get_bool_setting("simkl.syncLibraryParentWarm", True)


def library_page_warm_enabled() -> bool:
    return g.get_bool_setting("simkl.syncLibraryPageWarm", True)


def show_ids_from_payload(payload) -> set[int]:
    ids: set[int] = set()
    if not payload:
        return ids
    for media_key in ("shows", "anime"):
        for entry in _unwrap_sync_items(payload, media_key):
            if not isinstance(entry, dict):
                continue
            blob = sync_entry_media_blob(entry, media_key)
            simkl_id = (blob.get("ids") or {}).get("simkl")
            if simkl_id is not None:
                ids.add(int(simkl_id))
    return ids


def _active_watchlist_show_ids(db: "SimklSyncDatabase") -> set[int]:
    ids: set[int] = set()
    for status in ("watching", "plantowatch", "hold"):
        for catalog in ("tv", "anime"):
            for ref in db.get_shows_by_simkl_status(status, catalog=catalog):
                if ref.get("simkl_id") is not None:
                    ids.add(int(ref["simkl_id"]))
    return ids


def fetch_catalog_change_ids(db: "SimklSyncDatabase", *, force: bool = False) -> set[int]:
    """Return Simkl IDs from GET /changes intersected with active watchlist shows."""
    db.refresh_activities()
    last_poll = int(db.activities.get("last_changes_poll") or 0)
    now = int(time.time())
    if not force and last_poll and (now - last_poll) < CHANGES_POLL_INTERVAL_SEC:
        return set()

    date_from = datetime.datetime.utcfromtimestamp(last_poll or (now - CHANGES_POLL_INTERVAL_SEC)).strftime(
        "%Y-%m-%d"
    )
    payload = db.simkl_api.get_changes(date_from=date_from)
    if not isinstance(payload, dict):
        g.log(
            f"Simkl /changes poll skipped (no payload); date_from={date_from}; last_poll unchanged",
            "debug",
        )
        return set()

    db.execute_sql("UPDATE activities SET last_changes_poll=? WHERE sync_id=1", (now,))
    db.refresh_activities()

    changed: set[int] = set()
    for key in ("shows", "anime"):
        for simkl_id in payload.get(key) or []:
            try:
                changed.add(int(simkl_id))
            except (TypeError, ValueError):
                continue

    active = _active_watchlist_show_ids(db)
    return changed & active


def _show_row(db: "SimklSyncDatabase", simkl_id: int) -> dict | None:
    from resources.lib.database.simkl_sync.serial_sync import serial_tables

    catalog = db.show_catalog(int(simkl_id))
    st = serial_tables("anime" if catalog == "anime" else "tv")
    return db.fetchone(
        f"""
        SELECT s.simkl_id, m.value AS simkl_object, s.tmdb_id, s.tvdb_id, s.needs_milling
        FROM {st.show} AS s
                 LEFT JOIN {st.show_meta} AS m ON m.id = s.simkl_id AND m.type = 'simkl'
        WHERE s.simkl_id = ?
        """,
        (int(simkl_id),),
    )


def show_catalog_is_warm(db: "SimklSyncDatabase", simkl_id: int) -> bool:
    from resources.lib.database.simkl_sync.serial_sync import serial_tables

    catalog = db.show_catalog(int(simkl_id))
    st = serial_tables("anime" if catalog == "anime" else "tv")
    row = db.fetchone(
        f"""
        SELECT 1 AS ok
        FROM {st.episode} AS e
                 INNER JOIN {st.episode_meta} AS em ON em.id = e.simkl_id AND em.type = 'simkl'
        WHERE e.simkl_show_id = ?
        LIMIT 1
        """,
        (int(simkl_id),),
    )
    return row is not None


def resolve_warm_targets(
    db: "SimklSyncDatabase",
    *,
    delta_show_ids: set[int] | None = None,
    changes_show_ids: set[int] | None = None,
) -> list[tuple[dict, str]]:
    """Return (show_row, bucket) pairs deduped by simkl_id (first bucket wins)."""
    delta_show_ids = delta_show_ids or set()
    changes_show_ids = changes_show_ids or set()
    ordered: list[tuple[int, str]] = []

    def add(ids: set[int], bucket: str) -> None:
        seen = {show_id for show_id, _ in ordered}
        for show_id in ids:
            if show_id not in seen:
                ordered.append((int(show_id), bucket))

    watching_candidates: list[int] = []
    for catalog in ("tv", "anime"):
        rows = db.fetchall(
            """
            SELECT simkl_id, watched_episodes, needs_milling
            FROM shows
            WHERE COALESCE(simkl_status, '') = 'watching'
              AND catalog = ?
            """,
            (catalog,),
        )
        for row in rows or []:
            show_id = row.get("simkl_id")
            if show_id is None:
                continue
            sid = int(show_id)
            if show_catalog_is_warm(db, sid) and not row.get("needs_milling"):
                continue
            watching_candidates.append(sid)
    add(set(watching_candidates[:WATCHING_WARM_CAP]), BUCKET_NEXT_UP)

    bookmark_rows = db.fetchall(
        """
        SELECT DISTINCT e.simkl_show_id AS simkl_id, e.catalog AS catalog
        FROM bookmarks AS b
                 INNER JOIN episodes AS e ON e.simkl_id = b.simkl_id AND e.catalog = b.catalog
        WHERE b.type = 'episode'
        """
    )
    add({int(row["simkl_id"]) for row in bookmark_rows if row.get("simkl_id") is not None}, BUCKET_CONTINUE)

    recent_rows = db.fetchall(
        f"""
        SELECT DISTINCT simkl_show_id AS simkl_id, catalog
        FROM episodes
        WHERE watched > 0 AND catalog IN ('tv', 'anime')
        ORDER BY last_watched_at DESC
        LIMIT {RECENT_WATCHED_SHOW_LIMIT}
        """
    )
    add({int(row["simkl_id"]) for row in recent_rows if row.get("simkl_id") is not None}, BUCKET_WATCHED)

    completed_rows = db.fetchall(
        """
        SELECT simkl_id
        FROM shows
        WHERE catalog IN ('tv', 'anime')
          AND COALESCE(simkl_status, '') = 'completed'
          AND COALESCE(watched_episodes, 0) > 0
        """
    )
    add({int(row["simkl_id"]) for row in completed_rows if row.get("simkl_id") is not None}, BUCKET_WATCHED)

    add(delta_show_ids, BUCKET_DELTA)
    add(changes_show_ids, BUCKET_CATALOG)

    targets: list[tuple[dict, str]] = []
    for show_id, bucket in ordered:
        if bucket not in (BUCKET_DELTA, BUCKET_CATALOG) and show_catalog_is_warm(db, show_id):
            continue
        if bucket == BUCKET_CATALOG and show_catalog_is_warm(db, show_id):
            continue
        row = _show_row(db, show_id)
        if row:
            targets.append((row, bucket))
        else:
            targets.append(({"simkl_id": show_id}, bucket))
    return targets


def _show_title(show_row: dict) -> str:
    from resources.lib.modules.metadataHandler import MetadataHandler

    info = MetadataHandler.simkl_info(show_row) or {}
    title = info.get("title") or info.get("name")
    if title:
        return str(title)
    obj = show_row.get("simkl_object") or {}
    info = obj.get("info") if isinstance(obj, dict) else {}
    if isinstance(info, dict):
        return str(info.get("title") or info.get("name") or f"Show {show_row.get('simkl_id')}")
    return f"Show {show_row.get('simkl_id')}"


def _attach_show_ids_to_milled_tree(show_row: dict, milled: list[dict]) -> None:
    from resources.lib.modules.metadataHandler import MetadataHandler

    show_id = int(show_row.get("simkl_id"))
    show_info = MetadataHandler.simkl_info(show_row) or {}
    tmdb_id = show_row.get("tmdb_id")
    tvdb_id = show_row.get("tvdb_id")
    title = show_info.get("title") or show_info.get("name")
    for season in milled:
        MetadataHandler.simkl_info(season).update(
            {
                "simkl_show_id": show_id,
                "tmdb_show_id": tmdb_id,
                "tvdb_show_id": tvdb_id,
                "tvshowtitle": title,
            }
        )
        season.update(
            {
                "simkl_show_id": show_id,
                "tmdb_show_id": tmdb_id,
                "tvdb_show_id": tvdb_id,
            }
        )
        catalog = season.get("catalog") or show_row.get("catalog")
        for episode in season.get("episodes") or []:
            MetadataHandler.simkl_info(episode).update(
                {
                    "simkl_show_id": show_id,
                    "tmdb_show_id": tmdb_id,
                    "tvdb_show_id": tvdb_id,
                    "simkl_season_id": season.get("simkl_id"),
                    "tvshowtitle": title,
                }
            )
            episode.update(
                {
                    "simkl_show_id": show_id,
                    "tmdb_show_id": tmdb_id,
                    "tvdb_show_id": tvdb_id,
                    "simkl_season_id": season.get("simkl_id"),
                }
            )
            if catalog in ("movie", "tv", "anime"):
                episode.setdefault("catalog", catalog)


def warm_show_episodes_from_raw_api(db: "SimklSyncDatabase", show_row: dict) -> bool:
    """Persist season/episode rows from GET /tv|anime/episodes/{id} (fast warm path)."""
    from resources.lib.database.simkl_sync.milling import fetch_raw_show_episodes, pull_show_seasons

    show_id = show_row.get("simkl_id")
    if show_id is None:
        return False
    show_id = int(show_id)
    catalog = db.show_catalog(show_id)
    slug = db._meta_slug(show_id, "shows")
    raw = fetch_raw_show_episodes(show_id, catalog, slug=slug, api=db.simkl_api)
    if not raw:
        g.log(f"Simkl episode warm: raw fetch empty show={show_id} — mill fallback", "debug")
        return False

    milled = pull_show_seasons(show_id, catalog, True, slug=slug)
    if not milled:
        return False

    _attach_show_ids_to_milled_tree(show_row, milled)
    db.insert_simkl_seasons(milled)
    episodes = [episode for season in milled for episode in (season.get("episodes") or [])]
    if episodes:
        db.insert_simkl_episodes(episodes)
    db.execute_sql(
        "UPDATE shows SET needs_milling=0 WHERE simkl_id=? AND catalog=?",
        (show_id, catalog),
    )
    return True


def warm_episode_catalogs(
    db: "SimklSyncDatabase",
    targets: list[tuple[dict, str]],
    *,
    on_progress: Callable[[int, int, str, str], None] | None = None,
    notify_silent: bool = False,
) -> int:
    """Warm episode catalogs for target shows (raw Simkl episode list first, mill fallback)."""
    if not targets:
        return 0

    if notify_silent:
        g.notification(g.ADDON_NAME, g.get_language_string(31004))

    use_raw = episode_warm_uses_raw_endpoint()
    total = len(targets)
    warmed = 0
    pull_started = time.time()
    for start in range(0, total, EPISODE_WARM_BATCH_SIZE):
        batch = targets[start : start + EPISODE_WARM_BATCH_SIZE]
        mill_fallback: list[dict] = []
        if use_raw:
            for show_row, _bucket in batch:
                if not warm_show_episodes_from_raw_api(db, show_row):
                    mill_fallback.append(show_row)
        else:
            mill_fallback = [row for row, _ in batch]

        if mill_fallback:
            db.force_mill_shows(
                mill_fallback,
                mill_episodes=True,
                skip_provider_episode_updates=True,
                defer_episode_format=True,
            )

        for offset, (show_row, bucket) in enumerate(batch):
            current = start + offset + 1
            if on_progress:
                on_progress(current, total, _show_title(show_row), bucket)
        warmed += len(batch)

    pull_ms = (time.time() - pull_started) * 1000
    g.log(
        f"Simkl episode catalog warm complete: pulled={warmed} raw_fast={use_raw} pull_ms={pull_ms:.0f}",
        "info",
    )
    return warmed


def _nextup_episode_rows_for_catalog(db: "SimklSyncDatabase", catalog: str) -> list[dict]:
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope
    from resources.lib.modules.globals import g

    profile = "anime" if catalog == "anime" else "tv"
    sort_last = g.get_int_setting("nextup.sort") == 1
    limit = g.get_int_setting("item.limit") if g.get_bool_setting("limit.nextup") else 50
    with serial_profile_scope(db, profile):
        rows = db.get_nextup_episodes(sort_last, catalog=catalog) or []
    if limit > 0:
        rows = rows[: int(limit)]
    return rows


    return rows


def _continue_watching_episode_rows(db: "SimklSyncDatabase", catalog: str) -> list[dict]:
    from resources.lib.simkl.playback import list_continue_watching

    rows = list_continue_watching(catalog, page=1, resync_if_empty=False) or []
    for row in rows:
        if isinstance(row, dict):
            row.setdefault("catalog", catalog)
    return rows


def _watched_episode_rows_for_catalog(db: "SimklSyncDatabase", catalog: str) -> list[dict]:
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope
    from resources.lib.simkl.menu_helpers import paginate_simkl_lists

    profile = "anime" if catalog == "anime" else "tv"
    page_limit = g.get_int_setting("item.limit")
    with serial_profile_scope(db, profile):
        page = 1 if not paginate_simkl_lists() else 1
        rows = db.get_watched_episodes(page, catalog=catalog) or []
    if page_limit > 0 and g.get_bool_setting("limit.nextup"):
        rows = rows[: int(page_limit)]
    elif page_limit > 0:
        rows = rows[: int(page_limit)]
    return rows


def episode_rows_for_menu_bucket(
    db: "SimklSyncDatabase",
    catalog: str,
    bucket: str,
) -> list[dict]:
    if bucket == BUCKET_NEXT_UP:
        return _nextup_episode_rows_for_catalog(db, catalog)
    if bucket == BUCKET_CONTINUE:
        return _continue_watching_episode_rows(db, catalog)
    if bucket == BUCKET_WATCHED:
        return _watched_episode_rows_for_catalog(db, catalog)
    return []


def refresh_listed_episodes_for_menu_bucket(
    db: "SimklSyncDatabase",
    catalog: str,
    bucket: str,
    episode_rows: list[dict] | None = None,
) -> int:
    from resources.lib.database.simkl_sync.milling import refresh_listed_episodes_from_simkl
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope

    rows = episode_rows if episode_rows is not None else episode_rows_for_menu_bucket(db, catalog, bucket)
    if not rows:
        return 0
    profile = "anime" if catalog == "anime" else "tv"
    with serial_profile_scope(db, profile):
        refreshed = refresh_listed_episodes_from_simkl(db, rows)
    if refreshed:
        g.log(
            f"Simkl listed-episode refresh: {refreshed} row(s) ({catalog}, {bucket})",
            "debug",
        )
    return refreshed


def _scoped_parent_show_refs(db: "SimklSyncDatabase", catalog: str) -> list[dict]:
    """Watching + continue-watching parents for post-sync library parent warm."""
    seen: set[int] = set()
    refs: list[dict] = []

    def add(show_id: int | None) -> None:
        if show_id is None:
            return
        sid = int(show_id)
        if sid in seen:
            return
        if db.show_catalog(sid) != catalog:
            return
        seen.add(sid)
        refs.append({"simkl_id": sid, "catalog": catalog})

    watching = db.get_shows_by_simkl_status("watching", catalog=catalog) or []
    for ref in watching[:WATCHING_WARM_CAP]:
        add(ref.get("simkl_id"))

    for row in db.fetchall(
        """
        SELECT DISTINCT e.simkl_show_id AS simkl_id
        FROM bookmarks AS b
                 INNER JOIN episodes AS e ON e.simkl_id = b.simkl_id AND e.catalog = b.catalog
        WHERE b.type = 'episode' AND e.catalog = ?
        """,
        (catalog,),
    ):
        add(row.get("simkl_id"))

    return refs


def refresh_scoped_parent_shows_for_paint(db: "SimklSyncDatabase", catalog: str) -> dict[str, int]:
    from resources.lib.meta.list_paint import prepare_episode_parent_shows_for_paint

    if not library_parent_warm_enabled():
        return {"refs": 0, "detail_before": 0, "detail_after": 0}

    refs = _scoped_parent_show_refs(db, catalog)
    next_up_rows = _nextup_episode_rows_for_catalog(db, catalog)
    from resources.lib.meta.list_paint import parent_show_refs_from_episode_rows

    for ref in parent_show_refs_from_episode_rows(next_up_rows, catalog):
        sid = int(ref["simkl_id"])
        if sid not in {int(r["simkl_id"]) for r in refs}:
            refs.append(ref)

    if not refs:
        return {"refs": 0, "detail_before": 0, "detail_after": 0}

    stats = prepare_episode_parent_shows_for_paint(
        db,
        catalog,
        refs,
        episode_rows=next_up_rows or None,
    )
    if stats.get("detail_before") or stats.get("detail_after"):
        g.log(
            f"Simkl library parent show warm ({catalog}): "
            f"detail_needed {stats['detail_before']}->{stats['detail_after']} "
            f"parents={stats['refs']}",
            "debug",
        )
    return stats


def warm_library_episode_catalog(
    db: "SimklSyncDatabase",
    catalog: str,
    *,
    reason: str = "post_sync",
    buckets: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Post-sync / prefetch: listed-episode refresh + parent show warm for one serial catalog."""
    if not episode_warm_enabled() or catalog not in ("tv", "anime"):
        return {"listed": 0, "detail_before": 0, "detail_after": 0}

    bucket_list = buckets or (BUCKET_NEXT_UP, BUCKET_CONTINUE, BUCKET_WATCHED)
    listed_total = 0
    for bucket in bucket_list:
        listed_total += refresh_listed_episodes_for_menu_bucket(db, catalog, bucket)

    parent_stats = refresh_scoped_parent_shows_for_paint(db, catalog)
    g.log(
        f"warm_library_episode_catalog catalog={catalog} reason={reason} "
        f"listed={listed_total} parent={parent_stats.get('detail_after', 0)}",
        "debug",
    )
    return {
        "listed": listed_total,
        "detail_before": int(parent_stats.get("detail_before") or 0),
        "detail_after": int(parent_stats.get("detail_after") or 0),
    }


def refresh_nextup_parent_shows_for_paint(db: "SimklSyncDatabase", catalog: str) -> dict[str, int]:
    """Pre-warm Next Up parent shows so library open skips blocking Browse paint (tv + anime)."""
    return refresh_scoped_parent_shows_for_paint(db, catalog)


def refresh_parent_shows_for_show_ids(
    db: "SimklSyncDatabase",
    show_ids: list[int] | set[int],
) -> None:
    """Background parent warm after lazy episode catalog warm (Next Up / Continue Watching)."""
    from resources.lib.meta.list_paint import prepare_episode_parent_shows_for_paint

    if not episode_warm_enabled() or not show_ids or not library_parent_warm_enabled():
        return

    by_catalog: dict[str, list[dict]] = {}
    for raw_id in show_ids:
        if raw_id is None:
            continue
        sid = int(raw_id)
        catalog = db.show_catalog(sid)
        if catalog not in ("tv", "anime"):
            continue
        by_catalog.setdefault(catalog, []).append({"simkl_id": sid, "catalog": catalog})

    for catalog, refs in by_catalog.items():
        prepare_episode_parent_shows_for_paint(db, catalog, refs)


def refresh_nextup_listed_episodes(db: "SimklSyncDatabase", catalog: str) -> int:
    """Target Simkl plot/still for visible Next Up rows (tv + anime), not full-show mill."""
    return refresh_listed_episodes_for_menu_bucket(db, catalog, BUCKET_NEXT_UP)


def run_post_sync_episode_warm(
    db: "SimklSyncDatabase",
    *,
    payload,
    force: bool = False,
    notify_silent: bool = False,
    on_progress: Callable[[int, int, str, str], None] | None = None,
) -> int:
    changes_ids = fetch_catalog_change_ids(db, force=force)
    delta_ids = show_ids_from_payload(payload)
    targets = resolve_warm_targets(
        db,
        delta_show_ids=delta_ids,
        changes_show_ids=changes_ids,
    )
    if targets:
        g.log(f"Simkl episode catalog warm: {len(targets)} show(s)", "info")
    warmed = warm_episode_catalogs(
        db,
        targets,
        on_progress=on_progress,
        notify_silent=notify_silent,
    )
    if episode_warm_enabled():
        for catalog in ("tv", "anime"):
            warm_library_episode_catalog(db, catalog, reason="post_sync")
    if library_page_warm_enabled():
        from resources.lib.simkl.library_list_sync import warm_library_watchlist_pages_post_sync

        for catalog in ("movie", "tv", "anime"):
            warm_library_watchlist_pages_post_sync(catalog)
    return warmed


def schedule_lazy_episode_warm(db: "SimklSyncDatabase", show_ids: set[int] | list[int]) -> None:
    """On-demand episode catalog warm for Next Up / Continue Watching menus."""
    if not show_ids or not episode_warm_enabled():
        return

    import threading

    ids = [int(show_id) for show_id in show_ids if show_id is not None]
    unwarmed = [show_id for show_id in ids if not show_catalog_is_warm(db, show_id)]
    if not unwarmed:
        return

    def _warm() -> None:
        try:
            targets: list[tuple[dict, str]] = []
            for show_id in unwarmed[:LAZY_WARM_SHOW_CAP]:
                row = _show_row(db, show_id)
                targets.append((row or {"simkl_id": show_id}, BUCKET_NEXT_UP))
            if targets:
                g.log(f"Simkl lazy episode warm: {len(targets)} show(s)", "debug")
                warm_episode_catalogs(db, targets, notify_silent=True)
                refresh_parent_shows_for_show_ids(
                    db,
                    [int(row.get("simkl_id")) for row, _ in targets if row.get("simkl_id")],
                )
        except Exception:
            g.log_stacktrace()

    from resources.lib.common.thread_pool import defer_background

    defer_background(_warm)

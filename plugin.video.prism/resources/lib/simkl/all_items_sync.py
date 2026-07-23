"""Watchlist foundation sync via ``GET /sync/all-items`` (one call per phase).

Simkl-native ingest at activities sync time — menus read local DB only.
Option-2 LIST gap-fill at paint time mirrors discover menus.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from resources.lib.modules.globals import g
from resources.lib.simkl.episode_catalog_sync import (
    bucket_progress_label,
    episode_warm_enabled,
    run_post_sync_episode_warm,
)
from resources.lib.simkl.library import _unwrap_sync_items, simkl_entry_to_sync_dict
from resources.lib.simkl.statuses import MOVIE_STATUS_OPTIONS, SHOW_STATUS_OPTIONS

if TYPE_CHECKING:
    from resources.lib.database.simkl_sync.activities import SimklSyncDatabase

ALL_ITEMS_EXTENDED = "full_anime_seasons"
EPISODE_PRUNE_AFTER_SYNC = True

_MOVIE_STATUSES = tuple(status for status, _ in MOVIE_STATUS_OPTIONS)
_SHOW_STATUSES = tuple(status for status, _ in SHOW_STATUS_OPTIONS)


def build_all_items_params(*, date_from: str | None = None) -> dict:
    """Lean sync params — episode display meta comes from post-sync catalog warm."""
    params = {
        "extended": ALL_ITEMS_EXTENDED,
        "next_watch_info": "yes",
        "episode_watched_at": "yes",
    }
    if date_from:
        params["date_from"] = date_from
    return params


def fetch_all_items(api, *, date_from: str | None = None):
    return api.get_all_items(date_from=date_from, **build_all_items_params(date_from=date_from))


def ingest_payload(db: "SimklSyncDatabase", payload, *, is_delta: bool = False) -> None:
    if not payload:
        return
    if not is_delta:
        if _unwrap_sync_items(payload, "movies"):
            db.set_sync_progress(15, g.get_language_string(31001))
        db._process_movie_entries(_unwrap_sync_items(payload, "movies"))
        if _unwrap_sync_items(payload, "shows"):
            db.set_sync_progress(35, g.get_language_string(31002))
        db._process_show_entries(_unwrap_sync_items(payload, "shows"), "tv")
        if _unwrap_sync_items(payload, "anime"):
            db.set_sync_progress(50, g.get_language_string(31003))
        db._process_show_entries(_unwrap_sync_items(payload, "anime"), "anime")
    else:
        db._process_all_items_payload(payload)
    if EPISODE_PRUNE_AFTER_SYNC:
        db.prune_library_episodes()
    db.set_sync_progress(60, g.get_language_string(31010))
    _seed_display_meta_from_payload(db, payload)
    rebuild_library_cache_from_db(db)
    phase = "delta" if is_delta else "foundation"
    g.log(f"Simkl all-items ingest complete ({phase})", "info")


def rebuild_library_cache_from_db(db: "SimklSyncDatabase" | None = None) -> None:
    from resources.lib.database.session import get_sync_database
    from resources.lib.simkl.library_cache import _save_cached_refs

    db = db or get_sync_database()
    for status in _MOVIE_STATUSES:
        refs = db.get_movies_by_simkl_status(status)
        for ref in refs:
            ref["catalog"] = "movie"
        _save_cached_refs("movie", status, refs)
    for catalog in ("tv", "anime"):
        for status in _SHOW_STATUSES:
            refs = db.get_shows_by_simkl_status(status, catalog=catalog)
            for ref in refs:
                ref["catalog"] = catalog
            _save_cached_refs(catalog, status, refs)


def _seed_display_meta_from_payload(db: "SimklSyncDatabase", payload) -> None:
    from resources.lib.meta.display_store import get_display_meta_store
    from resources.lib.modules.meta_storage import slim_art_dict, slim_info_dict
    from resources.lib.modules.metadataHandler import MetadataHandler

    store = get_display_meta_store()
    rows_by_type: dict[str, list[dict]] = {"movie": [], "tvshow": []}
    for entry in _unwrap_sync_items(payload, "movies"):
        normalized = simkl_entry_to_sync_dict(entry, "movie")
        if not normalized:
            continue
        simkl_obj = normalized.get("simkl_object") or {}
        info = slim_info_dict(MetadataHandler.simkl_info(normalized) or {}, simkl=True)
        art = slim_art_dict(MetadataHandler.art(simkl_obj) or {}, "movie")
        if info or art:
            rows_by_type["movie"].append({"simkl_id": normalized["simkl_id"], "info": info, "art": art, "cast": []})
    for catalog, media_key in (("tv", "shows"), ("anime", "anime")):
        art_type = "anime" if catalog == "anime" else "tvshow"
        for entry in _unwrap_sync_items(payload, media_key):
            normalized = simkl_entry_to_sync_dict(entry, catalog)
            if not normalized:
                continue
            simkl_obj = normalized.get("simkl_object") or {}
            info = slim_info_dict(MetadataHandler.simkl_info(normalized) or {}, simkl=True)
            art = slim_art_dict(MetadataHandler.art(simkl_obj) or {}, art_type)
            if info or art:
                rows_by_type["tvshow"].append({"simkl_id": normalized["simkl_id"], "info": info, "art": art, "cast": []})
    for media_type, rows in rows_by_type.items():
        if rows:
            store.set_many_rows(media_type, rows)


def _episode_warm_progress(db: "SimklSyncDatabase", current: int, total: int, _title: str, bucket: str) -> None:
    menu = bucket_progress_label(bucket)
    message = g.get_language_string(31011).format(menu, current, total)
    percent = 70 + int(25 * current / max(total, 1))
    db.set_sync_progress(percent, message)


def sync_simkl_library(db: "SimklSyncDatabase", remote_activities, *, force: bool = False) -> None:
    first_sync = str(db.activities["all_activities"]) == db.base_date
    date_from = None if first_sync else db.activities["all_activities"]
    blocking_warm = not db.silent

    db.set_sync_progress(5, g.get_language_string(31000))
    payload = fetch_all_items(db.simkl_api, date_from=date_from)
    if payload:
        ingest_payload(db, payload, is_delta=not first_sync)
    if db._removed_from_list_changed(remote_activities):
        db._reconcile_removed_items()
        rebuild_library_cache_from_db(db)

    if episode_warm_enabled():
        db.set_sync_progress(65, g.get_language_string(31012))
        run_post_sync_episode_warm(
            db,
            payload=payload,
            force=force,
            notify_silent=db.silent,
            on_progress=(
                (lambda c, t, title, bucket: _episode_warm_progress(db, c, t, title, bucket))
                if blocking_warm
                else None
            ),
        )
    db.set_sync_progress(100, g.get_language_string(31013))

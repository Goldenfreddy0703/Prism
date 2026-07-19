"""Simkl detail enrichment for search and browse lists."""

from __future__ import annotations

import copy
from functools import partial

from resources.lib.database.cache import use_cache
from resources.lib.modules.globals import g
from resources.lib.simkl.catalog import resolve_item_catalog


@use_cache(cache_hours=12)
def _simkl_detail_sync_dict(simkl_id: int, catalog: str) -> dict | None:
    g.ensure_addon()
    from resources.lib.simkl.api_normalize import api_detail_to_sync_dict
    from resources.lib.simkl.related import _fetch_detail

    detail = _fetch_detail(catalog, int(simkl_id))
    if not detail:
        return None
    resolved_catalog = resolve_item_catalog(detail, catalog)
    sync = api_detail_to_sync_dict(detail, resolved_catalog)
    if sync:
        sync["catalog"] = resolved_catalog
    return sync


def _sync_dict_from_db_row(row: dict, catalog: str) -> dict | None:
    """Rebuild a sync dict from a movies/shows SQL row (no API)."""
    info = row.get("info")
    if not isinstance(info, dict) or not info:
        return None
    art = row.get("art")
    if not isinstance(art, dict):
        art = {}
    simkl_id = int(row["simkl_id"])
    sync = {
        "simkl_id": simkl_id,
        "catalog": catalog,
        "simkl_object": {"info": copy.deepcopy(info), "art": copy.deepcopy(art)},
    }
    for ext in ("tmdb_id", "tvdb_id", "imdb_id"):
        if row.get(ext) is not None:
            sync[ext] = row[ext]
    return sync


def _batch_load_sync_cache(items: list[dict]) -> dict[int, dict]:
    """Load display-ready sync rows from session cache, then simkl_sync.db for misses."""
    from resources.lib.database.sync_meta_cache import SyncMetaCache

    movie_ids: list[int] = []
    show_ids: list[int] = []
    catalog_by_id: dict[int, str] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        simkl_id = item.get("simkl_id")
        catalog = item.get("catalog")
        if simkl_id is None or catalog not in ("movie", "tv", "anime"):
            continue
        sid = int(simkl_id)
        catalog_by_id[sid] = catalog
        if catalog == "movie":
            movie_ids.append(sid)
        else:
            show_ids.append(sid)

    meta_cache = SyncMetaCache()
    cache: dict[int, dict] = {}

    movie_hits, movie_misses = meta_cache.partition_complete("movie", movie_ids)
    show_hits, show_misses = meta_cache.partition_complete("show", show_ids)

    for sid, row in movie_hits.items():
        sync = _sync_dict_from_db_row(row, "movie")
        if sync:
            cache[sid] = sync
    for sid, row in show_hits.items():
        catalog = catalog_by_id.get(sid) or "tv"
        sync = _sync_dict_from_db_row(row, catalog)
        if sync:
            cache[sid] = sync

    if movie_misses:
        from resources.lib.database.simkl_sync.movies import SimklSyncDatabase as MoviesDB

        placeholders = ",".join("?" * len(movie_misses))
        rows = MoviesDB().fetchall(
            f"SELECT simkl_id, info, art, tmdb_id, tvdb_id, imdb_id FROM movies WHERE simkl_id IN ({placeholders})",
            tuple(movie_misses),
        )
        meta_cache.set_many_rows("movie", rows or [])
        for row in rows or []:
            sync = _sync_dict_from_db_row(row, "movie")
            if sync:
                cache[int(row["simkl_id"])] = sync

    if show_misses:
        from resources.lib.database.simkl_sync.shows import SimklSyncDatabase as ShowsDB

        shows_db = ShowsDB()
        placeholders = ",".join("?" * len(show_misses))
        rows = shows_db.fetchall(
            f"SELECT simkl_id, info, art, tmdb_id, tvdb_id, imdb_id FROM shows WHERE simkl_id IN ({placeholders})",
            tuple(show_misses),
        )
        meta_cache.set_many_rows("show", rows or [])
        for row in rows or []:
            sid = int(row["simkl_id"])
            catalog = catalog_by_id.get(sid) or shows_db.show_catalog(sid)
            sync = _sync_dict_from_db_row(row, catalog)
            if sync:
                cache[sid] = sync

    return cache


def _is_anime_info(info: dict) -> bool:
    if not isinstance(info, dict):
        return False
    if info.get("catalog") == "anime":
        return True
    if info.get("mal_id"):
        return True
    ids = info.get("ids")
    return isinstance(ids, dict) and ids.get("mal") is not None


def _anime_title_fields_missing(info: dict) -> bool:
    """True when we still need Simkl detail to populate English / Romaji title slots."""
    if not _is_anime_info(info):
        return False
    romaji = info.get("title_romaji") or info.get("title")
    english = info.get("title_en")
    return not english or not romaji


def gapfill_anime_title_rows(rows: list) -> list:
    """Fetch Simkl anime detail for rows missing title_en/title_romaji (CDN JSON is often Romaji-only)."""
    if not rows:
        return rows

    from resources.lib.simkl.field_map import enrich_info_from_simkl

    for row in rows:
        if not isinstance(row, dict):
            continue
        info = row.get("info")
        if not isinstance(info, dict) or not _anime_title_fields_missing(info):
            continue
        simkl_id = row.get("simkl_id") or info.get("simkl_id")
        if simkl_id is None:
            continue
        detail = _simkl_detail_sync_dict(int(simkl_id), "anime")
        if not detail:
            continue
        source_info = (detail.get("simkl_object") or {}).get("info") or {}
        enrich_info_from_simkl(
            info,
            source_info,
            catalog=info.get("catalog") or "anime",
            mediatype=info.get("mediatype"),
        )
    return rows


def _merge_sync_item_rows(base: dict, overlay: dict) -> dict:
    """Merge a thin list row into a richer cached sync dict."""
    result = copy.deepcopy(base)
    overlay_blob = overlay.get("simkl_object") or {}
    overlay_info = overlay_blob.get("info") or {}
    overlay_art = overlay_blob.get("art") or {}
    dst_blob = result.setdefault("simkl_object", {})
    dst_info = dst_blob.setdefault("info", {})
    dst_art = dst_blob.setdefault("art", {})

    for key, val in overlay_info.items():
        if val is not None and val != "" and not dst_info.get(key):
            dst_info[key] = val
    for key, val in overlay_art.items():
        if val and not dst_art.get(key):
            dst_art[key] = val
    for ext_key in ("tmdb_id", "imdb_id", "tvdb_id", "mal_id"):
        if overlay.get(ext_key) and not result.get(ext_key):
            result[ext_key] = overlay[ext_key]
        if overlay_info.get(ext_key) and not dst_info.get(ext_key):
            dst_info[ext_key] = overlay_info[ext_key]
    if overlay.get("catalog") and not result.get("catalog"):
        result["catalog"] = overlay["catalog"]
    return result


def _apply_overlay_fields(src: dict, dst: dict) -> dict:
    """Preserve search/browse-only fields from the incoming row."""
    for key in ("_credit_role",):
        if key in src:
            dst[key] = src[key]

    src_info = (src.get("simkl_object") or {}).get("info") or {}
    dst_info = dst.setdefault("simkl_object", {}).setdefault("info", {})
    for key in ("score", "rank"):
        if src_info.get(key) is not None:
            dst_info[key] = src_info[key]
    if src.get("tmdb_id") is not None:
        dst["tmdb_id"] = src["tmdb_id"]
        dst_info.setdefault("tmdb_id", src["tmdb_id"])
    return dst


def _merge_discover_db_gaps(item: dict) -> dict:
    """Gap-fill from cached Simkl CDN discover rows when Simkl detail is thin."""
    simkl_id = item.get("simkl_id")
    catalog = item.get("catalog")
    if simkl_id is None or catalog not in ("movie", "tv", "anime"):
        return item

    from resources.lib.discover.cdn_store import get_row

    row = get_row(catalog, int(simkl_id))
    if not row:
        return item

    from resources.lib.discover.normalize import db_row_to_sync_dict

    discover_sync = db_row_to_sync_dict(row, catalog)
    if not discover_sync:
        return item

    return _merge_sync_item_rows(item, discover_sync)


def _sync_row_display_ready(item: dict) -> bool:
    """True when a row already has enough data to render a list item."""
    if not isinstance(item, dict):
        return False
    blob = item.get("simkl_object") or {}
    info = blob.get("info") if isinstance(blob.get("info"), dict) else {}
    art = blob.get("art") if isinstance(blob.get("art"), dict) else {}
    title = info.get("title") or item.get("title")
    poster = art.get("poster") or art.get("thumb") or info.get("poster")
    plot = info.get("plot") or info.get("overview")
    return bool(title and poster and plot)


def _enrich_sync_item(
    item: dict,
    *,
    sync_cache: dict[int, dict] | None = None,
) -> dict:
    """Hydrate from sync DB, gap-fill from discover CDN, then API only when still thin."""
    if not isinstance(item, dict):
        return item

    simkl_id = item.get("simkl_id")
    catalog = item.get("catalog")
    if simkl_id is None or catalog not in ("movie", "tv", "anime"):
        return item

    sid = int(simkl_id)
    working = copy.deepcopy(item)
    cached = (sync_cache or {}).get(sid)
    if cached:
        working = _merge_sync_item_rows(cached, working)
    working = _merge_discover_db_gaps(working)

    blob_info = (working.get("simkl_object") or {}).get("info") or {}
    if _sync_row_display_ready(working) and not _anime_title_fields_missing(blob_info):
        if cached:
            g.log(f"Simkl enrich skipped API (sync cache): {sid}", "debug")
        return _apply_overlay_fields(item, working)

    from resources.lib.database.sync_meta_cache import SyncMetaCache

    meta_cache = SyncMetaCache()
    if meta_cache.is_enrich_miss(catalog, sid):
        return _apply_overlay_fields(item, working)

    enriched = _simkl_detail_sync_dict(sid, catalog)
    if not enriched:
        meta_cache.mark_enrich_miss(catalog, sid)
        return _apply_overlay_fields(item, working)

    meta_cache.clear_enrich_miss(catalog, sid)

    enriched = copy.deepcopy(enriched)
    enriched = _merge_discover_db_gaps(enriched)
    return _apply_overlay_fields(item, enriched)


def enrich_sync_item_detail(item: dict) -> dict:
    """Upgrade a thin search/browse row using GET /movies|tv|anime/{simkl_id} when needed."""
    return _enrich_sync_item(item)


def enrich_sync_item_fast(item: dict) -> dict:
    """Gap-fill from local DB; only hit Simkl detail API when the row is still thin."""
    return _enrich_sync_item(item)


def enrich_sync_items(
    items: list[dict],
    *,
    parallel: bool | None = None,
    fast: bool = False,
) -> list[dict]:
    """Fetch Simkl detail records for a page of sync dicts."""
    if not items:
        return []

    rows = [item for item in items if isinstance(item, dict)]
    if not rows:
        return []

    sync_cache = _batch_load_sync_cache(rows)
    enricher = partial(_enrich_sync_item, sync_cache=sync_cache)

    def _enrich_row(row: dict) -> dict:
        g.ensure_addon()
        return enricher(row)

    use_parallel = parallel
    if use_parallel is None:
        use_parallel = g.get_bool_setting("general.fastMenus", True) and len(rows) > 1

    if not use_parallel or len(rows) == 1:
        enriched = [_enrich_row(row) for row in rows]
    else:
        from resources.lib.common.thread_pool import ThreadPool

        pool = ThreadPool()
        try:
            enriched = list(pool.executor.map(_enrich_row, rows))
        finally:
            pool.executor.shutdown(wait=True)

    enriched = [row for row in enriched if isinstance(row, dict)]
    if enriched:
        mode = "fast" if fast else "detail"
        g.log(f"Simkl {mode} enrich: {len(enriched)}/{len(rows)} items", "debug")
    return enriched

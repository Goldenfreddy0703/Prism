"""POV-style browse page resolve: local hydrate, parallel gap-fill, no blocking persist."""
from __future__ import annotations

import time
from typing import Any

from resources.lib.browse.page_payload import (
    _catalog_media_type,
    _merge_enriched_by_id,
    _normalize_thin_items,
    _paint_profile_for_payload,
    merge_discover_gaps_batch,
)
from resources.lib.modules.globals import g
from resources.lib.simkl.detail_gates import simkl_detail_needed


def _partition_needs_detail(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    from resources.lib.simkl.enrich import simkl_detail_plot_missing

    needs: list[dict] = []
    ready: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if simkl_detail_needed(row) or simkl_detail_plot_missing(row):
            needs.append(row)
        else:
            ready.append(row)
    return needs, ready


def _merge_provider_gaps(
    catalog: str,
    rows: list[dict],
    *,
    profile: str,
) -> tuple[list[dict], dict]:
    from resources.lib.meta.paint_cache import coalesce_page_rows_paint_info
    from resources.lib.meta.paint_complete import gap_scope_for_profile, partition_paint_rows
    from resources.lib.modules.metadataHandler import MetadataHandler

    media_type = _catalog_media_type(catalog)
    rows = coalesce_page_rows_paint_info(catalog, rows)
    handler = MetadataHandler()
    _complete, incomplete = partition_paint_rows(rows, media_type, profile=profile, handler=handler)
    stats: dict[str, Any] = {
        "complete": len(_complete),
        "incomplete": len(incomplete),
        "cast_batch": 0,
        "art_fetch": 0,
    }
    if not incomplete:
        return rows, stats

    gap_scope = gap_scope_for_profile(profile)
    prepared, _refs, prep_stats = handler.prepare_list_rows_for_paint(
        incomplete,
        media_type,
        profile=profile,
        gap_scope=gap_scope,
    )
    stats["cast_batch"] = int(prep_stats.get("cast_batch", 0))
    stats["art_fetch"] = int(prep_stats.get("art_fetch", 0))
    by_id = {
        int(row["simkl_id"]): row
        for row in (prepared or [])
        if isinstance(row, dict) and row.get("simkl_id") is not None
    }
    merged: list[dict] = []
    for row in rows:
        if isinstance(row, dict) and row.get("simkl_id") is not None:
            sid = int(row["simkl_id"])
            merged.append(by_id.get(sid, row))
        else:
            merged.append(row)
    return coalesce_page_rows_paint_info(catalog, merged), stats


def overlay_bookmark_fields(resolved: list[dict], sql_rows: list[dict]) -> list[dict]:
    """Preserve resume/bookmark columns from simkl_sync SQL reads."""
    by_id = {
        int(row["simkl_id"]): row
        for row in (sql_rows or [])
        if isinstance(row, dict) and row.get("simkl_id") is not None
    }
    if not by_id:
        return resolved
    out: list[dict] = []
    for row in resolved:
        if not isinstance(row, dict) or row.get("simkl_id") is None:
            out.append(row)
            continue
        sid = int(row["simkl_id"])
        sql = by_id.get(sid)
        if not sql:
            out.append(row)
            continue
        merged = dict(row)
        for key in ("resume_time", "percent_played", "play_count", "user_rating", "watched"):
            if sql.get(key) is not None and merged.get(key) is None:
                merged[key] = sql[key]
        out.append(merged)
    return out


def resolve_browse_page_rows(
    catalog: str,
    thin_rows: list[dict],
    *,
    profile: str,
    source: str = "",
    sql_rows: list[dict] | None = None,
) -> list[dict]:
    """Seren sync warmup for legacy resolve callers."""
    from resources.lib.meta.paint_cache import coalesce_page_rows_paint_info
    from resources.lib.pipeline.sync_page_warmup import warmup_sync_page_refs
    from resources.lib.simkl.enrich import hydrate_sync_items_local

    rows = _normalize_thin_items(catalog, thin_rows)
    if not rows:
        return []
    refs = [{"simkl_id": row.get("simkl_id")} for row in rows if isinstance(row, dict) and row.get("simkl_id")]
    warmup_sync_page_refs(catalog, refs)
    rows = hydrate_sync_items_local(rows)
    rows = coalesce_page_rows_paint_info(catalog, rows)
    if sql_rows:
        rows = overlay_bookmark_fields(rows, sql_rows)
    return rows


def resolve_mixed_browse_rows(
    sync_items: list[dict],
    *,
    profile: str,
    source: str = "",
    sql_rows: list[dict] | None = None,
) -> list[dict]:
    from resources.lib.pipeline.sync_page_warmup import warmup_sync_mixed_refs
    from resources.lib.simkl.media_ref import partition_by_catalog

    warmup_sync_mixed_refs(sync_items)
    movies, tv, anime = partition_by_catalog(sync_items)
    by_id: dict[int, dict] = {}
    for catalog, group in (("movie", movies), ("tv", tv), ("anime", anime)):
        if not group:
            continue
        resolved = resolve_browse_page_rows(
            catalog,
            group,
            profile=profile,
            source=source or profile,
        )
        for row in resolved:
            if isinstance(row, dict) and row.get("simkl_id") is not None:
                by_id[int(row["simkl_id"])] = row
    ordered: list[dict] = []
    for item in sync_items:
        if isinstance(item, dict) and item.get("simkl_id") is not None:
            sid = int(item["simkl_id"])
            ordered.append(by_id.get(sid, item))
        else:
            ordered.append(item)
    if sql_rows:
        ordered = overlay_bookmark_fields(ordered, sql_rows)
    return ordered


def try_resolve_browse_page_stamp_fast(
    catalog: str,
    thin_rows: list[dict],
    refs: list[dict],
    *,
    profile: str,
    source: str = "",
    sql_rows: list[dict] | None = None,
) -> tuple[list[dict] | None, str]:
    """POV-style warm open: overlay trusted display_meta only (no Simkl detail / provider HTTP)."""
    from resources.lib.meta.paint_complete import rows_page_menu_ready
    from resources.lib.meta.paint_stamp import page_refs_display_stamped
    from resources.lib.simkl.enrich import hydrate_sync_items_local

    if not refs or not page_refs_display_stamped(refs):
        return None, ""

    started = time.time()
    rows = _normalize_thin_items(catalog, thin_rows)
    if not rows:
        return None, ""

    paint_profile = profile or _paint_profile_for_payload(source, catalog)
    rows = hydrate_sync_items_local(rows)
    from resources.lib.meta.paint_cache import (
        coalesce_page_rows_paint_info,
        overlay_display_meta_stamps,
        overlay_stamped_display_meta_page,
    )

    rows = coalesce_page_rows_paint_info(catalog, rows)
    rows = overlay_stamped_display_meta_page(catalog, rows)
    rows = overlay_display_meta_stamps(rows)
    rows = coalesce_page_rows_paint_info(catalog, rows)
    if sql_rows:
        rows = overlay_bookmark_fields(rows, sql_rows)

    if not rows_page_menu_ready(rows, profile=paint_profile):
        return None, ""

    total_ms = int((time.time() - started) * 1000)
    g.log(
        f"Browse resolve: path=stamp_fast source={source} catalog={catalog} profile={paint_profile} "
        f"rows={len(rows)} total_ms={total_ms}",
        "debug",
    )
    return rows, "browse_stamp"


def try_resolve_mixed_stamp_fast(
    sync_items: list[dict],
    refs: list[dict],
    *,
    profile: str,
    source: str = "",
    sql_rows: list[dict] | None = None,
) -> tuple[list[dict] | None, str]:
    """Warm open for mixed movie/tv/anime pages (actor, related, etc.)."""
    from resources.lib.meta.paint_complete import rows_page_menu_ready
    from resources.lib.meta.paint_stamp import page_refs_display_stamped
    from resources.lib.simkl.enrich import hydrate_sync_items_local
    from resources.lib.simkl.media_ref import partition_by_catalog

    if not refs or not sync_items or not page_refs_display_stamped(refs):
        return None, ""

    paint_profile = profile or _paint_profile_for_payload(source, "mixed")
    started = time.time()
    from resources.lib.meta.paint_cache import (
        coalesce_page_rows_paint_info,
        overlay_display_meta_stamps,
        overlay_stamped_display_meta_page,
    )

    movies, tv, anime = partition_by_catalog(sync_items)
    by_id: dict[int, dict] = {}
    for catalog, group in (("movie", movies), ("tv", tv), ("anime", anime)):
        if not group:
            continue
        rows = _normalize_thin_items(catalog, group)
        if not rows:
            continue
        rows = hydrate_sync_items_local(rows)
        rows = coalesce_page_rows_paint_info(catalog, rows)
        rows = overlay_stamped_display_meta_page(catalog, rows)
        rows = overlay_display_meta_stamps(rows)
        rows = coalesce_page_rows_paint_info(catalog, rows)
        for row in rows:
            if isinstance(row, dict) and row.get("simkl_id") is not None:
                by_id[int(row["simkl_id"])] = row

    ordered: list[dict] = []
    for item in sync_items:
        if isinstance(item, dict) and item.get("simkl_id") is not None:
            sid = int(item["simkl_id"])
            ordered.append(by_id.get(sid, item))
        else:
            ordered.append(item)

    if sql_rows:
        ordered = overlay_bookmark_fields(ordered, sql_rows)

    if not rows_page_menu_ready(ordered, profile=paint_profile):
        return None, ""

    total_ms = int((time.time() - started) * 1000)
    g.log(
        f"Browse resolve: path=stamp_fast source={source} catalog=mixed profile={paint_profile} "
        f"rows={len(ordered)} total_ms={total_ms}",
        "debug",
    )
    return ordered, "browse_stamp"


def prefetch_resolved_page_rows(
    catalog: str,
    thin_rows: list[dict],
    *,
    list_id: str,
    page: int,
    profile: str,
    source: str,
    namespace: str,
) -> list[dict]:
    """Background prefetch: Seren sync update for the next page."""
    from resources.lib.pipeline.sync_page_warmup import warmup_sync_page_refs

    refs = [{"simkl_id": row.get("simkl_id")} for row in (thin_rows or []) if isinstance(row, dict)]
    warmup_sync_page_refs(catalog, refs)
    from resources.lib.meta.list_pipeline import _page_list_id, get_list_store
    from resources.lib.simkl.media_ref import sync_db_rows_for_refs

    resolved = sync_db_rows_for_refs(catalog, refs)
    get_list_store(namespace).remember_items(catalog, _page_list_id(list_id, page), resolved)
    return resolved

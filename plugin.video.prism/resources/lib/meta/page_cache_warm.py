"""Batch display_meta + provider DB overlay before Simkl detail HTTP (Fen metacache.fetch pattern)."""
from __future__ import annotations

from typing import Any

from resources.lib.meta.paint_cache import (
    coalesce_page_rows_paint_info,
    overlay_display_meta_stamps,
    overlay_provider_cached_meta_page,
    overlay_stamped_display_meta_page,
)
from resources.lib.meta.paint_complete import partition_paint_rows


def _rows_need_sync_batch(rows: list[dict[str, Any]]) -> bool:
    from resources.lib.database.sync_meta_cache import row_has_plot_meta

    checked = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        checked += 1
        if checked > 5:
            break
        if not row_has_plot_meta(row):
            return True
    return False


def _merge_sync_batch_rows(
    catalog: str,
    refs: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One batched simkl_sync read for the page ref set (Seren get_*_list IN query)."""
    if not refs or not rows:
        return rows
    from resources.lib.database.session import ensure_browse_db_read_mode
    from resources.lib.simkl.media_ref import sync_db_rows_for_refs

    ensure_browse_db_read_mode()
    synced = sync_db_rows_for_refs(catalog, refs)
    if not synced:
        return rows
    by_id = {
        int(row["simkl_id"]): row
        for row in synced
        if isinstance(row, dict) and row.get("simkl_id") is not None
    }
    if not by_id:
        return rows
    merged: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict) and row.get("simkl_id") is not None:
            sid = int(row["simkl_id"])
            merged.append(by_id.get(sid, row))
        else:
            merged.append(row)
    return merged


def warm_page_rows_from_cache(
    catalog: str,
    rows: list[dict[str, Any]],
    *,
    profile: str = "browse",
    refs: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """
    Merge stamped display_meta and cached provider blobs into sync rows.
    Returns (rows, complete_count, total_count) for menu_perf logging.
    """
    if not rows:
        return rows, 0, 0

    if refs and _rows_need_sync_batch(rows):
        rows = _merge_sync_batch_rows(catalog, refs, rows)

    rows = coalesce_page_rows_paint_info(catalog, rows)
    rows = overlay_stamped_display_meta_page(catalog, rows)
    rows = overlay_display_meta_stamps(rows)
    rows = overlay_provider_cached_meta_page(catalog, rows)
    rows = coalesce_page_rows_paint_info(catalog, rows)

    paint_media = "movie" if catalog == "movie" else "tvshow"
    movies = [row for row in rows if isinstance(row, dict) and row.get("catalog") == "movie"]
    tv_rows = [row for row in rows if isinstance(row, dict) and row.get("catalog") == "tv"]
    anime_rows = [row for row in rows if isinstance(row, dict) and row.get("catalog") == "anime"]
    total = len([row for row in rows if isinstance(row, dict)])
    complete = 0
    if movies:
        done, _inc = partition_paint_rows(movies, "movie", profile=profile)
        complete += len(done)
    if tv_rows:
        done, _inc = partition_paint_rows(tv_rows, "tvshow", profile=profile)
        complete += len(done)
    if anime_rows:
        done, _inc = partition_paint_rows(anime_rows, "anime", profile=profile)
        complete += len(done)
    if not movies and not tv_rows and not anime_rows and rows:
        done, _inc = partition_paint_rows(rows, paint_media, profile=profile)
        complete = len(done)
    return rows, complete, total

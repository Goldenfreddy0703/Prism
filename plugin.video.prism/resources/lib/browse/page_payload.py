"""Browse list gap-fill helpers (CDN/catalog batch merge)."""
from __future__ import annotations

def rows_page_list_ready(rows: list[dict]) -> bool:
    """True when every row has title, poster, and plot for menu paint (no cast/art)."""
    from resources.lib.simkl.enrich import (
        _row_has_list_paint_fields,
        simkl_detail_plot_missing,
    )

    if not rows:
        return True
    for row in rows:
        if not isinstance(row, dict):
            return False
        if not _row_has_list_paint_fields(row):
            return False
        if simkl_detail_plot_missing(row):
            return False
    return True


def merge_discover_gaps_batch(catalog: str, items: list[dict]) -> list[dict]:
    """Batch catalog_items + CDN gap-fill (vectorized _merge_discover_db_gaps)."""
    from resources.lib.discover.catalog_store import get_items_batch
    from resources.lib.discover.cdn_store import get_rows_by_ids
    from resources.lib.discover.normalize import db_row_to_sync_dict
    from resources.lib.simkl.enrich import (
        _apply_overlay_fields,
        _merge_sync_item_rows,
        _row_needs_discover_gapfill,
    )

    if not items:
        return []

    simkl_ids: list[int] = []
    for item in items:
        if isinstance(item, dict) and item.get("simkl_id") is not None:
            simkl_ids.append(int(item["simkl_id"]))
    catalog_batch = get_items_batch(catalog, simkl_ids) if simkl_ids else {}
    cdn_batch = get_rows_by_ids(catalog, simkl_ids) if simkl_ids else {}

    merged: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict) or raw.get("simkl_id") is None:
            continue
        working = dict(raw)
        working.setdefault("catalog", catalog)
        sid = int(working["simkl_id"])

        cached = catalog_batch.get(sid)
        if cached:
            working = _merge_sync_item_rows(working, cached)

        if _row_needs_discover_gapfill(working):
            cdn_row = cdn_batch.get(sid)
            if cdn_row:
                discover_sync = db_row_to_sync_dict(cdn_row, catalog)
                if discover_sync:
                    working = _merge_sync_item_rows(working, discover_sync)

        merged.append(_apply_overlay_fields(raw, working))
    return merged


def _normalize_thin_items(catalog: str, items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict) or item.get("simkl_id") is None:
            continue
        row = dict(item)
        row.setdefault("catalog", item.get("catalog") or catalog)
        out.append(row)
    return out


def _paint_profile_for_payload(source: str, catalog: str) -> str:
    s = (source or "").lower()
    if s.startswith("search"):
        return "search"
    if (
        "genre_slug" in s
        or "tmdb_genre" in s
        or "tenrai_genre" in s
        or s.startswith("genre")
    ):
        return "genre"
    if catalog == "anime":
        return "browse"
    return "browse"


def _catalog_media_type(catalog: str) -> str:
    return "movie" if catalog == "movie" else "tvshow"


def _merge_enriched_by_id(rows: list[dict], enriched: list[dict]) -> list[dict]:
    by_id = {
        int(row["simkl_id"]): row
        for row in enriched
        if isinstance(row, dict) and row.get("simkl_id") is not None
    }
    if not by_id:
        return rows
    merged: list[dict] = []
    for row in rows:
        if isinstance(row, dict) and row.get("simkl_id") is not None:
            sid = int(row["simkl_id"])
            merged.append(by_id.get(sid, row))
        else:
            merged.append(row)
    return merged

"""CatalogPagePipeline row resolution: SQL → browse resolver → paint."""
from __future__ import annotations

from resources.lib.meta.list_paint import (
    _seren_sync_resolve_page_rows,
    _seren_sync_resolve_page_rows_time_to_list,
)


def resolve_catalog_page_rows(
    catalog: str,
    refs: list[dict],
    rows: list[dict],
    profile: str,
    *,
    genre_fast_open: bool = False,
    catalog_fast_open: bool = False,
    paint_overrides: dict | None = None,
) -> tuple[list[dict], str]:
    overrides = paint_overrides or {}
    thin = overrides.get("thin_payload_rows")
    if thin is None:
        thin = overrides.get("payload_rows")
    source = str(overrides.get("browse_source") or "")

    if overrides.get("catalog_pipeline") and thin is not None:
        from resources.lib.browse.browse_paint_resolver import (
            resolve_browse_page_rows,
            resolve_mixed_browse_rows,
            try_resolve_browse_page_stamp_fast,
            try_resolve_mixed_stamp_fast,
        )
        from resources.lib.meta.list_paint import _order_rows_by_refs

        if overrides.get("mixed_list"):
            stamped, stamp_path = try_resolve_mixed_stamp_fast(
                thin,
                refs,
                profile=profile,
                source=source,
                sql_rows=rows,
            )
            if stamped is not None:
                return stamped, stamp_path
            resolved = resolve_mixed_browse_rows(
                thin,
                profile=profile,
                source=source or profile,
                sql_rows=rows,
            )
            return resolved, "browse_resolve"

        ordered = _order_rows_by_refs(catalog, refs, thin)
        stamped, stamp_path = try_resolve_browse_page_stamp_fast(
            catalog,
            ordered,
            refs,
            profile=profile,
            source=source,
            sql_rows=rows,
        )
        if stamped is not None:
            return stamped, stamp_path
        resolved = resolve_browse_page_rows(
            catalog,
            ordered,
            profile=profile,
            source=source,
            sql_rows=rows,
        )
        return resolved, "browse_resolve"

    if catalog_fast_open or genre_fast_open:
        return _seren_sync_resolve_page_rows_time_to_list(
            catalog,
            refs,
            rows,
            profile,
            paint_overrides=paint_overrides,
        )
    return _seren_sync_resolve_page_rows(catalog, refs, rows, profile)

"""Legacy browse materialize entry — Seren sync warmup only."""
from __future__ import annotations

from typing import Any

from resources.lib.modules.globals import g


def _order_like_items(items: list[dict], rows: list[dict]) -> list[dict]:
    by_id = {
        int(row["simkl_id"]): row
        for row in (rows or [])
        if isinstance(row, dict) and row.get("simkl_id") is not None
    }
    if not by_id:
        return list(rows or [])
    ordered: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sid = item.get("simkl_id")
        if sid is None:
            ordered.append(item)
            continue
        sid_int = int(sid)
        ordered.append(by_id.get(sid_int, item))
    if len(ordered) >= len(by_id):
        return ordered
    seen = {int(r["simkl_id"]) for r in ordered if isinstance(r, dict) and r.get("simkl_id") is not None}
    for sid, row in by_id.items():
        if sid not in seen:
            ordered.append(row)
    return ordered


def _seed_rows_to_sync(catalog: str, rows: list[dict], *, mixed: bool) -> None:
    from resources.lib.meta.list_pipeline import seed_browse_page
    from resources.lib.simkl.media_ref import partition_by_catalog

    if not rows:
        return
    if mixed:
        movies, tv, anime = partition_by_catalog(rows)
        for cat, group in (("movie", movies), ("tv", tv), ("anime", anime)):
            if group:
                seed_browse_page(cat, group)
        return
    seed_browse_page(catalog, rows)


def materialize_browse_page(
    catalog: str,
    items: list[dict],
    *,
    profile: str | None = None,
    source: str = "",
    mixed: bool = False,
    list_id: str | None = None,
    page: int | None = None,
    skip_resolve_if_ready: bool = True,
) -> list[dict]:
    """Warm simkl_sync rows via Seren _update_* (no blocking resolve pipeline)."""
    from resources.lib.pipeline.sync_page_warmup import warmup_sync_mixed_refs, warmup_sync_page_refs
    from resources.lib.simkl.enrich import hydrate_sync_items_local

    if not items:
        return []

    refs = [{"simkl_id": row.get("simkl_id")} for row in items if isinstance(row, dict) and row.get("simkl_id")]
    if mixed:
        warmup_sync_mixed_refs(items)
    else:
        warmup_sync_page_refs(catalog, refs)

    hydrated = hydrate_sync_items_local([dict(row) for row in items if isinstance(row, dict)])
    rows = _order_like_items(items, hydrated)
    _seed_rows_to_sync(catalog, rows, mixed=mixed)
    g.log(
        f"Browse materialize: path=sync_update source={source} catalog={catalog} mixed={mixed} rows={len(rows)}",
        "debug",
    )
    return rows


def materialize_episode_page(*args, **kwargs) -> list[dict]:
    """Episode drilldown pages use Simkl-local paint only."""
    items = kwargs.get("items") or (args[1] if len(args) > 1 else [])
    return list(items or [])

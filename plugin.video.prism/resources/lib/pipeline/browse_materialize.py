"""Foreground page materialize: menu-ready rows in simkl_sync before Seren menu paint."""
from __future__ import annotations

import time
from typing import Any

from resources.lib.modules.globals import g

_MATERIALIZED_RAM: dict[tuple[str, str, str, int], tuple[float, list[dict]]] = {}
_MATERIALIZED_TTL = 900.0


def _paint_profile(source: str, catalog: str, profile: str | None) -> str:
    if profile:
        return str(profile)
    from resources.lib.browse.page_payload import _paint_profile_for_payload

    return _paint_profile_for_payload(source, catalog)


def _materialize_cache_key(
    source: str,
    catalog: str,
    list_id: str | None,
    page: int | None,
) -> tuple[str, str, str, int]:
    return (str(source or ""), str(catalog or ""), str(list_id or ""), max(1, int(page or 1)))


def _read_materialized_cache(key: tuple[str, str, str, int]) -> list[dict] | None:
    entry = _MATERIALIZED_RAM.get(key)
    if not entry:
        return None
    ts, rows = entry
    if time.time() - ts > _MATERIALIZED_TTL:
        _MATERIALIZED_RAM.pop(key, None)
        return None
    return [dict(row) for row in rows if isinstance(row, dict)]


def _write_materialized_cache(key: tuple[str, str, str, int], rows: list[dict]) -> None:
    if not rows:
        return
    _MATERIALIZED_RAM[key] = (time.time(), [dict(row) for row in rows if isinstance(row, dict)])


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


def _stamp_rows(catalog: str, rows: list[dict], *, profile: str, mixed: bool) -> None:
    from resources.lib.meta.page_materialize import stamp_page_rows_to_display_meta
    from resources.lib.simkl.media_ref import partition_by_catalog

    if not rows:
        return
    if mixed:
        movies, tv, anime = partition_by_catalog(rows)
        for cat, group in (("movie", movies), ("tv", tv), ("anime", anime)):
            if group:
                stamp_page_rows_to_display_meta(cat, group, profile=profile)
        return
    stamp_page_rows_to_display_meta(catalog, rows, profile=profile)


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
    """
    Ensure visible page rows are menu-ready (clearlogo + plot + cast), persist to simkl_sync,
    and stamp display_meta. Returns ordered rows matching ``items``.
    """
    from resources.lib.meta.paint_complete import rows_page_menu_ready
    from resources.lib.simkl.enrich import hydrate_sync_items_local

    if not items:
        return []

    paint_profile = _paint_profile(source, catalog, profile)
    cache_key = _materialize_cache_key(source, catalog, list_id, page or g.PAGE)
    cached = _read_materialized_cache(cache_key)
    if cached and rows_page_menu_ready(cached, profile=paint_profile):
        _seed_rows_to_sync(catalog, cached, mixed=mixed)
        return _order_like_items(items, cached)

    if g.PLUGIN_HANDLE > 0:
        from resources.lib.net.request_policy import policy_from_settings

        policy_from_settings().reset_menu_budget()

    started = time.time()
    hydrated = hydrate_sync_items_local([dict(row) for row in items if isinstance(row, dict)])
    if skip_resolve_if_ready and rows_page_menu_ready(hydrated, profile=paint_profile):
        rows = _order_like_items(items, hydrated)
        _seed_rows_to_sync(catalog, rows, mixed=mixed)
        _stamp_rows(catalog, rows, profile=paint_profile, mixed=mixed)
        _write_materialized_cache(cache_key, rows)
        g.log(
            f"Browse materialize: path=ready source={source} catalog={catalog} mixed={mixed} "
            f"rows={len(rows)} ms={int((time.time() - started) * 1000)}",
            "debug",
        )
        return rows

    if mixed:
        from resources.lib.browse.browse_paint_resolver import resolve_mixed_browse_rows

        rows = resolve_mixed_browse_rows(
            items,
            profile=paint_profile,
            source=source or paint_profile,
        )
    else:
        from resources.lib.browse.browse_paint_resolver import resolve_browse_page_rows

        rows = resolve_browse_page_rows(
            catalog,
            items,
            profile=paint_profile,
            source=source or paint_profile,
        )

    rows = _order_like_items(items, rows)
    _seed_rows_to_sync(catalog, rows, mixed=mixed)
    _stamp_rows(catalog, rows, profile=paint_profile, mixed=mixed)
    _write_materialized_cache(cache_key, rows)
    g.log(
        f"Browse materialize: path=resolve source={source} catalog={catalog} mixed={mixed} "
        f"rows={len(rows)} ms={int((time.time() - started) * 1000)}",
        "debug",
    )
    return rows


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


def materialize_episode_page(
    catalog: str,
    episode_rows: list[dict],
    *,
    profile: str = "library_episodes",
    library_paint: bool = False,
) -> list[dict]:
    """Seed parent shows for episode menus; paint happens in render_catalog_episodes."""
    from resources.lib.meta.list_paint import (
        peek_episode_page_cache,
        prefetch_episode_parent_simkl_detail,
        upsert_episode_parent_shows,
    )
    from resources.lib.meta.paint_complete import rows_page_paint_ready

    if not episode_rows:
        return []

    if peek_episode_page_cache(catalog, episode_rows, paint_profile=profile) is not None:
        return episode_rows

    if rows_page_paint_ready(episode_rows, profile=profile):
        return episode_rows

    upsert_episode_parent_shows(episode_rows, catalog)
    if library_paint:
        prefetch_episode_parent_simkl_detail(episode_rows, catalog)
    return episode_rows

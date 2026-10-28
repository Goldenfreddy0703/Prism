"""Paint-first list pipeline: cache → ListItem → background enrich."""
from __future__ import annotations

import threading
import time
from typing import Any

from resources.lib.simkl.menu_helpers import list_filter_kwargs

# Browse lists use Seren-style simkl_sync milling (foreground provider update on cold pages).
BROWSE_LIST_KWARGS = {
    **list_filter_kwargs(),
    "skip_mill": True,
    "skip_update": False,
    "sync_path": True,
}


def browse_list_kwargs(**overrides) -> dict:
    """Shared list-builder kwargs for discover, search, library, genres, actor, etc."""
    kwargs = dict(BROWSE_LIST_KWARGS)
    kwargs.setdefault("menu_cache", True)
    kwargs.pop("paint_only", None)
    kwargs.update(overrides)
    return kwargs


def _resolve_catalog_paint_flags(
    list_kwargs: dict | None,
    *,
    library_paint: bool = False,
    simkl_detail_paint: bool = False,
    prefer_catalog_payload: bool = False,
    genre_paint: bool = False,
) -> tuple[bool, bool, bool, bool]:
    """Read paint-mode flags from list kwargs when callers only pass profile_list_kwargs."""
    merged = list_kwargs or {}
    return (
        library_paint or bool(merged.get("library_paint")),
        simkl_detail_paint or bool(merged.get("simkl_detail_paint")),
        bool(merged.get("prefer_catalog_payload", prefer_catalog_payload)),
        genre_paint or bool(merged.get("genre_paint")),
    )


def attach_preloaded_catalog_paint(
    catalog: str,
    refs: list[dict],
    list_kwargs: dict | None = None,
    *,
    hide_unaired: bool | None = None,
    hide_watched: bool | None = None,
    library_paint: bool = False,
    simkl_detail_paint: bool = False,
    prefer_catalog_payload: bool = False,
    payload_rows: list[dict] | None = None,
) -> dict:
    """Resolve catalog_items rows and paint the current page before ListBuilder runs."""
    from resources.lib.discover.catalog_store import sync_items_for_refs
    from resources.lib.meta.paint_cache import paint_catalog_page_rows

    merged = dict(list_kwargs or {})
    library_paint, simkl_detail_paint, prefer_catalog_payload, genre_paint = _resolve_catalog_paint_flags(
        merged,
        library_paint=library_paint,
        simkl_detail_paint=simkl_detail_paint,
        prefer_catalog_payload=prefer_catalog_payload,
    )
    if hide_unaired is None:
        hide_unaired = bool(merged.get("hide_unaired", False))
    if hide_watched is None:
        hide_watched = bool(merged.get("hide_watched", False))

    from resources.lib.meta.menu_paint_profile import MenuPaintProfile

    enrichment_reason = str(merged.get("enrichment_reason") or "").lower()
    defer_provider_prepare = bool(library_paint)

    profile_override = merged.get("paint_profile")
    if profile_override:
        paint_profile = str(profile_override)
    elif library_paint:
        paint_profile = MenuPaintProfile.LIBRARY.value
    elif simkl_detail_paint:
        paint_profile = MenuPaintProfile.SEARCH.value
    else:
        paint_profile = MenuPaintProfile.BROWSE.value

    prefer_rich = prefer_catalog_payload or library_paint or simkl_detail_paint or genre_paint
    from resources.lib.meta.paint_cache import get_session_page_paint, page_cache_catalog, page_paint_cache_key

    cache_catalog = page_cache_catalog(catalog, refs, mixed_list=bool(merged.get("mixed_list")))
    session_key = page_paint_cache_key(
        cache_catalog,
        refs,
        hide_unaired=hide_unaired,
        hide_watched=hide_watched,
        paint_profile=paint_profile,
        prefer_rich_payload=prefer_rich,
    )
    cached_page = get_session_page_paint(session_key)
    if cached_page is not None:
        from resources.lib.meta.paint_cache import mixed_page_paint_all_complete, overlay_page_watch_fields
        from resources.lib.meta.paint_complete import rows_page_paint_ready

        cached_page = overlay_page_watch_fields(cached_page)
        merged["preloaded_paint_rows"] = cached_page
        merged["preloaded_paint_complete"] = rows_page_paint_ready(cached_page, profile=paint_profile) or mixed_page_paint_all_complete(
            cached_page,
            profile=paint_profile,
        )
        return merged

    from resources.lib.meta.paint_complete import partition_paint_rows, rows_page_paint_ready
    from resources.lib.simkl.enrich import hydrate_sync_items_local, prepare_page_sync_for_paint

    if library_paint and refs and cache_catalog != "mixed":
        from resources.lib.simkl.media_ref import sync_db_rows_for_refs

        page_sync = sync_db_rows_for_refs(catalog, refs)
    elif payload_rows:
        normalized = rows_to_sync_items(payload_rows, catalog)
        page_sync = normalized or list(payload_rows)
    elif cache_catalog == "mixed":
        page_sync = sync_items_for_mixed_refs(refs)
    else:
        page_sync = sync_items_for_refs(catalog, refs)
    if not page_sync and cache_catalog != "mixed":
        page_sync = sync_items_for_refs(catalog, refs)
    if not page_sync:
        return merged

    page_sync = hydrate_sync_items_local(page_sync)
    paint_media = "movie" if catalog == "movie" else "tvshow"
    read_only_paint = rows_page_paint_ready(page_sync, profile=paint_profile)
    if not read_only_paint and library_paint:
        complete, incomplete = partition_paint_rows(page_sync, paint_media, profile=paint_profile)
        if incomplete:
            from resources.lib.simkl.enrich import enrich_sync_items_persisted

            enriched = enrich_sync_items_persisted(catalog, incomplete)
            by_id = {
                int(row["simkl_id"]): row
                for row in enriched
                if isinstance(row, dict) and row.get("simkl_id") is not None
            }
            page_sync = [
                by_id.get(int(row["simkl_id"]), row)
                if isinstance(row, dict) and row.get("simkl_id") is not None
                else row
                for row in page_sync
            ]
            read_only_paint = rows_page_paint_ready(page_sync, profile=paint_profile)

    if cache_catalog == "mixed":
        from resources.lib.simkl.enrich import prepare_mixed_page_sync_for_paint

        page_sync = prepare_mixed_page_sync_for_paint(page_sync, refs=refs)
    else:
        page_sync = prepare_page_sync_for_paint(
            catalog,
            page_sync,
            refs=refs,
            defer_simkl_detail=read_only_paint,
        )

    painted = paint_catalog_page_rows(
        refs,
        page_sync,
        hide_unaired=hide_unaired,
        hide_watched=hide_watched,
        prefer_rich_payload=prefer_rich,
        paint_profile=paint_profile,
        page_cache={"catalog": cache_catalog},
        defer_provider_prepare=defer_provider_prepare,
    )

    from resources.lib.meta.paint_cache import mixed_page_paint_all_complete, overlay_display_meta_stamps
    from resources.lib.meta.paint_complete import rows_page_paint_ready

    painted = overlay_display_meta_stamps(painted)
    merged["preloaded_paint_rows"] = painted
    merged["preloaded_paint_complete"] = rows_page_paint_ready(painted, profile=paint_profile) or mixed_page_paint_all_complete(
        painted,
        profile=paint_profile,
    )
    return merged


def sync_items_for_mixed_refs(refs: list[dict]) -> list[dict]:
    """Resolve ordered SyncRows for refs that may span movie, tv, and anime."""
    from resources.lib.discover.catalog_store import sync_items_for_refs

    by_catalog: dict[str, list[dict]] = {}
    for ref in refs or []:
        if not isinstance(ref, dict) or ref.get("simkl_id") is None:
            continue
        item_catalog = str(ref.get("catalog") or "movie")
        by_catalog.setdefault(item_catalog, []).append(ref)
    page_sync: list[dict] = []
    for item_catalog, catalog_refs in by_catalog.items():
        page_sync.extend(sync_items_for_refs(item_catalog, catalog_refs))
    return page_sync


def _run_title_list_builder(
    catalog: str,
    refs: list[dict],
    list_builder,
    merged: dict,
) -> None:
    if catalog == "movie":
        list_builder.movie_discover_builder(refs, **merged)
    elif catalog == "anime":
        list_builder.anime_discover_builder(refs, **merged)
    else:
        list_builder.show_discover_builder(refs, **merged)


def render_catalog_discover_refs(
    catalog: str,
    refs: list[dict],
    list_builder,
    *,
    list_kwargs: dict | None = None,
    library_paint: bool = False,
    simkl_detail_paint: bool = False,
    prefer_catalog_payload: bool = False,
    payload_rows: list[dict] | None = None,
    **kwargs,
) -> None:
    """Paint refs from catalog_items / display_meta, then render (Simkl-owned metadata)."""
    render_fast_title_list(
        catalog,
        refs,
        list_builder,
        list_kwargs=list_kwargs,
        library_paint=library_paint,
        simkl_detail_paint=simkl_detail_paint,
        prefer_catalog_payload=prefer_catalog_payload,
        payload_rows=payload_rows,
        **kwargs,
    )


def _paint_media_type(catalog: str) -> str:
    return "movie" if catalog == "movie" else "tvshow"


def _merge_enriched_into_page(rows: list[dict], enriched: list[dict]) -> list[dict]:
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


def _seren_sync_simkl_detail_fill(catalog: str, refs: list[dict], rows: list[dict]) -> list[dict]:
    """Blocking GET /movies|tv|anime/{id} for thin genre/library rows (plot, runtime, genres)."""
    from resources.lib.simkl.enrich import enrich_sync_items_persisted, simkl_detail_needed

    thin: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict) or not simkl_detail_needed(row):
            continue
        item = dict(row)
        if not item.get("catalog"):
            item["catalog"] = catalog
        thin.append(item)
    if not thin:
        return rows
    parallel = len(thin) > 1
    enriched = enrich_sync_items_persisted(catalog, thin, force_detail=True, parallel=parallel)
    rows = _merge_enriched_into_page(rows, enriched)
    from resources.lib.simkl.enrich import simkl_detail_plot_missing

    still_thin = [row for row in rows if isinstance(row, dict) and simkl_detail_plot_missing(row)]
    if still_thin:
        retry = []
        for row in still_thin:
            item = dict(row)
            item.setdefault("catalog", catalog)
            retry.append(item)
        enriched_retry = enrich_sync_items_persisted(
            catalog, retry, force_detail=True, parallel=len(retry) > 1
        )
        rows = _merge_enriched_into_page(rows, enriched_retry)
    return rows


def _seren_sync_finalize_page(catalog: str, refs: list[dict], rows: list[dict], profile: str) -> list[dict]:
    """Simkl detail for thin rows, then provider cast/art gap-fill for the visible page."""
    rows = _seren_sync_simkl_detail_fill(catalog, refs, rows)
    from resources.lib.meta.paint_cache import coalesce_page_rows_paint_info

    rows = coalesce_page_rows_paint_info(catalog, rows)
    rows = _seren_sync_provider_prepare(catalog, rows, profile)
    return coalesce_page_rows_paint_info(catalog, rows)


def _seren_sync_merge_repaired_rows(rows: list[dict], repaired: list[dict]) -> list[dict]:
    by_id = {
        int(row["simkl_id"]): row
        for row in repaired
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


def _order_rows_by_refs(catalog: str, refs: list[dict], rows: list[dict]) -> list[dict]:
    by_id = {
        int(row["simkl_id"]): row
        for row in rows
        if isinstance(row, dict) and row.get("simkl_id") is not None
    }
    ordered: list[dict] = []
    for ref in refs or []:
        if not isinstance(ref, dict) or ref.get("simkl_id") is None:
            continue
        sid = int(ref["simkl_id"])
        row = by_id.get(sid)
        if row is None:
            continue
        if not row.get("catalog"):
            row = dict(row)
            row["catalog"] = ref.get("catalog") or catalog
        ordered.append(row)
    if ordered:
        return ordered
    return list(rows or [])


def _genre_focus_batch_size() -> int:
    from resources.lib.modules.globals import g

    page_limit = max(1, g.get_int_setting("item.limit", 25))
    return min(page_limit, max(8, page_limit // 2))


def _seren_sync_resolve_page_rows_time_to_list(
    catalog: str,
    refs: list[dict],
    rows: list[dict],
    profile: str,
    *,
    paint_overrides: dict | None = None,
) -> tuple[list[dict], str]:
    """Fast genre open: one Simkl detail wave + IMDb cast; art stamps run after menu HTTP scope."""
    from resources.lib.meta.paint_cache import overlay_display_meta_stamps, overlay_stamped_display_meta_page
    from resources.lib.meta.paint_complete import partition_paint_rows, rows_page_menu_ready
    from resources.lib.meta.paint_cache import coalesce_page_rows_paint_info

    from resources.lib.meta.paint_complete import _FAST_OPEN_ART_DEFER_PROFILES

    paint_profile = profile if str(profile).lower() in _FAST_OPEN_ART_DEFER_PROFILES else "genre"
    fast_path = f"{paint_profile}_fast"
    overrides = paint_overrides or {}

    rows = coalesce_page_rows_paint_info(catalog, rows)
    rows = overlay_stamped_display_meta_page(catalog, rows)
    rows = overlay_display_meta_stamps(rows)

    if rows_page_menu_ready(rows, profile=paint_profile):
        return rows, "stamp"

    ordered = _order_rows_by_refs(catalog, refs, rows)
    ordered = _seren_sync_simkl_detail_fill(catalog, refs, ordered)
    ordered = coalesce_page_rows_paint_info(catalog, ordered)
    ordered = overlay_stamped_display_meta_page(catalog, ordered)
    ordered = overlay_display_meta_stamps(ordered)

    paint_media = _paint_media_type(catalog)
    _complete, incomplete = partition_paint_rows(ordered, paint_media, profile=paint_profile)
    if incomplete:
        prepared = _seren_sync_provider_prepare(catalog, incomplete, paint_profile)
        ordered = _seren_sync_merge_repaired_rows(ordered, prepared)
    rows_out = coalesce_page_rows_paint_info(catalog, ordered)
    return rows_out, fast_path


def _catalog_fast_open_profile(paint_overrides: dict) -> tuple[bool, str]:
    """Return (enabled, resolve profile) for fast catalog menu opens."""
    reason = str(paint_overrides.get("enrichment_reason") or "").lower()
    if paint_overrides.get("genre_fast_open") or reason == "genre":
        return True, "genre"
    if paint_overrides.get("search_fast_open") or reason == "search":
        return True, "search"
    if paint_overrides.get("discover_fast_open") or reason == "discover":
        return True, "browse"
    if paint_overrides.get("actor_fast_open") or reason == "actor":
        return True, "actor"
    if paint_overrides.get("library_fast_open") or (
        paint_overrides.get("library_paint") and paint_overrides.get("catalog_pipeline")
    ):
        return True, "library"
    if paint_overrides.get("related_fast_open") or reason == "related":
        return True, "related"
    return False, ""


def _schedule_stamp_for_sync_items(sync_items: list[dict]) -> None:
    from resources.lib.discover.sync_bridge import simkl_refs
    from resources.lib.meta.page_materialize import schedule_browse_page_stamp_background
    from resources.lib.simkl.media_ref import partition_by_catalog

    movies, tv, anime = partition_by_catalog(sync_items)
    for catalog, group in (("movie", movies), ("tv", tv), ("anime", anime)):
        if group:
            schedule_browse_page_stamp_background(catalog, simkl_refs(group))


def _seren_sync_resolve_mixed_sync_items(sync_items: list[dict], profile: str) -> list[dict]:
    """Foreground finalize for mixed movie/tv/anime pages (actor filmography)."""
    from resources.lib.simkl.media_ref import partition_by_catalog

    movies, tv, anime = partition_by_catalog(sync_items)
    by_id: dict[int, dict] = {}
    for catalog, group in (("movie", movies), ("tv", tv), ("anime", anime)):
        if not group:
            continue
        refs = [
            {"simkl_id": int(row["simkl_id"]), "catalog": row.get("catalog") or catalog}
            for row in group
            if isinstance(row, dict) and row.get("simkl_id") is not None
        ]
        if not refs:
            continue
        resolved, _path = _seren_sync_resolve_page_rows_time_to_list(catalog, refs, group, profile)
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
    return ordered


def _seren_sync_resolve_page_rows(
    catalog: str,
    refs: list[dict],
    rows: list[dict],
    profile: str,
) -> tuple[list[dict], str]:
    """Stamp overlay when possible; otherwise blocking finalize (full page or repair subset)."""
    from resources.lib.meta.page_materialize import stamp_page_rows_to_display_meta
    from resources.lib.meta.paint_cache import overlay_display_meta_stamps, overlay_stamped_display_meta_page
    from resources.lib.meta.paint_complete import partition_paint_rows, rows_page_menu_ready
    from resources.lib.meta.paint_stamp import page_refs_display_stamped

    from resources.lib.meta.paint_cache import coalesce_page_rows_paint_info

    rows = coalesce_page_rows_paint_info(catalog, rows)
    rows = overlay_stamped_display_meta_page(catalog, rows)
    rows = overlay_display_meta_stamps(rows)
    if rows_page_menu_ready(rows, profile=profile):
        return rows, "stamp"

    paint_media = _paint_media_type(catalog)
    _complete, incomplete = partition_paint_rows(rows, paint_media, profile=profile)
    if incomplete and page_refs_display_stamped(refs):
        repaired = _seren_sync_finalize_page(catalog, refs, incomplete, profile)
        rows = _seren_sync_merge_repaired_rows(rows, repaired)
        stamp_page_rows_to_display_meta(catalog, rows, profile=profile)
        return rows, "repair"

    rows = _seren_sync_finalize_page(catalog, refs, rows, profile)
    stamp_page_rows_to_display_meta(catalog, rows, profile=profile)
    return rows, "cold"


def _repair_page_sync_rows(catalog: str, refs: list[dict], rows: list[dict], profile: str) -> list[dict]:
    """Blocking enrich for incomplete page rows only, then re-read simkl_sync."""
    return _seren_sync_finalize_page(catalog, refs, rows, profile)


def _seren_sync_provider_prepare(catalog: str, rows: list[dict], profile: str) -> list[dict]:
    """Blocking IMDb/AniList/TMDB cast+art gap-fill for the visible page (info panel)."""
    from resources.lib.database.session import get_sync_database
    from resources.lib.meta.paint_complete import partition_paint_rows

    if not rows:
        return rows
    paint_media = _paint_media_type(catalog)
    _complete, incomplete = partition_paint_rows(rows, paint_media, profile=profile)
    if not incomplete:
        return rows
    db = get_sync_database()
    prepared, _enrich_refs, _stats = db.metadataHandler.prepare_list_rows_for_paint(
        incomplete,
        paint_media,
        db=db,
        profile=profile,
        overlay_sync=True,
    )
    by_id = {
        int(row["simkl_id"]): row
        for row in (prepared or [])
        if isinstance(row, dict) and row.get("simkl_id") is not None
    }
    merged_rows: list[dict] = []
    for row in rows:
        if isinstance(row, dict) and row.get("simkl_id") is not None:
            sid = int(row["simkl_id"])
            merged_rows.append(by_id.get(sid, row))
        else:
            merged_rows.append(row)
    return merged_rows


def _merged_seren_menu_kwargs(paint_overrides: dict) -> dict:
    from resources.lib.simkl.media_ref import menu_open_sync_params

    merged = browse_list_kwargs(**paint_overrides)
    merged.update(menu_open_sync_params())
    merged.pop("preloaded_paint_rows", None)
    merged.pop("preloaded_paint_complete", None)
    merged.pop("paint_only", None)
    return merged


def _merged_seren_direct_menu_kwargs(paint_overrides: dict) -> dict:
    """ListBuilder kwargs for Seren-style menu open: one simkl_sync SQL read, no pre-resolve."""
    merged = browse_list_kwargs(**paint_overrides)
    merged.pop("preloaded_paint_rows", None)
    merged.pop("preloaded_paint_complete", None)
    merged.pop("paint_only", None)
    merged.pop("catalog_pipeline", None)
    merged.setdefault("skip_mill", True)
    merged.setdefault("sync_path", True)
    merged.setdefault("skip_update", True)
    merged.setdefault("seren_direct_db", True)
    merged.setdefault("seren_menu_sql", True)
    return merged


def _seren_direct_db_menu(
    paint_overrides: dict,
    *,
    library_paint: bool,
    simkl_detail_paint: bool,
    prefer_catalog_payload: bool,
    catalog_fast_open: bool,
    fast_profile: str,
) -> bool:
    """Skip paint resolve / window page cache — match Seren: refs → get_*_list → ListItems."""
    if paint_overrides.get("seren_direct_db") is False:
        return False
    if paint_overrides.get("seren_direct_db") is True:
        return True
    if library_paint or simkl_detail_paint or prefer_catalog_payload:
        return False
    if paint_overrides.get("catalog_pipeline"):
        return False
    if paint_overrides.get("preloaded_paint_rows") or paint_overrides.get("preloaded_paint_complete"):
        return False
    if not catalog_fast_open:
        return False
    if fast_profile in ("library",):
        return False
    return True


def prepare_seren_menu_refs(catalog: str, items: list[dict]) -> list[dict]:
    """Otaku/Seren-style: write browse rows into simkl_sync, then list via get_*_list only."""
    from resources.lib.discover.sync_bridge import simkl_refs
    from resources.lib.meta.list_pipeline import seed_browse_page

    if not items:
        return []
    seed_browse_page(catalog, items)
    return simkl_refs(items)


def render_seren_menu_page(
    catalog: str,
    items: list[dict],
    list_builder,
    *,
    list_kwargs: dict | None = None,
    **kwargs,
) -> None:
    """Seed simkl_sync from page payload and paint with seren_direct_db (no catalog pipeline)."""
    refs = prepare_seren_menu_refs(catalog, items)
    if not refs:
        from resources.lib.modules.globals import g

        g.cancel_directory()
        return
    paint_kwargs = dict(list_kwargs or {})
    paint_kwargs.setdefault("seeded", True)
    paint_kwargs["seren_direct_db"] = True
    paint_kwargs["seren_menu_sql"] = True
    merged = browse_list_kwargs(**paint_kwargs)
    merged.pop("catalog_pipeline", None)
    merged.pop("prefer_catalog_payload", None)
    render_fast_title_list(
        catalog,
        refs,
        list_builder,
        list_kwargs=merged,
        seeded=True,
        **kwargs,
    )


def render_seren_browse_page(
    catalog: str,
    items: list[dict],
    list_builder,
    *,
    list_kwargs: dict | None = None,
    **kwargs,
) -> None:
    """Seed simkl_sync and render via Seren sync_path (replaces browse_sync module)."""
    from resources.lib.discover.sync_bridge import simkl_refs
    from resources.lib.modules.globals import g

    if not items:
        g.cancel_directory()
        return
    render_fast_title_list(
        catalog,
        simkl_refs(items),
        list_builder,
        list_kwargs=list_kwargs,
        payload_rows=items,
        seeded=True,
        **kwargs,
    )


def render_fast_title_list(
    catalog: str,
    refs: list[dict],
    list_builder,
    *,
    list_kwargs: dict | None = None,
    library_paint: bool = False,
    simkl_detail_paint: bool = False,
    prefer_catalog_payload: bool = False,
    payload_rows: list[dict] | None = None,
    menu_action: str = "",
    **kwargs,
) -> None:
    """Seren-speed title list: sync_path SQL read, rare page repair, optional legacy paint layer."""
    from resources.lib.meta.menu_paint_profile import MenuPaintProfile
    from resources.lib.meta.menu_perf import note_paint_rows, note_phase_ms, trace_menu_open
    from resources.lib.meta.paint_complete import rows_page_paint_ready
    from resources.lib.simkl.media_ref import sync_db_rows_for_refs
    from resources.lib.modules.globals import g

    if not refs:
        g.cancel_directory()
        return

    from resources.lib.meta.browse_settings_snapshot import begin_browse_menu_snapshot

    begin_browse_menu_snapshot()

    paint_overrides = dict(list_kwargs or {})
    paint_overrides.update(kwargs)
    library_paint, simkl_detail_paint, prefer_catalog_payload, _genre_paint = _resolve_catalog_paint_flags(
        paint_overrides,
        library_paint=library_paint,
        simkl_detail_paint=simkl_detail_paint,
        prefer_catalog_payload=prefer_catalog_payload,
    )
    profile = str(
        paint_overrides.get("paint_profile")
        or (MenuPaintProfile.LIBRARY.value if library_paint else MenuPaintProfile.BROWSE.value)
    )
    action = menu_action or str(paint_overrides.get("menu_action") or g.REQUEST_PARAMS.get("action") or "title_list")

    catalog_fast_open, fast_profile = _catalog_fast_open_profile(paint_overrides)
    genre_fast_open = catalog_fast_open and fast_profile == "genre"
    resolve_profile = fast_profile if catalog_fast_open else profile
    seren_direct_db = _seren_direct_db_menu(
        paint_overrides,
        library_paint=library_paint,
        simkl_detail_paint=simkl_detail_paint,
        prefer_catalog_payload=prefer_catalog_payload,
        catalog_fast_open=catalog_fast_open,
        fast_profile=fast_profile,
    )
    stamp_after_open: tuple[str, list[dict]] | None = None
    defer_persist: tuple[str, list[dict], str] | None = None
    defer_mixed_persist: tuple[list[dict], str] | None = None
    mixed_list = bool(paint_overrides.get("mixed_list"))

    if paint_overrides.get("catalog_pipeline") and payload_rows is not None:
        paint_overrides.setdefault("thin_payload_rows", payload_rows)

    trace_catalog = "mixed" if mixed_list else catalog
    with trace_menu_open(action, catalog=trace_catalog) as perf:
        if seren_direct_db:
            merged = _merged_seren_direct_menu_kwargs(paint_overrides)
            perf["path"] = "seren_direct_db"
            builder_started = time.time()
            if mixed_list:
                catalog_hint = paint_overrides.get("catalog_hint")
                label2_for_item = paint_overrides.get("label2_for_item")
                merged.pop("catalog_hint", None)
                merged.pop("label2_for_item", None)
                list_builder._mixed_media_from_sync_dicts(
                    refs,
                    catalog_hint=catalog_hint,
                    label2_for_item=label2_for_item,
                    **merged,
                )
            else:
                _run_title_list_builder(catalog, refs, list_builder, merged)
            note_phase_ms(perf, "builder_ms", builder_started)
            return

        merged = _merged_seren_menu_kwargs(paint_overrides)
        hide_unaired = bool(merged.get("hide_unaired", g.get_bool_setting("general.hideUnAired")))
        hide_watched = bool(merged.get("hide_watched", g.get_bool_setting("general.hideWatched")))
        prefer_rich = bool(
            prefer_catalog_payload or library_paint or simkl_detail_paint or genre_fast_open
        )
        from resources.lib.meta.list_window_cache import (
            get_window_page_items,
            page_list_window_key,
            serialize_page_rows_for_window,
            set_window_page_items,
        )
        from resources.lib.meta.paint_cache import (
            page_cache_catalog,
            page_paint_cache_key,
            set_session_page_paint,
        )

        cache_catalog = page_cache_catalog(catalog, refs, mixed_list=mixed_list)
        window_key = page_list_window_key(
            catalog,
            refs,
            mixed_list=mixed_list,
            paint_profile=resolve_profile,
            hide_unaired=hide_unaired,
            hide_watched=hide_watched,
            prefer_rich_payload=prefer_rich,
        )
        session_key = page_paint_cache_key(
            cache_catalog,
            refs,
            hide_unaired=hide_unaired,
            hide_watched=hide_watched,
            paint_profile=resolve_profile,
            prefer_rich_payload=prefer_rich,
        )
        cached_window = get_window_page_items(window_key)
        use_catalog_pipeline = bool(paint_overrides.get("catalog_pipeline"))
        sync_started = time.time()
        if cached_window and not use_catalog_pipeline:
            rows = cached_window
            open_path = "kodi_window"
            note_phase_ms(perf, "sync_db_ms", sync_started)
            note_phase_ms(perf, "finalize_ms", sync_started)
        elif mixed_list:
            from resources.lib.simkl.media_ref import partition_by_catalog

            movies, tv, anime = partition_by_catalog(refs)
            rows = []
            for item_catalog, group in (("movie", movies), ("tv", tv), ("anime", anime)):
                if group:
                    rows.extend(sync_db_rows_for_refs(item_catalog, group))
            note_phase_ms(perf, "sync_db_ms", sync_started)
            finalize_started = time.time()
            if paint_overrides.get("catalog_pipeline"):
                from resources.lib.pipeline.page_resolve import resolve_catalog_page_rows

                rows, open_path = resolve_catalog_page_rows(
                    catalog,
                    refs,
                    rows,
                    resolve_profile,
                    catalog_fast_open=catalog_fast_open,
                    paint_overrides=paint_overrides,
                )
            elif catalog_fast_open:
                rows, open_path = _seren_sync_resolve_page_rows_time_to_list(
                    catalog,
                    refs,
                    rows,
                    resolve_profile,
                    paint_overrides=paint_overrides,
                )
            else:
                rows, open_path = _seren_sync_resolve_page_rows(catalog, refs, rows, profile)
            note_phase_ms(perf, "finalize_ms", finalize_started)
            if not use_catalog_pipeline:
                set_window_page_items(window_key, serialize_page_rows_for_window(rows))
                set_session_page_paint(session_key, rows)
        else:
            rows = sync_db_rows_for_refs(catalog, refs)
            note_phase_ms(perf, "sync_db_ms", sync_started)
            finalize_started = time.time()
            if paint_overrides.get("catalog_pipeline"):
                from resources.lib.pipeline.page_resolve import resolve_catalog_page_rows

                rows, open_path = resolve_catalog_page_rows(
                    catalog,
                    refs,
                    rows,
                    resolve_profile,
                    catalog_fast_open=catalog_fast_open,
                    paint_overrides=paint_overrides,
                )
            elif catalog_fast_open:
                rows, open_path = _seren_sync_resolve_page_rows_time_to_list(
                    catalog,
                    refs,
                    rows,
                    resolve_profile,
                    paint_overrides=paint_overrides,
                )
            else:
                rows, open_path = _seren_sync_resolve_page_rows(catalog, refs, rows, profile)
            note_phase_ms(perf, "finalize_ms", finalize_started)
            if not use_catalog_pipeline:
                set_window_page_items(window_key, serialize_page_rows_for_window(rows))
                set_session_page_paint(session_key, rows)
        perf["path"] = open_path
        merged["preloaded_paint_rows"] = rows
        paint_complete_profile = resolve_profile if catalog_fast_open else profile
        preloaded_complete = open_path in (
            "stamp",
            "browse_resolve",
            "browse_stamp",
            "kodi_window",
        ) or (
            bool(rows)
            and all(isinstance(r, dict) and r.get("_menu_display_ready") for r in rows)
        )
        merged["preloaded_paint_complete"] = preloaded_complete
        note_paint_rows(perf, rows, profile=paint_complete_profile)
        builder_started = time.time()
        if mixed_list:
            catalog_hint = paint_overrides.get("catalog_hint")
            label2_for_item = paint_overrides.get("label2_for_item")
            merged.pop("catalog_hint", None)
            merged.pop("label2_for_item", None)
            list_builder._mixed_media_from_sync_dicts(
                rows,
                catalog_hint=catalog_hint,
                label2_for_item=label2_for_item,
                **merged,
            )
        else:
            _run_title_list_builder(catalog, refs, list_builder, merged)
        note_phase_ms(perf, "builder_ms", builder_started)
        if paint_overrides.get("catalog_pipeline") and rows:
            if mixed_list:
                defer_mixed_persist = (rows, paint_complete_profile)
            else:
                defer_persist = (catalog, rows, paint_complete_profile)
        elif catalog_fast_open and (open_path.endswith("_fast") or open_path == "stamp"):
            stamp_after_open = (catalog, refs)

    if defer_mixed_persist is not None:
        from resources.lib.meta.list_pipeline import defer_mixed_browse_persist

        defer_mixed_browse_persist(defer_mixed_persist[0], profile=defer_mixed_persist[1])
    elif defer_persist is not None:
        from resources.lib.meta.list_pipeline import defer_browse_page_persist

        defer_browse_page_persist(defer_persist[0], defer_persist[1], profile=defer_persist[2])
    elif stamp_after_open is not None:
        from resources.lib.meta.page_materialize import schedule_browse_page_stamp_background

        schedule_browse_page_stamp_background(stamp_after_open[0], stamp_after_open[1])


def rows_to_sync_items(rows: list[dict], catalog: str) -> list[dict]:
    """Normalize SQL/API rows into SyncRows for catalog_items upsert."""
    from resources.lib.simkl.media_ref import normalize_simkl_item

    items: list[dict] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("simkl_id") and isinstance(row.get("simkl_object"), dict) and row.get("catalog"):
            sid = int(row["simkl_id"])
            if sid not in seen:
                items.append(row)
                seen.add(sid)
            continue
        obj = row.get("simkl_object")
        if isinstance(obj, dict) and row.get("simkl_id") is not None and isinstance(obj.get("info"), dict):
            info = dict(obj["info"])
            art = dict(obj.get("art") or {}) if isinstance(obj.get("art"), dict) else {}
            item_catalog = row.get("catalog") or info.get("catalog") or catalog
            sync_item = {
                "simkl_id": int(row["simkl_id"]),
                "catalog": item_catalog,
                "simkl_object": {"info": info, "art": art},
            }
            for ext in ("tmdb_id", "tvdb_id", "imdb_id"):
                if row.get(ext) is not None:
                    sync_item[ext] = row[ext]
                elif info.get(ext) is not None:
                    sync_item[ext] = info[ext]
            sid = int(sync_item["simkl_id"])
            if sid not in seen:
                items.append(sync_item)
                seen.add(sid)
            continue
        if row.get("simkl_id") is not None and isinstance(row.get("info"), dict) and row["info"]:
            info = dict(row["info"])
            art = dict(row.get("art") or {}) if isinstance(row.get("art"), dict) else {}
            item_catalog = row.get("catalog") or info.get("catalog") or catalog
            sync_item = {
                "simkl_id": int(row["simkl_id"]),
                "catalog": item_catalog,
                "simkl_object": {"info": info, "art": art},
            }
            for ext in ("tmdb_id", "tvdb_id", "imdb_id"):
                if row.get(ext) is not None:
                    sync_item[ext] = row[ext]
                elif info.get(ext) is not None:
                    sync_item[ext] = info[ext]
            sid = int(sync_item["simkl_id"])
            if sid not in seen:
                items.append(sync_item)
                seen.add(sid)
            continue
        if isinstance(obj, dict):
            normalized = normalize_simkl_item(obj, row.get("catalog") or catalog)
            if normalized:
                sid = int(normalized["simkl_id"])
                if sid not in seen:
                    items.append(normalized)
                    seen.add(sid)
            continue
        show = row.get("show")
        if isinstance(show, dict):
            normalized = normalize_simkl_item(show, catalog)
            if normalized:
                sid = int(normalized["simkl_id"])
                if sid not in seen:
                    items.append(normalized)
                    seen.add(sid)
            continue
        if row.get("simkl_id") is not None and (row.get("title") or row.get("ids")):
            normalized = normalize_simkl_item(row, catalog)
            if normalized:
                sid = int(normalized["simkl_id"])
                if sid not in seen:
                    items.append(normalized)
                    seen.add(sid)
    return items


def prepare_catalog_refs(
    catalog: str,
    rows: list[dict],
    *,
    sync_items: list[dict] | None = None,
) -> list[dict]:
    """Upsert rows into catalog_items and return ordered list-builder refs."""
    from resources.lib.discover.sync_bridge import insert_discover_page, simkl_refs

    items = sync_items or rows_to_sync_items(rows, catalog)
    if items:
        insert_discover_page(catalog, items)

    refs: list[dict] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("simkl_id") or row.get("simkl_show_id")
        if sid is None:
            continue
        sid = int(sid)
        if sid in seen:
            continue
        seen.add(sid)
        refs.append({"simkl_id": sid, "catalog": row.get("catalog") or catalog})
    if refs:
        return refs
    return simkl_refs(items)


def render_catalog_rows(
    catalog: str,
    rows: list[dict],
    list_builder,
    *,
    sync_items: list[dict] | None = None,
    **kwargs,
) -> None:
    """Upsert DB/API rows, paint from catalog_items, render a single-catalog menu."""
    from resources.lib.modules.globals import g

    if not rows:
        g.cancel_directory()
        return
    refs = prepare_catalog_refs(catalog, rows, sync_items=sync_items)
    paint_rows = sync_items or rows_to_sync_items(rows, catalog) or rows
    render_catalog_discover_refs(
        catalog,
        refs,
        list_builder,
        payload_rows=paint_rows,
        prefer_catalog_payload=True,
        **kwargs,
    )


def episode_row_simkl_ids(episode_rows: list[dict]) -> list[int]:
    """Resolve episode Simkl IDs from mixed episode menu seed rows."""
    ids: list[int] = []
    seen: set[int] = set()
    for row in episode_rows or []:
        if not isinstance(row, dict):
            continue
        simkl_id = row.get("simkl_id")
        if simkl_id is None:
            episode = row.get("episode")
            if isinstance(episode, dict):
                simkl_id = episode.get("simkl_id")
        if simkl_id is None:
            continue
        sid = int(simkl_id)
        if sid not in seen:
            seen.add(sid)
            ids.append(sid)
    return ids


def peek_episode_page_cache(
    catalog: str,
    episode_rows: list[dict],
    *,
    paint_profile: str,
) -> list[dict] | None:
    """Return session-cached painted episode rows when the page key matches."""
    from resources.lib.meta.paint_cache import episode_page_paint_cache_key, get_session_page_paint

    episode_ids = episode_row_simkl_ids(episode_rows)
    if not episode_ids:
        return None
    cache_key = episode_page_paint_cache_key(catalog, episode_ids, paint_profile=paint_profile)
    return get_session_page_paint(cache_key)


def attach_preloaded_episode_paint(
    catalog: str,
    episode_rows: list[dict],
    list_kwargs: dict,
    db,
    *,
    filter_params: dict | None = None,
) -> dict:
    """Paint or load a library episode page from session cache (Next Up, Watched Episodes, etc.)."""
    from resources.lib.meta.menu_paint_profile import MenuPaintProfile
    from resources.lib.meta.paint_cache import (
        episode_page_paint_cache_key,
        get_session_page_paint,
        set_session_page_paint,
    )

    merged = dict(list_kwargs or {})
    paint_profile = str(merged.get("paint_profile") or MenuPaintProfile.LIBRARY_EPISODES.value)
    overlay_parents = bool(merged.get("overlay_parent_shows", False))
    episode_ids = episode_row_simkl_ids(episode_rows)
    if not episode_ids:
        return merged

    cache_key = episode_page_paint_cache_key(catalog, episode_ids, paint_profile=paint_profile)
    cached = get_session_page_paint(cache_key)
    if cached is not None:
        merged["preloaded_episode_rows"] = cached
        return merged

    load_params = dict(filter_params or {})
    load_params.setdefault("catalog", catalog)
    load_params.setdefault("catalog_hint", catalog)
    need_sync = db._mixed_episodes_missing_rows(episode_rows) or db._mixed_episodes_need_sync(episode_rows)
    if need_sync:
        load_params["skip_update"] = False
        load_params["skip_mill"] = True
    rows = db.get_mixed_episode_list(episode_rows, **load_params)
    enrichment_refs = None
    enrichment_media_type = None
    if overlay_parents:
        rows, enrichment_refs, enrichment_media_type = finish_episode_parent_paint(
            rows,
            catalog,
            paint_profile=paint_profile,
        )
    if rows:
        set_session_page_paint(cache_key, rows)
        merged["preloaded_episode_rows"] = rows
    if enrichment_refs:
        merged["enrichment_refs"] = enrichment_refs
        merged["enrichment_media_type"] = enrichment_media_type
    return merged


def upsert_episode_parent_shows(episode_rows: list[dict], catalog: str) -> None:
    """Ensure parent shows for episode menus exist in catalog_items."""
    from resources.lib.discover.sync_bridge import insert_discover_page

    sync_items = rows_to_sync_items(episode_rows, catalog)
    if sync_items:
        insert_discover_page(catalog, sync_items)


def _parent_show_refs_from_episode_rows(episode_rows: list[dict], catalog: str) -> list[dict]:
    from resources.lib.simkl.ids import show_id_from_item

    seen: set[int] = set()
    refs: list[dict] = []
    for row in episode_rows:
        show_id = show_id_from_item(row)
        if show_id is None:
            continue
        sid = int(show_id)
        if sid in seen:
            continue
        seen.add(sid)
        refs.append({"simkl_id": sid, "catalog": catalog})
    return refs


def prefetch_episode_parent_simkl_detail(episode_rows: list[dict], catalog: str) -> None:
    """Blocking Simkl GET /tv|anime/{id} for parent shows before episode rows load from DB."""
    refs = _parent_show_refs_from_episode_rows(episode_rows, catalog)

    if not refs:
        return
    from resources.lib.discover.catalog_store import sync_items_for_refs
    from resources.lib.simkl.enrich import prepare_page_sync_for_paint

    page_sync = sync_items_for_refs(catalog, refs)
    if page_sync:
        prepare_page_sync_for_paint(catalog, page_sync, refs=refs)


def _warm_parent_show_cast(show_ids: list[int], catalog: str) -> None:
    """Synchronous cast/art prepare for parent shows on episode library menus."""
    if not show_ids:
        return
    from resources.lib.database.session import get_sync_database
    from resources.lib.database.simkl_sync.serial_access import fetch_show_rows_by_ids
    from resources.lib.meta.menu_paint_profile import MenuPaintProfile

    db = get_sync_database()
    rows = fetch_show_rows_by_ids(db, catalog, show_ids)
    if not rows:
        return
    paint_media = "anime" if catalog == "anime" else "tvshow"
    db.metadataHandler.prepare_list_rows_for_paint(
        rows,
        paint_media,
        db=db,
        profile=MenuPaintProfile.LIBRARY.value,
        overlay_sync=True,
    )


def _episode_has_duration(info: dict) -> bool:
    if not isinstance(info, dict):
        return False
    if info.get("duration"):
        return True
    from resources.lib.discover.normalize import duration_from_runtime

    if duration_from_runtime(info.get("runtime")):
        return True
    if duration_from_runtime(info.get("tvshow.runtime")):
        return True
    tvshow = info.get("tvshow")
    return isinstance(tvshow, dict) and bool(duration_from_runtime(tvshow.get("runtime")))


def _show_sync_row_has_runtime(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    blob = row.get("simkl_object") or {}
    info = blob.get("info") if isinstance(blob.get("info"), dict) else row.get("info")
    if not isinstance(info, dict):
        return False
    from resources.lib.discover.normalize import duration_from_runtime

    return bool(duration_from_runtime(info.get("runtime")))


def _finalize_episode_paint_rows(episode_rows: list[dict], catalog: str) -> list[dict]:
    """Convert Simkl runtime → Kodi duration and backfill from parent show detail when thin."""
    from collections import defaultdict

    from resources.lib.discover.catalog_store import sync_items_for_refs
    from resources.lib.simkl.field_map import finalize_playback_info, inherit_show_fields
    from resources.lib.simkl.ids import show_id_from_item
    from resources.lib.simkl.enrich import enrich_page_for_paint

    finalized: list[dict] = []
    for row in episode_rows:
        if not isinstance(row, dict):
            finalized.append(row)
            continue
        item = dict(row)
        info = dict(item.get("info") or {})
        finalize_playback_info(info)
        item["info"] = info
        finalized.append(item)

    missing_by_show: dict[int, list[int]] = defaultdict(list)
    for idx, row in enumerate(finalized):
        if not isinstance(row, dict):
            continue
        info = row.get("info") or {}
        if not _episode_has_duration(info):
            show_id = show_id_from_item(row)
            if show_id is not None:
                missing_by_show[int(show_id)].append(idx)

    if missing_by_show:
        from resources.lib.discover.normalize import duration_from_runtime

        refs = [{"simkl_id": sid, "catalog": catalog} for sid in missing_by_show]
        page_sync = sync_items_for_refs(catalog, refs)
        thin = [row for row in (page_sync or []) if not _show_sync_row_has_runtime(row)]
        if thin:
            enrich_page_for_paint(catalog, thin, force_detail=False)

        for show_id, indices in missing_by_show.items():
            ctx = load_show_menu_context(show_id)
            show_info = (ctx or {}).get("show_info") or {}
            if not show_info or not duration_from_runtime(show_info.get("runtime")):
                from resources.lib.simkl.enrich import enrich_page_for_paint

                enrich_page_for_paint(
                    catalog,
                    [{"simkl_id": show_id, "catalog": catalog}],
                    force_detail=True,
                )
                ctx = load_show_menu_context(show_id)
                show_info = (ctx or {}).get("show_info") or {}
            if not show_info:
                continue
            for idx in indices:
                row = dict(finalized[idx])
                info = dict(row.get("info") or {})
                inherit_show_fields(info, show_info)
                finalize_playback_info(info)
                row["info"] = info
                finalized[idx] = row

    return finalized


def finish_episode_parent_paint(
    episode_rows: list[dict],
    catalog: str,
    *,
    paint_profile: str | None = None,
) -> tuple[list[dict], list[dict], str]:
    """After DB episode load: warm parent cast, overlay Simkl show metadata, queue background enrich."""
    from resources.lib.database.session import get_sync_database
    from resources.lib.meta.menu_paint_profile import MenuPaintProfile
    from resources.lib.meta.paint_cache import _prepare_paint_rows
    from resources.lib.simkl.ids import show_id_from_item

    show_ids = sorted(
        {
            int(show_id_from_item(row))
            for row in episode_rows
            if show_id_from_item(row) is not None
        }
    )
    _warm_parent_show_cast(show_ids, catalog)
    painted = overlay_mixed_episode_parent_context(episode_rows)
    painted = _finalize_episode_paint_rows(painted, catalog)

    profile = paint_profile or MenuPaintProfile.LIBRARY_EPISODES.value
    db = get_sync_database()
    painted, _episode_refs = _prepare_paint_rows(painted, "episode", db, profile=profile)

    refs = [{"simkl_id": sid, "catalog": catalog} for sid in show_ids]
    parent_media = "anime" if catalog == "anime" else "tvshow"
    return painted, refs, parent_media


def merge_episode_playback_overlay(rows: list[dict], seed_rows: list[dict]) -> list[dict]:
    """Apply fresh bookmark fields from menu seeds onto painted episode rows (Continue Watching)."""
    if not rows or not seed_rows:
        return rows
    by_id: dict[int, dict] = {}
    for seed in seed_rows:
        if not isinstance(seed, dict):
            continue
        simkl_id = seed.get("simkl_id")
        if simkl_id is None:
            continue
        by_id[int(simkl_id)] = seed
    if not by_id:
        return rows

    merged: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        simkl_id = row.get("simkl_id")
        if simkl_id is None:
            merged.append(row)
            continue
        seed = by_id.get(int(simkl_id))
        if not seed:
            merged.append(row)
            continue
        painted = dict(row)
        if seed.get("percent_played") is not None:
            painted["percent_played"] = seed["percent_played"]
        progress = seed.get("resume_time")
        if progress is None:
            progress = seed.get("progress")
        if progress is not None:
            painted["resume_time"] = progress
        if seed.get("force_resume_indicator"):
            painted["force_resume_indicator"] = True
        merged.append(painted)
    return merged


def render_catalog_episodes(
    catalog: str,
    episode_rows: list[dict],
    list_builder,
    **kwargs,
) -> None:
    """Episode menus: warm parent shows in catalog_items, then paint-first episode list."""
    from resources.lib.database.session import get_sync_database
    from resources.lib.discover.renderer import discover_list_kwargs
    from resources.lib.modules.globals import g

    if not episode_rows:
        g.cancel_directory()
        return

    list_kwargs = discover_list_kwargs(**kwargs)
    library_paint = bool(list_kwargs.pop("library_paint", False))
    list_kwargs["catalog"] = catalog
    list_kwargs["catalog_hint"] = catalog

    from resources.lib.meta.menu_paint_profile import MenuPaintProfile
    from resources.lib.pipeline.browse_materialize import materialize_episode_page

    paint_profile = str(
        list_kwargs.get("paint_profile") or MenuPaintProfile.LIBRARY_EPISODES.value
    )
    visible_rows = episode_rows
    if not list_kwargs.get("no_paging"):
        from resources.lib.simkl.menu_helpers import paginate_refs_for_page

        visible_rows = paginate_refs_for_page(episode_rows, g.PAGE)

    visible_rows = materialize_episode_page(
        catalog,
        visible_rows,
        profile=paint_profile,
        library_paint=library_paint,
    )

    cached_rows = peek_episode_page_cache(
        catalog,
        visible_rows,
        paint_profile=paint_profile,
    )

    db = get_sync_database()
    filter_params = list_builder._apply_list_filters(dict(list_kwargs))
    if cached_rows is not None:
        list_kwargs["preloaded_episode_rows"] = merge_episode_playback_overlay(cached_rows, visible_rows)
    else:
        upsert_episode_parent_shows(visible_rows, catalog)
        if library_paint:
            prefetch_episode_parent_simkl_detail(visible_rows, catalog)
        list_kwargs = attach_preloaded_episode_paint(
            catalog,
            visible_rows,
            list_kwargs,
            db,
            filter_params=filter_params,
        )
        preloaded = list_kwargs.get("preloaded_episode_rows")
        if preloaded is not None:
            list_kwargs["preloaded_episode_rows"] = merge_episode_playback_overlay(preloaded, visible_rows)

    from resources.lib.meta.list_pipeline import resolve_list_flags

    list_kwargs.update(
        resolve_list_flags(
            list_kwargs,
            seeded=True,
            preloaded=bool(list_kwargs.get("preloaded_episode_rows")),
        )
    )
    render_rows = episode_rows if list_kwargs.get("no_paging") else visible_rows
    list_builder.mixed_episode_builder(render_rows, **list_kwargs)


def paint_drilldown_rows(
    rows: list[dict],
    provider_media_type: str,
    db,
    *,
    hide_unaired: bool = False,
    hide_watched: bool = False,
) -> list[dict]:
    """Simkl-only season/episode drilldown paint (no provider cast/art HTTP)."""
    if not rows:
        return rows

    from resources.lib.meta.menu_paint_profile import MenuPaintProfile
    from resources.lib.meta.paint_cache import _apply_list_filters, _prepare_paint_rows
    from resources.lib.meta.paint_complete import row_paint_complete_drilldown

    if all(row_paint_complete_drilldown(row) for row in rows):
        filtered: list[dict] = []
        for row in rows:
            if _apply_list_filters(
                row,
                provider_media_type,
                hide_unaired=hide_unaired,
                hide_watched=hide_watched,
            ):
                continue
            filtered.append(row)
        return filtered

    prepared, _ = _prepare_paint_rows(
        rows,
        provider_media_type,
        db,
        profile=MenuPaintProfile.DRILLDOWN.value,
    )

    filtered: list[dict] = []
    for row in prepared:
        if _apply_list_filters(
            row,
            provider_media_type,
            hide_unaired=hide_unaired,
            hide_watched=hide_watched,
        ):
            continue
        filtered.append(row)
    return filtered


def _drilldown_catalog_for_show(show_id: int) -> str:
    from resources.lib.database.session import get_sync_database

    return get_sync_database().show_catalog(int(show_id)) or "tv"


def _resolve_drilldown_catalog(show_id: int, paint_kwargs: dict, extra_kwargs: dict | None = None) -> str:
    """Prefer sync DB anime profile over stale action_args catalog=tv."""
    db_catalog = _drilldown_catalog_for_show(show_id)
    merged = extra_kwargs or {}
    hint_catalog = paint_kwargs.get("catalog") or merged.get("catalog")
    if db_catalog == "anime":
        return "anime"
    if hint_catalog in ("movie", "tv", "anime"):
        return str(hint_catalog)
    return db_catalog


def _warm_drilldown_parent_show(show_id: int, catalog: str) -> None:
    """Ensure parent show row exists locally — no provider HTTP on drilldown open."""
    ctx = load_show_menu_context(show_id)
    if ctx and not _show_menu_context_sparse(ctx):
        return

    from resources.lib.discover.catalog_store import sync_items_for_refs
    from resources.lib.discover.sync_bridge import insert_discover_page

    refs = [{"simkl_id": int(show_id), "catalog": catalog}]
    page_sync = sync_items_for_refs(catalog, refs)
    if page_sync:
        insert_discover_page(catalog, page_sync)


def _drilldown_paint_kwargs(*, fast_open: bool = False, **kwargs) -> dict:
    from resources.lib.meta.menu_paint_profile import MenuPaintProfile, profile_list_kwargs

    merged = dict(kwargs)
    if fast_open:
        merged["drilldown_fast_open"] = True
    return profile_list_kwargs(MenuPaintProfile.DRILLDOWN, **merged)


def render_catalog_seasons(show_id: int, list_builder, **kwargs) -> None:
    """Season drilldown through the unified paint pipeline (MenuPaintProfile.DRILLDOWN)."""
    import time

    from resources.lib.simkl.menu_parent_refresh import capture_parent_folder_for_show

    capture_parent_folder_for_show(show_id)
    from resources.lib.database.session import get_sync_database
    from resources.lib.meta.menu_perf import note_phase_ms, paint_complete_stats, trace_menu_open
    from resources.lib.modules.globals import g
    from resources.lib.net.request_policy import policy_from_settings

    policy_from_settings().reset_menu_budget()
    from resources.lib.pipeline.drilldown_page import drilldown_fast_open_enabled

    fast_enabled = drilldown_fast_open_enabled()
    paint_kwargs = _drilldown_paint_kwargs(**kwargs)
    show_ctx = load_show_menu_context(show_id)
    if _show_menu_context_sparse(show_ctx):
        sync_row = _fetch_show_sync_row(show_id)
        if isinstance(sync_row, dict) and _show_needs_provider_enrich(sync_row):
            ensure_show_metadata(show_id)
        show_ctx = load_show_menu_context(show_id)
    set_show_menu_plugin_category(show_ctx)

    catalog = _resolve_drilldown_catalog(show_id, paint_kwargs, kwargs)
    _warm_drilldown_parent_show(show_id, catalog)

    db = get_sync_database()
    path = "drilldown_db"
    rows: list[dict] | None = None
    if fast_enabled:
        from resources.lib.pipeline.drilldown_page import build_season_menu_rows

        fast_kwargs = _drilldown_paint_kwargs(fast_open=True, **kwargs)
        sync_started = time.time()
        rows = build_season_menu_rows(
            show_id,
            catalog,
            db=db,
            show_ctx=show_ctx,
            paint_kwargs=fast_kwargs,
        )
        sync_ms = (time.time() - sync_started) * 1000.0
        if rows:
            path = "drilldown_fast"
            paint_kwargs = fast_kwargs
            g.log(
                f"Menu perf: action=showSeasons path=drilldown_fast rows={len(rows)} sync_db_ms={sync_ms:.0f}",
                "info",
            )

    if not rows:
        path = "drilldown_db"
        query_kwargs = {
            key: paint_kwargs[key]
            for key in ("hide_unaired", "hide_watched", "hide_specials", "skip_update", "skip_mill")
            if key in paint_kwargs
        }
        query_kwargs["skip_watch_refresh"] = False
        query_kwargs["force_watch_refresh"] = True
        season_fetch = db.get_anime_season_list if catalog == "anime" else db.get_season_list
        rows = season_fetch(show_id, **query_kwargs)

    if not rows:
        g.cancel_directory()
        return

    rows = _prepare_season_drilldown_rows(rows)
    rows = overlay_parent_context_on_rows(rows, show_ctx, show_id=int(show_id))

    action = (g.REQUEST_PARAMS or {}).get("action") or "showSeasons"
    with trace_menu_open(action, catalog=catalog, path=path) as perf_ctx:
        finalize_started = time.time()
        rows = paint_drilldown_rows(
            rows,
            "tvshow",
            db,
            hide_unaired=bool(paint_kwargs.get("hide_unaired", False)),
            hide_watched=bool(paint_kwargs.get("hide_watched", False)),
        )
        note_phase_ms(perf_ctx, "finalize_ms", finalize_started)
        complete, total = paint_complete_stats(rows, profile="drilldown")
        perf_ctx.update(row_count=len(rows), complete=complete, total=total)
        builder_started = time.time()
        list_builder.season_list_builder(show_id, media_list=rows, **paint_kwargs)
        note_phase_ms(perf_ctx, "builder_ms", builder_started)

    if path == "drilldown_fast":
        from resources.lib.meta.list_pipeline import defer_drilldown_persist

        defer_drilldown_persist(show_id, catalog, scope="seasons")
def render_catalog_drilldown_episodes(
    show_id: int,
    list_builder,
    *,
    season: int | None = None,
    **kwargs,
) -> None:
    """Episode drilldown (season or flat) through the unified paint pipeline."""
    import time

    from resources.lib.simkl.menu_parent_refresh import (
        capture_parent_folder_for_show,
        capture_season_list_folder_for_show,
    )

    capture_parent_folder_for_show(show_id)
    if season is not None:
        capture_season_list_folder_for_show(show_id)

    from resources.lib.database.session import get_sync_database
    from resources.lib.meta.menu_perf import note_phase_ms, paint_complete_stats, trace_menu_open
    from resources.lib.modules.globals import g
    from resources.lib.net.request_policy import policy_from_settings

    policy_from_settings().reset_menu_budget()
    from resources.lib.pipeline.drilldown_page import drilldown_fast_open_enabled

    fast_enabled = drilldown_fast_open_enabled()
    paint_kwargs = _drilldown_paint_kwargs(**kwargs)
    show_ctx = load_show_menu_context(show_id)
    if _show_menu_context_sparse(show_ctx):
        sync_row = _fetch_show_sync_row(show_id)
        if isinstance(sync_row, dict) and _show_needs_provider_enrich(sync_row):
            ensure_show_metadata(show_id)
        show_ctx = load_show_menu_context(show_id)
    season_ctx = load_season_menu_context(show_id, season) if season is not None else None
    set_show_menu_plugin_category(show_ctx, season_num=season)

    catalog = _resolve_drilldown_catalog(show_id, paint_kwargs, kwargs)
    _warm_drilldown_parent_show(show_id, catalog)

    flat_list = season is None
    db = get_sync_database()
    path = "drilldown_db"
    rows: list[dict] | None = None
    if fast_enabled:
        from resources.lib.pipeline.drilldown_page import build_episode_menu_rows

        fast_kwargs = _drilldown_paint_kwargs(fast_open=True, **kwargs)
        sync_started = time.time()
        rows = build_episode_menu_rows(
            show_id,
            catalog,
            season,
            flat_all=flat_list,
            db=db,
            show_ctx=show_ctx,
            season_ctx=season_ctx,
            paint_kwargs=fast_kwargs,
        )
        sync_ms = (time.time() - sync_started) * 1000.0
        if rows:
            path = "drilldown_fast"
            paint_kwargs = fast_kwargs
            action_name = "flatEpisodes" if flat_list else "seasonEpisodes"
            g.log(
                f"Menu perf: action={action_name} path=drilldown_fast rows={len(rows)} sync_db_ms={sync_ms:.0f}",
                "info",
            )

    if not rows:
        path = "drilldown_db"
        query_kwargs = {
            key: paint_kwargs[key]
            for key in (
                "hide_unaired",
                "hide_watched",
                "hide_specials",
                "skip_update",
                "skip_mill",
            )
            if key in paint_kwargs
        }
        query_kwargs["skip_watch_refresh"] = False
        query_kwargs["force_watch_refresh"] = True
        if flat_list:
            query_kwargs["flat_all"] = True
        episode_fetch = db.get_anime_episode_list if catalog == "anime" else db.get_episode_list
        rows = episode_fetch(show_id, season=season, **query_kwargs)

    if not rows:
        g.cancel_directory()
        return

    rows = overlay_parent_context_on_rows(
        rows,
        show_ctx,
        season_ctx=season_ctx,
        show_id=int(show_id),
    )

    action = (g.REQUEST_PARAMS or {}).get("action") or ("flatEpisodes" if flat_list else "seasonEpisodes")
    with trace_menu_open(action, catalog=catalog, path=path) as perf_ctx:
        finalize_started = time.time()
        rows = paint_drilldown_rows(
            rows,
            "tvshow",
            db,
            hide_unaired=bool(paint_kwargs.get("hide_unaired", False)),
            hide_watched=bool(paint_kwargs.get("hide_watched", False)),
        )
        note_phase_ms(perf_ctx, "finalize_ms", finalize_started)
        complete, total = paint_complete_stats(rows, profile="drilldown")
        perf_ctx.update(row_count=len(rows), complete=complete, total=total)
        builder_kwargs = dict(paint_kwargs)
        if flat_list:
            builder_kwargs["no_paging"] = True
        builder_started = time.time()
        list_builder.episode_list_builder(
            show_id,
            season=season,
            media_list=rows,
            **builder_kwargs,
        )
        note_phase_ms(perf_ctx, "builder_ms", builder_started)

    if path == "drilldown_fast":
        from resources.lib.meta.list_pipeline import defer_drilldown_persist

        defer_drilldown_persist(
            show_id,
            catalog,
            scope="flat" if flat_list else "episodes",
            season_num=season,
        )


def _cast_is_missing(row: dict) -> bool:
    cast = row.get("cast")
    return not cast or not isinstance(cast, list) or len(cast) == 0


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


_SHOW_MENU_CTX_CACHE: dict[tuple[int, int], dict[str, Any]] = {}


def clear_show_menu_context_cache() -> None:
    _SHOW_MENU_CTX_CACHE.clear()


def _finalize_anime_show_context(show_ctx: dict[str, Any] | None, simkl_show_id: int) -> dict[str, Any] | None:
    if not isinstance(show_ctx, dict):
        return show_ctx
    info = show_ctx.get("show_info")
    if not isinstance(info, dict):
        return show_ctx
    if not (info.get("catalog") == "anime" or info.get("mal_id")):
        return show_ctx

    from resources.lib.simkl.field_map import ensure_anime_title_slots

    ensure_anime_title_slots(info)
    if info.get("title") or info.get("tvshowtitle"):
        show_ctx["title"] = info.get("title") or info.get("tvshowtitle")
    return show_ctx


def _fetch_show_sync_row(simkl_id: int, *, catalog: str | None = None) -> dict[str, Any] | None:
    from resources.lib.database.session import get_sync_database
    from resources.lib.database.simkl_sync.serial_sync import serial_tables

    cat = catalog or _drilldown_catalog_for_show(int(simkl_id))
    st = serial_tables("anime" if cat == "anime" else "tv")
    return get_sync_database().fetchone(
        f"""
        SELECT simkl_id, info, art, [cast], season_count, episode_count
        FROM {st.show}
        WHERE simkl_id = ?
        """,
        (int(simkl_id),),
    )


def _show_context_from_sync_row(row: dict[str, Any]) -> dict[str, Any]:
    sid = int(row["simkl_id"])
    info = _copy_mapping(row.get("info"))
    info.setdefault("simkl_id", sid)
    if row.get("season_count") is not None:
        info.setdefault("season_count", row["season_count"])
    if row.get("episode_count") is not None:
        info.setdefault("episode_count", row["episode_count"])
    return {
        "title": info.get("title") or info.get("tvshowtitle"),
        "show_info": info,
        "show_art": _copy_mapping(row.get("art")),
        "show_cast": list(row.get("cast") or []),
    }


def _merge_painted_show_with_sync_row(
    painted_info: dict[str, Any],
    painted_art: dict[str, Any],
    painted_cast: list,
    sync_row: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list]:
    """Fill display-cache gaps from the sync DB after display_meta migration clears."""
    from resources.lib.common import tools as merge_tools
    from resources.lib.database.sync_meta_cache import row_has_plot_meta

    db_ctx = _show_context_from_sync_row(sync_row)
    db_info = db_ctx["show_info"]
    db_art = db_ctx["show_art"]
    db_cast = db_ctx["show_cast"]

    info = merge_tools.smart_merge_dictionary(
        dict(db_info),
        dict(painted_info),
        keep_original=True,
        extend_array=False,
    )
    if not row_has_plot_meta({"info": painted_info}) and row_has_plot_meta({"info": db_info}):
        for key in ("plot", "overview", "genre", "mpaa", "status", "studio"):
            if db_info.get(key) and not info.get(key):
                info[key] = db_info[key]
        for key in db_info:
            if str(key).startswith("rating.") and not info.get(key):
                info[key] = db_info[key]

    art = merge_tools.smart_merge_dictionary(
        dict(db_art),
        dict(painted_art),
        keep_original=True,
        extend_array=False,
    )
    cast = painted_cast if painted_cast else db_cast
    return info, art, cast


def _show_menu_context_sparse(show_ctx: dict[str, Any] | None) -> bool:
    if not show_ctx:
        return True
    from resources.lib.database.sync_meta_cache import row_has_display_meta, row_has_plot_meta

    pseudo = {
        "info": show_ctx.get("show_info") or {},
        "art": show_ctx.get("show_art") or {},
    }
    if not row_has_display_meta(pseudo):
        return True
    if not row_has_plot_meta(pseudo):
        return True
    cast = show_ctx.get("show_cast")
    return not cast or not isinstance(cast, list) or len(cast) == 0


def _show_needs_provider_enrich(row: dict) -> bool:
    if _cast_is_missing(row):
        return True
    info = row.get("info") if isinstance(row.get("info"), dict) else {}
    if not info.get("plot") and not info.get("overview"):
        return True
    art = row.get("art") if isinstance(row.get("art"), dict) else {}
    return not art.get("poster") and not art.get("thumb") and not art.get("fanart")


def load_show_menu_context(simkl_show_id: int) -> dict[str, Any] | None:
    """Load parent show info/art/cast for season and episode folder menus."""
    if not simkl_show_id:
        return None

    sid = int(simkl_show_id)
    from resources.lib.modules.globals import g

    cache_key = (sid, g.get_int_setting("general.anime.titlelanguage"))
    cached_ctx = _SHOW_MENU_CTX_CACHE.get(cache_key)
    if cached_ctx is not None:
        return cached_ctx

    from resources.lib.database.sync_meta_cache import row_has_display_meta
    from resources.lib.meta.display_store import get_display_meta_store

    sync_row = _fetch_show_sync_row(sid)
    painted = get_display_meta_store().get_row("tvshow", sid)
    if painted and row_has_display_meta(painted):
        info = _copy_mapping(painted.get("info"))
        art = _copy_mapping(painted.get("art"))
        cast = list(painted.get("cast") or [])
        if isinstance(sync_row, dict):
            from resources.lib.database.sync_meta_cache import row_has_plot_meta

            painted_sparse = not row_has_plot_meta(painted) or _cast_is_missing(painted)
            info, art, cast = _merge_painted_show_with_sync_row(info, art, cast, sync_row)
            if painted_sparse:
                get_display_meta_store().set_row(
                    "tvshow",
                    {
                        "simkl_id": sid,
                        "info": info,
                        "art": art,
                        "cast": cast,
                    },
                )
        show_ctx = {
            "title": info.get("title") or info.get("tvshowtitle"),
            "show_info": info,
            "show_art": art,
            "show_cast": cast,
        }
        show_ctx = _finalize_anime_show_context(show_ctx, sid)
        _SHOW_MENU_CTX_CACHE[cache_key] = show_ctx
        return show_ctx

    if not isinstance(sync_row, dict):
        return None

    show_ctx = _show_context_from_sync_row(sync_row)
    show_ctx = _finalize_anime_show_context(show_ctx, sid)
    _SHOW_MENU_CTX_CACHE[cache_key] = show_ctx
    return show_ctx


def load_season_menu_context(
    simkl_show_id: int,
    season_num: int,
    *,
    catalog: str | None = None,
) -> dict[str, Any] | None:
    """Optional season art/info when drilling into a single season's episodes."""
    if not simkl_show_id or season_num is None:
        return None

    from resources.lib.database.session import get_sync_database
    from resources.lib.database.simkl_sync.serial_access import profile_for_catalog
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope

    db = get_sync_database()
    resolved_catalog = catalog or db.show_catalog(int(simkl_show_id)) or "tv"
    with serial_profile_scope(db, profile_for_catalog(resolved_catalog)):
        season_table = db._st().season
        row = db.fetchone(
            f"""
            SELECT info, art, [cast]
            FROM {season_table}
            WHERE simkl_show_id = ? AND season = ?
            """,
            (int(simkl_show_id), int(season_num)),
        )
    if not isinstance(row, dict):
        return None

    return {
        "season_info": _copy_mapping(row.get("info")),
        "season_art": _copy_mapping(row.get("art")),
        "season_cast": list(row.get("cast") or []),
    }


def overlay_mixed_episode_parent_context(episode_rows: list[dict]) -> list[dict]:
    """Merge parent show info/art/cast onto mixed-episode menu rows after DB load."""
    from resources.lib.simkl.ids import show_id_from_item

    show_ctx_cache: dict[int, dict[str, Any]] = {}
    enriched: list[dict] = []
    for row in episode_rows:
        if not isinstance(row, dict):
            enriched.append(row)
            continue
        show_id = show_id_from_item(row)
        if show_id is None:
            enriched.append(row)
            continue
        sid = int(show_id)
        if sid not in show_ctx_cache:
            show_ctx_cache[sid] = load_show_menu_context(sid)
        ctx = show_ctx_cache.get(sid)
        if ctx:
            enriched.append(overlay_parent_context_on_rows([row], ctx)[0])
        else:
            enriched.append(row)
    return enriched


def _prepare_season_drilldown_rows(rows: list[dict]) -> list[dict]:
    """Ensure DB season rows are labeled as seasons (not parent show titles)."""
    from resources.lib.simkl.field_map import ensure_season_title

    prepared: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            prepared.append(row)
            continue
        item = dict(row)
        info = item.get("info")
        if not isinstance(info, dict):
            info = {}
        else:
            info = dict(info)
        season_num = item.get("season")
        if season_num is not None:
            info["season"] = int(season_num)
        info["mediatype"] = "season"
        show_title = info.get("tvshowtitle") or info.get("tvshow")
        if isinstance(show_title, dict):
            show_title = show_title.get("title")
        title = info.get("title")
        if title and show_title and str(title).strip() == str(show_title).strip():
            info.pop("title", None)
        ensure_season_title(info)
        item["info"] = info
        prepared.append(item)
    return prepared


def _fill_missing_display_fields(
    target_info: dict[str, Any],
    show_info: dict[str, Any],
    *,
    episode_safe: bool = False,
) -> None:
    """Copy show-level display fields when the child row is still sparse."""
    keys: tuple[str, ...]
    if episode_safe:
        keys = ("genre", "genres", "studio", "status", "mpaa", "rating", "runtime")
    else:
        keys = ("plot", "overview", "genre", "genres", "studio", "status", "mpaa", "rating", "runtime")
    for key in keys:
        if not target_info.get(key) and show_info.get(key):
            target_info[key] = show_info[key]
    for key in ("title_en", "title_romaji", "originaltitle"):
        if not target_info.get(key) and show_info.get(key):
            target_info[key] = show_info[key]


def _apply_parent_show_episode_thumb(merged: dict[str, Any]) -> None:
    """Use parent show/season poster as episode list thumb when no per-episode still exists."""
    info = merged.get("info") if isinstance(merged.get("info"), dict) else {}
    if (info.get("mediatype") or "").lower() != "episode":
        return
    art = merged.setdefault("art", {})
    if art.get("thumb") or info.get("thumb"):
        return
    thumb = (
        art.get("poster")
        or art.get("season.poster")
        or art.get("tvshow.poster")
        or art.get("fanart")
        or art.get("season.fanart")
        or art.get("tvshow.fanart")
    )
    if not thumb:
        return
    art["thumb"] = thumb
    info["thumb"] = thumb


def _parent_context_stamp(show_id: int, season_num: int | None = None) -> tuple[int, int | None, int]:
    from resources.lib.modules.globals import g

    return (
        int(show_id),
        int(season_num) if season_num is not None else None,
        g.get_int_setting("general.anime.titlelanguage"),
    )


def _resolve_parent_episode_thumb(
    show_art: dict[str, Any] | None,
    season_art: dict[str, Any] | None,
) -> str | None:
    show_art = show_art if isinstance(show_art, dict) else {}
    season_art = season_art if isinstance(season_art, dict) else {}
    return (
        season_art.get("poster")
        or season_art.get("thumb")
        or show_art.get("poster")
        or show_art.get("thumb")
        or show_art.get("fanart")
    )


def _overlay_episode_row_fast(
    row: dict,
    *,
    show_info: dict[str, Any] | None,
    show_art: dict[str, Any] | None,
    show_cast: list | None,
    season_info: dict[str, Any] | None,
    season_art: dict[str, Any] | None,
    season_cast: list | None,
    parent_thumb: str | None,
    stamp: tuple[int, int | None],
) -> dict:
    item = dict(row)
    info = dict(item.get("info") or {})
    art = dict(item.get("art") or {})
    if show_info:
        catalog = info.get("catalog") or show_info.get("catalog")
        if catalog == "anime":
            from resources.lib.simkl.field_map import localized_anime_show_title

            localized = localized_anime_show_title(info, source=show_info)
            if localized:
                info["tvshowtitle"] = localized
        elif not info.get("tvshowtitle"):
            info["tvshowtitle"] = show_info.get("title")
        if not info.get("tmdb_show_id") and show_info.get("tmdb_id"):
            info["tmdb_show_id"] = show_info.get("tmdb_id")
        if not info.get("tvdb_show_id") and show_info.get("tvdb_id"):
            info["tvdb_show_id"] = show_info.get("tvdb_id")
        if not info.get("year") and show_info.get("year"):
            info["year"] = show_info.get("year")
        _fill_missing_display_fields(info, show_info, episode_safe=True)
    if season_info and not info.get("simkl_season_id"):
        info["simkl_season_id"] = season_info.get("simkl_id")

    merged = {"info": info, "art": art, "cast": list(item.get("cast") or [])}
    from resources.lib.modules.metadataHandler import MetadataHandler

    MetadataHandler._show_season_art_fallback(merged, season_art, show_art)
    MetadataHandler._add_season_show_art(merged, season_art, show_art)
    MetadataHandler._add_season_show_cast(merged, season_cast, show_cast)
    _apply_parent_show_episode_thumb(merged)
    if parent_thumb and not merged["art"].get("thumb") and not merged["info"].get("thumb"):
        merged["art"]["thumb"] = parent_thumb
        merged["info"]["thumb"] = parent_thumb

    item["info"] = merged["info"]
    item["art"] = merged["art"]
    if merged.get("cast"):
        item["cast"] = merged["cast"]
    item["_parent_ctx"] = stamp
    return item


def overlay_parent_context_on_rows(
    rows: list[dict],
    show_ctx: dict[str, Any] | None,
    *,
    season_ctx: dict[str, Any] | None = None,
    show_id: int | None = None,
) -> list[dict]:
    """Attach parent show (and optional season) metadata to season/episode menu rows."""
    if not rows or not show_ctx:
        return rows

    show_info = show_ctx.get("show_info")
    show_art = show_ctx.get("show_art")
    show_cast = show_ctx.get("show_cast")
    season_info = (season_ctx or {}).get("season_info")
    season_art = (season_ctx or {}).get("season_art")
    season_cast = (season_ctx or {}).get("season_cast")
    resolved_show_id = show_id
    if resolved_show_id is None and isinstance(show_info, dict):
        resolved_show_id = show_info.get("simkl_id")
    season_num = season_info.get("season") if isinstance(season_info, dict) else None
    stamp = _parent_context_stamp(int(resolved_show_id), season_num) if resolved_show_id else None

    if stamp and all(isinstance(row, dict) and row.get("_parent_ctx") == stamp for row in rows):
        return rows

    episode_only = all(
        isinstance(row, dict) and (row.get("info") or {}).get("mediatype", "").lower() == "episode"
        for row in rows
    )
    parent_thumb = _resolve_parent_episode_thumb(show_art, season_art) if episode_only else None

    if episode_only and stamp:
        return [
            _overlay_episode_row_fast(
                row,
                show_info=show_info,
                show_art=show_art,
                show_cast=show_cast,
                season_info=season_info,
                season_art=season_art,
                season_cast=season_cast,
                parent_thumb=parent_thumb,
                stamp=stamp,
            )
            if isinstance(row, dict)
            else row
            for row in rows
        ]

    from resources.lib.modules.metadataHandler import MetadataHandler

    enriched: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            enriched.append(row)
            continue

        item = dict(row)
        item["info"] = _copy_mapping(item.get("info"))
        item["art"] = _copy_mapping(item.get("art"))
        item.setdefault("cast", item.get("cast") or [])

        merged = {"info": item["info"], "art": item["art"], "cast": list(item.get("cast") or [])}
        MetadataHandler._show_season_art_fallback(merged, season_art, show_art)
        MetadataHandler._add_season_show_info(merged, season_info, show_info)
        MetadataHandler._add_season_show_art(merged, season_art, show_art)
        MetadataHandler._add_season_show_cast(merged, season_cast, show_cast)
        if show_info:
            _fill_missing_display_fields(merged["info"], show_info, episode_safe=True)
            if (merged["info"].get("mediatype") or "").lower() == "episode":
                catalog = merged["info"].get("catalog") or show_info.get("catalog")
                if catalog == "anime":
                    from resources.lib.simkl.field_map import localized_anime_show_title

                    localized = localized_anime_show_title(merged["info"], source=show_info)
                    if localized:
                        merged["info"]["tvshowtitle"] = localized
        if (merged["info"].get("mediatype") or "").lower() != "episode":
            _apply_parent_show_episode_thumb(merged)

        item["info"] = merged["info"]
        item["art"] = merged["art"]
        if merged.get("cast"):
            item["cast"] = merged["cast"]
        if show_info:
            mediatype = (merged["info"].get("mediatype") or "").lower()
            if mediatype != "episode":
                for count_key in ("season_count", "episode_count"):
                    if show_info.get(count_key) is not None:
                        item.setdefault(count_key, show_info[count_key])
        if stamp:
            item["_parent_ctx"] = stamp
        enriched.append(item)

    return enriched


def set_show_menu_plugin_category(
    show_ctx: dict[str, Any] | None,
    *,
    season_num: int | None = None,
) -> None:
    """Set Kodi folder header from parent show (and season when applicable)."""
    if not show_ctx:
        return
    title = show_ctx.get("title")
    if not title:
        return

    import xbmcplugin

    from resources.lib.modules.globals import g

    label = str(title)
    if season_num is not None:
        label = f"{label} - Season {int(season_num)}"
    xbmcplugin.setPluginCategory(g.PLUGIN_HANDLE, label)


def ensure_show_metadata(simkl_show_id: int) -> None:
    """Fetch missing cast/art for one show (blocking, used on season drill-in)."""
    if not simkl_show_id:
        return
    from resources.lib.database.session import get_sync_database

    db = get_sync_database()
    from resources.lib.database.simkl_sync.serial_access import fetch_show_row

    catalog = db.show_catalog(int(simkl_show_id)) or "tv"
    row = fetch_show_row(
        db,
        catalog,
        int(simkl_show_id),
        columns="simkl_id, info, [cast], art, tmdb_id, tvdb_id, imdb_id, last_updated",
    )
    if not isinstance(row, dict):
        return
    if not _show_needs_provider_enrich(row):
        return

    paint_media = "anime" if catalog == "anime" else "tvshow"
    handler = db.metadataHandler
    merged, refs = handler.merge_list_meta_local([row], paint_media, db=db)
    if not refs:
        refs = [{"simkl_id": int(simkl_show_id), "needs_update": True, "_provider_type": "tvshow"}]
    handler.enrich_list_meta_online(refs, paint_media, db=db, persist=True)


def ensure_show_metadata_async(simkl_show_id: int) -> None:
    """Warm cast/art for a show the user is opening — does not block the menu."""
    if not simkl_show_id:
        return

    from resources.lib.modules.globals import g

    def _run() -> None:
        try:
            ensure_show_metadata(simkl_show_id)
        except Exception:
            g.log_stacktrace()

    from resources.lib.common.thread_pool import defer_background

    defer_background(_run, name=f"prism-show-meta-{int(simkl_show_id)}")

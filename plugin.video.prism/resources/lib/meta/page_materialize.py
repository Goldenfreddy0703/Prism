"""Sync-time and prefetch page materialization (Simkl detail + provider paint + display_meta stamp)."""
from __future__ import annotations

import threading
from typing import Any

_materialize_lock = threading.Lock()
_materialize_inflight: set[str] = set()


def _materialize_dedupe_key(catalog: str, refs: list[dict]) -> str:
    ids: list[int] = []
    for ref in refs or []:
        if isinstance(ref, dict) and ref.get("simkl_id") is not None:
            ids.append(int(ref["simkl_id"]))
    ids.sort()
    return f"{catalog}:{','.join(str(i) for i in ids)}"


def _try_acquire_materialize(key: str) -> bool:
    with _materialize_lock:
        if key in _materialize_inflight:
            return False
        _materialize_inflight.add(key)
        return True


def _release_materialize(key: str) -> None:
    with _materialize_lock:
        _materialize_inflight.discard(key)


def stamp_page_rows_to_display_meta(catalog: str, rows: list[dict[str, Any]], *, profile: str = "browse") -> int:
    """Persist paint-complete rows into display_meta with trust stamps."""
    if not rows:
        return 0
    from resources.lib.meta.paint_complete import partition_paint_rows

    paint_media = "movie" if catalog == "movie" else ("anime" if catalog == "anime" else "tvshow")
    movies = [row for row in rows if isinstance(row, dict) and row.get("catalog") == "movie"]
    tv_rows = [row for row in rows if isinstance(row, dict) and row.get("catalog") == "tv"]
    anime_rows = [row for row in rows if isinstance(row, dict) and row.get("catalog") == "anime"]
    written = 0
    from resources.lib.meta.display_store import get_display_meta_store

    store = get_display_meta_store()
    if movies:
        complete, _ = partition_paint_rows(movies, "movie", profile=profile)
        if complete:
            written += store.set_stamped_rows_batch("movie", complete)
    if tv_rows:
        complete, _ = partition_paint_rows(tv_rows, "tvshow", profile=profile)
        if complete:
            written += store.set_stamped_rows_batch("tvshow", complete)
    if anime_rows:
        complete, _ = partition_paint_rows(anime_rows, "anime", profile=profile)
        if complete:
            written += store.set_stamped_rows_batch("anime", complete)
    if not movies and not tv_rows and not anime_rows and rows:
        complete, _ = partition_paint_rows(rows, paint_media, profile=profile)
        store_media = "movie" if catalog == "movie" else paint_media
        if complete:
            written += store.set_stamped_rows_batch(store_media, complete)
    return written


def materialize_browse_page_rows(
    catalog: str,
    refs: list[dict],
    rows: list[dict],
    *,
    profile: str = "browse",
    skip_detail_if_plot_ready: bool = False,
) -> list[dict]:
    """Blocking Simkl detail + provider prepare + coalesce + display_meta stamp."""
    from resources.lib.meta.list_paint import _seren_sync_finalize_page, _seren_sync_simkl_detail_fill
    from resources.lib.meta.paint_cache import coalesce_page_rows_paint_info
    from resources.lib.simkl.enrich import simkl_detail_needed

    if skip_detail_if_plot_ready:
        needs_detail = any(
            isinstance(row, dict) and simkl_detail_needed(row) for row in (rows or [])
        )
        if needs_detail:
            rows = _seren_sync_simkl_detail_fill(catalog, refs, rows)
        rows = coalesce_page_rows_paint_info(catalog, rows)
        from resources.lib.meta.list_paint import _seren_sync_provider_prepare

        rows = _seren_sync_provider_prepare(catalog, rows, profile)
        rows = coalesce_page_rows_paint_info(catalog, rows)
    else:
        rows = _seren_sync_finalize_page(catalog, refs, rows, profile)
    stamp_page_rows_to_display_meta(catalog, rows, profile=profile)
    return rows


def materialize_refs_stamp_from_sync_db(
    catalog: str,
    refs: list[dict],
    *,
    profile: str = "browse",
) -> list[dict]:
    """Background: full provider art + display_meta stamp (no Simkl detail when plot already synced)."""
    from resources.lib.simkl.media_ref import sync_db_rows_for_refs

    rows = sync_db_rows_for_refs(catalog, refs)
    return materialize_browse_page_rows(
        catalog,
        refs,
        rows,
        profile=profile,
        skip_detail_if_plot_ready=True,
    )


def materialize_refs_from_sync_db(
    catalog: str,
    refs: list[dict],
    *,
    profile: str = "browse",
) -> list[dict]:
    """Load sync rows for refs, materialize, and return paint-ready rows."""
    from resources.lib.simkl.media_ref import sync_db_rows_for_refs

    rows = sync_db_rows_for_refs(catalog, refs)
    return materialize_browse_page_rows(catalog, refs, rows, profile=profile)


def schedule_browse_page_materialize(
    catalog: str,
    refs: list[dict],
    *,
    profile: str = "browse",
) -> None:
    """Background full-page materialize (stamps display_meta for warm re-open / scroll)."""
    if not refs:
        return

    key = _materialize_dedupe_key(catalog, refs)
    if not _try_acquire_materialize(key):
        return

    def _work() -> None:
        from resources.lib.modules.globals import g
        from resources.lib.net.request_policy import policy_from_settings

        g.ensure_addon()
        try:
            policy_from_settings().reset_menu_budget()
            materialize_refs_from_sync_db(catalog, refs, profile=profile)
        except Exception:
            g.log_stacktrace()
        finally:
            _release_materialize(key)

    if _schedule_materialize_background(_work):
        return
    _work()


def _schedule_materialize_background(work) -> bool:
    """Run materialize on a daemon thread when Kodi allows background workers."""
    from resources.lib.common.thread_pool import defer_background, prism_plugin_no_threads

    if prism_plugin_no_threads():
        return False
    defer_background(work, name="prism-materialize")
    return True


def schedule_browse_page_materialize_background(
    catalog: str,
    refs: list[dict],
    *,
    profile: str = "browse",
) -> None:
    """Background materialize (catalog pipeline)."""
    schedule_browse_page_materialize(catalog, refs, profile=profile)


def schedule_browse_page_stamp_background(
    catalog: str,
    refs: list[dict],
    *,
    profile: str = "browse",
) -> None:
    """After genre menu open: full art + stamps without repeating Simkl detail."""
    if not refs:
        return

    key = f"stamp:{_materialize_dedupe_key(catalog, refs)}"
    if not _try_acquire_materialize(key):
        return

    def _work() -> None:
        from resources.lib.modules.globals import g
        from resources.lib.net.request_policy import policy_from_settings

        g.ensure_addon()
        try:
            policy_from_settings().reset_menu_budget()
            materialize_refs_stamp_from_sync_db(catalog, refs, profile=profile)
        except Exception:
            g.log_stacktrace()
        finally:
            _release_materialize(key)

    if not _schedule_materialize_background(_work):
        _work()

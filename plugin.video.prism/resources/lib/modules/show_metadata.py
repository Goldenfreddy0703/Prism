"""Hybrid metadata helpers — lazy cast/art when user drills into a show."""
from __future__ import annotations

import threading

from resources.lib.modules.globals import g


def _cast_is_missing(row: dict) -> bool:
    cast = row.get("cast")
    return not cast or not isinstance(cast, list) or len(cast) == 0


def ensure_show_metadata(simkl_show_id: int) -> None:
    """Fetch missing cast/art for one show (blocking, used on season drill-in)."""
    if not simkl_show_id:
        return
    from resources.lib.database.simkl_sync.shows import SimklSyncDatabase

    db = SimklSyncDatabase()
    row = db.fetchone(
        """
        SELECT simkl_id, info, [cast], art, tmdb_id, tvdb_id, imdb_id, last_updated
        FROM shows
        WHERE simkl_id = ?
        """,
        (int(simkl_show_id),),
    )
    if not isinstance(row, dict):
        return
    if not _cast_is_missing(row):
        return

    handler = db.metadataHandler
    merged, refs = handler.merge_list_meta_local([row], "tvshow", db=db)
    if not refs:
        refs = [{"simkl_id": int(simkl_show_id), "needs_update": True, "_provider_type": "tvshow"}]
    handler.enrich_list_meta_online(refs, "tvshow", db=db, persist=True)


def ensure_show_metadata_async(simkl_show_id: int) -> None:
    """Warm cast/art for a show the user is opening — does not block the menu."""
    if not simkl_show_id:
        return
    from resources.lib.modules.meta_enrichment_queue import meta_enrichment_background

    if not meta_enrichment_background():
        ensure_show_metadata(simkl_show_id)
        return

    def _run() -> None:
        try:
            ensure_show_metadata(simkl_show_id)
        except Exception:
            g.log_stacktrace()

    threading.Thread(target=_run, daemon=True, name=f"prism-show-meta-{int(simkl_show_id)}").start()

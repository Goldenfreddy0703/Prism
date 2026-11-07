"""Seren-style page warmup: batch _update_* for visible refs (prefetch / background)."""
from __future__ import annotations


def warmup_sync_page_refs(catalog: str, refs: list[dict]) -> None:
    """Run hash-gated MetadataHandler.update for a page of simkl ids."""
    media_list = [
        dict(row)
        for row in (refs or [])
        if isinstance(row, dict) and row.get("simkl_id") is not None
    ]
    if not media_list:
        return
    from resources.lib.database.session import get_sync_database

    db = get_sync_database()
    if catalog == "movie":
        db._update_movies(media_list)
        return
    db._update_shows(media_list)


def warmup_sync_mixed_refs(items: list[dict]) -> None:
    from resources.lib.simkl.media_ref import partition_by_catalog

    movies, tv, anime = partition_by_catalog(items)
    for cat, group in (("movie", movies), ("tv", tv), ("anime", anime)):
        if group:
            warmup_sync_page_refs(cat, group)

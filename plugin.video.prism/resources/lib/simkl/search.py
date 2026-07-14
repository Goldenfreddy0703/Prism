"""Simkl search helpers — delegates to media_ref."""
from __future__ import annotations

from resources.lib.simkl.media_ref import fetch_search_page, persist_search_results


def _catalog_from_search_context(url: str, media_type: str) -> str:
    if "anime" in (url or "") or "anime" in (media_type or ""):
        return "anime"
    if "movie" in (url or "") or media_type == "movies":
        return "movie"
    return "tv"


def search_page(
    url: str,
    media_type: str,
    page: int,
    page_limit: int,
    query: str,
) -> list[dict]:
    """Fetch + normalize search results (no enrich/insert — use :func:`persist_search_results`)."""
    catalog = _catalog_from_search_context(url, media_type)
    return fetch_search_page(catalog, query, page, page_limit)


__all__ = ["fetch_search_page", "persist_search_results", "search_page"]

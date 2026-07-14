"""Resolve Simkl browse payloads to Prism storage catalogs (movie / tv / anime)."""
from __future__ import annotations

from typing import Any


def simkl_anime_type(item: dict[str, Any]) -> str | None:
    raw = item.get("anime_type") or item.get("animeType")
    if raw is None:
        return None
    text = str(raw).strip().lower()
    return text or None


def is_anime_movie_item(item: dict[str, Any], list_catalog: str = "") -> bool:
    """True when Simkl marks an anime catalog entry as a standalone film."""
    if simkl_anime_type(item) == "movie":
        return True
    simkl_type = str(item.get("type") or item.get("endpoint_type") or "").lower()
    if list_catalog == "anime" and simkl_type in ("movie", "movies"):
        return True
    return False


def catalog_from_simkl_url(url: str | None) -> str | None:
    """Infer movie / tv / anime from Simkl path (CDN ``url`` or website URL)."""
    if not url:
        return None
    path = str(url).strip().lower()
    if "/anime/" in path:
        return "anime"
    if "/movies/" in path or path.startswith("movies/"):
        return "movie"
    if "/tv/" in path or path.startswith("tv/"):
        return "tv"
    return None


def resolve_item_catalog(item: dict[str, Any], list_catalog: str) -> str:
    """Map a Simkl row + browse context to movie, tv, or anime storage catalog."""
    url_catalog = catalog_from_simkl_url(item.get("url"))
    if url_catalog == "movie" or list_catalog == "movie" or is_anime_movie_item(item, list_catalog):
        return "movie"

    simkl_type = str(item.get("type") or item.get("endpoint_type") or "").lower()
    if simkl_type in ("movie", "movies"):
        return "movie"
    if simkl_type in ("tv", "show"):
        return "tv"
    if simkl_type == "anime" or list_catalog == "anime" or url_catalog == "anime":
        return "anime"
    if url_catalog == "tv":
        return "tv"
    if list_catalog in ("movie", "tv", "anime"):
        return list_catalog

    ids = item.get("ids") or {}
    if ids.get("mal") or item.get("anime_type"):
        return "anime"
    return "tv"


def is_anime_movie_info(info: dict[str, Any] | None) -> bool:
    if not isinstance(info, dict):
        return False
    if info.get("mediatype") == "movie" and info.get("catalog") == "anime":
        return True
    if simkl_anime_type(info) == "movie":
        return True
    if str(info.get("type") or "").lower() in ("movie", "movies") and info.get("catalog") == "anime":
        return True
    return False

"""Anime list paint overlays and cache-key suffixes."""
from __future__ import annotations

from typing import Any

from resources.lib.anime.titles import display_name_for_row, ensure_anime_title_slots, title_language_setting
from resources.lib.anime.playback import scrape_preset_cache_key


def cache_key_suffix() -> tuple:
    """Extra tuple fields for anime page/drilldown paint caches."""
    return (title_language_setting(), scrape_preset_cache_key())


def overlay_list_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply anime title slots to in-memory list rows (discover/library paint)."""
    if not rows:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        info = row.get("info")
        if isinstance(info, dict):
            ensure_anime_title_slots(info)
        out.append(row)
    return out


def menu_display_name(
    info: dict[str, Any],
    *,
    fallback: str | None,
    item: dict[str, Any] | None = None,
    mediatype: str | None = None,
) -> str | None:
    """Resolve Kodi list label for an anime show/movie row."""
    if mediatype in ("season", "episode"):
        return fallback
    if item and item.get("mal_id") and isinstance(info, dict) and not info.get("mal_id"):
        info["mal_id"] = item["mal_id"]
    if isinstance(info, dict):
        from resources.lib.simkl.ids import sync_flat_ids_from_ids, sync_ids_from_flat

        sync_ids_from_flat(info)
        sync_flat_ids_from_ids(info)
    return display_name_for_row(info, fallback=fallback, apply_dub=True)

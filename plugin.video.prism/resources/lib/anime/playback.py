"""Anime sub/dub scrape filters, sort, and playback locale presets."""
from __future__ import annotations

from resources.lib.modules.catalog_profiles import (
    apply_anime_filter_preset,
    apply_anime_playback_preset,
    apply_anime_preset,
    apply_anime_sort_preset,
)


def scrape_preset_cache_key() -> str:
    """Stable fragment for paint RAM keys (filter + sort profile for anime)."""
    from resources.lib.modules.catalog_profiles import DEFAULT_FILTERS, filters_key
    from resources.lib.modules.globals import g

    filter_string = g.get_setting(filters_key("anime"), DEFAULT_FILTERS) or ""
    filters = ",".join(sorted(part for part in str(filter_string).split(",") if part))
    sort_bits = []
    for level in range(1, 4):
        sort_bits.append(str(g.get_int_setting(f"sortmethod.anime.{level}", 0)))
    key = f"{filters}|{'-'.join(sort_bits)}"
    return key


__all__ = [
    "apply_anime_filter_preset",
    "apply_anime_playback_preset",
    "apply_anime_preset",
    "apply_anime_sort_preset",
    "scrape_preset_cache_key",
]

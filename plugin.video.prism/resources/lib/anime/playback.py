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
    from resources.lib.modules.catalog_profiles import get_filters
    from resources.lib.modules.globals import g

    filters = ",".join(sorted(get_filters("anime") or []))
    sort_bits = []
    for level in range(1, 4):
        sort_bits.append(str(g.get_int_setting(f"sortmethod.anime.{level}", 0)))
    return f"{filters}|{'-'.join(sort_bits)}"


__all__ = [
    "apply_anime_filter_preset",
    "apply_anime_playback_preset",
    "apply_anime_preset",
    "apply_anime_sort_preset",
    "scrape_preset_cache_key",
]

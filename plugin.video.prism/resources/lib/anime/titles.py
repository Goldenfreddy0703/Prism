"""Anime display titles — single entry for list, calendar, and download labels."""
from __future__ import annotations

from typing import Any

from resources.lib.simkl.field_map import (
    ensure_anime_title_slots,
    format_anime_display_name,
    pick_anime_display_title,
    repair_inverted_anime_title_slots,
    resolve_anime_titles_from_source,
)

__all__ = [
    "ensure_anime_title_slots",
    "format_anime_display_name",
    "pick_anime_display_title",
    "repair_inverted_anime_title_slots",
    "resolve_anime_titles_from_source",
    "prefer_romaji_from_settings",
    "title_language_setting",
]


def prefer_romaji_from_settings() -> bool:
    from resources.lib.modules.globals import g

    return g.get_int_setting("general.anime.titlelanguage") == 1


def title_language_setting() -> int:
    from resources.lib.modules.globals import g

    return g.get_int_setting("general.anime.titlelanguage")


def display_name_for_row(
    info: dict[str, Any],
    *,
    fallback: str | None = None,
    apply_dub: bool = True,
) -> str | None:
    return format_anime_display_name(
        info,
        fallback=fallback,
        prefer_romaji=prefer_romaji_from_settings(),
        apply_dub=apply_dub,
    )

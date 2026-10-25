"""Pure Simkl detail-needed checks (no Kodi / HTTP imports)."""
from __future__ import annotations


def row_info_art(item: dict) -> tuple[dict, dict]:
    blob = item.get("simkl_object") if isinstance(item.get("simkl_object"), dict) else {}
    info = blob.get("info") if isinstance(blob.get("info"), dict) else {}
    if not info and isinstance(item.get("info"), dict):
        info = item["info"]
    art = blob.get("art") if isinstance(blob.get("art"), dict) else {}
    if not art and isinstance(item.get("art"), dict):
        art = item["art"]
    return info, art


def _is_anime_info(info: dict) -> bool:
    if not isinstance(info, dict):
        return False
    if info.get("catalog") == "anime":
        return True
    if info.get("mal_id"):
        return True
    ids = info.get("ids")
    return isinstance(ids, dict) and ids.get("mal") is not None


def anime_title_slots_need_detail(info: dict) -> bool:
    """True when an anime row still lacks a distinct English title slot."""
    if not _is_anime_info(info):
        return False
    from resources.lib.simkl.field_map import _is_likely_localized_english_title

    english = (info.get("title_en") or info.get("en_title") or "").strip()
    romaji = (info.get("title_romaji") or info.get("title") or "").strip()
    if not romaji:
        return False
    if not english:
        return True
    if english == romaji and not _is_likely_localized_english_title(romaji):
        return True
    return False


def sync_row_list_paint_ready(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    info, art = row_info_art(item)
    title = info.get("title") or item.get("title")
    poster = art.get("poster") or art.get("thumb") or info.get("poster")
    return bool(title and poster)


def has_simkl_owned_metadata(info: dict) -> bool:
    if not isinstance(info, dict) or not info:
        return False
    genres = info.get("genre") or info.get("genres")
    if genres:
        return True
    return any(str(key).startswith("rating.") for key in info)


def simkl_detail_plot_missing(item: dict) -> bool:
    """True when a row still lacks overview/plot (genre retry / detail wave)."""
    if not isinstance(item, dict):
        return True
    info, _ = row_info_art(item)
    return not (info.get("plot") or info.get("overview"))


def simkl_detail_needed(item: dict) -> bool:
    """True when a row still needs GET /movies|tv|anime/{id} before list paint."""
    if not isinstance(item, dict):
        return True
    if not sync_row_list_paint_ready(item):
        return True
    info, _ = row_info_art(item)
    if simkl_detail_plot_missing(item):
        return True
    if anime_title_slots_need_detail(info):
        return True
    return not has_simkl_owned_metadata(info)

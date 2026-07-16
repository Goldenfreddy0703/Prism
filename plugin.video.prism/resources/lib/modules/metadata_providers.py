"""Per-provider enable toggles for runtime metadata APIs."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resources.lib.discover.definitions import DiscoverList

_SETTING_BY_PROVIDER = {
    "tmdb": "metadata.tmdb.enabled",
    "tvdb": "metadata.tvdb.enabled",
    "fanart": "metadata.fanart.enabled",
    "mdblist": "metadata.mdblist.enabled",
}

_API_NAME_BY_PROVIDER = {
    "tmdb": "TMDB",
    "tvdb": "TVDB",
    "fanart": "Fanart-TV",
    "mdblist": "MDBList",
}

# Discover DB queries that depend on MDBList scores at browse time.
MDBLIST_DISCOVER_DB_QUERIES = frozenset({"top_mdblist", "hidden_gems"})


def provider_enabled(provider: str) -> bool:
    setting_id = _SETTING_BY_PROVIDER.get(provider)
    if not setting_id:
        return True
    from resources.lib.modules.globals import g

    return g.get_bool_setting(setting_id, True)


def gapfill_providers_enabled() -> bool:
    return any(provider_enabled(name) for name in ("tmdb", "tvdb", "fanart"))


def gapfill_provider_available_for_row(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    info = row.get("info") if isinstance(row.get("info"), dict) else {}
    if provider_enabled("tmdb") and info.get("tmdb_id"):
        return True
    if provider_enabled("tvdb") and info.get("tvdb_id"):
        return True
    if provider_enabled("fanart") and (
        info.get("tmdb_id") or info.get("tvdb_id") or info.get("imdb_id")
    ):
        return True
    return False


def cast_gapfill_available(row: dict, media_type: str) -> bool:
    if not isinstance(row, dict):
        return False
    info = row.get("info") if isinstance(row.get("info"), dict) else {}
    if provider_enabled("tmdb") and info.get("tmdb_id"):
        return True
    if media_type != "movie" and provider_enabled("tvdb") and info.get("tvdb_id"):
        return True
    return False


def art_gapfill_available(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    info = row.get("info") if isinstance(row.get("info"), dict) else {}
    if provider_enabled("fanart") and (
        info.get("tmdb_id") or info.get("tvdb_id") or info.get("imdb_id")
    ):
        return True
    if provider_enabled("tmdb") and info.get("tmdb_id"):
        return True
    if provider_enabled("tvdb") and info.get("tvdb_id"):
        return True
    return False


def mdblist_runtime_enabled() -> bool:
    return provider_enabled("mdblist")


def discover_db_query_allowed(query_name: str | None) -> bool:
    if not query_name:
        return True
    if query_name in MDBLIST_DISCOVER_DB_QUERIES:
        return mdblist_runtime_enabled()
    return True


def discover_list_visible(item: "DiscoverList") -> bool:
    if item.source == "db" and not discover_db_query_allowed(item.db_query):
        return False
    return True


def filter_discover_lists(lists: tuple["DiscoverList", ...]) -> tuple["DiscoverList", ...]:
    return tuple(item for item in lists if discover_list_visible(item))


def notify_tmdb_required() -> None:
    import xbmcgui

    from resources.lib.modules.globals import g

    xbmcgui.Dialog().notification(g.ADDON_NAME, g.get_language_string(30959))


# Match MetadataHandler ART_* spinner values (Fanart.TV / TMDb / TVDB).
ART_FANART = 0
ART_TMDB = 1
ART_TVDB = 2
ART_SIMKL = -1

_ART_PROVIDER = {
    ART_FANART: "fanart",
    ART_TMDB: "tmdb",
    ART_TVDB: "tvdb",
}


def fanart_art_usable() -> bool:
    if not provider_enabled("fanart"):
        return False
    from resources.lib.database.keys import get_api_key

    return bool(get_api_key("Fanart-TV"))


def art_provider_usable(provider: str) -> bool:
    if provider == "fanart":
        return fanart_art_usable()
    return provider_enabled(provider)


def effective_preferred_art_source(raw: int) -> int:
    """Use the stored preference when its provider is enabled; else fall back, then Simkl-only."""
    if raw == ART_FANART:
        order = (ART_FANART, ART_TMDB, ART_TVDB)
    elif raw == ART_TMDB:
        order = (ART_TMDB, ART_TVDB, ART_FANART)
    else:
        order = (ART_TVDB, ART_TMDB, ART_FANART)

    for choice in order:
        provider = _ART_PROVIDER.get(choice)
        if provider and art_provider_usable(provider):
            return choice
    return ART_SIMKL

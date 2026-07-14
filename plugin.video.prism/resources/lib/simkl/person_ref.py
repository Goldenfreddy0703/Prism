"""TMDB person search bridge — Simkl has no actor/person API.

Flow (same idea as plugin.video.themoviedb.helper person lists):
  1. TMDB ``search/person`` → pick a person (PersonRef)
  2. TMDB ``person/{id}/combined_credits`` → movie + TV rows
  3. Simkl ``GET /search/id?tmdb=…`` per credit → SyncRow with simkl_id
  4. ListBuilder renders Simkl-keyed filmography

PersonRef (menus / action_args):
  ``{mediatype: person, person_id: <tmdb_person_id>, person_name?, query?, catalog?}``

Filmography rows are SyncRows after resolution — never raw TMDB list items in Kodi menus.
"""
from __future__ import annotations

from typing import Any

from resources.lib.modules.globals import g


def actor_catalog_hint(action_args: dict[str, Any] | None = None) -> str | None:
    if isinstance(action_args, dict):
        catalog = action_args.get("catalog")
        if catalog in ("movie", "tv", "anime"):
            return catalog
    params = g.REQUEST_PARAMS or {}
    catalog = params.get("catalog")
    if catalog in ("movie", "tv", "anime"):
        return catalog
    return None


def normalize_person_ref(action_args: Any) -> dict[str, Any]:
    if not action_args:
        return {}
    if isinstance(action_args, dict):
        return dict(action_args)
    from resources.lib.simkl.search_menus import normalize_search_query

    query = normalize_search_query(action_args)
    return {"query": query} if query else {}


def person_filmography_args(
    person_id: int,
    person_name: str,
    query: str,
    *,
    catalog: str | None = None,
) -> dict[str, Any]:
    """action_args for ``actorCredits`` after picking a TMDB person."""
    args: dict[str, Any] = {
        "mediatype": "person",
        "person_id": int(person_id),
        "person_name": person_name,
        "query": query,
    }
    if catalog in ("movie", "tv", "anime"):
        args["catalog"] = catalog
    return args


def person_menu_info(person: dict[str, Any]) -> dict[str, Any]:
    """Kodi list info for a TMDB person picker row (not a playable title)."""
    info: dict[str, Any] = {
        "title": person.get("name") or "Unknown",
        "mediatype": "person",
        "tmdb_id": int(person["id"]),
    }
    original = person.get("original_name")
    if original:
        info["originaltitle"] = original
    biography = person.get("biography")
    if biography:
        info["plot"] = biography
    department = person.get("known_for_department")
    if department:
        info["tagline"] = department
    return info


def enrich_person_from_tmdb(person: dict[str, Any]) -> dict[str, Any]:
    """Optional TMDB person detail for picker biography/art."""
    from resources.lib.simkl import browse

    person_id = person.get("id")
    if person_id is None:
        return person
    details = browse.get_person_details(int(person_id))
    if not details:
        return person
    merged = dict(person)
    for key in ("biography", "profile_path", "known_for_department", "place_of_birth", "birthday"):
        value = details.get(key)
        if value and not merged.get(key):
            merged[key] = value
    return merged


def search_people(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    from resources.lib.simkl import browse

    return browse.search_people(query, limit=limit)


def fetch_filmography_page(person_id: int, page: int, page_limit: int) -> list[dict[str, Any]]:
    """TMDB combined credits → Simkl SyncRows for one page."""
    from resources.lib.simkl import browse

    return browse.combined_credits_by_person(int(person_id), page, page_limit)


def render_person_picker(people: list[dict[str, Any]], query: str) -> None:
    """Build TMDB person picker directory (→ actorCredits on select)."""
    from resources.lib.indexers.tmdb import TMDBAPI

    tmdb = TMDBAPI()
    catalog = actor_catalog_hint()

    for raw_person in people:
        if not isinstance(raw_person, dict) or raw_person.get("id") is None:
            continue
        person = enrich_person_from_tmdb(raw_person)
        name = person.get("name") or "Unknown"
        art = {"thumb": g.DEFAULT_ICON, "icon": g.DEFAULT_ICON}
        profile = person.get("profile_path")
        if profile:
            profile_url = tmdb._get_absolute_image_path(profile, "w342")
            art["thumb"] = profile_url
            art["icon"] = profile_url
            art["poster"] = profile_url

        department = person.get("known_for_department")
        credit_args = person_filmography_args(int(person["id"]), name, query, catalog=catalog)
        g.add_directory_item(
            name,
            action="actorCredits",
            action_args=credit_args,
            label2=department,
            menu_item={"art": art, "info": person_menu_info(person)},
        )
    g.close_directory(g.CONTENT_ACTORS)


__all__ = [
    "actor_catalog_hint",
    "enrich_person_from_tmdb",
    "fetch_filmography_page",
    "normalize_person_ref",
    "person_filmography_args",
    "person_menu_info",
    "render_person_picker",
    "search_people",
]

"""Build Simkl API request bodies from Prism item info dicts."""

from __future__ import annotations



from typing import Any



from resources.lib.simkl.ids import show_id_from_info





def _ids_from_info(info: dict[str, Any]) -> dict[str, Any]:

    raw = info.get("ids") or {}

    simkl_id = show_id_from_info(info) or info.get("simkl_id") or raw.get("simkl") or raw.get("simkl_id")

    payload = {}

    if simkl_id:

        payload["simkl"] = int(simkl_id)

    for key in ("imdb", "tmdb", "tvdb", "mal", "anidb", "slug"):

        value = raw.get(key) or info.get(f"{key}_id")

        if value:

            payload[key] = value

    return payload





def _base_media(info: dict[str, Any]) -> dict[str, Any]:

    item = {"ids": _ids_from_info(info)}

    if info.get("title"):

        item["title"] = info["title"]

    if info.get("year"):

        item["year"] = info["year"]

    return item





def _is_anime(info: dict[str, Any]) -> bool:

    ids = info.get("ids") or {}

    return bool(info.get("mal_id") or ids.get("mal"))





def _show_info_for_child(info: dict[str, Any]) -> dict[str, Any]:

    show_id = show_id_from_info(info)

    return {

        "simkl_id": show_id,

        "title": info.get("tvshowtitle"),

        "ids": {"simkl": show_id} if show_id else {},

    }





def info_to_history_payload(info: dict[str, Any], force_show: bool = False) -> dict[str, Any]:

    mediatype = info.get("mediatype", "").lower()

    if mediatype == "movie":

        return {"movies": [_base_media(info)]}



    if force_show or mediatype == "tvshow":

        key = "anime" if _is_anime(info) else "shows"

        return {key: [_base_media(info)]}



    if mediatype == "season":

        key = "anime" if _is_anime(info) else "shows"

        item = _base_media(_show_info_for_child(info))

        item["seasons"] = [{"number": int(info.get("season", 0))}]

        return {key: [item]}



    if mediatype == "episode":

        key = "anime" if _is_anime(info) else "shows"

        item = _base_media(_show_info_for_child(info))

        item["seasons"] = [

            {

                "number": int(info.get("season", 0)),

                "episodes": [{"number": int(info.get("episode", 0))}],

            }

        ]

        return {key: [item]}



    key = "anime" if _is_anime(info) else "shows"

    return {key: [_base_media(info)]}





def info_to_list_payload(info: dict[str, Any], status: str, force_show: bool = False) -> dict[str, Any]:

    payload = info_to_history_payload(info, force_show=force_show)

    for key in ("movies", "shows", "anime"):

        if key in payload:

            for item in payload[key]:

                item["to"] = status

    return payload


def info_to_ratings_payload(info: dict[str, Any], rating: int, force_show: bool = False) -> dict[str, Any]:
    payload = info_to_history_payload(info, force_show=force_show)
    for key in ("movies", "shows", "anime"):
        if key in payload:
            for item in payload[key]:
                item["rating"] = int(rating)
    return payload


def ratings_force_show(info: dict[str, Any]) -> bool:
    return (info.get("mediatype") or "").lower() in ("episode", "season")


def info_to_scrobble_payload(info: dict[str, Any], progress: float) -> dict[str, Any]:

    mediatype = info.get("mediatype", "").lower()

    body: dict[str, Any] = {"progress": round(float(progress), 2)}



    if mediatype == "movie":

        body["movie"] = _base_media(info)

        return body



    show_info = _show_info_for_child(info)

    if not show_info.get("title"):

        show_info["title"] = info.get("tvshowtitle") or info.get("title")

    episode = {

        "season": int(info.get("season", 0)),

        "number": int(info.get("episode", 0)),

    }

    ep_ids = info.get("ids") or {}

    if ep_ids.get("simkl_id") or (info.get("mediatype") == "episode" and info.get("simkl_id")):

        episode["ids"] = {"simkl_id": ep_ids.get("simkl_id") or info.get("simkl_id")}



    if _is_anime(info):

        body["anime"] = _base_media(show_info)

        body["episode"] = episode

    else:

        body["show"] = _base_media(show_info)

        body["episode"] = episode

    return body


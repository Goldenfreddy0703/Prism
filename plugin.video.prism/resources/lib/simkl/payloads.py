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
    """Match anime detection used elsewhere (catalog + MAL/AniDB, not MAL alone)."""
    if not isinstance(info, dict):
        return False
    if info.get("catalog") == "anime":
        return True
    if info.get("mal_id") or info.get("anidb_id"):
        return True
    ids = info.get("ids") or {}
    return bool(ids.get("mal") or ids.get("anidb"))


def _show_info_for_child(info: dict[str, Any]) -> dict[str, Any]:
    show_id = show_id_from_info(info)
    child: dict[str, Any] = {
        "simkl_id": show_id,
        "title": info.get("tvshowtitle"),
        "ids": {"simkl": int(show_id)} if show_id else {},
    }
    if show_id:
        child["simkl_id"] = int(show_id)
    raw = info.get("ids") or {}
    for key in ("imdb", "tmdb", "tvdb", "mal", "anidb", "slug"):
        value = raw.get(key) or info.get(f"{key}_id")
        if value is not None and key not in child["ids"]:
            child["ids"][key] = value
    if info.get("mal_show_id") and "mal" not in child["ids"]:
        child["ids"]["mal"] = info["mal_show_id"]
    return child


def _simkl_episode_coords(info: dict[str, Any]) -> tuple[int, int]:
    """Simkl API season/episode — use native anime cour numbers when available."""
    season = info.get("season", 0)
    episode = info.get("episode", 0)
    if _is_anime(info):
        if info.get("anime_season") is not None:
            season = info["anime_season"]
        if info.get("anime_episode") is not None:
            episode = info["anime_episode"]
    return int(season or 0), int(episode or 0)


def _show_level_provider_ids(info: dict[str, Any]) -> dict[str, str]:
    """Parent-show provider ids — must not be sent as episode.ids (causes 404)."""
    show_ids: dict[str, str] = {}
    for provider, flat_keys in (
        ("tvdb", ("tvdb_show_id", "tvdb_id")),
        ("anidb", ("anidb_show_id", "anidb_id")),
        ("mal", ("mal_show_id", "mal_id")),
    ):
        for flat_key in flat_keys:
            value = info.get(flat_key)
            if value is not None:
                show_ids[provider] = str(value)
                break
    return show_ids


def _simkl_episode_id_lookup(info: dict[str, Any]) -> dict[str, str] | None:
    """Simkl scrobble episode.ids only accepts tvdb and anidb (not simkl_id)."""
    ep_ids = info.get("ids") or {}
    show_ids = _show_level_provider_ids(info)
    payload: dict[str, str] = {}
    tvdb = ep_ids.get("tvdb")
    if tvdb is not None and str(tvdb) != show_ids.get("tvdb"):
        payload["tvdb"] = str(tvdb)
    anidb = ep_ids.get("anidb")
    if anidb is not None and str(anidb) != show_ids.get("anidb"):
        payload["anidb"] = str(anidb)
    return payload or None


def _anime_simkl_episode_ids(show_id: int) -> dict[int, int]:
    """Map an episode Simkl id to Simkl's own episode number (not the TVDB number)."""
    from resources.lib.database.simkl_sync.milling import fetch_raw_show_episodes

    mapping: dict[int, int] = {}
    for raw in fetch_raw_show_episodes(int(show_id), "anime") or []:
        if not isinstance(raw, dict) or raw.get("type") == "special":
            continue
        raw_ids = raw.get("ids") or {}
        raw_id = raw_ids.get("simkl_id") or raw_ids.get("simkl")
        number = raw.get("episode")
        if number is None:
            number = raw.get("number")
        if raw_id is None or number is None:
            continue
        try:
            mapping[int(raw_id)] = int(number)
        except (TypeError, ValueError):
            continue
    return mapping


def _anime_season_episode_numbers(show_id: int, season_num: int) -> list[int]:
    """Simkl episode numbers for one menu season.

    The local ``number`` column is the TVDB episode. Show 523776 stores 13-24,
    while Simkl's own list is 1-12. History has to send 1-12.
    """
    from resources.lib.database.session import get_sync_database
    from resources.lib.database.simkl_sync.serial_sync import serial_profile_scope

    db = get_sync_database()
    with serial_profile_scope(db, "anime"):
        st = db._st()
        rows = db.fetchall(
            f"""
            SELECT simkl_id, number
            FROM {st.episode}
            WHERE simkl_show_id = ? AND season = ? AND season > 0
            ORDER BY number
            """,
            (int(show_id), int(season_num)),
        ) or []
    by_id = _anime_simkl_episode_ids(show_id)
    nums: list[int] = []
    for row in rows:
        try:
            episode_id = int(row["simkl_id"])
        except (TypeError, ValueError, KeyError):
            episode_id = None
        if episode_id is not None and episode_id in by_id:
            nums.append(by_id[episode_id])
            continue
        try:
            nums.append(int(row["number"]))
        except (TypeError, ValueError, KeyError):
            continue
    return sorted(set(nums))


def _anime_scrobble_episode_number(info: dict[str, Any]) -> int:
    """Simkl's own episode number, not the TVDB number stored for menus."""
    native = info.get("anime_episode")
    if native is not None:
        try:
            return int(native)
        except (TypeError, ValueError):
            pass

    episode_id = info.get("simkl_id")
    show_id = show_id_from_info(info)
    if episode_id is not None and show_id is not None:
        try:
            from resources.lib.database.simkl_sync.milling import fetch_raw_show_episodes

            target = int(episode_id)
            for raw in fetch_raw_show_episodes(int(show_id), "anime") or []:
                if not isinstance(raw, dict):
                    continue
                raw_ids = raw.get("ids") or {}
                raw_id = raw_ids.get("simkl_id") or raw_ids.get("simkl")
                if raw_id is None or int(raw_id) != target:
                    continue
                number = raw.get("episode")
                if number is None:
                    number = raw.get("number")
                if number is not None:
                    return int(number)
        except Exception:
            pass

    fallback = info.get("episode")
    if fallback is None:
        fallback = info.get("number") or 0
    try:
        return int(fallback or 0)
    except (TypeError, ValueError):
        return 0


def _simkl_api_episode_block(info: dict[str, Any], *, for_history: bool = False) -> dict[str, Any]:
    """Episode object for Simkl scrobble / sync/history.

    Anime menus and scrapers use the TVDB season and episode. Simkl's anime
    episode list does not. Episode 1729886 is Simkl episode 4 and TVDB episode 16.
    Sending 16 returns 404.
    """
    if _is_anime(info):
        ep_num = _anime_scrobble_episode_number(info)
        if for_history:
            season = info.get("anime_season")
            season = 1 if season is None else int(season)
            block: dict[str, Any] = {"season": season, "number": ep_num}
        else:
            block = {"number": ep_num}
    else:
        season_num, episode_num = _simkl_episode_coords(info)
        block = {"season": season_num, "number": episode_num}

    episode_ids = _simkl_episode_id_lookup(info)
    if episode_ids:
        block["ids"] = episode_ids
    return block


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
        season_num = int(info.get("season") or 0)
        if _is_anime(info):
            show_id = show_id_from_info(info)
            menu_season = int(info.get("season") or 1)
            ep_numbers = _anime_season_episode_numbers(int(show_id), menu_season) if show_id else []
            # Simkl anime history is one cour: season 1 plus Simkl's own episode numbers.
            history_season = 0 if menu_season == 0 else 1
            if ep_numbers:
                item["seasons"] = [
                    {
                        "number": history_season,
                        "episodes": [{"number": n} for n in ep_numbers],
                    }
                ]
            else:
                item["seasons"] = [{"number": history_season}]
        else:
            item["seasons"] = [{"number": season_num}]
        return {key: [item]}

    if mediatype == "episode":
        key = "anime" if _is_anime(info) else "shows"
        item = _base_media(_show_info_for_child(info))
        episode_block = _simkl_api_episode_block(info, for_history=True)
        season_num = int(episode_block.get("season") or 1)
        episode_num = int(episode_block.get("number") or 0)
        item["seasons"] = [
            {
                "number": season_num,
                "episodes": [{"number": episode_num}],
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

    episode = _simkl_api_episode_block(info)

    is_anime = _is_anime(info)
    media_key = "anime" if is_anime else "show"
    body[media_key] = _base_media(show_info)
    body["episode"] = episode

    return body

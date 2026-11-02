"""Build Simkl-shaped season/episode trees from Simkl episode endpoints."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from resources.lib.discover.normalize import _normalize_air_date
from resources.lib.modules.globals import g

_RAW_EPISODES_CACHE: dict[tuple[int, str, str], list[dict[str, Any]]] = {}


def _ensure_listed_episode_fk_parents(
    db,
    built: list[dict[str, Any]],
    *,
    catalog: str,
    show_meta: dict[int, tuple[str, str | None]],
) -> None:
    """Ensure shows + seasons exist before listed-episode upsert (episodes FK both tables)."""
    from resources.lib.modules.metadataHandler import MetadataHandler
    from resources.lib.simkl.ids import season_key

    get = MetadataHandler.get_simkl_info
    show_ids = sorted({int(b["simkl_show_id"]) for b in built if b.get("simkl_show_id") is not None})
    missing_shows: list[dict[str, Any]] = []
    for sid in show_ids:
        if db.fetchone("SELECT simkl_id FROM shows WHERE simkl_id=?", (sid,)):
            continue
        cat = show_meta.get(sid, (catalog, None))[0]
        missing_shows.append(
            {
                "simkl_id": sid,
                "catalog": cat,
                "simkl_object": {
                    "info": {
                        "simkl_id": sid,
                        "catalog": cat,
                        "mediatype": "tvshow",
                    }
                },
            }
        )
    if missing_shows:
        db.insert_simkl_shows(missing_shows)

    season_coords: set[tuple[int, int, str]] = set()
    for ep in built:
        sid = ep.get("simkl_show_id")
        season_num = get(ep, "season")
        if sid is None or season_num is None:
            continue
        cat = show_meta.get(int(sid), (catalog, None))[0]
        season_coords.add((int(sid), int(season_num), cat))

    seasons_to_insert: list[dict[str, Any]] = []
    for sid, season_num, cat in sorted(season_coords):
        existing = db.fetchone(
            "SELECT 1 AS ok FROM seasons WHERE simkl_show_id=? AND season=? AND catalog=?",
            (sid, season_num, cat),
        )
        if existing:
            continue
        _, slug = show_meta.get(sid, (cat, None))
        seasons_to_insert.append(
            _build_season_dict(sid, season_num, [], False, 0, slug=slug, catalog=cat)
        )

    if seasons_to_insert:
        db.insert_simkl_seasons(seasons_to_insert)


def clear_raw_episodes_cache(show_id: int | None = None) -> None:
    """Drop in-process Simkl episode JSON (e.g. after sync invalidates a show)."""
    if show_id is None:
        _RAW_EPISODES_CACHE.clear()
        return
    sid = int(show_id)
    for key in [cache_key for cache_key in _RAW_EPISODES_CACHE if cache_key[0] == sid]:
        _RAW_EPISODES_CACHE.pop(key, None)


def fetch_raw_show_episodes(
    show_id: int,
    catalog: str,
    slug: str | None = None,
    *,
    api=None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Simkl /tv|anime/episodes JSON with per-process reuse (disk cache via use_cache)."""
    cache_key = (int(show_id), str(catalog), slug or "")
    if not force_refresh:
        cached = _RAW_EPISODES_CACHE.get(cache_key)
        if cached is not None:
            return cached

    if api is None:
        from resources.lib.indexers.simkl import thread_simkl_api

        api = thread_simkl_api()
    fetch_kwargs = {"ignore_cache": True} if force_refresh else {}
    if catalog == "anime":
        raw_episodes = api.get_anime_episodes(int(show_id), slug=slug, **fetch_kwargs) or []
    else:
        raw_episodes = api.get_tv_episodes(int(show_id), slug=slug, **fetch_kwargs) or []

    normalized = [episode for episode in raw_episodes if isinstance(episode, dict)]
    if not normalized and not force_refresh:
        from resources.lib.net.request_policy import get_request_policy

        get_request_policy().reset_menu_budget()
        return fetch_raw_show_episodes(
            show_id,
            catalog,
            slug=slug,
            api=api,
            force_refresh=True,
        )
    if normalized:
        _RAW_EPISODES_CACHE[cache_key] = normalized
    return normalized


def season_simkl_id(show_id: int, season_num: int) -> int:
    from resources.lib.simkl.ids import season_key

    return season_key(show_id, season_num)


def _episode_num(episode: dict[str, Any]) -> int | None:
    for key in ("episode", "number"):
        value = episode.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _season_num(episode: dict[str, Any], catalog: str = "tv") -> int:
    if episode.get("type") == "special":
        return 0
    if catalog == "anime":
        from resources.lib.simkl.field_map import anime_menu_season

        return anime_menu_season(episode)

    value = episode.get("season")
    if value is None:
        return 1
    try:
        season = int(value)
    except (TypeError, ValueError):
        return 1
    return 1 if season == 0 else season


def _episode_simkl_id(episode: dict[str, Any]) -> int | None:
    ids = episode.get("ids") or {}
    simkl_id = ids.get("simkl_id") or ids.get("simkl")
    if simkl_id is None:
        return None
    return int(simkl_id)


def _build_episode_dict(
    show_id: int,
    season_id: int,
    season_num: int,
    episode: dict[str, Any],
    slug: str | None = None,
    *,
    catalog: str = "tv",
    episode_num_override: int | None = None,
) -> dict[str, Any]:
    from resources.lib.simkl.ids import attach_tv_context

    episode_num = _episode_num(episode)
    if catalog == "anime":
        from resources.lib.simkl.field_map import anime_menu_episode_number

        episode_num = anime_menu_episode_number(episode, season_num, episode_num)
    if episode_num is None:
        episode_num = episode_num_override
    ep_id = _episode_simkl_id(episode)
    if ep_id is None or episode_num is None:
        return {}

    aired = _normalize_air_date(episode.get("date"))
    description = (
        episode.get("description")
        or episode.get("overview")
        or episode.get("en_description")
        or episode.get("desc")
    )
    info = {
        "simkl_id": ep_id,
        "mediatype": "episode",
        "catalog": catalog,
        "season": season_num,
        "episode": episode_num,
        "number": episode_num,
        "title": episode.get("title"),
        "overview": description,
        "plot": description,
        "aired": aired,
        "first_aired": aired,
    }
    if episode.get("runtime") is not None:
        info["runtime"] = episode.get("runtime")
    attach_tv_context(info, show_id, season_num=season_num, slug=slug)
    from resources.lib.simkl.field_map import enrich_episode_from_simkl_api, finalize_playback_info

    enrich_episode_from_simkl_api(info, episode)
    info["season"] = season_num
    info["episode"] = episode_num
    info["number"] = episode_num
    finalize_playback_info(info)
    from resources.lib.simkl.ids import canonicalize_info_identity

    canonicalize_info_identity(info)
    from resources.lib.simkl.images import attach_episode_still

    art = attach_episode_still(info, episode) or {}
    simkl_object: dict[str, Any] = {"info": info}
    if art:
        simkl_object["art"] = art
    return {
        "simkl_id": ep_id,
        "simkl_show_id": show_id,
        "catalog": catalog,
        "season": season_num,
        "episode": episode_num,
        "simkl_object": simkl_object,
    }


def _build_season_dict(
    show_id: int,
    season_num: int,
    episodes: list[dict[str, Any]],
    mill_episodes: bool,
    aired_episodes: int,
    slug: str | None = None,
    *,
    catalog: str = "tv",
) -> dict[str, Any]:
    from resources.lib.simkl.ids import attach_tv_context

    info = {
        "simkl_id": show_id,
        "mediatype": "season",
        "catalog": catalog,
        "season": season_num,
        "number": season_num,
        "simkl_show_id": show_id,
        "aired_episodes": aired_episodes,
    }
    if season_num == 0:
        info["title"] = "Specials"
        info["sorttitle"] = "Specials"
    else:
        info["title"] = g.get_language_string(30528).format(season_num)
        info["sorttitle"] = info["title"]
    attach_tv_context(info, show_id, season_num=season_num, slug=slug)
    season = {
        "simkl_show_id": show_id,
        "season": season_num,
        "aired_episodes": aired_episodes,
        "simkl_object": {"info": info},
    }
    if mill_episodes:
        season["episodes"] = episodes
    return season


def pull_show_seasons(
    show_id: int,
    catalog: str,
    mill_episodes: bool,
    slug: str | None = None,
    *,
    mill_season_filter: set[int] | frozenset[int] | None = None,
) -> list[dict[str, Any]]:
    raw_episodes = fetch_raw_show_episodes(show_id, catalog, slug=slug)

    def _raw_episode_order_key(raw: dict[str, Any]) -> tuple:
        season_num = _season_num(raw, catalog)
        if season_num == 0:
            # Specials keep Simkl's API order (stable sort); users can re-sort by date in Kodi.
            return (season_num, 0)
        return (season_num, _episode_num(raw) or 0)

    raw_episodes = sorted(
        [ep for ep in raw_episodes if isinstance(ep, dict)],
        key=_raw_episode_order_key,
    )

    if not raw_episodes:
        g.log(f"Simkl milling: no episodes returned for show {show_id} ({catalog})", "warning")
        return []

    grouped_raw: dict[int, list[dict[str, Any]]] = defaultdict(list)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    special_counters: dict[int, int] = defaultdict(int)
    for raw in raw_episodes:
        if not isinstance(raw, dict):
            continue
        season_num = _season_num(raw, catalog)
        grouped_raw[season_num].append(raw)
        if not mill_episodes:
            continue
        if mill_season_filter is not None and season_num not in mill_season_filter:
            continue
        episode_num_override = None
        if season_num == 0 and _episode_num(raw) is None:
            special_counters[season_num] += 1
            episode_num_override = special_counters[season_num]
        episode = _build_episode_dict(
            show_id,
            season_simkl_id(show_id, season_num),
            season_num,
            raw,
            slug=slug,
            catalog=catalog,
            episode_num_override=episode_num_override,
        )
        if episode:
            grouped[season_num].append(episode)

    seasons = []
    for season_num in sorted(grouped_raw.keys()):
        aired_count = sum(1 for raw in grouped_raw[season_num] if raw.get("aired") is True)
        if mill_episodes and season_num == 0:
            episodes = list(grouped[season_num])
        elif mill_episodes:
            episodes = sorted(grouped[season_num], key=lambda ep: ep.get("episode") or 0)
        else:
            episodes = []
        seasons.append(
            _build_season_dict(show_id, season_num, episodes, mill_episodes, aired_count, slug=slug, catalog=catalog)
            )

    return seasons


def count_special_episodes(show_id: int, catalog: str = "tv", slug: str | None = None) -> int:
    """Return how many Simkl episodes are tagged as specials for a show."""
    raw_episodes = fetch_raw_show_episodes(show_id, catalog, slug=slug)
    return sum(1 for raw in raw_episodes if raw.get("type") == "special")


def _listed_episode_coord_variants(
    show_id: int,
    season: int,
    episode: int,
    *,
    catalog: str,
) -> set[tuple[int, int, int]]:
    """Menu/DB season keys vs Simkl API episode JSON can disagree on season 0/1."""
    sid, s, ep = int(show_id), int(season), int(episode)
    out = {(sid, s, ep)}
    if catalog in ("tv", "anime"):
        if s == 0:
            out.add((sid, 1, ep))
        elif s == 1:
            out.add((sid, 0, ep))
    return out


def _anime_tvdb_menu_coord(item: dict, show_id: int) -> tuple[int, int, int] | None:
    """TVDB season/episode the anime menu displays, when it differs from the stored row."""
    from resources.lib.simkl.field_map import anime_menu_episode_number, anime_menu_season, tvdb_from_episode

    info = item.get("info") if isinstance(item.get("info"), dict) else {}
    nested = item.get("episode") if isinstance(item.get("episode"), dict) else {}
    simkl_obj = item.get("simkl_object") if isinstance(item.get("simkl_object"), dict) else {}
    obj_info = simkl_obj.get("info") if isinstance(simkl_obj.get("info"), dict) else {}
    merged: dict = {**obj_info, **info, **nested}
    if "tvdb" not in merged and merged.get("tvdb_season") is not None:
        merged["tvdb"] = {
            "season": merged.get("tvdb_season"),
            "episode": merged.get("tvdb_episode"),
        }
    tvdb_season, tvdb_ep = tvdb_from_episode(merged)
    if tvdb_season is None or tvdb_ep is None:
        return None
    menu_season = anime_menu_season(merged)
    menu_ep = anime_menu_episode_number(merged, menu_season, int(tvdb_ep))
    if menu_ep is None:
        return None
    return int(show_id), int(menu_season), int(menu_ep)


def _menu_episode_target(item: dict, *, db, catalog_hint: str = "tv") -> tuple[dict | None, bool]:
    """One menu row. The bool is true when a real episode id looked like a different show."""
    from resources.lib.simkl.ids import is_synthetic_episode_id, show_id_from_item, split_synthetic_episode_id

    item_catalog = item.get("catalog") if isinstance(item.get("catalog"), str) else catalog_hint
    show_id = None
    season = None
    ep_num = None
    coords = db._episode_coords_from_list_item(item)
    if coords:
        show_id, season, ep_num = coords
    elif isinstance(item.get("episode"), dict):
        nested = item["episode"]
        nested_coords = db._episode_coords_from_list_item(
            {"simkl_show_id": show_id_from_item(item), **nested, "episode": nested}
        )
        if nested_coords:
            show_id, season, ep_num = nested_coords
    if show_id is None:
        show_id = item.get("simkl_show_id") or show_id_from_item(item)
    if show_id is None:
        return None, False
    show_id = int(show_id)
    if not db.fetchone("SELECT simkl_id FROM shows WHERE simkl_id=?", (show_id,)):
        return None, False

    catalog = item_catalog or catalog_hint
    stored = db.show_catalog(show_id)
    if stored in ("tv", "anime"):
        catalog = stored
    target = {
        "show_id": show_id,
        "catalog": catalog,
        "preferred": set(),
        "acceptable": set(),
        "ids": set(),
    }
    if season is not None and ep_num is not None:
        preferred = (show_id, int(season), int(ep_num))
        target["preferred"].add(preferred)
        target["acceptable"].update(
            _listed_episode_coord_variants(show_id, int(season), int(ep_num), catalog=catalog)
        )
    if catalog == "anime":
        tvdb_coord = _anime_tvdb_menu_coord(item, show_id)
        if tvdb_coord is not None:
            target["acceptable"].update(
                _listed_episode_coord_variants(*tvdb_coord, catalog="anime")
            )

    phantom = False
    simkl_id = item.get("simkl_id")
    if simkl_id is not None:
        sid = int(simkl_id)
        target["ids"].add(sid)
        if is_synthetic_episode_id(sid):
            split_show, split_season, split_ep = split_synthetic_episode_id(sid)
            if split_show == show_id:
                target["acceptable"].update(
                    _listed_episode_coord_variants(split_show, split_season, split_ep, catalog=catalog)
                )
            else:
                phantom = True
    if not target["preferred"] and not target["acceptable"] and not target["ids"]:
        return None, phantom
    return target, phantom


def _raw_match_rank(show_id: int, catalog: str, raw: dict[str, Any], target: dict) -> int | None:
    """Lower is a closer match. None means this raw is a different episode."""
    ep_id = _episode_simkl_id(raw)
    if ep_id is not None and ep_id in target["ids"]:
        return 0
    season_num = _season_num(raw, catalog)
    ep_num = _episode_num(raw)
    if catalog == "anime":
        from resources.lib.simkl.field_map import anime_menu_episode_number

        ep_num = anime_menu_episode_number(raw, season_num, ep_num)
    if ep_num is None:
        return None
    coord = (int(show_id), int(season_num), int(ep_num))
    if coord in target["preferred"]:
        return 1
    if coord in target["acceptable"]:
        return 2
    from resources.lib.simkl.ids import is_synthetic_episode_id, split_synthetic_episode_id

    if ep_id is not None and is_synthetic_episode_id(ep_id):
        split_show, split_season, split_ep = split_synthetic_episode_id(ep_id)
        if split_show == show_id and (split_show, split_season, split_ep) in target["acceptable"]:
            return 2
    return None


def refresh_listed_episodes_from_simkl(db, media_items) -> int:
    """Fetch Simkl episode plot/still for visible menu rows without milling the whole show."""
    from resources.lib.net.request_policy import get_request_policy
    from resources.lib.simkl.ids import slug_from_info

    get_request_policy().reset_menu_budget()
    media_items = db._resolve_episode_list_ids(media_items)
    targets_by_show: dict[int, list[dict]] = {}
    phantom_ids = 0
    target_count = 0
    for item in media_items or []:
        if not isinstance(item, dict):
            continue
        hint = item.get("catalog") if isinstance(item.get("catalog"), str) else "tv"
        target, phantom = _menu_episode_target(item, db=db, catalog_hint=hint)
        if phantom:
            phantom_ids += 1
        if not target:
            continue
        target_count += 1
        targets_by_show.setdefault(int(target["show_id"]), []).append(target)

    if not targets_by_show:
        g.log("Simkl listed-episode refresh: no episode targets", "debug")
        return 0

    show_meta: dict[int, tuple[str, str | None]] = {}
    for show_id, show_targets in targets_by_show.items():
        catalog = show_targets[0]["catalog"]
        row = db.fetchone(
            "SELECT info FROM shows WHERE simkl_id=? AND catalog=?",
            (show_id, catalog),
        )
        slug = slug_from_info((row or {}).get("info") or {}) if row else None
        show_meta[show_id] = (catalog, slug)

    refreshed = 0

    for show_id in sorted(targets_by_show):
        catalog, slug = show_meta[show_id]
        show_targets = targets_by_show[show_id]
        raw_episodes = fetch_raw_show_episodes(show_id, catalog, slug=slug, api=db.simkl_api)
        built: list[dict[str, Any]] = []
        seen_episode_ids: set[int] = set()
        for target in show_targets:
            best_raw = None
            best_rank = 99
            for raw in raw_episodes or []:
                if not isinstance(raw, dict):
                    continue
                rank = _raw_match_rank(show_id, catalog, raw, target)
                if rank is None or rank > best_rank:
                    continue
                best_raw = raw
                best_rank = rank
                if best_rank == 0:
                    break
            if best_raw is None:
                continue
            season_num = _season_num(best_raw, catalog)
            episode = _build_episode_dict(
                show_id,
                season_simkl_id(show_id, season_num),
                season_num,
                best_raw,
                slug=slug,
                catalog=catalog,
            )
            episode_id = episode.get("simkl_id") if episode else None
            if not episode or episode_id is None or int(episode_id) in seen_episode_ids:
                continue
            seen_episode_ids.add(int(episode_id))
            built.append(episode)
        if not built:
            g.log(
                f"Simkl listed-episode refresh: 0 matched for show {show_id} ({catalog})",
                "debug",
            )
            continue
        _ensure_listed_episode_fk_parents(db, built, catalog=catalog, show_meta=show_meta)
        db.insert_simkl_episodes(built)
        db._format_episodes(built, preloaded=True)
        refreshed += len(built)
        g.log(
            f"Simkl listed-episode refresh: {len(built)} episode(s) for show {show_id} ({catalog})",
            "debug",
        )
        try:
            from resources.lib.meta.paint_cache import clear_session_page_paint_for_show

            clear_session_page_paint_for_show(show_id)
        except Exception:
            pass
    return refreshed

"""Saved TMDB Discover lists for movies and TV. Opened through Simkl."""
from __future__ import annotations

import uuid
from typing import Any

import xbmcgui

from resources.lib.common import tools
from resources.lib.modules.globals import g

_STREAMS: dict[str, dict[str, Any]] = {}
_STREAM_ORDER: list[str] = []

_MOVIE_SORTS: tuple[tuple[str, int], ...] = (
    ("popularity.desc", 31385),
    ("popularity.asc", 31386),
    ("vote_average.desc", 31387),
    ("vote_average.asc", 31388),
    ("vote_count.desc", 31389),
    ("vote_count.asc", 31390),
    ("primary_release_date.desc", 31391),
    ("primary_release_date.asc", 31392),
    ("title.asc", 31393),
    ("title.desc", 31394),
    ("original_title.asc", 31395),
    ("original_title.desc", 31396),
    ("revenue.desc", 31397),
    ("revenue.asc", 31398),
)
_TV_SORTS: tuple[tuple[str, int], ...] = (
    ("popularity.desc", 31385),
    ("popularity.asc", 31386),
    ("vote_average.desc", 31387),
    ("vote_average.asc", 31388),
    ("vote_count.desc", 31389),
    ("vote_count.asc", 31390),
    ("first_air_date.desc", 31399),
    ("first_air_date.asc", 31400),
    ("name.asc", 31401),
    ("name.desc", 31402),
    ("original_name.asc", 31403),
    ("original_name.desc", 31404),
)
_STATUSES: tuple[tuple[str, int], ...] = (
    ("0", 31421),
    ("1", 31422),
    ("2", 31423),
    ("3", 31424),
    ("4", 31425),
    ("5", 31426),
)
_LANGUAGES: tuple[tuple[str, int], ...] = (
    ("en", 31366),
    ("fr", 31367),
    ("de", 31368),
    ("es", 31369),
    ("pt", 31430),
    ("it", 31371),
    ("ko", 31372),
    ("zh", 31373),
    ("ja", 31376),
    ("hi", 31427),
    ("ru", 31428),
    ("ar", 31429),
)
_COUNTRIES: tuple[tuple[str, int], ...] = (
    ("US", 31431),
    ("GB", 31432),
    ("JP", 31433),
    ("KR", 31434),
    ("FR", 31435),
    ("DE", 31436),
    ("ES", 31437),
    ("IT", 31438),
    ("CN", 31439),
    ("IN", 31440),
    ("CA", 31441),
    ("AU", 31442),
    ("BR", 31443),
    ("MX", 31444),
)
_RELATIVE = {"current": 31378, "next": 31383, "previous": 31384}
_STATUS_VALUES = {value for value, _label in _STATUSES}
_LANGUAGE_VALUES = {value for value, _label in _LANGUAGES}
_COUNTRY_VALUES = {value for value, _label in _COUNTRIES}


def show_lists() -> None:
    catalog = _catalog()
    if not _tmdb_ready():
        return
    draft = _draft(catalog)
    icon = _icon(catalog)
    g.add_directory_item(
        _draft_label(draft),
        action="tmdbMyListOpen",
        catalog=catalog,
        list_id="draft",
        description=_summary(catalog, draft),
        cm=[(g.get_language_string(31286), _plugin("tmdbMyListRenameDraft", "draft", catalog))],
        menu_item=g.create_icon_dict(icon, g.ICONS_PATH),
    )
    g.add_directory_item(
        g.get_language_string(31282),
        action="tmdbMyListEdit",
        catalog=catalog,
        is_folder=False,
        description=g.get_language_string(31381),
        menu_item=g.create_icon_dict(icon, g.ICONS_PATH),
    )
    g.add_directory_item(
        g.get_language_string(31283),
        action="tmdbMyListClear",
        catalog=catalog,
        is_folder=False,
        description=g.get_language_string(31382),
        menu_item=g.create_icon_dict(icon, g.ICONS_PATH),
    )
    g.add_directory_item(
        g.get_language_string(31284),
        action="tmdbMyListSave",
        catalog=catalog,
        is_folder=False,
        menu_item=g.create_icon_dict(icon, g.ICONS_PATH),
    )
    for entry in _load_entries(catalog):
        list_id = str(entry.get("id") or "")
        if not list_id:
            continue
        g.add_directory_item(
            str(entry.get("name") or g.get_language_string(31281)),
            action="tmdbMyListOpen",
            catalog=catalog,
            list_id=list_id,
            description=_summary(catalog, entry.get("filters") or {}),
            cm=[
                (g.get_language_string(31286), _plugin("tmdbMyListRename", list_id, catalog)),
                (g.get_language_string(31287), _plugin("tmdbMyListDelete", list_id, catalog)),
                (g.get_language_string(31288), _plugin("tmdbMyListLoad", list_id, catalog)),
            ],
            menu_item=g.create_icon_dict(icon, g.ICONS_PATH),
        )
    g.close_directory(g.CONTENT_MENU, cache=False)


def open_list(list_builder) -> None:
    from resources.lib.meta.list_pipeline import make_list_id
    from resources.lib.pipeline.catalog_page import CatalogPagePipeline
    from resources.lib.simkl import browse
    from resources.lib.simkl.search_menus import notify_empty_search

    catalog = _catalog()
    if not _tmdb_ready():
        return
    list_id = _requested_list_id()
    filters = _filters_for(catalog, list_id)
    if not filters:
        g.cancel_directory()
        return
    page_limit = min(60, max(10, int(g.get_int_setting("item.limit", 20) or 20)))
    menu_page = max(1, int(g.PAGE or 1))
    fetched = _fetch_page(catalog, filters, menu_page, page_limit)
    if not fetched.items:
        notify_empty_search(30766)
        return
    page = browse.GenreBrowsePage(fetched.items, fetched.has_next)
    CatalogPagePipeline.open_genre(
        catalog,
        page,
        list_builder,
        next_action="tmdbMyListOpen",
        next_args={"list_id": list_id, "catalog": catalog},
        list_id=make_list_id("tmdb-custom", catalog, list_id, _filter_token(_query_filters(catalog, filters)), menu_page),
        browse_source=f"tmdb_custom:{catalog}:{list_id}",
    )


def edit_draft() -> None:
    catalog = _catalog()
    draft = _draft(catalog)
    while True:
        rows = _editor_rows(catalog)
        labels = [f"{g.get_language_string(label_id)}: {_row_value(catalog, draft, key)}" for key, label_id in rows]
        choice = xbmcgui.Dialog().select(g.get_language_string(31282), labels)
        if choice < 0:
            break
        _edit_row(catalog, draft, rows[choice][0])
        _save_draft(catalog, draft)
    _refresh()


def clear_draft() -> None:
    catalog = _catalog()
    current = _draft(catalog)
    _save_draft(catalog, {"sort_by": current.get("sort_by") or "popularity.desc"})
    _refresh()


def save_draft() -> None:
    catalog = _catalog()
    draft = _draft(catalog)
    name = g.get_keyboard_input(heading=g.get_language_string(31285), default=str(draft.get("name") or ""))
    if not name or not str(name).strip():
        return
    filters = _clean_filters(draft)
    entries = _load_entries(catalog)
    entries.append({"id": uuid.uuid4().hex, "name": str(name).strip(), "filters": filters})
    _write_entries(catalog, entries)
    _save_draft(catalog, {"sort_by": "popularity.desc"})
    _refresh()


def rename_draft() -> None:
    catalog = _catalog()
    draft = _draft(catalog)
    name = g.get_keyboard_input(heading=g.get_language_string(31286), default=str(draft.get("name") or ""))
    if name is None:
        return
    name = str(name).strip()
    if name:
        draft["name"] = name
    else:
        draft.pop("name", None)
    _save_draft(catalog, draft)
    _refresh()


def rename_list() -> None:
    catalog = _catalog()
    list_id = _requested_list_id()
    entries = _load_entries(catalog)
    entry = next((row for row in entries if str(row.get("id")) == list_id), None)
    if not entry:
        return
    name = g.get_keyboard_input(heading=g.get_language_string(31286), default=str(entry.get("name") or ""))
    if not name or not str(name).strip():
        return
    entry["name"] = str(name).strip()
    _write_entries(catalog, entries)
    _refresh()


def delete_list() -> None:
    catalog = _catalog()
    list_id = _requested_list_id()
    if not list_id or list_id == "draft":
        return
    if not xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(31289)):
        return
    _write_entries(catalog, [row for row in _load_entries(catalog) if str(row.get("id")) != list_id])
    _refresh()


def load_list_into_draft() -> None:
    catalog = _catalog()
    list_id = _requested_list_id()
    entry = next((row for row in _load_entries(catalog) if str(row.get("id")) == list_id), None)
    if not entry:
        return
    draft = _clean_filters(entry.get("filters") or {})
    draft["name"] = str(entry.get("name") or "")
    _save_draft(catalog, draft)
    _refresh()


def _catalog() -> str:
    catalog = str(g.REQUEST_PARAMS.get("catalog") or "movie")
    if isinstance(g.REQUEST_PARAMS.get("action_args"), dict):
        catalog = str(g.REQUEST_PARAMS["action_args"].get("catalog") or catalog)
    return catalog if catalog in ("movie", "tv") else "movie"


def _tmdb_ready() -> bool:
    from resources.lib.meta.provider_settings import notify_tmdb_required, tmdb_features_enabled

    if tmdb_features_enabled():
        return True
    notify_tmdb_required()
    g.cancel_directory()
    return False


def _icon(catalog: str) -> str:
    return "list_movies" if catalog == "movie" else "list_shows"


def _requested_list_id() -> str:
    args = g.REQUEST_PARAMS.get("action_args")
    if isinstance(args, dict) and args.get("list_id"):
        return str(args["list_id"])
    return str(g.REQUEST_PARAMS.get("list_id") or "draft")


def _filters_for(catalog: str, list_id: str) -> dict[str, Any] | None:
    if list_id == "draft":
        return _clean_filters(_draft(catalog))
    entry = next((row for row in _load_entries(catalog) if str(row.get("id")) == list_id), None)
    if not entry:
        return None
    return _clean_filters(entry.get("filters") or {})


def _draft(catalog: str) -> dict[str, Any]:
    stored = g.get_runtime_setting(_draft_key(catalog))
    if isinstance(stored, dict) and stored.get("sort_by"):
        return dict(stored)
    return {"sort_by": "popularity.desc"}


def _save_draft(catalog: str, draft: dict[str, Any]) -> None:
    g.set_runtime_setting(_draft_key(catalog), _clean_filters(draft, keep_name=True))


def _draft_key(catalog: str) -> str:
    return f"tmdb_list_draft_{catalog}"


def _draft_label(draft: dict[str, Any]) -> str:
    name = str(draft.get("name") or "").strip() or g.get_language_string(31281)
    return g.get_language_string(31380) % name


def _sorts(catalog: str) -> tuple[tuple[str, int], ...]:
    return _MOVIE_SORTS if catalog == "movie" else _TV_SORTS


def _editor_rows(catalog: str) -> list[tuple[str, int]]:
    shared = [
        ("sort", 31290),
        ("year", 31304),
    ]
    if catalog == "movie":
        shared.extend([("min_year", 31305), ("max_year", 31306)])
    shared.extend(
        [
            ("genres", 31315),
            ("genres_exclude", 31316),
            ("vote_average_gte", 31405),
            ("vote_average_lte", 31406),
            ("vote_count_gte", 31407),
            ("vote_count_lte", 31408),
            ("runtime_gte", 31409),
            ("runtime_lte", 31410),
            ("original_language", 31411),
            ("origin_country", 31412),
        ]
    )
    if catalog == "tv":
        shared.append(("status", 31420))
        shared.append(("network", 31417))
    else:
        shared.append(("company", 31413))
    shared.append(("exclude_company", 31414))
    return shared


def _summary(catalog: str, filters: dict[str, Any]) -> str:
    parts = [_sort_label(catalog, filters)]
    for key, label_id in _editor_rows(catalog)[1:]:
        if filters.get(key) in (None, "", [], {}):
            continue
        parts.append(f"{g.get_language_string(label_id)}: {_row_value(catalog, filters, key)}")
    return " | ".join(parts)


def _edit_row(catalog: str, draft: dict[str, Any], key: str) -> None:
    if key == "sort":
        _edit_sort(catalog, draft)
    elif key == "year":
        _edit_year(draft)
    elif key in ("min_year", "max_year"):
        _edit_number(draft, key, 31305 if key == "min_year" else 31306, decimal=False)
        if draft.get(key):
            draft.pop("year", None)
    elif key in ("genres", "genres_exclude"):
        _edit_genres(catalog, draft, key)
    elif key == "vote_average_gte":
        _edit_number(draft, key, 31405, decimal=True)
    elif key == "vote_average_lte":
        _edit_number(draft, key, 31406, decimal=True)
    elif key == "vote_count_gte":
        _edit_number(draft, key, 31407, decimal=False)
    elif key == "vote_count_lte":
        _edit_number(draft, key, 31408, decimal=False)
    elif key == "runtime_gte":
        _edit_number(draft, key, 31409, decimal=False)
    elif key == "runtime_lte":
        _edit_number(draft, key, 31410, decimal=False)
    elif key == "original_language":
        _edit_choice(draft, key, 31411, _LANGUAGES)
    elif key == "origin_country":
        _edit_choice(draft, key, 31412, _COUNTRIES)
    elif key == "status":
        _edit_choice(draft, key, 31420, _STATUSES)
    elif key == "company":
        _edit_named(draft, "company", "company_name", 31413, 31415, 31416, "search/company")
    elif key == "exclude_company":
        _edit_named(draft, "exclude_company", "exclude_company_name", 31414, 31415, 31416, "search/company")
    elif key == "network":
        _edit_named(draft, "network", "network_name", 31417, 31418, 31419, "search/network")


def _edit_sort(catalog: str, draft: dict[str, Any]) -> None:
    options = _sorts(catalog)
    labels = [g.get_language_string(label_id) for _value, label_id in options]
    choice = xbmcgui.Dialog().select(g.get_language_string(31290), labels)
    if choice < 0:
        return
    draft["sort_by"] = options[choice][0]


def _edit_year(draft: dict[str, Any]) -> None:
    heading = g.get_language_string(31304)
    choice = xbmcgui.Dialog().select(
        heading,
        [
            g.get_language_string(31291),
            g.get_language_string(31378),
            g.get_language_string(31383),
            g.get_language_string(31384),
            g.get_language_string(31379),
        ],
    )
    if choice < 0:
        return
    if choice == 0:
        draft.pop("year", None)
        return
    if choice in (1, 2, 3):
        draft["year"] = ("current", "next", "previous")[choice - 1]
        draft.pop("min_year", None)
        draft.pop("max_year", None)
        return
    _edit_number(draft, "year", 31304, decimal=False)
    if draft.get("year"):
        draft.pop("min_year", None)
        draft.pop("max_year", None)


def _edit_choice(draft: dict[str, Any], key: str, heading_id: int, choices: tuple[tuple[str, int], ...]) -> None:
    labels = [g.get_language_string(31291)] + [g.get_language_string(label_id) for _value, label_id in choices]
    choice = xbmcgui.Dialog().select(g.get_language_string(heading_id), labels)
    if choice < 0:
        return
    if choice == 0:
        draft.pop(key, None)
        return
    draft[key] = choices[choice - 1][0]


def _edit_genres(catalog: str, draft: dict[str, Any], key: str) -> None:
    from resources.lib.simkl import browse

    heading_id = 31315 if key == "genres" else 31316
    heading = g.get_language_string(heading_id)
    mode = xbmcgui.Dialog().select(heading, [g.get_language_string(31291), g.get_language_string(31324)])
    if mode < 0:
        return
    if mode == 0:
        draft.pop(key, None)
        return
    genres = browse.get_tmdb_genres(catalog)
    if not genres:
        return
    current = {str(value) for value in _as_list(draft.get(key))}
    labels = [str(item.get("name") or item.get("id")) for item in genres]
    preselect = [index for index, item in enumerate(genres) if str(item.get("id")) in current]
    picked = xbmcgui.Dialog().multiselect(heading, labels, preselect=preselect)
    if picked is None:
        return
    values = [str(genres[index]["id"]) for index in picked if genres[index].get("id") is not None]
    if values:
        draft[key] = values
    else:
        draft.pop(key, None)


def _edit_named(
    draft: dict[str, Any],
    id_key: str,
    name_key: str,
    heading_id: int,
    prompt_id: int,
    empty_id: int,
    path: str,
) -> None:
    heading = g.get_language_string(heading_id)
    mode = xbmcgui.Dialog().select(heading, [g.get_language_string(31291), g.get_language_string(31324)])
    if mode < 0:
        return
    if mode == 0:
        draft.pop(id_key, None)
        draft.pop(name_key, None)
        return
    query = g.get_keyboard_input(heading=g.get_language_string(prompt_id), default="")
    if not query or not str(query).strip():
        return
    matches = _search_named(path, str(query).strip())
    if not matches:
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(empty_id))
        return
    choice = xbmcgui.Dialog().select(heading, [name for _item_id, name in matches])
    if choice < 0:
        return
    item_id, name = matches[choice]
    draft[id_key] = str(item_id)
    draft[name_key] = name


def _search_named(path: str, query: str) -> list[tuple[str, str]]:
    from resources.lib.indexers.tmdb import TMDBAPI

    payload = TMDBAPI().get_json(path, raw=True, query=query)
    rows = payload.get("results") if isinstance(payload, dict) else None
    matches: list[tuple[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("id") is None or not row.get("name"):
            continue
        matches.append((str(row["id"]), str(row["name"])))
        if len(matches) >= 20:
            break
    return matches


def _edit_number(draft: dict[str, Any], key: str, heading_id: int, *, decimal: bool) -> None:
    raw = g.get_keyboard_input(heading=g.get_language_string(heading_id), default=str(draft.get(key) or ""))
    if raw is None:
        return
    text = str(raw).strip()
    if not text:
        draft.pop(key, None)
        return
    try:
        value: int | float = float(text) if decimal else int(text)
    except ValueError:
        return
    draft[key] = value


def _row_value(catalog: str, draft: dict[str, Any], key: str) -> str:
    if key == "sort":
        return _sort_label(catalog, draft)
    raw = draft.get(key)
    if key == "year" and str(raw) in _RELATIVE:
        return g.get_language_string(_RELATIVE[str(raw)])
    if key in ("company", "exclude_company", "network"):
        name_key = {
            "company": "company_name",
            "exclude_company": "exclude_company_name",
            "network": "network_name",
        }[key]
        return str(draft.get(name_key) or raw or g.get_language_string(31291))
    if key in ("genres", "genres_exclude"):
        values = _as_list(raw)
        if not values:
            return g.get_language_string(31291)
        return ", ".join(_genre_names(catalog, values))
    if raw in (None, "", [], {}):
        return g.get_language_string(31291)
    return _choice_label(_choices_for(key), raw)


def _choices_for(key: str) -> tuple[tuple[str, int], ...]:
    return {
        "original_language": _LANGUAGES,
        "origin_country": _COUNTRIES,
        "status": _STATUSES,
    }.get(key, ())


def _choice_label(choices: tuple[tuple[str, int], ...], value: Any) -> str:
    for choice, label_id in choices:
        if choice == str(value):
            return g.get_language_string(label_id)
    return str(value)


def _sort_label(catalog: str, draft: dict[str, Any]) -> str:
    sort_by = str(draft.get("sort_by") or "popularity.desc")
    for value, label_id in _sorts(catalog):
        if value == sort_by:
            return g.get_language_string(label_id)
    return sort_by


def _genre_names(catalog: str, values: list[str]) -> list[str]:
    from resources.lib.simkl import browse

    names = {str(item.get("id")): str(item.get("name")) for item in browse.get_tmdb_genres(catalog)}
    return [names.get(value, value) for value in values]


class _FetchedPage:
    def __init__(self, items: list[dict], has_next: bool):
        self.items = items
        self.has_next = has_next


def _fetch_page(catalog: str, filters: dict[str, Any], menu_page: int, page_limit: int) -> _FetchedPage:
    from resources.lib.indexers.tmdb import TMDBAPI
    from resources.lib.simkl.browse import _parallel_resolve_tmdb_discover_rows

    token = f"{catalog}:{_filter_token(_query_filters(catalog, filters))}"
    state = _STREAMS.get(token)
    if state is None:
        state = {"items": [], "tmdb_page": 1, "total_pages": 1, "exhausted": False, "seen": set(), "empty_pages": 0}
        _STREAMS[token] = state
        _STREAM_ORDER.append(token)
        while len(_STREAM_ORDER) > 6:
            _STREAMS.pop(_STREAM_ORDER.pop(0), None)

    need = menu_page * page_limit
    tmdb = TMDBAPI()
    media = "movie" if catalog == "movie" else "tv"
    while len(state["items"]) < need and not state["exhausted"] and int(state["tmdb_page"]) <= int(state["total_pages"]):
        params = _tmdb_params(catalog, filters, int(state["tmdb_page"]))
        params["include_adult"] = False
        params["language"] = tmdb.lang_full_code
        response = tmdb.get_json(f"discover/{media}", raw=True, **params)
        rows = response.get("results") if isinstance(response, dict) else None
        if not isinstance(rows, list) or not rows:
            state["exhausted"] = True
            break
        state["total_pages"] = int(response.get("total_pages") or 1)
        resolved = _parallel_resolve_tmdb_discover_rows(rows, catalog)
        before = len(state["items"])
        for row in rows:
            if not isinstance(row, dict) or row.get("id") is None:
                continue
            try:
                tmdb_id = int(row["id"])
            except (TypeError, ValueError):
                continue
            normalized = resolved.get(tmdb_id)
            if not normalized or normalized.get("simkl_id") is None:
                continue
            simkl_id = int(normalized["simkl_id"])
            if simkl_id in state["seen"]:
                continue
            state["seen"].add(simkl_id)
            state["items"].append(normalized)
        if len(state["items"]) == before:
            state["empty_pages"] = int(state["empty_pages"]) + 1
        else:
            state["empty_pages"] = 0
        if int(state["tmdb_page"]) >= int(state["total_pages"]) or int(state["empty_pages"]) >= 3:
            state["exhausted"] = True
            break
        state["tmdb_page"] = int(state["tmdb_page"]) + 1

    start = (menu_page - 1) * page_limit
    end = start + page_limit
    return _FetchedPage(state["items"][start:end], len(state["items"]) > end or not state["exhausted"])


def _tmdb_params(catalog: str, filters: dict[str, Any], page: int) -> dict[str, Any]:
    resolved = _query_filters(catalog, filters)
    allowed_sorts = {value for value, _label in _sorts(catalog)}
    sort_by = str(resolved.get("sort_by") or "popularity.desc")
    if sort_by not in allowed_sorts:
        sort_by = "popularity.desc"
    params: dict[str, Any] = {"page": page, "sort_by": sort_by}
    year_key = "primary_release_year" if catalog == "movie" else "first_air_date_year"
    year = _as_int(resolved.get("year"))
    if year is not None:
        params[year_key] = year
    if catalog == "movie" and year is None:
        min_year = _as_int(resolved.get("min_year"))
        max_year = _as_int(resolved.get("max_year"))
        if min_year is not None:
            params["primary_release_date.gte"] = f"{min_year}-01-01"
        if max_year is not None:
            params["primary_release_date.lte"] = f"{max_year}-12-31"
    mapping = [
        ("genres", "with_genres"),
        ("genres_exclude", "without_genres"),
        ("vote_average_gte", "vote_average.gte"),
        ("vote_average_lte", "vote_average.lte"),
        ("vote_count_gte", "vote_count.gte"),
        ("vote_count_lte", "vote_count.lte"),
        ("runtime_gte", "with_runtime.gte"),
        ("runtime_lte", "with_runtime.lte"),
        ("original_language", "with_original_language"),
        ("origin_country", "with_origin_country"),
        ("exclude_company", "without_companies"),
    ]
    if catalog == "movie":
        mapping.append(("company", "with_companies"))
    else:
        mapping.extend((("network", "with_networks"), ("status", "with_status")))
    for source, target in mapping:
        value = resolved.get(source)
        if value in (None, "", [], {}):
            continue
        if source == "original_language" and str(value) not in _LANGUAGE_VALUES:
            continue
        if source == "origin_country" and str(value) not in _COUNTRY_VALUES:
            continue
        if source == "status" and str(value) not in _STATUS_VALUES:
            continue
        if isinstance(value, list):
            params[target] = ",".join(str(part) for part in value if str(part))
        else:
            params[target] = value
    return params


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _query_filters(catalog: str, filters: dict[str, Any]) -> dict[str, Any]:
    del catalog
    import datetime

    out = dict(filters)
    year = out.get("year")
    if year == "current":
        out["year"] = datetime.date.today().year
    elif year == "next":
        out["year"] = datetime.date.today().year + 1
    elif year == "previous":
        out["year"] = datetime.date.today().year - 1
    return out


def _filter_token(filters: dict[str, Any]) -> str:
    return tools.md5_hash(_clean_filters(filters))[:16]


def _clean_filters(filters: dict[str, Any], *, keep_name: bool = False) -> dict[str, Any]:
    cleaned: dict[str, Any] = {"sort_by": str(filters.get("sort_by") or "popularity.desc")}
    if keep_name and filters.get("name"):
        cleaned["name"] = str(filters["name"])
    keys = (
        "year",
        "min_year",
        "max_year",
        "genres",
        "genres_exclude",
        "vote_average_gte",
        "vote_average_lte",
        "vote_count_gte",
        "vote_count_lte",
        "runtime_gte",
        "runtime_lte",
        "original_language",
        "origin_country",
        "company",
        "company_name",
        "exclude_company",
        "exclude_company_name",
        "network",
        "network_name",
        "status",
    )
    for key in keys:
        value = filters.get(key)
        if value in (None, "", [], {}):
            continue
        cleaned[key] = value
    return cleaned


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(part) for part in value if str(part)]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _load_entries(catalog: str) -> list[dict[str, Any]]:
    from resources.lib.database.saved_lists import load_saved_lists

    return load_saved_lists(catalog)


def _write_entries(catalog: str, entries: list[dict[str, Any]]) -> None:
    from resources.lib.database.saved_lists import save_saved_lists

    save_saved_lists(catalog, entries)


def _plugin(action: str, list_id: str, catalog: str) -> str:
    url = g.create_url(g.BASE_URL, {"action": action, "list_id": list_id, "catalog": catalog})
    return f"RunPlugin({url})"


def _refresh() -> None:
    g.refresh_visible_container()

"""Saved Tenrai anime lists. One draft, edited in a dialog, opened through Simkl."""
from __future__ import annotations

import uuid
from typing import Any

import xbmcgui

from resources.lib.common import tools
from resources.lib.modules.globals import g

_DRAFT_KEY = "tenrai_anime_list_draft"
_STREAMS: dict[str, dict[str, Any]] = {}
_STREAM_ORDER: list[str] = []

_SORTS: tuple[tuple[str, str, int], ...] = (
    ("members", "desc", 31292),
    ("popularity", "asc", 31293),
    ("score", "desc", 31294),
    ("favorites", "desc", 31295),
    ("title", "asc", 31296),
    ("start_date", "desc", 31297),
    ("episodes", "desc", 31298),
    ("scored_by", "desc", 31299),
    ("rank", "asc", 31300),
    ("added", "desc", 31301),
)
_SEASONS = (
    ("current", 31378),
    ("next", 31383),
    ("previous", 31384),
    ("winter", 31327),
    ("spring", 31328),
    ("summer", 31329),
    ("fall", 31330),
)
_RELATIVE_LABELS = {
    "current": 31378,
    "next": 31383,
    "previous": 31384,
}
_DAYS = (
    ("monday", 31333),
    ("tuesday", 31334),
    ("wednesday", 31335),
    ("thursday", 31336),
    ("friday", 31337),
    ("saturday", 31338),
    ("sunday", 31339),
    ("today", 31331),
    ("tomorrow", 31332),
    ("other", 31365),
)
_TYPES = (
    ("tv", 31340),
    ("movie", 31341),
    ("ova", 31342),
    ("ona", 31343),
    ("special", 31344),
    ("tv_special", 31345),
)
_STATUSES = (
    ("airing", 31346),
    ("complete", 31347),
    ("upcoming", 31348),
)
_RATINGS = (
    ("g", 31349),
    ("pg", 31350),
    ("pg13", 31351),
    ("r17", 31352),
    ("r", 31353),
    ("rx", 31354),
)
_SOURCES = (
    ("original", 31355),
    ("manga", 31356),
    ("light_novel", 31357),
    ("web_novel", 31358),
    ("visual_novel", 31359),
    ("game", 31360),
    ("web_manga", 31361),
    ("novel", 31362),
    ("4_koma_manga", 31363),
    ("mixed_media", 31364),
    ("other", 31365),
)
_LANGUAGES = (
    ("english", 31366),
    ("french", 31367),
    ("german", 31368),
    ("spanish", 31369),
    ("portuguese_br", 31370),
    ("italian", 31371),
    ("korean", 31372),
    ("mandarin", 31373),
    ("hebrew", 31374),
    ("hungarian", 31375),
    ("japanese", 31376),
)

_QUERY_KEYS = (
    "season",
    "year",
    "min_year",
    "max_year",
    "broadcast_day",
    "type",
    "type_exclude",
    "status",
    "status_exclude",
    "rating",
    "rating_exclude",
    "source",
    "genres",
    "genres_exclude",
    "min_score",
    "min_members",
    "min_episodes",
    "max_episodes",
    "voice_language",
    "producers",
)


def show_lists() -> None:
    draft = _draft()
    g.add_directory_item(
        _draft_label(draft),
        action="animeTenraiListOpen",
        list_id="draft",
        description=_summary(draft),
        cm=[(g.get_language_string(31286), _plugin("animeTenraiListRenameDraft", "draft"))],
        menu_item=g.create_icon_dict("list_anime", g.ICONS_PATH),
    )
    g.add_directory_item(
        g.get_language_string(31282),
        action="animeTenraiListEdit",
        is_folder=False,
        description=g.get_language_string(31381),
        menu_item=g.create_icon_dict("list_anime", g.ICONS_PATH),
    )
    g.add_directory_item(
        g.get_language_string(31283),
        action="animeTenraiListClear",
        is_folder=False,
        description=g.get_language_string(31382),
        menu_item=g.create_icon_dict("list_anime", g.ICONS_PATH),
    )
    g.add_directory_item(
        g.get_language_string(31284),
        action="animeTenraiListSave",
        is_folder=False,
        menu_item=g.create_icon_dict("list_anime", g.ICONS_PATH),
    )
    for entry in _load_entries():
        list_id = str(entry.get("id") or "")
        if not list_id:
            continue
        g.add_directory_item(
            str(entry.get("name") or g.get_language_string(31281)),
            action="animeTenraiListOpen",
            list_id=list_id,
            description=_summary(entry.get("filters") or {}),
            cm=[
                (g.get_language_string(31286), _plugin("animeTenraiListRename", list_id)),
                (g.get_language_string(31287), _plugin("animeTenraiListDelete", list_id)),
                (g.get_language_string(31288), _plugin("animeTenraiListLoad", list_id)),
            ],
            menu_item=g.create_icon_dict("list_anime", g.ICONS_PATH),
        )
    g.close_directory(g.CONTENT_MENU, cache=False)


def open_list(list_builder) -> None:
    from resources.lib.meta.list_pipeline import make_list_id
    from resources.lib.pipeline.catalog_page import CatalogPagePipeline
    from resources.lib.simkl import browse
    from resources.lib.simkl.search_menus import notify_empty_search

    list_id = _requested_list_id()
    filters = _filters_for(list_id)
    if not filters:
        g.cancel_directory()
        return
    page_limit = max(1, int(g.get_int_setting("item.limit", 20) or 20))
    menu_page = max(1, int(g.PAGE or 1))
    fetched = _fetch_page(filters, menu_page, page_limit)
    if not fetched.items:
        notify_empty_search(30766)
        return
    page = browse.GenreBrowsePage(fetched.items, fetched.has_next)
    CatalogPagePipeline.open_genre(
        "anime",
        page,
        list_builder,
        next_action="animeTenraiListOpen",
        next_args={"list_id": list_id},
        list_id=make_list_id("tenrai-custom", list_id, _filter_token(_query_filters(filters)), menu_page),
        browse_source=f"tenrai_custom:{list_id}",
    )


def edit_draft() -> None:
    draft = _draft()
    while True:
        rows = _editor_rows(draft)
        labels = [f"{g.get_language_string(label_id)}: {_row_value(draft, key)}" for key, label_id in rows]
        choice = xbmcgui.Dialog().select(g.get_language_string(31282), labels)
        if choice < 0:
            break
        _edit_row(draft, rows[choice][0])
        _save_draft(draft)
    _refresh()


def clear_draft() -> None:
    current = _draft()
    _save_draft({"order_by": current.get("order_by") or "members", "sort": current.get("sort") or "desc"})
    _refresh()


def save_draft() -> None:
    draft = _draft()
    name = g.get_keyboard_input(
        heading=g.get_language_string(31285),
        default=str(draft.get("name") or ""),
    )
    if not name or not str(name).strip():
        return
    filters = _clean_filters(draft)
    filters.pop("name", None)
    entries = _load_entries()
    entries.append({"id": uuid.uuid4().hex, "name": str(name).strip(), "filters": filters})
    _write_entries(entries)
    _save_draft({"order_by": "members", "sort": "desc"})
    _refresh()


def rename_draft() -> None:
    draft = _draft()
    name = g.get_keyboard_input(
        heading=g.get_language_string(31286),
        default=str(draft.get("name") or ""),
    )
    if name is None:
        return
    name = str(name).strip()
    if name:
        draft["name"] = name
    else:
        draft.pop("name", None)
    _save_draft(draft)
    _refresh()


def rename_list() -> None:
    list_id = _requested_list_id()
    entries = _load_entries()
    entry = next((row for row in entries if str(row.get("id")) == list_id), None)
    if not entry:
        return
    name = g.get_keyboard_input(
        heading=g.get_language_string(31286),
        default=str(entry.get("name") or ""),
    )
    if not name or not str(name).strip():
        return
    entry["name"] = str(name).strip()
    _write_entries(entries)
    _refresh()


def delete_list() -> None:
    list_id = _requested_list_id()
    if not list_id or list_id == "draft":
        return
    if not xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(31289)):
        return
    _write_entries([row for row in _load_entries() if str(row.get("id")) != list_id])
    _refresh()


def load_list_into_draft() -> None:
    list_id = _requested_list_id()
    entry = next((row for row in _load_entries() if str(row.get("id")) == list_id), None)
    if not entry:
        return
    draft = _clean_filters(entry.get("filters") or {})
    draft["name"] = str(entry.get("name") or "")
    _save_draft(draft)
    _refresh()


def _requested_list_id() -> str:
    args = g.REQUEST_PARAMS.get("action_args")
    if isinstance(args, dict) and args.get("list_id"):
        return str(args["list_id"])
    return str(g.REQUEST_PARAMS.get("list_id") or "draft")


def _filters_for(list_id: str) -> dict[str, Any] | None:
    if list_id == "draft":
        return _clean_filters(_draft())
    entry = next((row for row in _load_entries() if str(row.get("id")) == list_id), None)
    if not entry:
        return None
    return _clean_filters(entry.get("filters") or {})


def _draft() -> dict[str, Any]:
    stored = g.get_runtime_setting(_DRAFT_KEY)
    if isinstance(stored, dict) and stored.get("order_by"):
        return dict(stored)
    return {"order_by": "members", "sort": "desc"}


def _save_draft(draft: dict[str, Any]) -> None:
    g.set_runtime_setting(_DRAFT_KEY, _clean_filters(draft, keep_name=True))


def _draft_label(draft: dict[str, Any]) -> str:
    name = str(draft.get("name") or "").strip() or g.get_language_string(31281)
    return g.get_language_string(31380) % name


def _summary(filters: dict[str, Any]) -> str:
    parts = [_sort_label(filters)]
    for key, label_id in _editor_rows(filters)[1:]:
        if _raw(filters, key) in (None, "", [], {}):
            continue
        parts.append(f"{g.get_language_string(label_id)}: {_row_value(filters, key)}")
    return " | ".join(parts)


def _editor_rows(draft: dict[str, Any]) -> list[tuple[str, int]]:
    del draft
    return [
        ("sort", 31290),
        ("season", 31302),
        ("year", 31304),
        ("min_year", 31305),
        ("max_year", 31306),
        ("broadcast_day", 31307),
        ("type", 31308),
        ("type_exclude", 31309),
        ("status", 31310),
        ("status_exclude", 31311),
        ("rating", 31312),
        ("rating_exclude", 31313),
        ("source", 31314),
        ("genres", 31315),
        ("genres_exclude", 31316),
        ("min_score", 31317),
        ("min_members", 31318),
        ("min_episodes", 31319),
        ("max_episodes", 31320),
        ("voice_language", 31321),
        ("producers", 31322),
        ("sfw_strict", 31323),
    ]


def _edit_row(draft: dict[str, Any], key: str) -> None:
    if key == "sort":
        _edit_sort(draft)
    elif key == "season":
        _edit_choice(draft, "season", 31302, _SEASONS)
    elif key == "year":
        _edit_year(draft)
    elif key == "broadcast_day":
        _edit_choice(draft, "broadcast_day", 31307, _DAYS)
    elif key == "voice_language":
        _edit_choice(draft, "voice_language", 31321, _LANGUAGES)
    elif key == "source":
        _edit_choice(draft, "source", 31314, _SOURCES)
    elif key in ("type", "type_exclude"):
        _edit_multi(draft, key, 31308 if key == "type" else 31309, _TYPES)
    elif key in ("status", "status_exclude"):
        _edit_multi(draft, key, 31310 if key == "status" else 31311, _STATUSES)
    elif key in ("rating", "rating_exclude"):
        _edit_multi(draft, key, 31312 if key == "rating" else 31313, _RATINGS)
    elif key in ("genres", "genres_exclude"):
        _edit_genres(draft, key)
    elif key == "producers":
        _edit_studio(draft)
    elif key == "sfw_strict":
        _edit_bool(draft, "sfw_strict", 31323)
    elif key == "min_score":
        _edit_number(draft, key, 31317, decimal=True)
    elif key in ("min_year", "max_year", "min_members", "min_episodes", "max_episodes"):
        labels = {
            "min_year": 31305,
            "max_year": 31306,
            "min_members": 31318,
            "min_episodes": 31319,
            "max_episodes": 31320,
        }
        _edit_number(draft, key, labels[key], decimal=False)
        if key in ("min_year", "max_year") and draft.get(key):
            draft.pop("year", None)


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


def _edit_sort(draft: dict[str, Any]) -> None:
    labels = [g.get_language_string(label_id) for _order, _sort, label_id in _SORTS]
    choice = xbmcgui.Dialog().select(g.get_language_string(31290), labels)
    if choice < 0:
        return
    order_by, sort, _label = _SORTS[choice]
    draft["order_by"] = order_by
    draft["sort"] = sort


def _edit_choice(draft: dict[str, Any], key: str, heading_id: int, choices: tuple[tuple[str, int], ...]) -> None:
    labels = [g.get_language_string(31291)] + [g.get_language_string(label_id) for _value, label_id in choices]
    choice = xbmcgui.Dialog().select(g.get_language_string(heading_id), labels)
    if choice < 0:
        return
    if choice == 0:
        draft.pop(key, None)
        return
    draft[key] = choices[choice - 1][0]


def _edit_multi(draft: dict[str, Any], key: str, heading_id: int, choices: tuple[tuple[str, int], ...]) -> None:
    heading = g.get_language_string(heading_id)
    mode = xbmcgui.Dialog().select(heading, [g.get_language_string(31291), g.get_language_string(31324)])
    if mode < 0:
        return
    if mode == 0:
        draft.pop(key, None)
        return
    current = _as_list(draft.get(key))
    labels = [g.get_language_string(label_id) for _value, label_id in choices]
    preselect = [index for index, (value, _label) in enumerate(choices) if value in current]
    picked = xbmcgui.Dialog().multiselect(heading, labels, preselect=preselect)
    if picked is None:
        return
    values = [choices[index][0] for index in picked]
    if values:
        draft[key] = values
    else:
        draft.pop(key, None)


def _edit_genres(draft: dict[str, Any], key: str) -> None:
    from resources.lib.simkl import browse

    heading_id = 31315 if key == "genres" else 31316
    heading = g.get_language_string(heading_id)
    mode = xbmcgui.Dialog().select(heading, [g.get_language_string(31291), g.get_language_string(31324)])
    if mode < 0:
        return
    if mode == 0:
        draft.pop(key, None)
        return
    picker = browse.get_tenrai_anime_picker_items()
    items = list(picker.get("genres") or []) + list(picker.get("tags") or [])
    if not items:
        return
    current = {str(value) for value in _as_list(draft.get(key))}
    labels = [str(item.get("name") or item.get("mal_id")) for item in items]
    preselect = [index for index, item in enumerate(items) if str(item.get("mal_id")) in current]
    picked = xbmcgui.Dialog().multiselect(heading, labels, preselect=preselect)
    if picked is None:
        return
    values = [str(items[index]["mal_id"]) for index in picked if items[index].get("mal_id") is not None]
    if values:
        draft[key] = values
    else:
        draft.pop(key, None)


def _edit_studio(draft: dict[str, Any]) -> None:
    heading = g.get_language_string(31322)
    mode = xbmcgui.Dialog().select(heading, [g.get_language_string(31291), g.get_language_string(31324)])
    if mode < 0:
        return
    if mode == 0:
        draft.pop("producers", None)
        draft.pop("producers_name", None)
        return
    query = g.get_keyboard_input(heading=g.get_language_string(31325))
    if not query or not str(query).strip():
        return
    matches = _search_studios(str(query).strip())
    if not matches:
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(31326))
        return
    labels = [name for _mal_id, name in matches]
    choice = xbmcgui.Dialog().select(heading, labels)
    if choice < 0:
        return
    mal_id, name = matches[choice]
    draft["producers"] = str(mal_id)
    draft["producers_name"] = name


def _search_studios(query: str) -> list[tuple[str, str]]:
    from resources.lib.indexers.tenrai import TenraiAPI

    payload = TenraiAPI().get_json("producers", raw=True, q=query, limit=20)
    rows = payload.get("data") if isinstance(payload, dict) else None
    matches: list[tuple[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("mal_id") is None:
            continue
        name = _producer_name(row)
        if name:
            matches.append((str(row["mal_id"]), name))
    return matches


def _producer_name(row: dict[str, Any]) -> str:
    if row.get("name"):
        return str(row["name"])
    titles = row.get("titles") or []
    if titles and isinstance(titles[0], dict) and titles[0].get("title"):
        return str(titles[0]["title"])
    return ""


def _edit_bool(draft: dict[str, Any], key: str, heading_id: int) -> None:
    choice = xbmcgui.Dialog().select(
        g.get_language_string(heading_id),
        [g.get_language_string(31291), g.get_language_string(31377)],
    )
    if choice < 0:
        return
    if choice == 0:
        draft.pop(key, None)
    else:
        draft[key] = True


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
    if not decimal and isinstance(value, float):
        value = int(value)
    draft[key] = value


def _row_value(draft: dict[str, Any], key: str) -> str:
    if key == "sort":
        return _sort_label(draft)
    if key == "sfw_strict":
        return g.get_language_string(31377 if draft.get("sfw_strict") else 31291)
    if key == "producers":
        return str(draft.get("producers_name") or draft.get("producers") or g.get_language_string(31291))
    if key in ("genres", "genres_exclude"):
        values = _as_list(draft.get(key))
        if not values:
            return g.get_language_string(31291)
        return ", ".join(_genre_names(values))
    raw = draft.get(key)
    if key in ("season", "year") and str(raw) in _RELATIVE_LABELS:
        return g.get_language_string(_RELATIVE_LABELS[str(raw)])
    if raw in (None, "", [], {}):
        return g.get_language_string(31291)
    if isinstance(raw, list):
        return ", ".join(_choice_label(_choices_for(key), value) for value in raw)
    return _choice_label(_choices_for(key), raw)


def _choices_for(key: str) -> tuple[tuple[str, int], ...]:
    return {
        "season": _SEASONS,
        "broadcast_day": _DAYS,
        "type": _TYPES,
        "type_exclude": _TYPES,
        "status": _STATUSES,
        "status_exclude": _STATUSES,
        "rating": _RATINGS,
        "rating_exclude": _RATINGS,
        "source": _SOURCES,
        "voice_language": _LANGUAGES,
    }.get(key, ())


def _choice_label(choices: tuple[tuple[str, int], ...], value: Any) -> str:
    for choice, label_id in choices:
        if choice == str(value):
            return g.get_language_string(label_id)
    return str(value)


def _sort_label(draft: dict[str, Any]) -> str:
    order_by = str(draft.get("order_by") or "members")
    sort = str(draft.get("sort") or "desc")
    for known_order, known_sort, label_id in _SORTS:
        if known_order == order_by and known_sort == sort:
            return g.get_language_string(label_id)
    return order_by


def _genre_names(values: list[str]) -> list[str]:
    from resources.lib.simkl import browse

    picker = browse.get_tenrai_anime_picker_items()
    names = {
        str(item.get("mal_id")): str(item.get("name"))
        for item in list(picker.get("genres") or []) + list(picker.get("tags") or [])
        if item.get("mal_id") is not None
    }
    return [names.get(value, value) for value in values]


def _raw(filters: dict[str, Any], key: str) -> Any:
    if key == "sort":
        return filters.get("order_by")
    return filters.get(key)


class _FetchedPage:
    def __init__(self, items: list[dict], has_next: bool):
        self.items = items
        self.has_next = has_next


def _fetch_page(filters: dict[str, Any], menu_page: int, page_limit: int) -> _FetchedPage:
    from resources.lib.indexers.tenrai import TenraiAPI
    from resources.lib.simkl.browse import _append_tenrai_resolved_rows, _parallel_resolve_mal_rows

    token = _filter_token(_query_filters(filters))
    state = _STREAMS.get(token)
    if state is None:
        state = {"items": [], "tenrai_page": 1, "exhausted": False, "seen": set(), "empty_pages": 0}
        _STREAMS[token] = state
        _STREAM_ORDER.append(token)
        while len(_STREAM_ORDER) > 6:
            _STREAMS.pop(_STREAM_ORDER.pop(0), None)

    need = menu_page * page_limit
    tenrai = TenraiAPI()
    while len(state["items"]) < need and not state["exhausted"]:
        response = tenrai.get_json("anime", raw=True, **_tenrai_params(filters, int(state["tenrai_page"]), page_limit))
        rows = response.get("data") if isinstance(response, dict) else None
        if not isinstance(rows, list) or not rows:
            state["exhausted"] = True
            break
        before = len(state["items"])
        _append_tenrai_resolved_rows(state["items"], rows, _parallel_resolve_mal_rows(rows), state["seen"])
        if len(state["items"]) == before:
            state["empty_pages"] = int(state["empty_pages"]) + 1
        else:
            state["empty_pages"] = 0
        pagination = response.get("pagination") if isinstance(response, dict) else {}
        has_next = bool((pagination or {}).get("has_next_page"))
        if not has_next or int(state["empty_pages"]) >= 3:
            state["exhausted"] = True
            break
        state["tenrai_page"] = int(state["tenrai_page"]) + 1

    start = (menu_page - 1) * page_limit
    end = start + page_limit
    chunk = state["items"][start:end]
    has_next = len(state["items"]) > end or not state["exhausted"]
    return _FetchedPage(chunk, has_next)


def _current_mal_season() -> tuple[str, int]:
    """MAL cour for today. Winter is January-March, then spring, summer, and fall."""
    import datetime

    today = datetime.date.today()
    if today.month <= 3:
        return "winter", today.year
    if today.month <= 6:
        return "spring", today.year
    if today.month <= 9:
        return "summer", today.year
    return "fall", today.year


def _shift_mal_season(season: str, year: int, steps: int) -> tuple[str, int]:
    order = ("winter", "spring", "summer", "fall")
    index = order.index(season) + steps
    year += index // 4
    index %= 4
    return order[index], year


def _chosen_year(year: Any, current_year: int) -> int | None:
    if year == "current":
        return current_year
    if year == "next":
        return current_year + 1
    if year == "previous":
        return current_year - 1
    if year in (None, ""):
        return None
    return int(year)


def _query_filters(filters: dict[str, Any]) -> dict[str, Any]:
    """Turn Current, Next, and Previous into a season and season year when the list is opened."""
    out = dict(filters)
    if out.get("season_year") and not out.get("year"):
        out["year"] = out["season_year"]
    out.pop("season_year", None)
    season = out.get("season")
    year = out.get("year")
    current_season, current_year = _current_mal_season()
    if season == "current":
        resolved_season, resolved_year = current_season, current_year
    elif season == "next":
        resolved_season, resolved_year = _shift_mal_season(current_season, current_year, 1)
    elif season == "previous":
        resolved_season, resolved_year = _shift_mal_season(current_season, current_year, -1)
    else:
        resolved_season, resolved_year = None, None
    if resolved_season:
        out["season"] = resolved_season
        out["season_year"] = resolved_year
        out.pop("year", None)
        return out
    chosen_year = _chosen_year(year, current_year)
    if season:
        out.pop("year", None)
        if chosen_year is not None:
            out["season_year"] = chosen_year
    elif chosen_year is not None:
        out["season_year"] = chosen_year
        out.pop("year", None)
    return out


def _tenrai_params(filters: dict[str, Any], page: int, page_limit: int) -> dict[str, Any]:
    from resources.lib.simkl.browse import adult_content_enabled

    filters = _query_filters(filters)
    params: dict[str, Any] = {
        "page": page,
        "limit": min(100, max(1, int(page_limit))),
        "order_by": filters.get("order_by") or "members",
        "sort": filters.get("sort") or "desc",
    }
    for key in _QUERY_KEYS + ("season_year",):
        value = filters.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            params[key] = ",".join(str(part) for part in value)
        else:
            params[key] = value
    if filters.get("sfw_strict"):
        params["sfw-strict"] = "true"
    elif not adult_content_enabled():
        params["sfw"] = "true"
    return params


def _filter_token(filters: dict[str, Any]) -> str:
    return tools.md5_hash(_clean_filters(filters))[:16]


def _clean_filters(filters: dict[str, Any], *, keep_name: bool = False) -> dict[str, Any]:
    cleaned: dict[str, Any] = {
        "order_by": str(filters.get("order_by") or "members"),
        "sort": str(filters.get("sort") or "desc"),
    }
    if keep_name and filters.get("name"):
        cleaned["name"] = str(filters["name"])
    for key in _QUERY_KEYS:
        value = filters.get(key)
        if value in (None, "", [], {}):
            continue
        cleaned[key] = value
    if filters.get("sfw_strict"):
        cleaned["sfw_strict"] = True
    if filters.get("producers_name"):
        cleaned["producers_name"] = str(filters["producers_name"])
    return cleaned


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(part) for part in value if str(part)]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _load_entries() -> list[dict[str, Any]]:
    from resources.lib.database.saved_lists import load_saved_lists

    return load_saved_lists("anime")


def _write_entries(entries: list[dict[str, Any]]) -> None:
    from resources.lib.database.saved_lists import save_saved_lists

    save_saved_lists("anime", entries)


def _plugin(action: str, list_id: str) -> str:
    url = g.create_url(g.BASE_URL, {"action": action, "list_id": list_id})
    return f"RunPlugin({url})"


def _refresh() -> None:
    g.refresh_visible_container()

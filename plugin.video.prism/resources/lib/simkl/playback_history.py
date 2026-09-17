"""My Watch History main-menu helpers."""
from __future__ import annotations

from resources.lib.database.session import get_sync_database
from resources.lib.modules.globals import g
from resources.lib.modules.list_builder import ListBuilder
from resources.lib.modules.metadataHandler import MetadataHandler
from resources.lib.simkl.ids import build_action_args

def _home_enabled(setting_id: str, default: bool = True) -> bool:
    value = g.get_setting(setting_id)
    if value in (None, ""):
        return default
    return g.get_bool_setting(setting_id)


def _show_display_title(show_id: int) -> str:
    db = get_sync_database()
    try:
        show_row = db.get_show(int(show_id))
        if isinstance(show_row, dict) and show_row.get("name"):
            return str(show_row["name"])
    except Exception:
        pass
    return str(show_id)


def _entry_display_title(entry: dict) -> str:
    db = get_sync_database()
    if entry.get("kind") == "movie":
        try:
            movie_row = db.get_movie(int(entry["simkl_id"]))
            if isinstance(movie_row, dict) and movie_row.get("name"):
                return str(movie_row["name"])
        except Exception:
            pass
        sync_row = entry.get("sync_row") if isinstance(entry.get("sync_row"), dict) else {}
        info = MetadataHandler.simkl_info(sync_row) or {}
        title = info.get("title") or info.get("originaltitle")
        if title:
            year = info.get("year")
            return f"{title} ({year})" if year else str(title)
        return str(entry.get("simkl_id") or "")

    season = entry.get("season")
    episode = entry.get("episode")
    ep_label = ""
    if season is not None and episode is not None:
        ep_label = f" S{int(season):02d}E{int(episode):02d}"

    show_id = entry.get("simkl_show_id")
    if show_id is not None:
        try:
            show_row = db.get_show(int(show_id))
            if isinstance(show_row, dict) and show_row.get("name"):
                return f"{show_row['name']}{ep_label}"
        except Exception:
            pass

    sync_row = entry.get("sync_row") if isinstance(entry.get("sync_row"), dict) else {}
    show_blob = sync_row.get("show") if isinstance(sync_row.get("show"), dict) else {}
    show_info = MetadataHandler.simkl_info(show_blob) or {}
    title = show_info.get("tvshowtitle") or show_info.get("title")
    if title:
        return f"{title}{ep_label}"
    return ep_label.strip() or str(entry.get("simkl_id") or "")


def hydrate_movie_menu_row(simkl_id: int) -> dict | None:
    db = get_sync_database()
    try:
        row = db.get_movie(int(simkl_id))
    except Exception:
        row = None
    return row if isinstance(row, dict) else None


def hydrate_show_menu_row(show_id: int, catalog: str | None = None) -> dict | None:
    db = get_sync_database()
    try:
        ref = {"simkl_id": int(show_id)}
        if catalog:
            ref["catalog"] = catalog
        rows = db.get_show_list([ref], hide_unaired=False, hide_watched=False)
        if rows and isinstance(rows[0], dict):
            return rows[0]
    except Exception:
        pass
    return None


def _menu_row_for_entry(entry: dict) -> dict | None:
    db = get_sync_database()
    resume_time = entry.get("resume_time")
    percent_played = entry.get("percent_played")
    in_progress = bool(entry.get("in_progress"))
    label = _entry_display_title(entry)

    if entry.get("kind") == "movie":
        menu_row = hydrate_movie_menu_row(int(entry["simkl_id"]))
        if not menu_row:
            return None
        menu_row["name"] = label
        menu_row.setdefault("catalog", "movie")
        info = menu_row.get("info")
        if isinstance(info, dict):
            info.setdefault("mediatype", "movie")
            info.setdefault("catalog", "movie")
        if in_progress:
            menu_row["resume_time"] = resume_time
            menu_row["percent_played"] = percent_played
            menu_row["force_resume_indicator"] = True
        return {
            "kind": "movie",
            "label": label,
            "action": "getSources",
            "is_folder": False,
            "is_playable": True,
            "menu_item": menu_row,
            "action_args": build_action_args(menu_row),
            "resume": resume_time,
        }

    show_id = entry.get("simkl_show_id")
    if show_id is None:
        return None

    catalog = entry.get("catalog") or db.show_catalog(int(show_id))
    show_row = hydrate_show_menu_row(int(show_id), catalog=catalog)
    if not show_row:
        return None
    show_row.setdefault("catalog", catalog)
    info = show_row.get("info")
    if not isinstance(info, dict):
        info = {}
        show_row["info"] = info
    info.setdefault("mediatype", "tvshow")
    info.setdefault("catalog", catalog)
    show_name = _show_display_title(int(show_id))
    show_row["name"] = show_name
    return {
        "kind": "show",
        "catalog": catalog,
        "label": show_name,
        "action": "showSeasons",
        "is_folder": True,
        "is_playable": False,
        "menu_item": show_row,
        "action_args": build_action_args(show_row),
    }


def _rows_from_specs(specs: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for spec in specs:
        item = dict(spec["menu_item"])
        if spec.get("resume") is not None:
            item["resume_time"] = spec["resume"]
            item.setdefault("force_resume_indicator", True)
        rows.append(item)
    return rows


def _spec_is_renderable(spec: dict | None) -> bool:
    if not spec:
        return False
    menu_item = spec.get("menu_item")
    if not isinstance(menu_item, dict) or not menu_item.get("name"):
        return False
    return bool(spec.get("action_args"))


def _collect_playback_history_specs(page: int = 1) -> list[dict]:
    """Entries that can actually be painted into the history folder (Prism playback only)."""
    db = get_sync_database()
    in_progress = db.get_global_continue_watching() or []
    history = db.get_global_playback_history(page) or []
    combined = list(in_progress) + list(history)

    specs: list[dict] = []
    seen_keys: set[tuple[str, int]] = set()
    for entry in combined:
        if entry.get("kind") == "movie" and entry.get("simkl_id") is not None:
            key = ("movie", int(entry["simkl_id"]))
        elif entry.get("simkl_show_id") is not None:
            key = ("show", int(entry["simkl_show_id"]))
        elif entry.get("simkl_id") is not None:
            key = ("item", int(entry["simkl_id"]))
        else:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        spec = _menu_row_for_entry(entry)
        if _spec_is_renderable(spec):
            specs.append(spec)
    return specs


def has_watch_history_menu_items() -> bool:
    return bool(_collect_playback_history_specs(1))


def add_watch_history_home_item() -> None:
    """My Watch History folder — hidden when empty (same pattern as My Files)."""
    if not _home_enabled("home.showWatchHistory", True):
        return
    if not has_watch_history_menu_items():
        return

    g.add_directory_item(
        g.get_language_string(31122),
        action="playbackHistory",
        description=g.get_language_string(31123),
        menu_item=g.create_icon_dict("shows_recent", g.ICONS_PATH),
    )


def _render_history_specs(specs: list[dict]) -> None:
    """Paint history rows in chronological order with per-item actions (movie play / show folder)."""
    import xbmcplugin

    list_items = []
    for spec in specs:
        menu_item = dict(spec["menu_item"])
        item_params = {
            "is_folder": spec.get("is_folder", False),
            "is_playable": spec.get("is_playable", False),
            "action_args": spec.get("action_args"),
            "bulk_add": True,
        }
        if spec.get("resume") is not None:
            item_params["resume"] = spec["resume"]
        entry = g.add_directory_item(
            menu_item.get("name"),
            action=spec.get("action", "getSources"),
            menu_item=menu_item,
            **item_params,
        )
        if entry is not None:
            list_items.append(entry)

    if not list_items:
        g.cancel_directory()
        return

    xbmcplugin.addDirectoryItems(g.PLUGIN_HANDLE, list_items, len(list_items))
    has_shows = any(spec.get("kind") == "show" for spec in specs)
    g.close_directory(g.CONTENT_SHOW if has_shows else g.CONTENT_MOVIE)


def render_playback_history() -> None:
    from resources.lib.meta.list_paint import render_catalog_rows
    from resources.lib.meta.menu_paint_profile import MenuPaintProfile, profile_list_kwargs
    from resources.lib.simkl.media_ref import render_mixed_sync_list
    from resources.lib.simkl.menu_helpers import paginate_simkl_lists

    no_paging = not paginate_simkl_lists()
    page = 1 if no_paging else g.PAGE
    specs = _collect_playback_history_specs(page)

    if not specs:
        g.cancel_directory()
        return

    movie_specs = [spec for spec in specs if spec.get("kind") == "movie"]
    show_specs = [spec for spec in specs if spec.get("kind") == "show"]
    movie_rows = _rows_from_specs(movie_specs)
    show_rows = _rows_from_specs(show_specs)
    builder = ListBuilder()
    list_kwargs = profile_list_kwargs(
        MenuPaintProfile.LIBRARY,
        no_paging=no_paging,
        seeded=True,
    )

    if movie_specs and not show_specs:
        render_catalog_rows(
            "movie",
            movie_rows,
            builder,
            sync_items=movie_rows,
            **list_kwargs,
        )
        return

    if show_specs and not movie_specs:
        render_mixed_sync_list(show_rows, **list_kwargs)
        return

    _render_history_specs(specs)

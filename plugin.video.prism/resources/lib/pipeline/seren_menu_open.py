"""Seren-style menu open: seed simkl_sync → _update_* → one SQL read → ListItems."""
from __future__ import annotations

from typing import Callable

from resources.lib.modules.globals import g
from resources.lib.net.request_policy import policy_from_settings


def _seren_list_kwargs(list_kwargs: dict | None) -> dict:
    merged = dict(list_kwargs or {})
    merged["seren_direct_db"] = True
    merged["seren_menu_sql"] = True
    merged["seeded"] = True
    merged.pop("catalog_pipeline", None)
    merged.pop("prefer_catalog_payload", None)
    merged.setdefault("skip_mill", True)
    merged.setdefault("sync_path", True)
    merged.setdefault("skip_update", False)
    merged.setdefault("paint_only", False)
    return merged


def open_seren_title_list(
    catalog: str,
    refs: list[dict],
    list_builder: Callable,
    *,
    items: list[dict],
    list_kwargs: dict | None = None,
    list_id: str | None = None,
    page: int | None = None,
    **render_kwargs,
) -> None:
    """Single-catalog title page: Seren sync update then SQL list paint."""
    from resources.lib.meta.list_paint import render_seren_menu_page

    policy_from_settings().reset_menu_budget()
    merged = _seren_list_kwargs(list_kwargs)
    merged.setdefault("menu_action", g.REQUEST_PARAMS.get("action") or "browse")
    if list_id:
        merged.setdefault("list_id", list_id)
    if page is not None:
        merged["page"] = page
    render_seren_menu_page(
        catalog,
        items,
        list_builder,
        list_kwargs=merged,
        **render_kwargs,
    )


def open_seren_mixed_list(
    items: list[dict],
    list_builder: Callable,
    *,
    list_kwargs: dict | None = None,
    catalog_hint: str | None = None,
    label2_for_item: Callable | None = None,
    list_id: str | None = None,
    page: int | None = None,
) -> None:
    """Mixed movie/tv/anime page: Seren sync update then SQL list paint."""
    from resources.lib.meta.list_paint import render_seren_menu_page

    policy_from_settings().reset_menu_budget()
    merged = _seren_list_kwargs(list_kwargs)
    merged["mixed_list"] = True
    merged.setdefault("menu_action", g.REQUEST_PARAMS.get("action") or "browse")
    if catalog_hint is not None:
        merged["catalog_hint"] = catalog_hint
    if label2_for_item is not None:
        merged["label2_for_item"] = label2_for_item
    if list_id:
        merged.setdefault("list_id", list_id)
    if page is not None:
        merged["page"] = page

    catalog = catalog_hint or "movie"
    render_seren_menu_page(
        catalog,
        items,
        list_builder,
        list_kwargs=merged,
        mixed_list=True,
        catalog_hint=catalog_hint,
        label2_for_item=label2_for_item,
    )


def open_seren_library_list(
    catalog: str,
    refs: list[dict],
    list_builder: Callable,
    *,
    items: list[dict],
    list_kwargs: dict | None = None,
    library_paint: bool = True,
    list_id: str | None = None,
    **render_kwargs,
) -> None:
    """Library status / recently watched: Seren sync update then SQL list paint."""
    from resources.lib.meta.list_paint import render_seren_menu_page

    policy_from_settings().reset_menu_budget()
    merged = _seren_list_kwargs(list_kwargs)
    merged.setdefault("menu_action", g.REQUEST_PARAMS.get("action") or "library")
    if library_paint:
        merged["library_paint"] = True
    if list_id:
        merged.setdefault("list_id", list_id)
    render_seren_menu_page(
        catalog,
        items,
        list_builder,
        list_kwargs=merged,
        library_paint=library_paint,
        **render_kwargs,
    )

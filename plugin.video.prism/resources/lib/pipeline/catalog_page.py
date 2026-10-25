"""Single menu pipeline: refs → stamps → materialize → ListBuilder."""
from __future__ import annotations

from typing import Any, Callable

from resources.lib.modules.globals import g
from resources.lib.net.request_policy import policy_from_settings


class CatalogPagePipeline:
    """Vertical slice entry points for browse menus."""

    @staticmethod
    def open_genre(
        catalog: str,
        page: Any,
        list_builder: Callable,
        *,
        next_action: str,
        next_args: Any,
        list_id: str | None = None,
        browse_source: str = "genre",
    ) -> None:
        from resources.lib.discover.renderer import discover_list_kwargs
        from resources.lib.discover.sync_bridge import simkl_refs
        from resources.lib.meta.list_paint import render_fast_title_list
        from resources.lib.meta.list_pipeline import get_list_store, make_list_id

        policy_from_settings().reset_menu_budget()
        resolved_list_id = list_id or make_list_id(next_action, next_args, g.PAGE)
        store = get_list_store("genre")
        store.remember_items(catalog, resolved_list_id, page.items)
        page_refs = simkl_refs(page.items)

        list_kwargs = discover_list_kwargs(
            enrichment_reason="genre",
            genre_fast_open=True,
            seeded=True,
            prefer_catalog_payload=True,
            menu_action=next_action,
            catalog_pipeline=True,
            browse_source=browse_source,
            thin_payload_rows=page.items,
        )
        list_kwargs["next_action"] = next_action
        list_kwargs["next_args"] = next_args
        if page.has_next_page:
            list_kwargs["has_next_page"] = True

        render_fast_title_list(
            catalog,
            page_refs,
            list_builder,
            list_kwargs=list_kwargs,
            payload_rows=page.items,
            prefer_catalog_payload=True,
            seeded=True,
        )

    @staticmethod
    def open_search(
        catalog: str,
        refs: list[dict],
        list_builder: Callable,
        *,
        list_kwargs: dict | None = None,
        payload_rows: list[dict] | None = None,
    ) -> None:
        from resources.lib.meta.list_paint import render_fast_title_list
        policy_from_settings().reset_menu_budget()
        merged = dict(list_kwargs or {})
        merged.setdefault("menu_action", g.REQUEST_PARAMS.get("action") or "search")
        merged["catalog_pipeline"] = True
        if payload_rows is not None:
            merged.setdefault("thin_payload_rows", payload_rows)
        render_fast_title_list(
            catalog,
            refs,
            list_builder,
            list_kwargs=merged,
            payload_rows=payload_rows,
            prefer_catalog_payload=True,
            seeded=True,
        )

    @staticmethod
    def open_discover(
        catalog: str,
        refs: list[dict],
        list_builder: Callable,
        *,
        list_kwargs: dict | None = None,
        payload_rows: list[dict] | None = None,
    ) -> None:
        CatalogPagePipeline.open_search(
            catalog,
            refs,
            list_builder,
            list_kwargs=list_kwargs,
            payload_rows=payload_rows,
        )

    @staticmethod
    def open_library_browse(
        catalog: str,
        refs: list[dict],
        list_builder: Callable,
        *,
        list_kwargs: dict | None = None,
        library_paint: bool = True,
        payload_rows: list[dict] | None = None,
    ) -> None:
        from resources.lib.meta.list_paint import render_fast_title_list
        policy_from_settings().reset_menu_budget()
        merged = dict(list_kwargs or {})
        merged.setdefault("menu_action", g.REQUEST_PARAMS.get("action") or "library")
        merged["catalog_pipeline"] = True
        if payload_rows is not None:
            merged.setdefault("thin_payload_rows", payload_rows)
        render_fast_title_list(
            catalog,
            refs,
            list_builder,
            list_kwargs=merged,
            library_paint=library_paint,
            payload_rows=payload_rows,
            prefer_catalog_payload=payload_rows is not None,
            seeded=True,
        )

    @staticmethod
    def open_mixed_browse(
        items: list[dict],
        list_builder: Callable,
        *,
        list_kwargs: dict | None = None,
        catalog_hint: str | None = None,
        label2_for_item: Callable | None = None,
    ) -> None:
        """Mixed movie/tv/anime pages (actor filmography)."""
        from resources.lib.discover.sync_bridge import simkl_refs
        from resources.lib.meta.list_paint import render_fast_title_list

        policy_from_settings().reset_menu_budget()
        merged = dict(list_kwargs or {})
        merged.setdefault("menu_action", g.REQUEST_PARAMS.get("action") or "actorCredits")
        merged["catalog_pipeline"] = True
        merged["mixed_list"] = True
        if catalog_hint is not None:
            merged["catalog_hint"] = catalog_hint
        if label2_for_item is not None:
            merged["label2_for_item"] = label2_for_item
        render_fast_title_list(
            catalog_hint or "movie",
            simkl_refs(items),
            list_builder,
            list_kwargs=merged,
            payload_rows=items,
            prefer_catalog_payload=True,
            seeded=True,
        )

    @staticmethod
    def open_calendar(
        catalog: str,
        refs: list[dict],
        list_builder: Callable,
        *,
        list_kwargs: dict | None = None,
    ) -> None:
        CatalogPagePipeline.open_library_browse(
            catalog,
            refs,
            list_builder,
            list_kwargs=list_kwargs,
            library_paint=False,
        )

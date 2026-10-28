"""Single menu pipeline: refs → materialize → Seren paint."""
from __future__ import annotations

from typing import Any, Callable

from resources.lib.modules.globals import g


class CatalogPagePipeline:
    """Vertical slice entry points for browse menus."""

    @staticmethod
    def _render_browse(
        catalog: str,
        refs: list[dict],
        list_builder: Callable,
        *,
        list_kwargs: dict | None = None,
        payload_rows: list[dict] | None = None,
        **render_kwargs,
    ) -> None:
        """Legacy entry — prefer seren_menu_open helpers."""
        from resources.lib.pipeline.seren_menu_open import open_seren_title_list

        items = payload_rows if payload_rows is not None else []
        if not items:
            from resources.lib.meta.list_paint import render_fast_title_list

            merged = dict(list_kwargs or {})
            render_fast_title_list(
                catalog,
                refs,
                list_builder,
                list_kwargs=merged,
                seeded=True,
                **render_kwargs,
            )
            return
        open_seren_title_list(
            catalog,
            refs,
            list_builder,
            items=items,
            list_kwargs=list_kwargs,
            **render_kwargs,
        )

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
        from resources.lib.meta.list_pipeline import get_list_store, make_list_id
        from resources.lib.pipeline.seren_menu_open import open_seren_title_list

        resolved_list_id = list_id or make_list_id(next_action, next_args, g.PAGE)
        store = get_list_store("genre")
        store.remember_items(catalog, resolved_list_id, page.items)
        page_refs = simkl_refs(page.items)

        list_kwargs = discover_list_kwargs(
            enrichment_reason="genre",
            genre_fast_open=True,
            seeded=True,
            menu_action=next_action,
            browse_source=browse_source,
            paint_profile="genre",
        )
        list_kwargs["next_action"] = next_action
        list_kwargs["next_args"] = next_args
        if page.has_next_page:
            list_kwargs["has_next_page"] = True

        open_seren_title_list(
            catalog,
            page_refs,
            list_builder,
            items=page.items,
            list_kwargs=list_kwargs,
            list_id=resolved_list_id,
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
        from resources.lib.pipeline.seren_menu_open import open_seren_title_list

        merged = dict(list_kwargs or {})
        merged.setdefault("menu_action", g.REQUEST_PARAMS.get("action") or "search")
        items = payload_rows or []
        open_seren_title_list(
            catalog,
            refs,
            list_builder,
            items=items,
            list_kwargs=merged,
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
        list_id: str | None = None,
    ) -> None:
        from resources.lib.pipeline.seren_menu_open import open_seren_library_list

        merged = dict(list_kwargs or {})
        merged.setdefault("menu_action", g.REQUEST_PARAMS.get("action") or "library")
        items = payload_rows or []
        open_seren_library_list(
            catalog,
            refs,
            list_builder,
            items=items,
            list_kwargs=merged,
            library_paint=library_paint,
            list_id=list_id,
        )

    @staticmethod
    def open_mixed_browse(
        items: list[dict],
        list_builder: Callable,
        *,
        list_kwargs: dict | None = None,
        catalog_hint: str | None = None,
        label2_for_item: Callable | None = None,
        list_id: str | None = None,
    ) -> None:
        """Mixed movie/tv/anime pages (actor filmography, unified search)."""
        from resources.lib.pipeline.seren_menu_open import open_seren_mixed_list

        open_seren_mixed_list(
            items,
            list_builder,
            list_kwargs=list_kwargs,
            catalog_hint=catalog_hint,
            label2_for_item=label2_for_item,
            list_id=list_id,
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

"""Background scheduling for library verify / materialize (no menu-thread Simkl)."""
from __future__ import annotations

from typing import Callable

from resources.lib.common.thread_pool import defer_background, prism_plugin_no_threads


class LibrarySyncService:
    """Run library-side Simkl work on background threads."""

    @staticmethod
    def schedule_verify(catalog: str, status: str, worker: Callable[[], None]) -> None:
        if prism_plugin_no_threads():
            worker()
            return
        defer_background(worker, name="prism-library-verify")

    @staticmethod
    def schedule_materialize(catalog: str, refs: list[dict], *, profile: str = "library") -> None:
        if not refs:
            return
        from resources.lib.meta.page_materialize import schedule_browse_page_materialize_background

        schedule_browse_page_materialize_background(catalog, refs, profile=profile)

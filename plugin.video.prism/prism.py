from __future__ import annotations

import sys

from resources.lib.modules import router
from resources.lib.modules.globals import g
from resources.lib.modules.prismMonitor import ONWAKE_NETWORK_UP_DELAY
from resources.lib.modules.timeLogger import TimeLogger


def _sleeping_retry_handler():
    sleeping = False

    if g.PLATFORM == "android":
        attempts = 0
        while (
            attempts <= ONWAKE_NETWORK_UP_DELAY
            and (sleeping := g.get_bool_runtime_setting("system.sleeping", False))
            and not g.wait_for_abort(1)
        ):
            attempts += 1
        if sleeping and not g.abort_requested():
            g.log(
                f"Ignoring {g.REQUEST_PARAMS.get('action', '')} plugin action as system is supposed to be \"sleeping\"",
                "info",
            )

    return not sleeping


def _release_plugin_threads() -> None:
    """Release thread pools after plugin exit; avoid tearing down sync workers on normal menu browse."""
    try:
        from resources.lib.common.thread_pool import plugin_action_allows_threads, release_global_executors

        action = (g.REQUEST_PARAMS or {}).get("action")
        heavy = plugin_action_allows_threads(action)
        release_global_executors(wait=heavy, cancel_futures=heavy)
    except Exception:
        pass
    if not g.abort_requested():
        return
    try:
        from resources.lib.common.thread_pool import plugin_action_allows_threads

        if not plugin_action_allows_threads((g.REQUEST_PARAMS or {}).get("action")):
            return
        from resources.lib.database.session import get_sync_database

        db = get_sync_database()
        for pool in (db.task_queue, db.mill_task_queue):
            pool.force_stop()
    except Exception:
        pass


def _configure_invoker_thread_pool(action: str | None) -> None:
    """Seren-like browse uses default pools; background RunPlugin uses inline pool when not scraping."""
    from resources.lib.common.thread_pool import (
        enter_prism_plugin_mode,
        exit_prism_plugin_mode,
        plugin_action_allows_threads,
    )

    if plugin_action_allows_threads(action):
        exit_prism_plugin_mode()
        return
    if g.PLUGIN_HANDLE > 0 and not g.FROM_WIDGET:
        exit_prism_plugin_mode()
        return
    enter_prism_plugin_mode()
    g.set_runtime_setting("prism.inline_pool", True)


def prism_endpoint():
    plugin_slot_token = None
    try:
        try:
            from resources.lib.common.plugin_invoker_gate import (
                acquire_prism_plugin_slot,
                release_prism_plugin_slot,
                should_hold_plugin_slot_from_argv,
            )

            if should_hold_plugin_slot_from_argv():
                plugin_slot_token = acquire_prism_plugin_slot()

            g.init_globals(sys.argv)
            _configure_invoker_thread_pool((g.REQUEST_PARAMS or {}).get("action"))

            if _sleeping_retry_handler() and not g.abort_requested():
                from resources.lib.modules.widget_loader import WidgetLoadGate

                with WidgetLoadGate(), TimeLogger(f"{g.REQUEST_PARAMS.get('action', '')}"):
                    router.dispatch(g.REQUEST_PARAMS)

        except Exception:
            g.cancel_directory()
            raise

        finally:
            if plugin_slot_token:
                from resources.lib.common.plugin_invoker_gate import release_prism_plugin_slot

                release_prism_plugin_slot(plugin_slot_token)
            _release_plugin_threads()
            g.clear_runtime_setting("prism.inline_pool")
            g.deinit()
    finally:
        from resources.lib.common.thread_pool import exit_prism_plugin_mode

        exit_prism_plugin_mode()


if __name__ == "__main__":  # pragma: no cover
    prism_endpoint()

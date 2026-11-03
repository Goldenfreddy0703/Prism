"""Unified sync HTTP and request policy for Prism."""

from importlib import import_module

_EXPORTS = {
    "HttpLedger": "resources.lib.net.http_ledger",
    "menu_http_scope": "resources.lib.net.http_ledger",
    "HttpSessions": "resources.lib.net.http_sessions",
    "close_all_sessions": "resources.lib.net.http_sessions",
    "get_http_sessions": "resources.lib.net.http_sessions",
    "RequestPolicy": "resources.lib.net.request_policy",
    "get_request_policy": "resources.lib.net.request_policy",
    "policy_from_settings": "resources.lib.net.request_policy",
    "sync_http_request": "resources.lib.net.sync_bridge",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name):
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_path), name)
    globals()[name] = value
    return value

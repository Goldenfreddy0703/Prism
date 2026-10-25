"""List page load source + finalize cache stats for Menu perf."""
from __future__ import annotations

from typing import Any

_last_list_source: str = ""
_finalize_stats: dict[str, Any] = {}


def set_list_source(source: str) -> None:
    global _last_list_source
    _last_list_source = str(source or "")


def pop_list_source() -> str:
    global _last_list_source
    source = _last_list_source or ""
    _last_list_source = ""
    return source


def set_finalize_stats(**kwargs: Any) -> None:
    _finalize_stats.clear()
    _finalize_stats.update(kwargs)


def pop_finalize_stats() -> dict[str, Any]:
    stats = dict(_finalize_stats)
    _finalize_stats.clear()
    return stats

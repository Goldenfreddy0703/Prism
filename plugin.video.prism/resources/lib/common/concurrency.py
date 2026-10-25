"""Seren-aligned concurrency derived from general.threadpoolScale (no HTTP settings knobs)."""
from __future__ import annotations

from resources.lib.modules.globals import g

# Default, Low, Medium, High, Extreme — matches Seren thread_pool.scaled_workers
_SCALED_WORKERS = [20, 10, 20, 40, 80]


def pool_workers() -> int:
    """Thread pool size from Threading Scale; threadpool.limiter forces serial."""
    if g.get_bool_runtime_setting("threadpool.limiter"):
        return 1
    scale = g.get_int_setting("general.threadpoolScale", -1)
    idx = int(scale) + 1
    if idx < 0:
        idx = 0
    if idx >= len(_SCALED_WORKERS):
        idx = len(_SCALED_WORKERS) - 1
    return int(_SCALED_WORKERS[idx])


def http_concurrent_cap() -> int:
    """Max concurrent non-exempt HTTP through the gateway."""
    return max(1, pool_workers())


def menu_http_budget() -> int:
    """Soft per-menu ceiling for budgeted (non-CDN-exempt) requests."""
    workers = pool_workers()
    return max(64, workers * 4)


def per_provider_caps() -> dict[str, int]:
    """Internal per-provider in-flight caps; scale with Threading Scale."""
    w = pool_workers()
    return {
        "simkl": min(32, max(8, w * 2)),
        "tmdb": min(24, max(8, w + 4)),
        "tvdb": min(16, max(6, w)),
        "fanart": min(12, max(4, w // 2 + 2)),
        "imdb": min(12, max(4, w // 2 + 2)),
        "anilist": min(12, max(4, w // 2 + 2)),
        "default": min(24, max(8, w + 4)),
    }

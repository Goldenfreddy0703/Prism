"""Simkl URL classes for RequestPolicy (CDN detail/episodes vs rate-limited APIs)."""
from __future__ import annotations

import re
from urllib import parse

# Simkl docs: detail + episode-list are CDN-cached; not subject to 10 GET/sec or daily quota.
_EPISODES_PATH = re.compile(
    r"^/(?:tv|anime)/episodes/",
    re.IGNORECASE,
)
_CDN_MISC = re.compile(
    r"^/(?:redirect|calendar|trending)(?:/|$)",
    re.IGNORECASE,
)


def _simkl_path(url: str) -> str:
    if not url:
        return ""
    if url.startswith("/"):
        return url.split("?", 1)[0]
    parsed = parse.urlparse(url)
    return parsed.path or ""


def simkl_menu_budget_exempt(url: str, method: str = "GET") -> bool:
    """True when Simkl treats the call as CDN catalog (no menu HTTP budget)."""
    if method.upper() != "GET":
        return False
    path = _simkl_path(url)
    if not path:
        return False
    if _EPISODES_PATH.match(path):
        return True
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) == 2 and parts[0] in ("movies", "tv", "anime"):
        return True
    if _CDN_MISC.match(path):
        return True
    return False

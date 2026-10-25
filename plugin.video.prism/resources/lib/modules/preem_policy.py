"""Preemptive scrape termination policies (per source family)."""
from __future__ import annotations

PREEM_OFF = 0
PREEM_FIRST = 1
PREEM_MINIMUM = 2

_LEGACY_BOOL = {
    "cloud": "preem.cloudfiles",
    "adaptive": "preem.adaptiveSources",
    "direct": "preem.directSources",
}

_DEFAULT_POLICY = {
    "torrents": PREEM_FIRST,
    "hosters": PREEM_OFF,
    "cloud": PREEM_FIRST,
    "adaptive": PREEM_FIRST,
    "direct": PREEM_FIRST,
}


def _policy_from_legacy(family: str) -> int | None:
    from resources.lib.modules.globals import g

    legacy = _LEGACY_BOOL.get(family)
    if not legacy:
        return None
    legacy_raw = g.get_setting(legacy, None)
    if legacy_raw is None or str(legacy_raw).strip() == "":
        return None
    return PREEM_FIRST if g.get_bool_setting(legacy) else PREEM_OFF


def _apply_legacy_indexer_type(family: str, policy: int) -> int:
    """Map removed ``preem.type`` (torrent / hoster / both) onto split policies."""
    from resources.lib.modules.globals import g

    type_raw = g.get_setting("preem.type", None)
    if type_raw is None or str(type_raw).strip() == "":
        return policy
    preem_type = g.get_int_setting("preem.type", 0)
    if preem_type == 0 and family == "hosters":
        return PREEM_OFF
    if preem_type == 1 and family == "torrents":
        return PREEM_OFF
    if preem_type == 2 and family == "hosters":
        return g.get_int_setting("preem.torrents.policy", policy)
    return policy


def load_preem_policy(family: str) -> int:
    """Return OFF / FIRST / MINIMUM for torrents, hosters, cloud, adaptive, or direct."""
    from resources.lib.modules.globals import g

    key = f"preem.{family}.policy"
    raw = g.get_setting(key, None)
    legacy_policy = _policy_from_legacy(family)

    if raw is not None and str(raw).strip() != "":
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = PREEM_OFF
        if value not in (PREEM_OFF, PREEM_FIRST, PREEM_MINIMUM):
            value = PREEM_OFF
        if legacy_policy is not None and value == _DEFAULT_POLICY.get(family) and legacy_policy != value:
            value = legacy_policy
    elif legacy_policy is not None:
        value = legacy_policy
    elif family == "torrents":
        if not g.get_bool_setting("preem.enabled"):
            value = PREEM_OFF
        else:
            limit = g.get_int_setting("preem.limit", 5)
            value = PREEM_MINIMUM if limit > 0 else PREEM_OFF
    else:
        value = _DEFAULT_POLICY.get(family, PREEM_OFF)

    if family in ("torrents", "hosters"):
        value = _apply_legacy_indexer_type(family, value)
    return value

"""Paint-first list pipeline: cache → ListItem → background enrich."""
from __future__ import annotations

from resources.lib.simkl.menu_helpers import list_filter_kwargs

# Browse lists block on provider gap-fill (cast, art) before paint; leftovers enrich in background.
BROWSE_LIST_KWARGS = {**list_filter_kwargs(), "skip_mill": True, "skip_update": True}


def browse_list_kwargs(**overrides) -> dict:
    """Shared list-builder kwargs for discover, search, library, genres, actor, etc."""
    kwargs = dict(BROWSE_LIST_KWARGS)
    kwargs.setdefault("menu_cache", True)
    kwargs.update(overrides)
    return kwargs

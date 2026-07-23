"""LIST vs FULL metadata profiles for browse vs play/resolver paths."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

LIST_CAST_HEAD = 15


class MetaProfile:
    LIST = "list"
    FULL = "full"


_profile_stack: list[str] = []


def current_profile() -> str:
    return _profile_stack[-1] if _profile_stack else MetaProfile.FULL


def include_provider_children() -> bool:
    """FULL profile persists nested season/episode provider blobs; LIST does not."""
    return current_profile() == MetaProfile.FULL


def cast_head_for_profile(profile: str | None = None) -> int | None:
    """Max cast members to store for list paint; None means no cap (FULL)."""
    active = profile or current_profile()
    if active == MetaProfile.LIST:
        return LIST_CAST_HEAD
    return None


def persist_provider_blobs(profile: str | None = None) -> bool:
    """LIST enrich still merges display rows but skips heavy provider blob tables when False."""
    active = profile or current_profile()
    return active == MetaProfile.FULL


@contextmanager
def profile_scope(profile: str) -> Iterator[str]:
    _profile_stack.append(profile)
    try:
        yield profile
    finally:
        if _profile_stack and _profile_stack[-1] == profile:
            _profile_stack.pop()

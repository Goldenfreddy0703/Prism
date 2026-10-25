"""Table profiles for TV vs anime serial content (shows/seasons/episodes families)."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from resources.lib.database.simkl_sync.database import SimklSyncDatabase


@dataclass(frozen=True)
class SerialTables:
    show: str
    season: str
    episode: str
    show_meta: str
    season_meta: str
    episode_meta: str
    catalog: str


TV_TABLES = SerialTables(
    show="shows",
    season="seasons",
    episode="episodes",
    show_meta="shows_meta",
    season_meta="seasons_meta",
    episode_meta="episodes_meta",
    catalog="tv",
)

ANIME_TABLES = SerialTables(
    show="shows",
    season="seasons",
    episode="episodes",
    show_meta="shows_meta",
    season_meta="seasons_meta",
    episode_meta="episodes_meta",
    catalog="anime",
)

_PROFILES = {"tv": TV_TABLES, "anime": ANIME_TABLES}


def serial_tables(profile: str) -> SerialTables:
    key = str(profile or "tv").lower()
    if key == "anime":
        return ANIME_TABLES
    return TV_TABLES


def current_serial_tables(db: SimklSyncDatabase) -> SerialTables:
    stack = getattr(db, "_serial_profile_stack", None) or []
    return serial_tables(stack[-1] if stack else "tv")


def catalog_filter_sql(st: SerialTables, table_alias: str = "") -> tuple[str, tuple[str]]:
    """SQL fragment ``AND {alias}catalog = ?`` plus bind value for tv/anime profile."""
    prefix = f"{table_alias}." if table_alias else ""
    return f" AND {prefix}catalog = ?", (st.catalog,)


@contextmanager
def serial_profile_scope(db: SimklSyncDatabase, profile: str) -> Iterator[SerialTables]:
    if not hasattr(db, "_serial_profile_stack"):
        db._serial_profile_stack = []
    db._serial_profile_stack.append(str(profile or "tv").lower())
    try:
        yield serial_tables(db._serial_profile_stack[-1])
    finally:
        db._serial_profile_stack.pop()

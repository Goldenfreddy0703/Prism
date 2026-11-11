"""Saved My Lists for anime, movies, and TV. One small database, not search history."""
from __future__ import annotations

import json
import os
from typing import Any

from resources.lib.database import SQLiteConnection
from resources.lib.modules.globals import g

_CATALOGS = ("anime", "movie", "tv")
_LEGACY_FILES = {
    "anime": "tenrai_anime_lists.json",
    "movie": "tmdb_movie_lists.json",
    "tv": "tmdb_tv_lists.json",
}
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS saved_lists (
    catalog TEXT NOT NULL,
    list_id TEXT NOT NULL,
    name TEXT NOT NULL,
    filters TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (catalog, list_id)
)
"""


def load_saved_lists(catalog: str) -> list[dict[str, Any]]:
    if catalog not in _CATALOGS:
        return []
    _migrate_legacy_json(catalog)
    with _connection() as db:
        rows = db.fetchall(
            "SELECT list_id, name, filters FROM saved_lists WHERE catalog = ? ORDER BY position ASC, list_id ASC",
            (catalog,),
        )
    entries: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("list_id"):
            continue
        entries.append(
            {
                "id": str(row["list_id"]),
                "name": str(row.get("name") or ""),
                "filters": _filters_from_text(row.get("filters")),
            }
        )
    return entries


def save_saved_lists(catalog: str, entries: list[dict[str, Any]]) -> None:
    if catalog not in _CATALOGS:
        return
    rows: list[tuple[str, str, str, str, int]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        list_id = str(entry.get("id") or "").strip()
        if not list_id or list_id in seen:
            continue
        seen.add(list_id)
        filters = entry.get("filters") if isinstance(entry.get("filters"), dict) else {}
        rows.append((catalog, list_id, str(entry.get("name") or ""), _filters_text(filters), len(rows)))
    with _connection() as db:
        with db.transaction() as cursor:
            cursor.execute("DELETE FROM saved_lists WHERE catalog = ?", (catalog,))
            cursor.executemany(
                "INSERT INTO saved_lists (catalog, list_id, name, filters, position) VALUES (?, ?, ?, ?, ?)",
                rows,
            )


def _connection():
    return _SavedListsConnection(g.LISTS_DB_PATH)


class _SavedListsConnection(SQLiteConnection):
    def __enter__(self):
        connection = super().__enter__()
        connection.execute_sql(_CREATE_TABLE)
        return connection


def _migrate_legacy_json(catalog: str) -> None:
    path = os.path.join(g.ADDON_USERDATA_PATH, _LEGACY_FILES[catalog])
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    incoming = payload.get("lists")
    if not isinstance(incoming, list):
        return
    current = []
    with _connection() as db:
        stored = db.fetchall(
            "SELECT list_id, name, filters FROM saved_lists WHERE catalog = ? ORDER BY position ASC, list_id ASC",
            (catalog,),
        )
    for row in stored or []:
        if isinstance(row, dict) and row.get("list_id"):
            current.append(
                {
                    "id": str(row["list_id"]),
                    "name": str(row.get("name") or ""),
                    "filters": _filters_from_text(row.get("filters")),
                }
            )
    known = {str(entry["id"]) for entry in current}
    added = False
    for entry in incoming:
        if not isinstance(entry, dict):
            continue
        list_id = str(entry.get("id") or "").strip()
        if not list_id or list_id in known:
            continue
        filters = entry.get("filters") if isinstance(entry.get("filters"), dict) else {}
        current.append({"id": list_id, "name": str(entry.get("name") or ""), "filters": filters})
        known.add(list_id)
        added = True
    if added:
        save_saved_lists(catalog, current)
    try:
        os.remove(path)
    except OSError:
        return
    temporary = path + ".tmp"
    if os.path.exists(temporary):
        try:
            os.remove(temporary)
        except OSError:
            return


def _filters_text(filters: dict[str, Any]) -> str:
    return json.dumps(filters, ensure_ascii=False, sort_keys=True)


def _filters_from_text(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}

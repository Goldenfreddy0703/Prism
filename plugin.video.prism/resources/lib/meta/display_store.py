"""POV-style display metadata store (RAM → prism_meta.db → simkl_sync)."""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import threading
from typing import Any

from resources.lib.common import tools
from resources.lib.database.sync_meta_cache import SyncMetaCache, row_has_display_meta
from resources.lib.modules.globals import g

_STORE_LOCK = threading.Lock()
_STORE: DisplayMetaStore | None = None

_PREFETCH_LIMIT = 500
_MAX_ROWS = 25000


def get_display_meta_store() -> DisplayMetaStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = DisplayMetaStore()
    return _STORE


class DisplayMetaStore:
    """Kodi-ready list metadata cache separate from simkl_sync provider blobs."""

    def __init__(self) -> None:
        g.ensure_addon()
        self._path = g.PRISM_META_DB_PATH
        tools.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._ram = SyncMetaCache()
        self._conn: sqlite3.Connection | None = None
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=OFF")
            self._conn.execute("PRAGMA synchronous=OFF")
            self._conn.execute("PRAGMA temp_store=MEMORY")
        return self._conn

    def _init_schema(self) -> None:
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS display_meta (
                media_type TEXT NOT NULL,
                simkl_id INTEGER NOT NULL,
                info TEXT,
                art TEXT,
                [cast] TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (media_type, simkl_id)
            );
            CREATE INDEX IF NOT EXISTS idx_display_meta_updated
                ON display_meta(updated_at DESC);
            """
        )
        conn.commit()

    @staticmethod
    def _media_key(media_type: str) -> str:
        return "movie" if media_type == "movie" else "show"

    @staticmethod
    def _encode_blob(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _decode_blob(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _row_from_record(self, record: sqlite3.Row) -> dict[str, Any]:
        return {
            "simkl_id": int(record["simkl_id"]),
            "info": self._decode_blob(record["info"]) or {},
            "art": self._decode_blob(record["art"]) or {},
            "cast": self._decode_blob(record["cast"]) or [],
        }

    def get_row(self, media_type: str, simkl_id: int) -> dict[str, Any] | None:
        cache_type = self._media_key(media_type)
        ram_row = self._ram.get_row(cache_type, int(simkl_id))
        if ram_row and row_has_display_meta(ram_row):
            return ram_row

        conn = self._connect()
        record = conn.execute(
            """
            SELECT media_type, simkl_id, info, art, [cast]
            FROM display_meta
            WHERE media_type = ? AND simkl_id = ?
            """,
            (cache_type, int(simkl_id)),
        ).fetchone()
        if not record:
            return None
        row = self._row_from_record(record)
        if row_has_display_meta(row):
            self._ram.set_row(cache_type, row)
            return row
        return None

    def get_batch(self, media_type: str, simkl_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not simkl_ids:
            return {}
        cache_type = self._media_key(media_type)
        hits: dict[int, dict[str, Any]] = {}
        misses: list[int] = []

        for simkl_id in simkl_ids:
            sid = int(simkl_id)
            ram_row = self._ram.get_row(cache_type, sid)
            if ram_row and row_has_display_meta(ram_row):
                hits[sid] = ram_row
            else:
                misses.append(sid)

        if misses:
            placeholders = ",".join("?" * len(misses))
            conn = self._connect()
            records = conn.execute(
                f"""
                SELECT media_type, simkl_id, info, art, [cast]
                FROM display_meta
                WHERE media_type = ? AND simkl_id IN ({placeholders})
                """,
                (cache_type, *misses),
            ).fetchall()
            for record in records or []:
                row = self._row_from_record(record)
                if row_has_display_meta(row):
                    sid = int(row["simkl_id"])
                    hits[sid] = row
                    self._ram.set_row(cache_type, row)

        return hits

    def set_row(self, media_type: str, row: dict[str, Any]) -> None:
        if not isinstance(row, dict) or row.get("simkl_id") is None:
            return
        from resources.lib.meta.storage import slim_db_row
        from resources.lib.meta.profiles import MetaProfile

        slim = slim_db_row(row, profile=MetaProfile.LIST)
        if not row_has_display_meta(slim):
            return

        cache_type = self._media_key(media_type)
        sid = int(slim["simkl_id"])
        self._ram.set_row(cache_type, slim)

        now = datetime.datetime.now().isoformat()
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO display_meta (media_type, simkl_id, info, art, [cast], updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_type, simkl_id) DO UPDATE SET
                info = excluded.info,
                art = excluded.art,
                [cast] = excluded.[cast],
                updated_at = excluded.updated_at
            """,
            (
                cache_type,
                sid,
                self._encode_blob(slim.get("info")),
                self._encode_blob(slim.get("art")),
                self._encode_blob(slim.get("cast")),
                now,
            ),
        )
        conn.commit()
        self._enforce_row_cap()

    def set_many_rows(self, media_type: str, rows: list[dict[str, Any]]) -> None:
        for row in rows or []:
            if isinstance(row, dict):
                self.set_row(media_type, row)

    def overlay_rows(self, rows: list[dict[str, Any]], media_type: str) -> list[dict[str, Any]]:
        """Replace row info/art/cast with display-cache hits when available."""
        if not rows:
            return rows
        simkl_ids = [int(row["simkl_id"]) for row in rows if isinstance(row, dict) and row.get("simkl_id") is not None]
        if not simkl_ids:
            return rows
        hits = self.get_batch(media_type, simkl_ids)
        if not hits:
            return rows

        from resources.lib.common import tools as merge_tools

        merged: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                merged.append(row)
                continue
            sid = row.get("simkl_id")
            if sid is None:
                merged.append(row)
                continue
            cached = hits.get(int(sid))
            if not cached:
                merged.append(row)
                continue
            updated = dict(row)
            updated["info"] = merge_tools.smart_merge_dictionary(
                dict(row.get("info") or {}),
                dict(cached.get("info") or {}),
                keep_original=False,
                extend_array=False,
            )
            updated["art"] = merge_tools.smart_merge_dictionary(
                dict(row.get("art") or {}),
                dict(cached.get("art") or {}),
                keep_original=False,
                extend_array=False,
            )
            if cached.get("cast"):
                updated["cast"] = cached["cast"]
            merged.append(updated)
        return merged

    def prefetch(self, limit: int = _PREFETCH_LIMIT) -> int:
        """Warm recent display rows into RAM (service idle)."""
        if limit <= 0:
            return 0
        conn = self._connect()
        warmed = 0
        half = max(1, limit // 2)
        for cache_type, sql_limit in (("movie", half), ("show", max(1, limit - half))):
            records = conn.execute(
                """
                SELECT media_type, simkl_id, info, art, [cast]
                FROM display_meta
                WHERE media_type = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (cache_type, sql_limit),
            ).fetchall()
            for record in records or []:
                row = self._row_from_record(record)
                if row_has_display_meta(row):
                    self._ram.set_row(cache_type, row)
                    warmed += 1
        return warmed

    def _enforce_row_cap(self) -> None:
        conn = self._connect()
        count_row = conn.execute("SELECT COUNT(*) AS count FROM display_meta").fetchone()
        total = int(count_row["count"]) if count_row else 0
        if total <= _MAX_ROWS:
            return
        trim = total - _MAX_ROWS
        conn.execute(
            """
            DELETE FROM display_meta
            WHERE rowid IN (
                SELECT rowid FROM display_meta
                ORDER BY updated_at ASC
                LIMIT ?
            )
            """,
            (trim,),
        )
        conn.commit()

    def clear_all(self) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM display_meta")
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()

from __future__ import annotations

import collections
import datetime
import json
import time
from functools import cached_property
from urllib import parse

import xbmcgui

from resources.lib.common import tools
from resources.lib.common.thread_pool import ThreadPool
from resources.lib.database import Database
from resources.lib.modules.exceptions import InvalidMediaTypeException
from resources.lib.modules.exceptions import UnsupportedProviderType
from resources.lib.modules.globals import g
from resources.lib.discover.normalize import _int_or_none
from resources.lib.modules.metadataHandler import MetadataHandler
from resources.lib.modules.sync_lock import SyncLock

schema = {
    "shows_meta": {
        "columns": collections.OrderedDict(
            [
                ("id", ["INTEGER", "NOT NULL"]),
                ("type", ["TEXT", "NOT NULL"]),
                ("meta_hash", ["TEXT", "NOT NULL"]),
                ("value", ["PICKLE", "NOT NULL"]),
            ]
        ),
        "table_constraints": ["UNIQUE(id, type)"],
        "default_seed": [],
    },
    "seasons_meta": {
        "columns": collections.OrderedDict(
            [
                ("id", ["INTEGER", "NOT NULL"]),
                ("type", ["TEXT", "NOT NULL"]),
                ("meta_hash", ["TEXT", "NOT NULL"]),
                ("value", ["PICKLE", "NOT NULL"]),
            ]
        ),
        "table_constraints": ["UNIQUE(id, type)"],
        "default_seed": [],
    },
    "episodes_meta": {
        "columns": collections.OrderedDict(
            [
                ("id", ["INTEGER", "NOT NULL"]),
                ("type", ["TEXT", "NOT NULL"]),
                ("meta_hash", ["TEXT", "NOT NULL"]),
                ("value", ["PICKLE", "NOT NULL"]),
            ]
        ),
        "table_constraints": ["UNIQUE(id, type)"],
        "default_seed": [],
    },
    "movies_meta": {
        "columns": collections.OrderedDict(
            [
                ("id", ["INTEGER", "NOT NULL"]),
                ("type", ["TEXT", "NOT NULL"]),
                ("meta_hash", ["TEXT", "NOT NULL"]),
                ("value", ["PICKLE", "NOT NULL"]),
            ]
        ),
        "table_constraints": ["UNIQUE(id, type)"],
        "default_seed": [],
    },
    "shows": {
        "columns": collections.OrderedDict(
            [
                ("simkl_id", ["INTEGER", "PRIMARY KEY", "NOT NULL"]),
                ("tvdb_id", ["INTEGER", "NULL"]),
                ("tmdb_id", ["INTEGER", "NULL"]),
                ("imdb_id", ["INTEGER", "NULL"]),
                ("info", ["PICKLE", "NULL"]),
                ("cast", ["PICKLE", "NULL"]),
                ("art", ["PICKLE", "NULL"]),
                ("meta_hash", ["TEXT", "NULL"]),
                ("season_count", ["INTEGER", "NULL", "DEFAULT 0"]),
                ("episode_count", ["INTEGER", "NULL", "DEFAULT 0"]),
                ("unwatched_episodes", ["INTEGER", "NULL", "DEFAULT 0"]),
                ("watched_episodes", ["INTEGER", "NULL", "DEFAULT 0"]),
                ("last_updated", ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"]),
                ("args", ["TEXT", "NOT NULL"]),
                ("air_date", ["TEXT"]),
                ("is_airing", ["BOOLEAN"]),
                ("last_watched_at", ["TEXT"]),
                ("last_collected_at", ["TEXT"]),
                ("user_rating", ["INTEGER", "NULL"]),
                ("needs_update", ["BOOLEAN", "NOT NULL", "DEFAULT 1"]),
                ("needs_milling", ["BOOLEAN", "NOT NULL", "DEFAULT 1"]),
            ]
        ),
        "table_constraints": [],
        "default_seed": [],
    },
    "seasons": {
        "columns": collections.OrderedDict(
            [
                ("simkl_id", ["INTEGER", "NOT NULL"]),
                ("simkl_show_id", ["INTEGER", "NOT NULL"]),
                ("tvdb_id", ["INTEGER", "NULL"]),
                ("tmdb_id", ["INTEGER", "NULL"]),
                ("season", ["INTEGER", "NOT NULL"]),
                ("info", ["PICKLE", "NULL"]),
                ("cast", ["PICKLE", "NULL"]),
                ("art", ["PICKLE", "NULL"]),
                ("meta_hash", ["TEXT", "NULL"]),
                ("episode_count", ["INTEGER", "NULL", "DEFAULT 0"]),
                ("unwatched_episodes", ["INTEGER", "NULL", "DEFAULT 0"]),
                ("watched_episodes", ["INTEGER", "NULL", "DEFAULT 0"]),
                ("last_updated", ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"]),
                ("args", ["TEXT", "NOT NULL"]),
                ("air_date", ["TEXT"]),
                ("is_airing", ["BOOLEAN"]),
                ("last_watched_at", ["TEXT"]),
                ("last_collected_at", ["TEXT"]),
                ("user_rating", ["INTEGER", "NULL"]),
                ("needs_update", ["BOOLEAN", "NOT NULL", "DEFAULT 1"]),
            ]
        ),
        "table_constraints": [
            "PRIMARY KEY(simkl_show_id, season)",
            "UNIQUE(simkl_id)"
            "FOREIGN KEY(simkl_show_id) REFERENCES shows(simkl_id) ON UPDATE CASCADE ON DELETE CASCADE",
        ],
        "default_seed": [],
    },
    "episodes": {
        "columns": collections.OrderedDict(
            [
                ("simkl_id", ["INTEGER", "NOT NULL"]),
                ("simkl_show_id", ["INTEGER", "NOT NULL"]),
                ("simkl_season_id", ["INTEGER", "NOT NULL"]),
                ("season", ["INTEGER", "NOT NULL"]),
                ("tvdb_id", ["INTEGER", "NULL"]),
                ("tmdb_id", ["INTEGER", "NULL"]),
                ("imdb_id", ["INTEGER", "NULL"]),
                ("info", ["PICKLE", "NULL"]),
                ("cast", ["PICKLE", "NULL"]),
                ("art", ["PICKLE", "NULL"]),
                ("meta_hash", ["TEXT", "NULL"]),
                ("last_updated", ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"]),
                ("collected", ["INTEGER", "NOT NULL", "DEFAULT 0"]),
                ("watched", ["INTEGER", "NOT NULL", "DEFAULT 0"]),
                ("number", ["INTEGER", "NOT NULL"]),
                ("args", ["TEXT", "NOT NULL"]),
                ("air_date", ["TEXT"]),
                ("last_watched_at", ["TEXT"]),
                ("collected_at", ["TEXT"]),
                ("user_rating", ["INTEGER", "NULL"]),
                ("needs_update", ["BOOLEAN", "NOT NULL", "DEFAULT 1"]),
            ]
        ),
        "table_constraints": [
            "PRIMARY KEY(simkl_show_id, season, number)",
            "UNIQUE(simkl_id)"
            "FOREIGN KEY(simkl_season_id) REFERENCES seasons(simkl_id) ON UPDATE CASCADE ON DELETE CASCADE",
            "FOREIGN KEY(simkl_show_id) REFERENCES shows(simkl_id) ON UPDATE CASCADE ON DELETE CASCADE",
        ],
        "indices": [
            ("idx_episodes_showid", ["simkl_show_id"]),
            ("idx_episodes_seasonid", ["simkl_season_id"]),
            ("idx_episodes_showid_season_number_lastwatched", ["simkl_show_id", "season", "number", "last_watched_at"]),
            ("idx_episodes_season_number", ["season", "number"]),
            ("idx_episodes_collected", ["collected"]),
        ],
        "default_seed": [],
    },
    "movies": {
        "columns": collections.OrderedDict(
            [
                ("simkl_id", ["INTEGER", "PRIMARY KEY", "NOT NULL"]),
                ("tmdb_id", ["INTEGER", "NULL"]),
                ("tvdb_id", ["INTEGER", "NULL"]),
                ("imdb_id", ["INTEGER", "NULL"]),
                ("info", ["PICKLE", "NULL"]),
                ("cast", ["PICKLE", "NULL"]),
                ("art", ["PICKLE", "NULL"]),
                ("meta_hash", ["TEXT", "NULL"]),
                ("last_updated", ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"]),
                ("collected", ["INTEGER", "NOT NULL", "DEFAULT 0"]),
                ("watched", ["INTEGER", "NOT NULL", "DEFAULT 0"]),
                ("args", ["TEXT", "NOT NULL"]),
                ("air_date", ["TEXT"]),
                ("last_watched_at", ["TEXT"]),
                ("collected_at", ["TEXT"]),
                ("user_rating", ["INTEGER", "NULL"]),
                ("needs_update", ["BOOLEAN", "NOT NULL", "DEFAULT 1"]),
            ]
        ),
        "table_constraints": [],
        "indices": [
            ("idx_movies_collected", ["collected"]),
            ("idx_movies_watched_lastwatched", ["watched", "last_watched_at"]),
        ],
        "default_seed": [],
    },
    "hidden": {
        "columns": collections.OrderedDict(
            [
                ("simkl_id", ["INTEGER", "NOT NULL"]),
                ("mediatype", ["TEXT", "NOT NULL"]),
                ("section", ["TEXT", "NOT NULL"]),
            ]
        ),
        "table_constraints": ["PRIMARY KEY(simkl_id, simkl_id, mediatype, section)"],
        "indices": [("idx_hidden_section_mediatype", ["section", "mediatype"])],
        "default_seed": [],
    },
    "activities": {
        "columns": collections.OrderedDict(
            [
                ("sync_id", ["INTEGER", "PRIMARY KEY"]),
                (
                    "all_activities",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                (
                    "shows_watched",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                (
                    "movies_watched",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                (
                    "shows_rated",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                (
                    "movies_rated",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                (
                    "shows_collected",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                (
                    "movies_collected",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                ("hidden_sync", ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"]),
                (
                    "shows_meta_update",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                (
                    "movies_meta_update",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                (
                    "movies_bookmarked",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                (
                    "episodes_bookmarked",
                    ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"],
                ),
                ("lists_sync", ["TEXT", "NOT NULL", "DEFAULT '1970-01-01T00:00:00'"]),
                ("simkl_username", ["TEXT", "NULL"]),
                ("last_activities_call", ["INTEGER", "NOT NULL", "DEFAULT 1"]),
            ]
        ),
        "table_constraints": ["UNIQUE(sync_id)"],
        "default_seed": [],
    },
    "bookmarks": {
        "columns": collections.OrderedDict(
            [
                ("simkl_id", ["INTEGER", "PRIMARY KEY", "NOT NULL"]),
                ("resume_time", ["TEXT", "NOT NULL"]),
                ("percent_played", ["TEXT", "NOT NULL"]),
                ("type", ["TEXT", "NOT NULL"]),
                ("paused_at", ["TEXT", "NOT NULL"]),
            ]
        ),
        "table_constraints": [],
        "indices": [("idx_bookmarks_paused", ["paused_at"])],
        "default_seed": [],
    },
    "lists": {
        "columns": collections.OrderedDict(
            [
                ("simkl_id", ["INTEGER", "PRIMARY KEY", "NOT NULL"]),
                ("name", ["TEXT", "NOT NULL"]),
                ("username", ["TEXT", "NOT NULL"]),
                ("last_updated", ["TEXT", "NOT NULL"]),
                ("movie", ["BOOLEAN", "NOT NULL"]),
                ("show", ["BOOLEAN", "NOT NULL"]),
                ("sort_by", ["TEXT", "NOT NULL"]),
                ("sort_how", ["TEXT", "NOT NULL"]),
                ("slug", ["TEXT", "NOT NULL"]),
                ("meta_hash", ["TEXT", "NOT NULL"]),
            ]
        ),
        "table_constraints": [],
        "default_seed": [],
    },
}


class SimklSyncDatabase(Database):
    def __init__(
        self,
        db_path=None,
    ):
        super().__init__(db_path or g.SIMKL_SYNC_DB_PATH, schema)

        self.activities = {}
        self.item_list = []
        self.base_date = "1970-01-01T00:00:00"
        self.task_queue = ThreadPool()
        self.mill_task_queue = ThreadPool()
        self.refresh_activities()
        self._migrate_library_status_columns()
        self._migrate_movies_tvdb_id_column()
        self._migrate_library_cache_tables()

        if self.activities is None:
            self.clear_all_meta(False)
            self.set_base_activities()

        self.notification_prefix = f"{g.ADDON_NAME}: Simkl"
        self.hide_unaired = g.get_bool_setting("general.hideUnAired")
        self.hide_specials = g.get_bool_setting("general.hideSpecials")
        self.hide_watched = g.get_bool_setting("general.hideWatched")
        self.page_limit = g.get_int_setting("item.limit")

    @cached_property
    def metadataHandler(self):
        from resources.lib.modules.metadataHandler import MetadataHandler

        return MetadataHandler()

    @cached_property
    def simkl_api(self):
        from resources.lib.indexers.simkl import SimklAPI

        return SimklAPI()

    def clear_specific_item_meta(self, simkl_id, media_type):
        if media_type in ["tvshow", "show"]:
            media_type = "shows"
        elif media_type == "movie":
            media_type = "movies"
        elif media_type == "episode":
            media_type = "episodes"
        elif media_type == "season":
            media_type = "seasons"

        if media_type not in ["shows", "movies", "seasons", "episodes"]:
            raise InvalidMediaTypeException(media_type)

        self.execute_sql(f"DELETE from {media_type}_meta where id=?", (simkl_id,))
        self.execute_sql(
            f"UPDATE {media_type} SET info=null, art=null, cast=null, meta_hash=null where simkl_id=?",
            (simkl_id,),
        )

    def _update_last_activities_call(self):
        self.execute_sql("UPDATE activities SET last_activities_call=? WHERE sync_id=1", (int(time.time()),))
        self.refresh_activities()

    def _insert_last_activities_column(self):
        self.execute_sql("ALTER TABLE activities ADD last_activities_call INTEGER NOT NULL DEFAULT 1")

    def get_library_status(self, simkl_id: int, catalog: str, info: dict | None = None) -> str | None:
        if isinstance(info, dict) and info.get("simkl_status"):
            return info.get("simkl_status")
        table = "movies" if catalog == "movie" else "shows"
        row = self.fetchone(f"SELECT simkl_status FROM {table} WHERE simkl_id=?", (int(simkl_id),))
        return row.get("simkl_status") if row else None

    def _migrate_library_status_columns(self):
        """Add simkl_status column for local watchlist membership (survives metadata refresh)."""
        for table in ("movies", "shows"):
            columns = {row["name"] for row in self.fetchall(f"PRAGMA table_info({table})")}
            if "simkl_status" not in columns:
                self.execute_sql(f"ALTER TABLE {table} ADD COLUMN simkl_status TEXT")
                g.log(f"SimklSync: migrated {table}.simkl_status column", "info")
            self.execute_sql(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_simkl_status ON {table}(simkl_status)"
            )

        for table in ("movies", "shows"):
            rows = self.fetchall(f"SELECT simkl_id, info, simkl_status FROM {table}")
            for row in rows:
                if row.get("simkl_status"):
                    continue
                info = row.get("info")
                if not isinstance(info, dict):
                    continue
                status = info.get("simkl_status")
                if status:
                    self.execute_sql(
                        f"UPDATE {table} SET simkl_status=? WHERE simkl_id=?",
                        (status, row["simkl_id"]),
                    )

    def _migrate_movies_tvdb_id_column(self):
        columns = {row["name"] for row in self.fetchall("PRAGMA table_info(movies)")}
        if "tvdb_id" not in columns:
            self.execute_sql("ALTER TABLE movies ADD COLUMN tvdb_id INTEGER")
            g.log("SimklSync: migrated movies.tvdb_id column", "info")
            self.execute_sql("CREATE INDEX IF NOT EXISTS idx_movies_tvdb_id ON movies(tvdb_id)")

        rows = self.fetchall("SELECT simkl_id, info, tvdb_id FROM movies WHERE tvdb_id IS NULL")
        for row in rows:
            info = row.get("info")
            if not isinstance(info, dict):
                continue
            tvdb_id = info.get("tvdb_id")
            if tvdb_id is None and isinstance(info.get("ids"), dict):
                tvdb_id = info["ids"].get("tvdb")
            if tvdb_id is not None:
                self.execute_sql(
                    "UPDATE movies SET tvdb_id=? WHERE simkl_id=?",
                    (int(tvdb_id), row["simkl_id"]),
                )

    def _migrate_library_cache_tables(self):
        from resources.lib.simkl.library_cache import ensure_library_cache_tables

        ensure_library_cache_tables(self)

    @staticmethod
    def _library_status_from_item(item) -> str | None:
        from resources.lib.modules.metadataHandler import MetadataHandler

        if not isinstance(item, dict):
            return None
        status = item.get("simkl_status")
        if status:
            return status
        info = MetadataHandler.simkl_info(item)
        if isinstance(info, dict) and info.get("simkl_status"):
            return info.get("simkl_status")
        return None

    def _preserve_library_status_on_items(self, items, table: str) -> None:
        from resources.lib.modules.metadataHandler import MetadataHandler

        for item in items:
            if not isinstance(item, dict) or not item.get("simkl_id"):
                continue
            if self._library_status_from_item(item):
                continue
            row = self.fetchone(
                f"SELECT simkl_status, info FROM {table} WHERE simkl_id=?",
                (int(item["simkl_id"]),),
            )
            if not row:
                continue
            existing = row.get("simkl_status")
            if not existing and isinstance(row.get("info"), dict):
                existing = row["info"].get("simkl_status")
            if not existing:
                continue
            info = MetadataHandler.simkl_info(item)
            if isinstance(info, dict):
                info["simkl_status"] = existing
            item["simkl_status"] = existing

    @staticmethod
    def _get_datetime_now():
        return g.datetime_to_string(datetime.datetime.utcnow())

    @staticmethod
    def _get_aired_cutoff():
        from resources.lib.modules.air_date_delay import aired_cutoff_datetime_string

        return aired_cutoff_datetime_string()

    def refresh_activities(self):
        self.activities = self.fetchone("SELECT * FROM activities WHERE sync_id=1")

    def set_base_activities(self):
        username = g.get_setting("simkl.username")
        self.execute_sql(
            "REPLACE INTO activities(sync_id, simkl_username) VALUES(1, ?)",
            (username,),
        )
        self.activities = self.fetchone("SELECT * FROM activities WHERE sync_id=1")

    def flush_activities(self, clear_meta=False):
        if clear_meta:
            self.clear_all_meta()
        self.execute_sql("DELETE FROM activities")
        self.set_base_activities()

    def clear_user_information(self, notify=True):
        username = self.activities["simkl_username"]
        self.execute_sql(
            [
                "UPDATE episodes SET watched=?",
                "UPDATE episodes SET collected=?",
                "UPDATE movies SET watched=?",
                "UPDATE movies SET collected=?",
                "UPDATE shows SET unwatched_episodes=?",
                "UPDATE shows SET watched_episodes=?",
                "UPDATE seasons SET unwatched_episodes=?",
                "UPDATE seasons SET watched_episodes=?",
            ],
            (0,),
        )
        self.execute_sql(
            [
                "UPDATE episodes SET last_watched_at=?",
                "UPDATE shows SET last_watched_at=?",
                "UPDATE seasons SET last_watched_at=?",
                "UPDATE movies SET last_watched_at=?",
            ],
            (None,),
        )
        self.execute_sql(
            [
                "UPDATE episodes SET collected_at=?",
                "UPDATE shows SET last_collected_at=?",
                "UPDATE seasons SET last_collected_at=?",
                "UPDATE movies SET collected_at=?",
            ],
            (None,),
        )
        self.execute_sql(
            [
                "DELETE from bookmarks WHERE TRUE",
                "DELETE from hidden WHERE TRUE",
            ]
        )
        self.execute_sql(
            [
                "UPDATE episodes SET user_rating=?",
                "UPDATE shows SET user_rating=?",
                "UPDATE seasons SET user_rating=?",
                "UPDATE movies SET user_rating=?",
            ],
            (None,),
        )
        self.execute_sql("DELETE from lists WHERE username=?", (username,))
        self.set_simkl_user("")
        self.set_base_activities()
        if notify:
            g.notification(self.notification_prefix, g.get_language_string(30270), time=5000)

    def set_simkl_user(self, simkl_username):
        g.log(f"Setting Simkl username: {simkl_username}")
        self.execute_sql("UPDATE activities SET simkl_username=?", (simkl_username,))

    def clear_all_meta(self, notify=True):
        if notify:
            confirm = xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(30179))
            if confirm == 0:
                return

        self.execute_sql(
            [
                "UPDATE shows SET info=?, cast=?, art=?, meta_hash=?",
                "UPDATE seasons SET info=?, cast=?, art=?, meta_hash=?",
                "UPDATE episodes SET info=?, cast=?, art=?, meta_hash=?",
                "UPDATE movies SET info=?, cast=?, art=?, meta_hash=?",
            ],
            (None, None, None, None),
        )

        self.execute_sql(
            [
                "DELETE FROM movies_meta",
                "DELETE FROM shows_meta",
                "DELETE FROM seasons_meta",
                "DELETE FROM episodes_meta",
            ]
        )
        if notify:
            g.notification(self.notification_prefix, g.get_language_string(30271), time=5000)

    def re_build_database(self, silent=False):
        if not silent:
            confirm = xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(30179))
            if confirm == 0:
                return

        self.rebuild_database()
        self.set_base_activities()
        self.refresh_activities()

        from resources.lib.database.simkl_sync import activities

        if sync_errors := activities.SimklSyncDatabase().sync_activities(silent):
            g.notification(self.notification_prefix, g.get_language_string(30332), time=5000)
        elif sync_errors is None:
            self.refresh_activities()
        else:
            g.notification(self.notification_prefix, g.get_language_string(30272), time=5000)

    def save_to_meta_table(self, items, meta_type, provider_type, id_column):
        if items is None:
            return
        sql_statement = f"""
            INSERT INTO {meta_type}_meta (id, type, meta_hash, value) VALUES (?, ?, ?, ?)
            ON CONFLICT(id, type) DO UPDATE
                SET (meta_hash, value) = (excluded.meta_hash, excluded.value)
            """
        obj = None
        meta_hash = None
        if provider_type == "simkl":
            obj = MetadataHandler.simkl_object
            meta_hash = self.simkl_api.meta_hash
        elif provider_type == "tmdb":
            obj = MetadataHandler.tmdb_object
            meta_hash = self.metadataHandler.tmdb_api.meta_hash
        elif provider_type == "tvdb":
            obj = MetadataHandler.tvdb_object
            meta_hash = self.metadataHandler.tvdb_api.meta_hash
        elif provider_type == "fanart":
            obj = MetadataHandler.fanart_object
            meta_hash = self.metadataHandler.fanarttv_api.meta_hash

        if obj is None or meta_hash is None:
            raise UnsupportedProviderType(provider_type)

        meta_ok = MetadataHandler.simkl_meta_savable if provider_type == "simkl" else MetadataHandler.full_meta_up_to_par

        singular = meta_type.rstrip("s") if meta_type.endswith("s") else meta_type
        media_hint = "movie" if singular == "movie" else "episode" if singular == "episode" else "season" if singular == "season" else "tvshow"

        self.execute_sql(
            sql_statement,
            (
                (
                    i.get(id_column),
                    provider_type,
                    meta_hash,
                    self.clean_meta(obj(i), provider_type=provider_type, media_type=media_hint),
                )
                for i in items
                if (i and obj(i) and i.get(id_column) and meta_ok(meta_type, obj(i)))
            ),
        )

        for i in items:
            if i and obj(i):
                if obj(i).get("seasons"):
                    self.save_to_meta_table(i.get("seasons"), "season", provider_type, id_column)
                if obj(i).get("episodes"):
                    self.save_to_meta_table(i.get("episodes"), "episode", provider_type, id_column)

    @staticmethod
    def _meta_table_lookup_id(meta_type: str, ext_id) -> int | str | None:
        """Normalize an external id for *_meta table lookups."""
        if ext_id is None:
            return None
        if meta_type == "imdb":
            from resources.lib.simkl.field_map import _normalize_imdb_id

            return _normalize_imdb_id(ext_id)
        return _int_or_none(ext_id)

    def load_cached_provider_meta(self, media_table: str, simkl_id: int, info: dict) -> dict:
        """Load pickled provider blobs from *_meta for offline art merge."""
        result: dict = {}
        simkl_row = self.fetchone(
            f"SELECT value FROM {media_table}_meta WHERE id=? AND type='simkl'",
            (int(simkl_id),),
        )
        if simkl_row and simkl_row.get("value"):
            result["simkl_object"] = simkl_row["value"]

        for meta_type, id_key in (("tmdb", "tmdb_id"), ("tvdb", "tvdb_id"), ("imdb", "imdb_id")):
            lookup_id = self._meta_table_lookup_id(meta_type, info.get(id_key))
            if lookup_id is None:
                continue
            row = self.fetchone(
                f"SELECT value FROM {media_table}_meta WHERE id=? AND type=?",
                (lookup_id, meta_type),
            )
            if row and row.get("value"):
                result[f"{meta_type}_object"] = row["value"]

        fanart_id = info.get("tvdb_id") if media_table == "shows" else info.get("tmdb_id")
        fanart_lookup_id = _int_or_none(fanart_id)
        if fanart_lookup_id is not None:
            row = self.fetchone(
                f"SELECT value FROM {media_table}_meta WHERE id=? AND type='fanart'",
                (fanart_lookup_id,),
            )
            if row and row.get("value"):
                result["fanart_object"] = row["value"]
        return result

    @staticmethod
    def clean_meta(item, *, provider_type=None, media_type=None):
        if not item:
            return None

        from resources.lib.modules.meta_storage import slim_provider_blob

        result = {
            "info": {key: value for key, value in item.get("info", {}).items() if key not in ["seasons", "episodes"]},
            "art": item.get("art"),
            "cast": item.get("cast"),
        }

        if result.get("info") or result.get("art") or result.get("cast"):
            return slim_provider_blob(result, provider_type=provider_type, media_type=media_type)
        g.log(
            f"Bad Item meta discovered when cleaning - item: {item}",
            "error",
        )
        return None

    @staticmethod
    def _apply_request_force_update(db_rows, request_refs) -> None:
        """Honor gap-fill requests that need a provider refresh even when DB says meta is current."""
        force_ids = {
            int(ref["simkl_id"])
            for ref in request_refs or []
            if ref.get("simkl_id") is not None
            and ref.get("needs_update") in (True, "true", "True", 1, "1")
        }
        if not force_ids:
            return
        for row in db_rows or []:
            simkl_id = row.get("simkl_id")
            if simkl_id is not None and int(simkl_id) in force_ids:
                row["needs_update"] = True

    def _set_needs_update(self, items, media_type):
        update_list = self.fetchall(f"SELECT simkl_id from {media_type} WHERE needs_update")
        if not update_list:
            return
        update_set = {tid.get('simkl_id') for tid in update_list}
        for i in items:
            i["needs_update"] = i.get("simkl_id") in update_set

    def _prepare_sync_inserts(self, items: list[dict]) -> None:
        from resources.lib.simkl.ids import sync_sql_columns_from_info

        for item in items:
            if isinstance(item, dict):
                sync_sql_columns_from_info(item)

    def insert_simkl_movies(self, movies, force_meta=False):
        if not movies:
            return

        if force_meta:
            to_insert = [i for i in movies if isinstance(i, dict) and i.get("simkl_id")]
        else:
            to_insert = self._filter_media_items_that_needs_updating(movies, "movies")

        if not to_insert:
            return

        self._prepare_sync_inserts(to_insert)
        self._preserve_library_status_on_items(to_insert, "movies")
        g.log(f"Inserting Movies into sync database: {len(to_insert)}")
        from resources.lib.modules.meta_storage import slim_art_dict, slim_info_dict

        get = MetadataHandler.get_simkl_info
        simkl_obj = MetadataHandler.simkl_object
        self.execute_sql(
            self.upsert_movie_query,
            (
                (
                    i.get("simkl_id"),
                    slim_info_dict(MetadataHandler.simkl_info(i) or {}, simkl=True) or None,
                    slim_art_dict(MetadataHandler.art(simkl_obj(i)) or {}, "movie") or None,
                    None,
                    get(i, "collected"),
                    get(i, "watched"),
                    g.validate_date(get(i, "aired")),
                    g.validate_date(get(i, "dateadded")),
                    get(i, "tmdb_id"),
                    get(i, "tvdb_id"),
                    get(i, "imdb_id"),
                    None,
                    self._create_args(i),
                    g.validate_date(get(i, "collected_at")),
                    g.validate_date(get(i, "last_watched_at")),
                    get(i, "user_rating"),
                    self._library_status_from_item(i),
                )
                for i in to_insert
            ),
        )
        self.save_to_meta_table(to_insert, "movies", "simkl", "simkl_id")
        self._set_needs_update(movies, "movies")
        from resources.lib.database.sync_meta_cache import SyncMetaCache

        cache = SyncMetaCache()
        for item in to_insert:
            cache.set_row(
                "movie",
                {
                    "simkl_id": item.get("simkl_id"),
                    "info": slim_info_dict(MetadataHandler.simkl_info(item) or {}, simkl=True),
                    "art": slim_art_dict(MetadataHandler.art(simkl_obj(item)) or {}, "movie"),
                    "tmdb_id": get(item, "tmdb_id"),
                    "tvdb_id": get(item, "tvdb_id"),
                    "imdb_id": get(item, "imdb_id"),
                    "air_date": g.validate_date(get(item, "aired")),
                },
            )

    def insert_simkl_shows(self, shows, force_meta=False):
        if not shows:
            return

        if force_meta:
            to_insert = [i for i in shows if isinstance(i, dict) and i.get("simkl_id")]
        else:
            to_insert = self._filter_media_items_that_needs_updating(shows, "shows")

        if not to_insert:
            return

        self._prepare_sync_inserts(to_insert)
        self._preserve_library_status_on_items(to_insert, "shows")
        g.log(f"Inserting Shows into sync database: {len(to_insert)}")
        from resources.lib.modules.meta_storage import slim_art_dict, slim_info_dict

        get = MetadataHandler.get_simkl_info
        simkl_obj = MetadataHandler.simkl_object
        self.execute_sql(
            self.upsert_show_query,
            (
                (
                    i.get("simkl_id"),
                    slim_info_dict(MetadataHandler.simkl_info(i) or {}, simkl=True) or None,
                    slim_art_dict(
                        MetadataHandler.art(simkl_obj(i)) or {},
                        "anime"
                        if (MetadataHandler.simkl_info(i) or {}).get("catalog") == "anime"
                        else "tvshow",
                    )
                    or None,
                    None,
                    g.validate_date(get(i, "aired")),
                    g.validate_date(get(i, "dateadded")),
                    get(i, "tmdb_id"),
                    get(i, "tvdb_id"),
                    get(i, "imdb_id"),
                    self.simkl_api.meta_hash,
                    get(i, "season_count"),
                    get(i, "episode_count"),
                    self._create_args(i),
                    get(i, "is_airing"),
                    g.validate_date(get(i, "last_watched_at")),
                    g.validate_date(get(i, "last_collected_at")),
                    get(i, "user_rating"),
                    self._library_status_from_item(i),
                )
                for i in to_insert
            ),
        )
        self.save_to_meta_table(to_insert, "shows", "simkl", "simkl_id")
        self._set_needs_update(shows, "shows")
        from resources.lib.database.sync_meta_cache import SyncMetaCache

        cache = SyncMetaCache()
        for item in to_insert:
            info = MetadataHandler.simkl_info(item) or {}
            cache.set_row(
                "show",
                {
                    "simkl_id": item.get("simkl_id"),
                    "info": slim_info_dict(info, simkl=True),
                    "art": slim_art_dict(
                        MetadataHandler.art(simkl_obj(item)) or {},
                        "anime" if info.get("catalog") == "anime" else "tvshow",
                    ),
                    "tmdb_id": get(item, "tmdb_id"),
                    "tvdb_id": get(item, "tvdb_id"),
                    "imdb_id": get(item, "imdb_id"),
                    "air_date": g.validate_date(get(item, "aired")),
                    "is_airing": get(item, "is_airing"),
                },
            )

    def insert_simkl_episodes(self, episodes):
        if not episodes:
            return

        to_insert = self._filter_media_items_that_needs_updating(episodes, "episodes")

        if not to_insert:
            return
        self._prepare_sync_inserts(to_insert)
        g.log(f"Inserting episodes into sync database: {len(to_insert)}")
        get = MetadataHandler.get_simkl_info

        if missing_season_ids := [i for i in to_insert if not i.get("simkl_season_id")]:
            predicate = " OR ".join(
                [f"(simkl_show_id={get(i, 'simkl_show_id')} AND season={get(i, 'season')})" for i in missing_season_ids]
            )
            season_ids = self.fetchall(f"SELECT simkl_show_id, simkl_id, season FROM seasons WHERE {predicate}")
            season_ids = {f"{i['simkl_show_id']}-{i['season']}": i["simkl_id"] for i in season_ids}
            for i in to_insert:
                i["simkl_season_id"] = season_ids.get(f"{get(i, 'simkl_show_id')}-{get(i, 'season')}")

        self.execute_sql(
            self.upsert_episode_query,
            (
                (
                    i.get("simkl_id"),
                    i.get("simkl_show_id"),
                    i.get("simkl_season_id"),
                    get(i, "playcount"),
                    get(i, "collected"),
                    g.validate_date(get(i, "aired")),
                    g.validate_date(get(i, "dateadded")),
                    get(i, "season"),
                    get(i, "episode"),
                    get(i, "tmdb_id"),
                    get(i, "tvdb_id"),
                    get(i, "imdb_id"),
                    None,
                    None,
                    None,
                    self._create_args(i),
                    g.validate_date(get(i, "last_watched_at")),
                    g.validate_date(get(i, "collected_at")),
                    get(i, "user_rating"),
                    self.simkl_api.meta_hash,
                )
                for i in to_insert
            ),
        )
        self.save_to_meta_table(to_insert, "episodes", "simkl", "simkl_id")
        self._set_needs_update(episodes, "episodes")

    def insert_simkl_seasons(self, seasons):
        if not seasons:
            return

        to_insert = self._filter_media_items_that_needs_updating(seasons, "seasons")

        if not to_insert:
            return

        self._prepare_sync_inserts(to_insert)
        g.log(f"Inserting seasons into sync database: {len(to_insert)}")
        get = MetadataHandler.get_simkl_info
        for i in to_insert:
            g.log(
                f"[season trace] insert_simkl_seasons show={i.get('simkl_show_id')} "
                f"season={get(i, 'season')} row_id={i.get('simkl_id')} title={get(i, 'title')}",
                "debug",
            )
        self.execute_sql(
            self.upsert_season_query,
            (
                (
                    i.get("simkl_show_id"),
                    i.get("simkl_id"),
                    None,
                    None,
                    None,
                    g.validate_date(get(i, "aired")),
                    g.validate_date(get(i, "dateadded")),
                    get(i, "tmdb_id"),
                    get(i, "tvdb_id"),
                    self.simkl_api.meta_hash,
                    None,
                    get(i, "season"),
                    self._create_args(i),
                    g.validate_date(get(i, "last_watched_at")),
                    g.validate_date(get(i, "last_collected_at")),
                    get(i, "user_rating"),
                )
                for i in to_insert
            ),
        )
        self.save_to_meta_table(to_insert, "seasons", "simkl", "simkl_id")
        self._set_needs_update(seasons, "seasons")

    def _mill_if_needed(self, list_to_update, queue_wrapper=None, mill_episodes=True):
        if queue_wrapper is None:
            queue_wrapper = self._queue_mill_tasks

        ids_to_mill_check = ",".join(str(i.get("simkl_show_id", i.get("simkl_id"))) for i in list_to_update)
        now = self._get_aired_cutoff()

        query = f"""
            SELECT s.simkl_id, s.needs_milling, s.season_count, agg.meta_count, agg.tot_season_count, agg.tot_meta_count
            FROM shows AS s
                     LEFT JOIN(SELECT s.simkl_id,
                                      sum(CASE
                                              WHEN se.simkl_id IS NOT NULL
                                                  AND se.season != 0 AND Datetime(se.air_date) < Datetime('{now}')
                                                  THEN 1
                                              ELSE 0
                                          END)           AS season_count,
                                      sum(CASE
                                              WHEN sm.id IS NOT NULL
                                                  AND se.season != 0
                                                  AND Datetime(se.air_date) < Datetime('{now}')
                                                  THEN 1
                                              ELSE 0
                                          END)           AS meta_count,
                                      count(se.simkl_id) AS tot_season_count,
                                      count(sm.id)       AS tot_meta_count
                               FROM shows AS s
                                        INNER JOIN seasons AS se
                                                   ON s.simkl_id = se.simkl_show_id
                                        LEFT JOIN seasons_meta AS sm
                                                  ON sm.id = se.simkl_id
                                                      AND sm.type = 'simkl'
                                                      AND sm.meta_hash = '{self.simkl_api.meta_hash}'
                               WHERE s.simkl_id IN ({ids_to_mill_check})
                               GROUP BY s.simkl_id) AS agg
                              ON s.simkl_id = agg.simkl_id
            WHERE s.simkl_id IN ({ids_to_mill_check})
              AND (s.needs_milling
                OR (agg.season_count IS NULL OR agg.season_count != s.season_count)
                OR (agg.meta_count = 0 OR agg.meta_count != s.season_count)
                OR agg.tot_season_count != agg.tot_meta_count)
            """
        needs_milling = self.fetchall(query)
        if needs_milling is not None:
            needs_milling = {x.get('simkl_id') for x in needs_milling}
        else:
            needs_milling = set()

        if mill_episodes:
            query = f"""
                SELECT s.simkl_id,
                       s.episode_count,
                       agg.episode_count,
                       agg.meta_count,
                       agg.tot_episode_count,
                       agg.tot_meta_count
                FROM shows AS s
                         LEFT JOIN(SELECT s.simkl_id,
                                          sum(CASE
                                                  WHEN e.simkl_id IS NOT NULL
                                                      AND e.season != 0
                                                      AND Datetime(e.air_date) < Datetime('{now}')
                                                      THEN 1
                                              END)          AS episode_count,
                                          sum(CASE
                                                  WHEN em.id IS NOT NULL
                                                      AND e.season != 0
                                                      AND Datetime(e.air_date) < Datetime('{now}')
                                                      THEN 1
                                              END)          AS meta_count,
                                          count(e.simkl_id) AS tot_episode_count,
                                          count(em.id)      AS tot_meta_count
                                   FROM shows
                                            AS s
                                            INNER JOIn episodes AS e
                                                       ON s.simkl_id = e.simkl_show_id
                                            LEFT JOIN episodes_meta AS em
                                                      ON em.id = e.simkl_id
                                                          AND em.type = 'simkl'
                                                          AND em.meta_hash = '{self.simkl_api.meta_hash}'
                                   WHERE s.simkl_id IN ({ids_to_mill_check})
                                   GROUP BY s.simkl_id) AS agg ON s.simkl_id = agg.simkl_id
                WHERE s.simkl_id IN ({ids_to_mill_check})
                  AND ((agg.episode_count IS NULL OR agg.episode_count != s.episode_count)
                    OR (agg.meta_count = 0 OR agg.meta_count != s.episode_count)
                    OR agg.tot_episode_count != agg.tot_meta_count)
                """
            episodes_needs_milling = self.fetchall(query)
            if episodes_needs_milling is not None:
                needs_milling.update({x.get('simkl_id') for x in episodes_needs_milling})

            missing_episodes = self.fetchall(
                f"""
                SELECT s.simkl_id
                FROM shows AS s
                WHERE s.simkl_id IN ({ids_to_mill_check})
                  AND EXISTS (SELECT 1 FROM seasons AS se WHERE se.simkl_show_id = s.simkl_id)
                  AND NOT EXISTS (SELECT 1 FROM episodes AS e WHERE e.simkl_show_id = s.simkl_id)
                """
            )
            if missing_episodes:
                needs_milling.update({x.get("simkl_id") for x in missing_episodes})

            missing_specials = self.fetchall(
                f"""
                SELECT s.simkl_id
                FROM shows AS s
                WHERE s.simkl_id IN ({ids_to_mill_check})
                  AND EXISTS (SELECT 1 FROM seasons AS se WHERE se.simkl_show_id = s.simkl_id)
                  AND NOT EXISTS (SELECT 1 FROM seasons AS se WHERE se.simkl_show_id = s.simkl_id AND se.season = 0)
                """
            )
            if missing_specials:
                from resources.lib.database.simkl_sync.milling import count_special_episodes

                for row in missing_specials:
                    show_id = row.get("simkl_id")
                    if show_id:
                        catalog = self._infer_show_catalog(show_id)
                        slug = self._meta_slug(show_id, "shows")
                        if count_special_episodes(int(show_id), catalog, slug=slug) > 0:
                            needs_milling.add(show_id)

        show_milling_count = len(needs_milling)
        if show_milling_count > 0:
            g.log(f"{show_milling_count} items require season milling", "debug")
        else:
            return

        self.mill_seasons(
            [i for i in list_to_update if i.get("simkl_show_id", i.get("simkl_id")) in needs_milling],
            queue_wrapper,
            mill_episodes,
        )

    def mill_seasons(self, show_collection, queue_wrapper, mill_episodes=False):
        with SyncLock(
            f"mill_seasons_episodes_{mill_episodes}",
            {show.get("simkl_show_id", show.get("simkl_id")) for show in show_collection},
        ) as sync_lock:
            # Everything we are milling may already be being milled in another process/thread
            # we need to check if there are any running IDs first.  The sync_lock wont exit until
            # the other process/thread is done with its milling giving good results.
            if len(sync_lock.running_ids) > 0:
                get = MetadataHandler.get_simkl_info
                simkl_info = MetadataHandler.simkl_info

                queue_wrapper(self._pull_show_seasons, [(i, mill_episodes) for i in sync_lock.running_ids])
                results = self.mill_task_queue.wait_completion()

                seasons = []
                episodes = []

                season_ids = {}
                episode_ids = {}

                for show in show_collection:
                    show_info = simkl_info(show)
                    show_catalog = (
                        show.get("catalog")
                        or show_info.get("catalog")
                        or self._infer_show_catalog(get(show, "simkl_id"))
                    )
                    extended_seasons = {get(x, "season"): x for x in get(show, "seasons", [])}
                    # We make a dict here to ensure that the season numbers are unique due to a few bad simkl_meta records.
                    milled_seasons = results.get(show.get("simkl_id"), [])
                    g.log(
                        f"[season trace] mill_seasons show={get(show, 'simkl_id')} "
                        f"milled_keys={[s.get('season') for s in milled_seasons]} "
                        f"extended_keys={list(extended_seasons.keys())}",
                        "debug",
                    )
                    for s_num, season in {
                        season.get("season", get(season, "season")): season for season in milled_seasons
                    }.items():
                        simkl_info(season).update({"simkl_show_id": get(show, "simkl_id")})
                        simkl_info(season).update({"tmdb_show_id": get(show, "tmdb_id")})
                        simkl_info(season).update({"tvdb_show_id": get(show, "tvdb_id")})
                        if show_catalog in ("movie", "tv", "anime"):
                            simkl_info(season).setdefault("catalog", show_catalog)

                        season.update({"simkl_show_id": show.get("simkl_id")})
                        season.update({"tmdb_show_id": show.get("tmdb_id")})
                        season.update({"tvdb_show_id": show.get("tvdb_id")})
                        if show_catalog in ("movie", "tv", "anime"):
                            season.setdefault("catalog", show_catalog)

                        simkl_info(season).update({"dateadded": get(show, "dateadded")})
                        simkl_info(season).update({"tvshowtitle": get(show, "title")})

                        if s_num > 0:
                            show.update(
                                {
                                    "season_count": show.get("season_count", 0)
                                    + (1 if get(season, "aired_episodes", 0) > 0 else 0)
                                }
                            )
                            show.update(
                                {'episode_count': show.get("episode_count", 0) + get(season, "aired_episodes", 0)}
                            )

                        extended_season = extended_seasons.get(s_num)
                        if extended_season:
                            tools.smart_merge_dictionary(season, extended_season, keep_original=True)

                        g.log(
                            f"[season trace] mill_seasons -> insert season={s_num} "
                            f"row_id={get(season, 'simkl_id')} episodes={len(season.get('episodes') or [])}",
                            "debug",
                        )
                        seasons.append(season)
                        if get(show, "simkl_id") not in season_ids:
                            season_ids[get(show, "simkl_id")] = []

                        season_ids[get(show, "simkl_id")].append(get(season, "simkl_id"))

                        extended_episodes = {get(x, "episode"): x for x in get(extended_season, "episodes", [])}
                        season_episodes = season.get("episodes") or get(season, "episodes") or []
                        for episode in season_episodes:
                            e_num = episode.get("episode", get(episode, "episode"))
                            simkl_info(episode).update({"simkl_show_id": get(show, "simkl_id")})
                            simkl_info(episode).update({"tmdb_show_id": get(show, "tmdb_id")})
                            simkl_info(episode).update({"tvdb_show_id": get(show, "tvdb_id")})
                            simkl_info(episode).update({"simkl_season_id": get(season, "simkl_id")})
                            from resources.lib.simkl.field_map import inherit_show_fields

                            inherit_show_fields(simkl_info(episode), show_info)

                            episode.update({"simkl_show_id": show.get("simkl_id")})
                            episode.update({"tmdb_show_id": show.get("tmdb_id")})
                            episode.update({"tvdb_show_id": show.get("tvdb_id")})
                            episode.update({"simkl_season_id": season.get("simkl_id")})
                            if show_catalog in ("movie", "tv", "anime"):
                                episode.setdefault("catalog", show_catalog)

                            simkl_info(episode).update({"tvshowtitle": get(show, "title")})

                            if extended_episode := extended_episodes.get(e_num):
                                tools.smart_merge_dictionary(episode, extended_episode, keep_original=True)

                            episodes.append(episode)
                            if get(show, "simkl_id") not in episode_ids:
                                episode_ids[get(show, "simkl_id")] = []

                            episode_ids[get(show, "simkl_id")].append(get(episode, "simkl_id"))

                self.insert_simkl_seasons(seasons)
                self.insert_simkl_episodes(episodes)
                if mill_episodes and episodes:
                    episode_refs = [{"simkl_id": get(ep, "simkl_id")} for ep in episodes if get(ep, "simkl_id")]
                    self._update_episodes(episode_refs)
                    self._format_episodes(episode_refs)

                if mill_episodes:
                    self.execute_sql(
                        [
                            f"""
                            DELETE FROM episodes
                            WHERE simkl_show_id = {simkl_id} AND simkl_id NOT IN ({','.join(map(str, episode))})
                            """
                            for simkl_id, episode in episode_ids.items()
                        ]
                    )

                self.execute_sql(
                    [
                        f"""
                        DELETE FROM seasons
                        WHERE simkl_show_id = {simkl_id} AND simkl_id NOT IN ({','.join(map(str, season))})
                        """
                        for simkl_id, season in season_ids.items()
                    ]
                )

                self.execute_sql(
                    "UPDATE shows SET episode_count=?, season_count=? WHERE simkl_id=? ",
                    (
                        (i.get("episode_count", 0), i.get("season_count", 0), i["simkl_id"])
                        for i in show_collection
                        if i["simkl_id"] in sync_lock.running_ids
                    ),
                )

                self.update_shows_statistics({"simkl_id": i} for i in sync_lock.running_ids)

                if mill_episodes:
                    self.update_season_statistics({"simkl_id": i['simkl_id']} for i in seasons)

                self.execute_sql(
                    f"UPDATE shows SET needs_milling=0 WHERE simkl_id IN ({','.join(map(str, sync_lock.running_ids))})"
                )

    def _resolve_sync_simkl_id(self, item: dict):
        simkl_id = item.get("simkl_id")
        if simkl_id is not None:
            return int(simkl_id)
        ids = item.get("ids") or {}
        simkl_id = ids.get("simkl") or ids.get("simkl_id")
        return int(simkl_id) if simkl_id is not None else None

    def _filter_media_items_that_needs_updating(self, requested, media_type):
        if not requested:
            return requested

        requested = [i for i in requested if isinstance(i, dict)]
        if not requested:
            return []

        get = MetadataHandler.get_simkl_info

        resolved = []
        for item in requested:
            simkl_id = self._resolve_sync_simkl_id(item)
            if simkl_id is not None:
                resolved.append((item, simkl_id))

        if not resolved:
            return []

        query_predicate = [
            f"({simkl_id}, '{self.simkl_api.meta_hash}', '{get(item, 'dateadded')}')"
            for item, simkl_id in resolved
        ]

        query = f"""
            WITH requested(simkl_id, meta_hash, updated_at) AS (VALUES {','.join(query_predicate)})
            SELECT r.simkl_id AS simkl_id
            FROM requested AS r
            LEFT JOIN {media_type} AS db
                      ON r.simkl_id == db.simkl_id
            LEFT JOIN {media_type}_meta AS m
                      ON db.simkl_id == id AND type = 'simkl'
            WHERE db.simkl_id IS NULL
                  OR m.value IS NULL
                  OR m.meta_hash != r.meta_hash
                  OR Datetime(db.last_updated) < Datetime(r.updated_at)
            """

        result = {r["simkl_id"] for r in self.fetchall(query)}

        nested_key = media_type.rstrip("s")

        def _requested_record(item):
            nested = item.get(nested_key)
            if isinstance(nested, dict):
                return nested
            return item

        return [_requested_record(item) for item, simkl_id in resolved if simkl_id in result]

    def _pull_show_seasons(self, show_id, mill_episodes):
        from resources.lib.database.simkl_sync.milling import pull_show_seasons
        from resources.lib.simkl.catalog import is_anime_movie_info

        row = self.fetchone("SELECT info FROM shows WHERE simkl_id = ?", (int(show_id),))
        if row and is_anime_movie_info(row.get("info")):
            g.log(f"Skipping season mill for anime movie show_id={show_id}", "debug")
            return {show_id: []}

        catalog = self._infer_show_catalog(show_id)
        slug = self._meta_slug(show_id, "shows")
        g.log(f"[season trace] _pull_show_seasons show={show_id} inferred_catalog={catalog} slug={slug}", "debug")
        return {show_id: pull_show_seasons(int(show_id), catalog, mill_episodes, slug=slug)}

    def _infer_show_catalog(self, show_id):
        row = self.fetchone(
            """
            SELECT m.value AS simkl_object, s.info AS show_info
            FROM shows_meta AS m
            LEFT JOIN shows AS s ON s.simkl_id = m.id
            WHERE m.id = ? AND m.type = 'simkl'
            """,
            (int(show_id),),
        )
        if row:
            for info in (
                (row.get("simkl_object") or {}).get("info") or {},
                row.get("show_info") or {},
            ):
                if not isinstance(info, dict):
                    continue
            ids = info.get("ids") or {}
            if ids.get("mal") or info.get("mal_id"):
                return "anime"
                if info.get("catalog") == "anime" or info.get("type") == "anime":
                    return "anime"
        return "tv"

    @staticmethod
    def _create_args(item):
        from resources.lib.simkl.ids import serialize_action_args

        return serialize_action_args(item)

    def _queue_mill_tasks(self, func, args):
        for arg in args:
            self.mill_task_queue.put(func, *arg)

    @staticmethod
    def requires_update(new_date, old_date):
        parsed_new = tools.parse_datetime(new_date, False) if new_date else None
        parsed_old = tools.parse_datetime(old_date, False) if old_date else None
        if parsed_new is None:
            return False
        if parsed_old is None:
            return True
        return parsed_new > parsed_old

    @staticmethod
    def wrap_in_simkl_object(items):
        for item in items:
            if item.get("show") is not None:
                info = item["show"].pop("info")
                item["show"].update({"simkl_id": info.get("simkl_id")})
                item["show"].update({"simkl_object": {"info": info}})
            if item.get("episode") is not None:
                info = item["episode"].pop("info")
                item["episode"].update({"simkl_id": info.get("simkl_id")})
                item["episode"].update({"tvdb_id": info.get("tvdb_id")})
                item["episode"].update({"tmdb_id": info.get("tmdb_id")})
                item["episode"].update({"simkl_object": {"info": info}})
        return items

    def _meta_slug(self, simkl_id, media_type):
        from resources.lib.simkl.ids import slug_from_info

        row = self.fetchone(
            f"""
            SELECT value FROM {media_type}_meta
            WHERE id = ? AND type = 'simkl'
            """,
            (int(simkl_id),),
        )
        if row and row.get("value"):
            obj = row["value"]
            if isinstance(obj, dict):
                slug = slug_from_info(obj.get("info") or obj)
                if slug:
                    return slug
        info_row = self.fetchone(f"SELECT info FROM {media_type} WHERE simkl_id = ?", (int(simkl_id),))
        if info_row and info_row.get("info"):
            return slug_from_info(info_row["info"])
        return None

    def _get_single_meta(self, simkl_id, media_type):
        from resources.lib.simkl.ids import movie_api_path, show_api_path

        if media_type == "shows":
            api_url = show_api_path(int(simkl_id))
        elif media_type == "movies":
            api_url = movie_api_path(int(simkl_id))
        else:
            api_url = f"/{media_type}/{simkl_id}"
        return self._update_single_meta(
            api_url,
            self.fetchone(
                f"""
                SELECT id AS simkl_id, value AS simkl_object
                FROM {media_type}_meta
                WHERE id = ? AND type = 'simkl'
                """,
                (int(simkl_id),),
            ),
            media_type,
        )

    def _update_single_meta(self, api_url, item, media_type):
        from resources.lib.simkl.api_normalize import api_detail_to_sync_dict

        simkl_object = MetadataHandler.simkl_object
        if item is None:
            item = {}
        if simkl_object(item) is None or simkl_object(item) == {}:
            catalog = {"shows": "tv", "movies": "movie"}.get(media_type, media_type)
            new_object = self.simkl_api.get_json(
                api_url,
                authorized=False,
                client_id=self.simkl_api.client_id,
            )
            if not new_object:
                g.log(f"Simkl meta fetch failed: {api_url}", "warning")
                return item

            sync_item = api_detail_to_sync_dict(new_object, catalog)
            if not sync_item:
                g.log(f"Simkl meta could not be normalized: {api_url}", "warning")
                return item

            if media_type == "movies":
                self.insert_simkl_movies([sync_item])
            elif media_type == "shows":
                self.insert_simkl_shows([sync_item])
            elif media_type == "seasons":
                self.insert_simkl_seasons([sync_item])
            elif media_type == "episodes":
                self.insert_simkl_episodes([sync_item])

            item["simkl_id"] = sync_item.get("simkl_id")
            item["simkl_object"] = sync_item.get("simkl_object", {})
        return item

    def _extract_browse_page(self, url, media_type, **params):
        result = []

        hide_watched = params.get("hide_watched", self.hide_watched)
        hide_unaired = params.get("hide_unaired", self.hide_unaired)
        get = MetadataHandler.get_simkl_info
        page_number = params.pop("page", 1)
        params.pop("pull_all", None)
        params.pop("ignore_cache", None)
        no_paging = params.pop("no_paging", False)

        if url.startswith("search/"):
            query = params.get("query") or params.get("q")
            if not query:
                g.log(f"Simkl search missing query for {url}", "warning")
                return []
            params.pop("fields", None)
            params.pop("field", None)
            params.pop("extended", None)
            from resources.lib.simkl.search import search_page

            return search_page(
                url,
                media_type,
                page_number,
                self.page_limit,
                query,
            )

        g.log(f"Unsupported legacy browse URL (use Discover menus): {url}", "warning")
        return []

    @staticmethod
    def _entry_show_simkl_id(entry: dict) -> int | None:
        if not isinstance(entry, dict):
            return None
        for key in ("show", "anime"):
            blob = entry.get(key)
            if isinstance(blob, dict):
                simkl_id = (blob.get("ids") or {}).get("simkl")
                if simkl_id is not None:
                    return int(simkl_id)
        if entry.get("ids", {}).get("simkl") is not None:
            return int(entry["ids"]["simkl"])
        return None

    @staticmethod
    def _episode_marked_watched(episode: dict, entry: dict | None = None) -> bool:
        if not isinstance(episode, dict):
            return False
        if episode.get("watched") in (True, 1, "true", "True"):
            return True
        if episode.get("watched_at") or episode.get("last_watched_at"):
            return True
        return False

    def apply_show_watch_counters(self, entries):
        """Apply Simkl summary progress (watched/total episode counts) to show rows for list indicators."""
        rows = []
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            simkl_id = self._entry_show_simkl_id(entry)
            watched = entry.get("watched_episodes_count")
            total = entry.get("total_episodes_count")
            if simkl_id is None or watched is None or total is None:
                continue
            watched = int(watched)
            total = int(total)
            rows.append((watched, total, max(0, total - watched), simkl_id))

        if not rows:
            return

        self.execute_sql(
            """
            UPDATE shows
            SET watched_episodes = MAX(watched_episodes, ?),
                episode_count = MAX(episode_count, ?),
                unwatched_episodes = ?
            WHERE simkl_id = ?
            """,
            rows,
        )

    def apply_watched_episodes_from_entries(self, entries, shows):
        show_ids = {show["simkl_id"]: show for show in shows if show.get("simkl_id")}
        rows = []

        for entry in entries or []:
            show_id = self._entry_show_simkl_id(entry)
            if show_id is None or show_id not in show_ids:
                continue

            for season in entry.get("seasons") or []:
                season_num = season.get("number") if season.get("number") is not None else season.get("season")
                if season_num is None:
                    continue
                for episode in season.get("episodes") or []:
                    episode_num = episode.get("number") if episode.get("number") is not None else episode.get("episode")
                    if episode_num is None:
                        continue
                    if not self._episode_marked_watched(episode, entry):
                        continue
                    rows.append(
                        {
                            "simkl_show_id": show_id,
                            "season": int(season_num),
                            "episode": int(episode_num),
                            "last_watched_at": episode.get("watched_at")
                            or episode.get("last_watched_at")
                            or entry.get("last_watched_at"),
                            "watched": 1,
                        }
                    )

        if not rows:
            self.apply_show_watch_counters(entries)
            return

        show_id_list = ",".join(str(i) for i in show_ids.keys())
        with self.create_temp_table(
            "_episodes_watched",
            ["simkl_show_id", "season", "episode", "last_watched_at", "watched"],
            primary_key="simkl_show_id, season, episode",
        ) as temp_table:
            temp_table.insert_data(rows)
            self.execute_sql(
                [
                    f"UPDATE episodes SET watched=0 WHERE simkl_show_id IN ({show_id_list})",
                    """
                    UPDATE episodes
                    SET (watched, last_watched_at) = (
                        SELECT watched, last_watched_at
                        FROM _episodes_watched
                        WHERE _episodes_watched.simkl_show_id = episodes.simkl_show_id
                            AND _episodes_watched.season = episodes.season
                            AND _episodes_watched.episode = episodes.number
                    )
                    WHERE simkl_show_id IN ({show_ids})
                      AND EXISTS (
                        SELECT 1
                        FROM _episodes_watched
                        WHERE _episodes_watched.simkl_show_id = episodes.simkl_show_id
                            AND _episodes_watched.season = episodes.season
                            AND _episodes_watched.episode = episodes.number
                    )
                    """.format(show_ids=show_id_list),
                ]
            )

        self.update_shows_statistics({"simkl_id": show_id} for show_id in show_ids.keys())
        self.apply_show_watch_counters(entries)

    def apply_completed_show_watch_flags(self, entries):
        """Completed Simkl list entries should appear fully watched in Kodi lists."""
        for entry in entries or []:
            if not isinstance(entry, dict) or entry.get("status") != "completed":
                continue
            show_id = self._entry_show_simkl_id(entry)
            if show_id is None:
                continue
            show_id = int(show_id)

            watched = entry.get("watched_episodes_count")
            total = entry.get("total_episodes_count")
            if total is not None:
                try:
                    total_int = int(total)
                except (TypeError, ValueError):
                    total_int = 0
                if total_int > 0:
                    watched_int = int(watched) if watched is not None else total_int
                    self.execute_sql(
                        """
                        UPDATE shows
                        SET watched_episodes=MAX(watched_episodes, ?),
                            episode_count=MAX(episode_count, ?),
                            unwatched_episodes=0
                        WHERE simkl_id=?
                        """,
                        (max(watched_int, total_int), total_int, show_id),
                    )

            episode_rows = self.fetchone(
                "SELECT COUNT(*) AS episode_count FROM episodes WHERE simkl_show_id=? AND season != 0",
                (show_id,),
            )
            if episode_rows and int(episode_rows.get("episode_count") or 0) > 0:
                self.mark_show_watched(show_id, 1)

    def apply_movie_watch_flags(self, entries):
        """Align movies.watched with Simkl list status, not prior watch history alone."""
        watched_ids: list[int] = []
        unwatched_ids: list[int] = []
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            blob = entry.get("movie") or entry
            if not isinstance(blob, dict):
                continue
            simkl_id = (blob.get("ids") or {}).get("simkl")
            if simkl_id is None:
                continue
            simkl_id = int(simkl_id)
            status = entry.get("status")
            if status == "completed":
                watched_ids.append(simkl_id)
            elif status in ("plantowatch", "dropped", "hold", "watching"):
                unwatched_ids.append(simkl_id)
            elif entry.get("last_watched_at"):
                watched_ids.append(simkl_id)

        if unwatched_ids:
            placeholders = ",".join("?" * len(unwatched_ids))
            self.execute_sql(
                f"UPDATE movies SET watched=0 WHERE simkl_id IN ({placeholders})",
                tuple(unwatched_ids),
            )
        if not watched_ids:
            return

        placeholders = ",".join("?" * len(watched_ids))
        self.execute_sql(
            f"UPDATE movies SET watched=1 WHERE simkl_id IN ({placeholders})",
            tuple(watched_ids),
        )

    def apply_movie_library_status(self, entries):
        """Merge Simkl list status into movies.info for My Library menus."""
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            status = entry.get("status")
            if not status:
                continue
            blob = entry.get("movie") or entry
            if not isinstance(blob, dict):
                continue
            simkl_id = (blob.get("ids") or {}).get("simkl")
            if simkl_id is None:
                continue
            self.set_simkl_status(int(simkl_id), "movie", status)

    def set_simkl_status(self, simkl_id: int, catalog: str, status: str | None) -> None:
        """Persist Simkl list status on a movie or show row for My Library menus."""
        table = "movies" if catalog == "movie" else "shows"
        row = self.fetchone(f"SELECT info FROM {table} WHERE simkl_id=?", (int(simkl_id),))
        if not row:
            return
        info = row.get("info")
        if not isinstance(info, dict):
            info = {}
        if status:
            info["simkl_status"] = status
        else:
            info.pop("simkl_status", None)
        self.execute_sql(
            f"UPDATE {table} SET info=?, simkl_status=? WHERE simkl_id=?",
            (info, status, int(simkl_id)),
        )

    def set_user_rating(self, simkl_id: int, catalog: str, rating: int | None) -> None:
        """Persist Simkl user rating (1-10) on a movie or show row."""
        table = "movies" if catalog == "movie" else "shows"
        self.execute_sql(
            f"UPDATE {table} SET user_rating=? WHERE simkl_id=?",
            (rating, int(simkl_id)),
        )
        row = self.fetchone(f"SELECT info FROM {table} WHERE simkl_id=?", (int(simkl_id),))
        if not row:
            return
        info = row.get("info")
        if not isinstance(info, dict):
            return
        if rating is not None:
            info["user_rating"] = rating
        else:
            info.pop("user_rating", None)
        self.execute_sql(f"UPDATE {table} SET info=? WHERE simkl_id=?", (info, int(simkl_id)))

    def apply_show_library_status(self, entries):
        """Merge Simkl list status into shows.info for My Library menus."""
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            status = entry.get("status")
            if not status:
                continue
            blob = entry.get("show") or entry.get("anime") or entry
            if not isinstance(blob, dict):
                continue
            simkl_id = (blob.get("ids") or {}).get("simkl")
            if simkl_id is None:
                continue
            self.set_simkl_status(int(simkl_id), "show", status)

    def apply_library_watch_state(self, catalog: str, entries, sync_items):
        if catalog == "movie":
            self.apply_movie_watch_flags(entries)
            self.apply_movie_library_status(entries)
            return
        self.apply_show_library_status(entries)
        self.apply_watched_episodes_from_entries(entries, sync_items)
        self.apply_completed_show_watch_flags(entries)

    def update_shows_statistics(self, media_list):
        self.__update_shows_statisics(media_list)

    def _update_all_shows_statisics(self):
        self.__update_shows_statisics()

    def __update_shows_statisics(self, media_list=None):
        now = self._get_aired_cutoff()
        if media_list:
            where_restriction_clause = f"WHERE simkl_id in ({','.join(str(i.get('simkl_id')) for i in media_list)})"
        else:
            where_restriction_clause = ""
        self.execute_sql(
            f"""
            UPDATE shows
            SET (
                    air_date, is_airing,
                    season_count, episode_count, watched_episodes, unwatched_episodes,
                    last_watched_at, last_collected_at
                    ) = (SELECT coalesce(CASE
                                             WHEN min(coalesce(e.air_date, datetime('9999-12-31T00:00:00'))
                                                      ) <> datetime('9999-12-31T00:00:00')
                                                 THEN min(e.air_date)
                                             END,
                                         s.air_date)               AS air_date,
                                coalesce(CASE
                                             WHEN max(e.simkl_id) IS NOT NULL
                                                 THEN CASE
                                                          WHEN e.season > 0 AND max(e.air_date) > datetime('{now}')
                                                              THEN 1
                                                          ELSE 0
                                                 END
                                             END, s.is_airing)     AS is_airing,
                                coalesce(CASE
                                             WHEN count(DISTINCT CASE
                                                                     WHEN e.season > 0
                                                                         AND Datetime(e.air_date) < Datetime('{now}')
                                                                         THEN season END) > 0
                                                 THEN count(DISTINCT CASE
                                                                         WHEN e.season > 0
                                                                             AND Datetime(e.air_date) < Datetime('{now}')
                                                                             THEN season END)
                                             END, s.season_count)  AS season_count,
                                coalesce(CASE
                                             WHEN max(e.simkl_id) IS NOT NULL
                                                 THEN sum(
                                                     CASE
                                                         WHEN e.season > 0
                                                             AND datetime(e.air_date) < datetime('{now}')
                                                             THEN 1
                                                         ELSE 0
                                                         END
                                                 )
                                             END, s.episode_count) AS episode_count,
                                coalesce(CASE
                                             WHEN max(e.simkl_id) IS NOT NULL
                                                 THEN sum(
                                                     CASE
                                                         WHEN e.season > 0 AND e.watched > 0
                                                             AND (e.air_date IS NULL OR datetime(e.air_date) < datetime('{now}'))
                                                             THEN 1
                                                         ELSE 0
                                                         END
                                                 )
                                             END,
                                         s.watched_episodes)       AS watched_episodes,
                                coalesce(CASE
                                             WHEN sum(CASE
                                                          WHEN e.season > 0
                                                              AND Datetime(e.air_date) < Datetime('{now}')
                                                              THEN 1 END) > s.episode_count
                                                 THEN sum(CASE
                                                              WHEN e.season > 0
                                                                  AND Datetime(e.air_date) < Datetime('{now}')
                                                                  THEN 1 END)
                                             ELSE s.episode_count
                                             END - sum(CASE
                                                           WHEN e.season > 0 AND e.watched > 0
                                                               AND (e.air_date IS NULL OR Datetime(e.air_date) < Datetime('{now}'))
                                                               THEN 1
                                                           ELSE 0
                                    END), s.unwatched_episodes)    AS unwatched_episodes,
                                CASE
                                    WHEN max(e.simkl_id) IS NOT NULL
                                        THEN max(e.last_watched_at)
                                    ELSE s.last_watched_at
                                    END                            AS last_watched_at,
                                CASE
                                    WHEN max(e.simkl_id) IS NOT NULL
                                        THEN max(e.collected_at)
                                    ELSE s.last_collected_at
                                    END                            AS last_collected_at
                         FROM shows AS s
                                  LEFT JOIN episodes AS e
                                            ON e.simkl_show_id = s.simkl_id
                         WHERE s.simkl_id = shows.simkl_id
                         GROUP BY e.simkl_show_id)
            {where_restriction_clause}
            """
        )

    def update_season_statistics(self, media_list):
        self.__update_season_statistics(media_list)

    def _update_all_season_statistics(self):
        self.__update_season_statistics()

    def __update_season_statistics(self, media_list=None):
        now = self._get_aired_cutoff()
        if media_list:
            where_restriction_clause = f"AND simkl_id in ({','.join(str(i.get('simkl_id')) for i in media_list)})"
        else:
            where_restriction_clause = ""
        self.execute_sql(
            f"""
            UPDATE seasons
            SET (
                    air_date, is_airing,
                    episode_count, watched_episodes, unwatched_episodes,
                    last_watched_at, last_collected_at
                    ) = (SELECT coalesce(
                                        CASE
                                            WHEN min(coalesce(e.air_date, datetime('9999-12-31T00:00:00'))
                                                     ) <> datetime('9999-12-31T00:00:00')
                                                THEN min(e.air_date)
                                            END,
                                        seasons.air_date
                                    )   as air_date,
                                CASE
                                    WHEN coalesce(
                                            CASE
                                                WHEN max(e.simkl_id) IS NOT NULL
                                                    THEN CASE
                                                             WHEN max(e.air_date) > datetime('{now}')
                                                                 THEN 1
                                                             ELSE 0
                                                    END
                                                END,
                                            seasons.is_airing
                                        )
                                        THEN coalesce(
                                            CASE
                                                WHEN max(e.simkl_id) IS NOT NULL
                                                    THEN CASE
                                                             WHEN max(e.air_date) > datetime('{now}')
                                                                 THEN 1
                                                             ELSE 0
                                                    END
                                                END,
                                            seasons.is_airing
                                        )
                                    ELSE 0
                                    END as is_airing,
                                CASE
                                    WHEN coalesce(
                                            CASE
                                                WHEN max(e.simkl_id) is not null
                                                    THEN sum(
                                                        CASE
                                                            WHEN datetime(e.air_date) < datetime('{now}')
                                                                THEN 1
                                                            ELSE 0
                                                            END
                                                    )
                                                END,
                                            seasons.episode_count
                                        ) IS NOT NULL
                                        THEN coalesce(
                                            CASE
                                                WHEN max(e.simkl_id) is not null
                                                    THEN sum(
                                                        CASE
                                                            WHEN datetime(e.air_date) < datetime('{now}')
                                                                THEN 1
                                                            ELSE 0
                                                            END
                                                    )
                                                END,
                                            seasons.episode_count
                                        )
                                    ELSE 0
                                    END AS episode_count,
                                CASE
                                    WHEN coalesce(
                                            CASE
                                                WHEN max(e.simkl_id) IS NOT NULL
                                                    THEN sum(
                                                        CASE
                                                            WHEN e.watched > 0
                                                                    AND datetime(e.air_date) < datetime('{now}')
                                                                THEN 1
                                                            ELSE 0
                                                            END
                                                    )
                                                END,
                                            seasons.watched_episodes
                                        ) IS NOT NULL
                                        THEN coalesce(
                                            CASE
                                                WHEN max(e.simkl_id) IS NOT NULL
                                                    THEN sum(
                                                        CASE
                                                            WHEN e.watched > 0
                                                                    AND datetime(e.air_date) < datetime('{now}')
                                                                THEN 1
                                                            ELSE 0
                                                            END
                                                    )
                                                END,
                                            seasons.watched_episodes
                                        )
                                    ELSE 0
                                    END AS watched_episodes,
                                CASE
                                    WHEN coalesce(
                                            CASE
                                                WHEN max(e.simkl_id) IS NOT NULL
                                                    THEN sum(
                                                        CASE
                                                            WHEN e.watched == 0
                                                                    AND datetime(e.air_date) < datetime('{now}')
                                                                THEN 1
                                                            ELSE 0
                                                            END
                                                    )
                                                END,
                                            seasons.unwatched_episodes
                                        ) IS NOT NULL
                                        THEN coalesce(
                                            CASE
                                                WHEN max(e.simkl_id) IS NOT NULL
                                                    THEN sum(
                                                        CASE
                                                            WHEN e.watched == 0
                                                                    AND datetime(e.air_date) < datetime('{now}')
                                                                THEN 1
                                                            ELSE 0
                                                            END
                                                    )
                                                END,
                                            seasons.unwatched_episodes
                                        )
                                    ELSE 0
                                    END AS unwatched_episodes,
                                CASE
                                    WHEN max(e.simkl_id) IS NOT NULL
                                        THEN max(e.last_watched_at)
                                    ELSE seasons.last_watched_at
                                    END AS last_watched_at,
                                CASE
                                    WHEN max(e.simkl_id) IS NOT NULL
                                        THEN max(e.collected_at)
                                    ELSE seasons.last_collected_at
                                    END AS last_collected_at
                         FROM episodes AS e
                         WHERE e.simkl_season_id = seasons.simkl_id
                         GROUP BY e.simkl_season_id)
            WHERE EXISTS(SELECT simkl_season_id FROM episodes AS ep WHERE ep.simkl_season_id = seasons.simkl_id)
            {where_restriction_clause}
            """
        )

    def clean_orphaned_metadata(self):
        media_meta_types = {
            "movies": ["simkl", "tmdb", "tvdb", "imdb", "fanart"],
            "episodes": ["simkl", "tmdb", "tvdb", "imdb", "fanart"],
            "seasons": ["simkl", "tmdb", "tvdb", "fanart"],
            "shows": ["simkl", "tmdb", "tvdb", "imdb", "fanart"],
        }
        for media_type in media_meta_types:
            for meta_type in media_meta_types[media_type]:
                if meta_type == "fanart":
                    self.execute_sql(self._clean_orphaned_fanart_metadata_query(media_type))
                else:
                    self.execute_sql(self._clean_orphaned_metadata_query(media_type, meta_type))

    def _clean_orphaned_metadata_query(self, media_type, meta_type):
        return f'''
            DELETE
            FROM {media_type}_meta
            WHERE type = '{meta_type}'
              AND id IN (SELECT id
                         FROM {media_type}_meta AS meta
                LEFT JOIN {media_type} AS media
                         ON media.{meta_type}_id = meta.id
                         WHERE meta.type = '{meta_type}'
                           AND media.{meta_type}_id IS NULL)
        '''

    def _clean_orphaned_fanart_metadata_query(self, media_type):
        if media_type == "movies":
            return f'''
                DELETE
                FROM {media_type}_meta
                WHERE type = 'fanart'
                  AND id IN (SELECT id
                             FROM {media_type}_meta AS meta
                                      LEFT JOIN {media_type} AS media ON media.imdb_id = meta.id OR media.tmdb_id = meta.id
                             WHERE meta.type = 'fanart'
                               AND media.imdb_id IS NULL
                               AND media.tmdb_id IS NULL)
            '''

        return f'''
            DELETE
            FROM {media_type}_meta
            WHERE type = 'fanart'
              AND id IN (SELECT id
                         FROM {media_type}_meta AS meta
                                  LEFT JOIN {media_type} AS media ON media.tvdb_id = meta.id
                         WHERE meta.type = 'fanart'
                           AND media.tvdb_id IS NULL)
        '''

    @property
    def upsert_movie_query(self):
        return """
                WITH new(simkl_id, info, art, cast, collected, watched, air_date,
                         last_updated, tmdb_id, tvdb_id, imdb_id, meta_hash, args,
                         collected_at, last_watched_at, user_rating, simkl_status,
                         needs_update
                    ) AS (values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE))
                INSERT
                INTO movies(simkl_id, info, art, cast, collected, watched, air_date,
                            last_updated, tmdb_id, tvdb_id, imdb_id, meta_hash, args,
                            collected_at, last_watched_at, user_rating, simkl_status,
                            needs_update)
                SELECT simkl_id,
                       info,
                       art,
                       [cast],
                       coalesce(collected, 0),
                       coalesce(watched, 0),
                       air_date,
                       coalesce(last_updated, '1970-01-01T00:00:00'),
                       tmdb_id,
                       tvdb_id,
                       imdb_id,
                       meta_hash,
                       coalesce(args, FALSE),
                       collected_at,
                       last_watched_at,
                       user_rating,
                       simkl_status,
                       needs_update
                FROM new
                WHERE TRUE
                ON CONFLICT(simkl_id) DO UPDATE
                    SET (info, art, cast, collected, watched, air_date,
                            last_updated, tmdb_id, tvdb_id, imdb_id, meta_hash,
                            args, collected_at, last_watched_at, user_rating, simkl_status,
                            needs_update) = (SELECT coalesce(new.info, old.info),
                                                    coalesce(new.art, old.art),
                                                    coalesce(new.cast, old.cast),
                                                    coalesce(new.collected, old.collected),
                                                    coalesce(new.watched, old.watched),
                                                    coalesce(new.air_date, old.air_date),
                                                    coalesce(new.last_updated, old.last_updated),
                                                    coalesce(new.tmdb_id, old.tmdb_id),
                                                    coalesce(new.tvdb_id, old.tvdb_id),
                                                    coalesce(new.imdb_id, old.imdb_id),
                                                    coalesce(new.meta_hash, old.meta_hash),
                                                    coalesce(new.args, old.args),
                                                    coalesce(new.collected_at, old.collected_at),
                                                    coalesce(new.last_watched_at, old.last_watched_at),
                                                    coalesce(new.user_rating, old.user_rating),
                                                    coalesce(new.simkl_status, old.simkl_status),
                                                    CASE
                                                        WHEN old.needs_update
                                                            THEN CASE
                                                                     WHEN new.info <> old.info
                                                                         OR new.art <> old.art
                                                                         OR new.cast <> old.cast
                                                                         THEN TRUE
                                                                     ELSE old.needs_update END
                                                        ELSE CASE
                                                                 WHEN Datetime(coalesce(old.last_updated, 0))
                                                                     < Datetime(new.last_updated)
                                                                     THEN TRUE
                                                                 ELSE FALSE END
                                                        END AS needs_update
                                             FROM new
                                                      LEFT JOIN movies AS old
                                                                ON old.simkl_id = new.simkl_id)
                """

    @property
    def upsert_show_query(self):
        return """
            WITH new(simkl_id, info, art, cast, air_date, last_updated,
                     tmdb_id, tvdb_id, imdb_id, meta_hash,
                     season_count, episode_count,
                     args, is_airing,
                     last_watched_at, last_collected_at, user_rating, simkl_status,
                     needs_update, needs_milling)
                     AS (VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, TRUE))
            INSERT
            INTO shows(simkl_id, info, art, cast, air_date, last_updated,
                       tmdb_id, tvdb_id, imdb_id, meta_hash,
                       season_count, episode_count,
                       args, is_airing,
                       last_watched_at, last_collected_at, user_rating, simkl_status,
                       needs_update, needs_milling)
            SELECT simkl_id,
                   info,
                   art,
                   [cast],
                   air_date,
                   coalesce(last_updated, '1970-01-01T00:00:00'),
                   tmdb_id,
                   tvdb_id,
                   imdb_id,
                   meta_hash,
                   coalesce(season_count, 0),
                   coalesce(episode_count, 0),
                   coalesce(args, FALSE),
                   is_airing,
                   last_watched_at,
                   last_collected_at,
                   user_rating,
                   simkl_status,
                   needs_update,
                   needs_milling
            FROM new
            WHERE TRUE
            ON CONFLICT(simkl_id) DO UPDATE
                SET (info, art, cast, air_date, last_updated,
                        tmdb_id, tvdb_id, imdb_id, meta_hash,
                        season_count, episode_count, watched_episodes, unwatched_episodes,
                        args, is_airing,
                        last_watched_at, last_collected_at, user_rating, simkl_status,
                        needs_update,
                        needs_milling) = (SELECT coalesce(new.info, old.info),
                                                 coalesce(new.art, old.art),
                                                 coalesce(new.cast, old.cast),
                                                 coalesce(new.air_date, old.air_date),
                                                 coalesce(new.last_updated, old.last_updated),
                                                 coalesce(new.tmdb_id, old.tmdb_id),
                                                 coalesce(new.tvdb_id, old.tvdb_id),
                                                 coalesce(new.imdb_id, old.imdb_id),
                                                 coalesce(new.meta_hash, old.meta_hash),
                                                 coalesce(new.season_count, old.season_count),
                                                 coalesce(new.episode_count, old.episode_count),
                                                 coalesce(old.watched_episodes, 0),
                                                 coalesce(old.unwatched_episodes, 0),
                                                 coalesce(new.args, old.args),
                                                 coalesce(new.is_airing, old.is_airing),
                                                 coalesce(new.last_watched_at, old.last_watched_at),
                                                 coalesce(new.last_collected_at, old.last_collected_at),
                                                 coalesce(new.user_rating, old.user_rating),
                                                 coalesce(new.simkl_status, old.simkl_status),
                                                 CASE
                                                     WHEN old.needs_update
                                                         THEN CASE
                                                                  WHEN new.info <> old.info
                                                                      OR new.art <> old.art
                                                                      OR new.cast <> old.cast
                                                                      THEN FALSE
                                                                  ELSE old.needs_update END
                                                     ELSE CASE
                                                              WHEN Datetime(coalesce(old.last_updated, 0))
                                                                  < Datetime(new.last_updated)
                                                                  THEN TRUE
                                                              ELSE FALSE END
                                                     END AS needs_update,
                                                 CASE
                                                     WHEN old.needs_milling THEN old.needs_milling
                                                     ELSE CASE
                                                              WHEN Datetime(coalesce(old.last_updated, 0))
                                                                  < Datetime(new.last_updated)
                                                                  THEN TRUE
                                                              ELSE FALSE END
                                                     END AS needs_milling
                                          FROM new
                                                   LEFT JOIN shows AS old
                                                             on old.simkl_id = new.simkl_id)
            """

    @property
    def upsert_season_query(self):
        return """
            WITH new(simkl_show_id, simkl_id, info, art, cast,
                     air_date, last_updated,
                     tmdb_id, tvdb_id, meta_hash, episode_count,
                     season, args,
                     last_watched_at, last_collected_at, user_rating,
                     needs_update) AS (VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE))
            INSERT
            INTO seasons(simkl_show_id, simkl_id, info, art, cast,
                         air_date, last_updated,
                         tmdb_id, tvdb_id, meta_hash, episode_count,
                         season, args,
                         last_watched_at, last_collected_at, user_rating,
                         needs_update)
            SELECT simkl_show_id,
                   simkl_id,
                   info,
                   art,
                   [cast],
                   air_date,
                   coalesce(last_updated, '1970-01-01T00:00:00'),
                   tmdb_id,
                   tvdb_id,
                   meta_hash,
                   coalesce(episode_count, 0),
                   season,
                   coalesce(args, FALSE),
                   last_watched_at,
                   last_collected_at,
                   user_rating,
                   needs_update
            FROM new
            WHERE TRUE
            ON CONFLICT(simkl_show_id, season) DO UPDATE
                SET (simkl_id, info, art, cast,
                        air_date, last_updated,
                        tmdb_id, tvdb_id, meta_hash, episode_count,
                        args,
                        last_watched_at, last_collected_at, user_rating,
                        needs_update) = (SELECT new.simkl_id,
                                                coalesce(new.info, old.info),
                                                coalesce(new.art, old.art),
                                                coalesce(new.cast, old.cast),
                                                coalesce(new.air_date, old.air_date),
                                                coalesce(new.last_updated, old.last_updated),
                                                coalesce(new.tmdb_id, old.tmdb_id),
                                                coalesce(new.tvdb_id, old.tvdb_id),
                                                coalesce(new.meta_hash, old.meta_hash),
                                                coalesce(new.episode_count, old.episode_count),
                                                coalesce(new.args, old.args),
                                                coalesce(new.last_watched_at, old.last_watched_at),
                                                coalesce(new.last_collected_at, old.last_collected_at),
                                                coalesce(new.user_rating, old.user_rating),
                                                CASE
                                                    WHEN old.needs_update
                                                        THEN CASE
                                                                 WHEN new.info != old.info
                                                                     OR new.art != old.art
                                                                     OR new.cast != old.cast
                                                                     THEN FALSE
                                                                 ELSE old.needs_update END
                                                    ELSE CASE
                                                             WHEN Datetime(coalesce(old.last_updated, 0))
                                                                 < Datetime(new.last_updated)
                                                                 THEN TRUE
                                                             ELSE FALSE END
                                                    END AS needs_update
                                         FROM new
                                                  LEFT JOIN seasons AS old
                                                            ON old.simkl_show_id = new.simkl_show_id
                                                                AND old.season = new.season)
            """

    @property
    def upsert_episode_query(self):
        return """
            WITH new(simkl_id, simkl_show_id, simkl_season_id,
                     watched, collected,
                     air_date, last_updated,
                     season, number,
                     tmdb_id, tvdb_id, imdb_id,
                     info, art, cast,
                     args, last_watched_at, collected_at,
                     user_rating, meta_hash,
                     needs_update) AS (VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE))
            INSERT
            INTO episodes(simkl_id, simkl_show_id, simkl_season_id,
                          watched, collected,
                          air_date, last_updated,
                          season, number,
                          tmdb_id, tvdb_id, imdb_id,
                          info, art, cast,
                          args, last_watched_at, collected_at,
                          user_rating, meta_hash, needs_update)
            SELECT simkl_id,
                   simkl_show_id,
                   simkl_season_id,
                   coalesce(watched, 0),
                   coalesce(collected, 0),
                   air_date,
                   coalesce(last_updated, '1970-01-01T00:00:00'),
                   season,
                   number,
                   tmdb_id,
                   tvdb_id,
                   imdb_id,
                   info,
                   art,
                   [cast],
                   coalesce(args, FALSE),
                   last_watched_at,
                   collected_at,
                   user_rating,
                   meta_hash,
                   needs_update
            FROM new
            WHERE TRUE
            ON CONFLICT(simkl_show_id, season, number) DO UPDATE
                SET (simkl_id, simkl_season_id,
                        watched, collected,
                        air_date, last_updated,
                        tmdb_id, tvdb_id, imdb_id,
                        info, art, cast,
                        args, last_watched_at, collected_at,
                        user_rating, meta_hash,
                        needs_update) = (SELECT new.simkl_id,
                                                coalesce(new.simkl_season_id, old.simkl_season_id),
                                                coalesce(new.watched, old.watched),
                                                coalesce(new.collected, old.collected),
                                                coalesce(new.air_date, old.air_date),
                                                coalesce(new.last_updated, old.last_updated),
                                                coalesce(new.tmdb_id, old.tmdb_id),
                                                coalesce(new.tvdb_id, old.tvdb_id),
                                                coalesce(new.imdb_id, old.imdb_id),
                                                coalesce(new.info, old.info),
                                                coalesce(new.art, old.art),
                                                coalesce(new.cast, old.cast),
                                                coalesce(new.args, old.args),
                                                coalesce(new.last_watched_at, old.last_watched_at),
                                                coalesce(new.collected_at, old.collected_at),
                                                coalesce(new.user_rating, old.user_rating),
                                                coalesce(new.meta_hash, old.meta_hash),
                                                CASE
                                                    WHEN old.needs_update
                                                        THEN CASE
                                                                 WHEN new.info <> old.info
                                                                     OR new.art <> old.art
                                                                     OR new.cast <> old.cast
                                                                     THEN FALSE
                                                                 ELSE old.needs_update END
                                                    ELSE CASE
                                                             WHEN
                                                                     Datetime(coalesce(old.last_updated, 0))
                                                                     < Datetime(new.last_updated)
                                                                 THEN TRUE
                                                             ELSE FALSE END
                                                    END AS needs_update
                                         FROM new
                                                  LEFT JOIN episodes AS old
                                                            ON old.simkl_show_id = new.simkl_show_id
                                                                AND old.season = new.season
                                                                AND old.number = new.number)
            """

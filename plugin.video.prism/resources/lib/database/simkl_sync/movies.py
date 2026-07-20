from __future__ import annotations

from resources.lib.database.simkl_sync import database
from resources.lib.modules.globals import g
from resources.lib.modules.guard_decorators import guard_against_none
from resources.lib.modules.guard_decorators import guard_against_none_or_empty
from resources.lib.modules.metadataHandler import MetadataHandler


class SimklSyncDatabase(database.SimklSyncDatabase):
    def extract_browse_page(self, url, **params):
        return super()._extract_browse_page(url, "movies", **params)

    @guard_against_none(list)
    def get_movie_list(self, media_list, **params):
        skip_update = params.pop("skip_update", False)
        if not skip_update:
            self._update_movies(media_list)

        from resources.lib.database.sync_meta_cache import SyncMetaCache
        from resources.lib.modules.meta_enrichment_queue import meta_enrichment_background

        meta_cache = SyncMetaCache()

        query = f"""
            SELECT m.simkl_id,
                   m.info,
                   m.art,
                   m.[cast],
                   m.args,
                   m.last_updated,
                   m.tmdb_id,
                   m.tvdb_id,
                   m.imdb_id,
                   b.resume_time,
                   b.percent_played,
                   m.watched AS play_count,
                   m.user_rating
            FROM movies AS m
                     LEFT JOIN bookmarks AS b
                               ON m.simkl_id = b.simkl_id
            WHERE m.simkl_id IN ({','.join(str(i.get('simkl_id')) for i in media_list)})
            """

        if params.pop("hide_unaired", self.hide_unaired):
            query += (
                f" AND (m.air_date IS NULL OR Datetime(m.air_date) < Datetime('{self._get_aired_cutoff()}'))"
            )
        if params.pop("hide_watched", self.hide_watched):
            query += " AND watched = 0"

        rows = self.fetchall(query)
        meta_cache.set_many_rows("movie", rows or [])

        if skip_update:
            from resources.lib.modules.meta_enrichment_queue import (
                hybrid_apply_list_meta,
                hybrid_foreground_first_page,
                hybrid_widget_local_meta,
            )

            if hybrid_widget_local_meta():
                rows, enrichment_refs = self.metadataHandler.merge_list_meta_local(rows, "movie", db=self)
                from resources.lib.simkl.enrich import gapfill_anime_title_rows

                rows = gapfill_anime_title_rows(rows)
                self.set_list_enrichment_refs(enrichment_refs, "movie")
            elif hybrid_foreground_first_page():
                rows = self.metadataHandler.gapfill_list_meta(rows, "movie", db=self, persist=True)
                from resources.lib.simkl.enrich import gapfill_anime_title_rows

                rows = gapfill_anime_title_rows(rows)
                self.set_list_enrichment_refs([], "movie")
            else:
                rows = hybrid_apply_list_meta(rows, "movie", self)
        else:
            self.set_list_enrichment_refs([], "movie")
        return MetadataHandler.sort_list_items(rows, media_list)

    @guard_against_none(list)
    def get_collected_movies(self, page):
        paginate = True

        query = """
            SELECT m.simkl_id, meta.value AS simkl_object
            FROM movies AS m
                     LEFT JOIN movies_meta AS meta
                               ON m.simkl_id = meta.id
            WHERE collected = TRUE
            """

        if paginate:
            query += f"ORDER BY collected_at desc LIMIT {self.page_limit} OFFSET {self.page_limit * (page - 1)}"

        return self.fetchall(query)

    @guard_against_none(list)
    def get_watched_movies(self, page):
        return self.fetchall(
            f"""
            SELECT m.simkl_id, meta.value AS simkl_object
            FROM movies AS m
                     LEFT JOIN movies_meta AS meta
                               ON m.simkl_id = meta.id
            WHERE watched = 1
            ORDER BY last_watched_at DESC
            LIMIT {self.page_limit} OFFSET {self.page_limit * (page - 1)}
            """
        )

    @guard_against_none(list)
    def get_movies_by_simkl_status(self, status: str) -> list[dict]:
        rows = self.fetchall(
            "SELECT simkl_id FROM movies WHERE simkl_status = ?",
            (status,),
        )
        if not rows:
            rows = self.fetchall("SELECT simkl_id, info FROM movies")
            rows = [
                {"simkl_id": row["simkl_id"]}
                for row in rows
                if isinstance(row.get("info"), dict) and row["info"].get("simkl_status") == status
            ]
        refs = [{"simkl_id": row["simkl_id"]} for row in rows]
        if not refs:
            return refs
        from resources.lib.simkl.library_sort import sort_library_refs

        return sort_library_refs(refs, "movie")

    def get_all_collected_movies(self):
        return self.fetchall(
            """
            SELECT m.simkl_id, meta.value AS simkl_object
            FROM movies AS m
                     LEFT JOIN movies_meta AS meta
                         ON m.simkl_id = meta.id
            WHERE collected = TRUE
            """
        )

    @guard_against_none()
    def mark_movie_watched(self, simkl_id):
        play_count = self.fetchone("SELECT watched FROM movies WHERE simkl_id=?", (simkl_id,))["watched"]
        self._mark_movie_record("watched", play_count + 1, simkl_id)

    @guard_against_none()
    def mark_movie_unwatched(self, simkl_id):
        self._mark_movie_record("watched", 0, simkl_id)

    @guard_against_none()
    def mark_movie_collected(self, simkl_id):
        self._mark_movie_record("collected", 1, simkl_id)

    @guard_against_none()
    def mark_movie_uncollected(self, simkl_id):
        self._mark_movie_record("collected", 0, simkl_id)

    @guard_against_none()
    def _mark_movie_record(self, column, value, simkl_id):
        if column == "watched":
            datetime_column = "last_watched_at"
        elif column == "collected":
            datetime_column = "collected_at"
        else:
            datetime_column = None
        if datetime_column is None:
            # Just in case we forgot any methods that call this
            raise TypeError("NoneType Error: Date Time Column")
        self.execute_sql(
            f"UPDATE movies SET {column}=?, {datetime_column}=? WHERE simkl_id=?",
            (value, self._get_datetime_now() if value > 0 else None, simkl_id),
        )

    def _fetch_movie_summary(self, simkl_id):
        from resources.lib.simkl.ids import movie_api_path

        return self.simkl_api.get_json_cached(
            movie_api_path(int(simkl_id)),
            authorized=False,
            client_id=self.simkl_api.client_id,
        )

    @guard_against_none(list)
    def get_movie(self, simkl_id):
        return self.get_movie_list([self._get_single_movie_meta(simkl_id)], hide_unaired=False, hide_watched=False)[0]

    @guard_against_none()
    def _get_single_movie_meta(self, simkl_id):
        return self._get_single_meta(simkl_id, "movies")

    @guard_against_none_or_empty()
    def _update_movies(self, list_to_update):
        get = MetadataHandler.get_simkl_info

        sql_statement = f"""
            WITH requested(simkl_id, last_updated) AS (VALUES
                    {','.join(f"({i.get('simkl_id')},'{get(i, 'dateadded')}')" for i in list_to_update)})
            SELECT r.simkl_id,
                   simkl_meta.value      AS simkl_object,
                   simkl_meta.meta_hash  AS simkl_meta_hash,
                   tmdb_id,
                   tmdb.value       AS tmdb_object,
                   tmdb.meta_hash   AS tmdb_meta_hash,
                   tvdb_id,
                   tvdb.value       AS tvdb_object,
                   tvdb.meta_hash   AS tvdb_meta_hash,
                   fanart.value     AS fanart_object,
                   fanart.meta_hash AS fanart_meta_hash,
                   m.needs_update
            FROM requested as r
                     LEFT JOIN movies AS m
                               ON r.simkl_id = m.simkl_id
                     LEFT JOIN movies_meta AS simkl_meta
                               ON simkl_meta.id = m.simkl_id AND simkl_meta.type = 'simkl'
                     LEFT JOIN movies_meta AS tmdb
                               ON tmdb.id = m.tmdb_id AND tmdb.type = 'tmdb'
                     LEFT JOIN movies_meta AS tvdb
                               ON tvdb.id = m.tvdb_id AND tvdb.type = 'tvdb'
                     LEFT JOIN movies_meta AS fanart
                               ON fanart.id = m.tmdb_id AND fanart.type = 'fanart'
            """

        db_list_to_update = self.fetchall(sql_statement)
        self._apply_request_force_update(db_list_to_update, list_to_update)

        for movie in db_list_to_update:
            movie["_entity"] = "movie"
            self.task_queue.put(self.metadataHandler.update, movie)
        updated_items = self.task_queue.wait_completion()

        if not updated_items:
            return

        self.task_queue.put(
            self.save_to_meta_table,
            (i for i in updated_items if "tmdb_object" in i),
            "movies",
            "tmdb",
            "tmdb_id",
        )
        self.task_queue.put(
            self.save_to_meta_table,
            (i for i in updated_items if "tvdb_object" in i),
            "movies",
            "tvdb",
            "tvdb_id",
        )
        self.task_queue.put(
            self.save_to_meta_table,
            (i for i in updated_items if "fanart_object" in i),
            "movies",
            "fanart",
            "tmdb_id",
        )
        self.task_queue.wait_completion()

        formatted_items = self.metadataHandler.format_db_object(updated_items)

        self.execute_sql(
            self.upsert_movie_query,
            [
                (
                    i["info"]["simkl_id"],
                    i["info"],
                    i.get("art"),
                    i.get("cast"),
                    None,
                    None,
                    i["info"].get("aired"),
                    i["info"].get("dateadded"),
                    i["info"].get("tmdb_id"),
                    i["info"].get("tvdb_id"),
                    i["info"].get("imdb_id"),
                    self.metadataHandler.meta_hash,
                    self._create_args(i),
                    None,
                    None,
                    None,
                    self.get_library_status(i["info"]["simkl_id"], "movie", i["info"]),
                )
                for i in formatted_items
            ],
        )

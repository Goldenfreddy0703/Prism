from __future__ import annotations

from resources.lib.common.thread_pool import ThreadPool
from resources.lib.database.simkl_sync import database
from resources.lib.modules.globals import g
from resources.lib.modules.guard_decorators import guard_against_none
from resources.lib.modules.guard_decorators import guard_against_none_or_empty
from resources.lib.modules.metadataHandler import MetadataHandler


class SimklSyncDatabase(database.SimklSyncDatabase):
    """
    Handles database records for show/season/episode items

    """

    def show_catalog(self, simkl_show_id: int) -> str:
        """Return ``tv`` or ``anime`` for a synced show row."""
        return self._infer_show_catalog(int(simkl_show_id)) or "tv"

    def _filter_show_rows_by_catalog(self, rows, catalog: str | None):
        if not catalog:
            return rows
        return [row for row in rows if self.show_catalog(row.get("simkl_id")) == catalog]

    def _filter_episode_rows_by_catalog(self, rows, catalog: str | None):
        if not catalog:
            return rows
        return [row for row in rows if self.show_catalog(row.get("simkl_show_id")) == catalog]

    @guard_against_none(list)
    def get_shows_by_simkl_status(self, status: str, catalog: str | None = None) -> list[dict]:
        rows = self.fetchall(
            "SELECT simkl_id FROM shows WHERE simkl_status = ?",
            (status,),
        )
        if not rows:
            all_rows = self.fetchall("SELECT simkl_id, info FROM shows")
            rows = [
                {"simkl_id": row["simkl_id"]}
                for row in all_rows
                if isinstance(row.get("info"), dict) and row["info"].get("simkl_status") == status
            ]
        refs = []
        for row in rows:
            simkl_id = row.get("simkl_id")
            if catalog and self.show_catalog(simkl_id) != catalog:
                continue
            refs.append({"simkl_id": simkl_id})
        if not refs:
            return refs
        from resources.lib.simkl.library_sort import sort_library_refs

        return sort_library_refs(refs, catalog or "tv")

    def extract_browse_page(self, url, **params):
        """
        Extracts items from page
        :param url: URL endpoint to extract
        :type url: string
        :param params: Kwargs to pass to super call
        :type params: any
        :return: List of items from page
        :rtype: list
        """
        return super()._extract_browse_page(url, "shows", **params)

    @guard_against_none()
    def _update_shows_statistics_from_show_id(self, simkl_show_id):
        self.update_shows_statistics([{"simkl_id": simkl_show_id}])
        self.update_season_statistics(
            self.fetchall("select simkl_id from seasons where simkl_show_id=?", (simkl_show_id,))
        )

    @guard_against_none()
    def mark_show_watched(self, show_id, watched):
        """
        Mark watched status for all items of a show except specials
        :param show_id: Simkl ID of the show to update
        :type show_id: int
        :param watched: 1 for watched 0 for unwatched
        :type watched: int
        :return: None
        :rtype: None
        """
        g.log(f"Marking show {show_id} as watched in sync database", "debug")
        self._mill_if_needed([{"simkl_id": show_id}])
        self.execute_sql(
            "UPDATE episodes SET watched=?, last_watched_at=? WHERE simkl_show_id = ? AND season != 0",
            (watched, self._get_datetime_now() if watched > 0 else None, show_id),
        )
        self._update_shows_statistics_from_show_id(show_id)

    @guard_against_none()
    def mark_season_watched(self, show_id, season, watched):
        """
         Mark watched status for all items of a season
        :param show_id: Simkl ID of the show to update
        :type show_id: int
        :param season: Season number to mark
        :type season: int
        :param watched: 1 for watched 0 for unwatched
        :type watched: int
        :return: None
        :rtype: None
        """
        g.log(f"Marking season {season} as watched in sync database", "debug")
        self.execute_sql(
            "UPDATE episodes SET watched=?, last_watched_at=?" " WHERE simkl_show_id=? AND season=?",
            (
                watched,
                self._get_datetime_now() if watched > 0 else None,
                show_id,
                season,
            ),
        )
        self._update_shows_statistics_from_show_id(show_id)

    @guard_against_none()
    def mark_show_collected(self, show_id, collected):
        """
        Sets collected status for all items of a given show
        :param show_id: ID of show to update
        :type show_id: int
        :param collected: Status of collection (1=True, 0=False)
        :type collected: int
        :return: None
        :rtype: None
        """
        g.log(f"Marking show {show_id} as collected in sync database", "debug")
        self._mill_if_needed([{"simkl_id": show_id}])
        self.execute_sql(
            "UPDATE episodes SET collected=?, collected_at=? WHERE simkl_show_id=?",
            (collected, self._get_datetime_now() if collected > 0 else None, show_id),
        )

    @guard_against_none()
    def mark_episode_watched(self, show_id, season, number):
        """
        Mark an individual episode item as watched
        :param show_id: ID of show to update
        :type show_id: int
        :param season: Season number of episode
        :type season: int
        :param number: Episode number to update
        :type number: int
        :return: None
        :rtype: None
        """
        g.log(
            f"Marking episode {show_id} S{season}E{number} as watched in sync database",
            "debug",
        )
        play_count = self.fetchone(
            "SELECT watched from episodes " "where simkl_show_id=? and season=? and number=?",
            (show_id, season, number),
        ).get("watched")
        if play_count is None:
            return
        self._mark_episode_record("watched", play_count + 1, show_id, season, number)
        self._update_shows_statistics_from_show_id(show_id)

    @guard_against_none()
    def mark_episode_unwatched(self, show_id, season, number):
        """
        Mark an individual episode item as unwatched
        :param show_id: ID of show to update
        :type show_id: int
        :param season: Season number of episode
        :type season: int
        :param number: Episode number to update
        :type number: int
        :return: None
        :rtype: None
        """
        g.log(
            f"Marking episode {show_id} S{season}E{number} as unwatched in sync database",
            "debug",
        )

        self._mark_episode_record("watched", 0, show_id, season, number)
        self._update_shows_statistics_from_show_id(show_id)

    @guard_against_none()
    def _mark_show_record(self, column, value, show_id):
        self.execute_sql(f"UPDATE shows SET {column}=? WHERE simkl_id=?", (value, show_id))

    @guard_against_none()
    def _mark_episode_record(self, column, value, show_id, season, number):
        if column == "watched":
            datetime_column = "last_watched_at"
        elif column == "collected":
            datetime_column = "collected_at"
        else:
            datetime_column = None

        if datetime_column is None:
            # Just in case we forgot any methods that call this
            raise ValueError
        self.execute_sql(
            f"UPDATE episodes SET {column}=?, {datetime_column}=? WHERE simkl_show_id=? AND season=? AND number=?",
            (
                value,
                self._get_datetime_now() if value > 0 else None,
                show_id,
                season,
                number,
            ),
        )
        self._update_shows_statistics_from_show_id(show_id)

    @guard_against_none(list)
    def get_recently_watched_shows(self, page=1, force_all=False, catalog=None):
        """
        Returns a list of recently watched shows
        :param page: Page to pull
        :param force_all: Enforce pulling of all items
        :param catalog: ``tv``, ``anime``, or None for all
        """
        query = """
            SELECT sm.id                   AS simkl_id,
                   sm.value                AS simkl_object,
                   MAX(ep.last_watched_at) AS last_watched_at
            FROM shows_meta AS sm
                     INNER JOIN episodes AS ep
                               ON ep.simkl_show_id = sm.id AND sm.type = 'simkl'
            WHERE ep.watched > 0
            GROUP BY sm.id
            ORDER BY last_watched_at DESC
            """

        rows = self.fetchall(query)
        rows = self._filter_show_rows_by_catalog(rows, catalog)

        if force_all:
            return rows

        offset = self.page_limit * (page - 1)
        return rows[offset : offset + self.page_limit]

    @guard_against_none(list)
    def get_collected_shows(self, page=1, force_all=False):
        """
        Returns all shows marked as collected from the database
        :param page: Page to pull
        :type page: int
        :param force_all: Enforce pulling of all items
        :type force_all: bool
        :return: List of show records
        :rtype: list
        """
        paginate = True
        sort = 0

        order_by = "ORDER BY max(e.collected_at) DESC" if sort == 0 else ""
        limit = (
            f"LIMIT {self.page_limit} OFFSET {self.page_limit * (page - 1)}"
            if paginate and not force_all and sort != 1
            else ""
        )

        query = f"""
            SELECT e.simkl_show_id AS simkl_id, m.value AS simkl_object
            FROM episodes AS e
                     LEFT JOIN shows AS sh
                               ON sh.simkl_id = e.simkl_show_id
                     LEFT JOIN shows_meta AS m
                               ON m.id = e.simkl_show_id AND m.type = 'simkl'
            WHERE e.collected = TRUE
            GROUP BY e.simkl_show_id
            {order_by}
            {limit}
            """

        return self.fetchall(query)

    def get_collected_episodes(self):
        """
        Returns a list of all episode objects marked as collected
        :return: List of episode objects
        :rtype: list
        """
        return self.fetchall("""SELECT simkl_id as simkl_id FROM episodes WHERE collected=1""")

    @guard_against_none(list)
    def get_show_list(self, media_list, **params):
        """
        Takes in a list of shows from a Simkl endpoint, updates meta where required and returns the formatted list
        :param media_list: List of shows to retrieve
        :type media_list: list
        :return: List of updated shows with full meta
        :rtype: list
        """
        g.log("Fetching show list from sync database and updating", "debug")
        media_list = [i for i in media_list if i.get("simkl_id")]
        skip_mill = params.pop("skip_mill", False)
        skip_update = params.pop("skip_update", False)
        if not skip_update:
            self._update_mill_format_shows(media_list, False, skip_mill=skip_mill)
        g.log("Show list update and milling complete", "debug")
        from resources.lib.database.sync_meta_cache import SyncMetaCache

        meta_cache = SyncMetaCache()

        statement = f"""
            SELECT s.simkl_id, s.info, s.[cast], s.art, s.args, s.last_updated, s.watched_episodes, s.unwatched_episodes, s.episode_count,
                s.season_count, s.air_date, s.user_rating, s.is_airing, s.tmdb_id, s.tvdb_id, s.imdb_id
            FROM shows AS s
            WHERE s.simkl_id IN ({','.join(str(i.get('simkl_id')) for i in media_list)})
            """
        if params.pop("hide_unaired", self.hide_unaired):
            statement += (
                f" AND (s.air_date IS NULL OR Datetime(s.air_date) < Datetime('{self._get_aired_cutoff()}'))"
            )
        if params.pop("hide_watched", self.hide_watched):
            statement += " AND (s.episode_count = 0 OR s.watched_episodes < s.episode_count)"

        rows = self.fetchall(statement)
        meta_cache.set_many_rows("show", rows or [])

        from resources.lib.meta.display_store import get_display_meta_store

        rows = get_display_meta_store().overlay_rows(rows, "tvshow")
        if skip_update:
            from resources.lib.meta.enrichment import (
                hybrid_apply_list_meta,
                hybrid_widget_local_meta,
            )

            if hybrid_widget_local_meta():
                rows, enrichment_refs = self.metadataHandler.merge_list_meta_local(rows, "tvshow", db=self)
                from resources.lib.simkl.enrich import gapfill_anime_title_rows

                rows = gapfill_anime_title_rows(rows)
                self.set_list_enrichment_refs(enrichment_refs, "tvshow")
            else:
                rows = hybrid_apply_list_meta(rows, "tvshow", self)
        else:
            self.set_list_enrichment_refs([], "tvshow")
        return MetadataHandler.sort_list_items(rows, media_list)

    def _has_season_rows(self, simkl_show_id, *, season=None, simkl_id=None) -> bool:
        if season is not None:
            row = self.fetchone(
                "SELECT simkl_id FROM seasons WHERE simkl_show_id=? AND season=? LIMIT 1",
                (int(simkl_show_id), int(season)),
            )
        elif simkl_id is not None:
            row = self.fetchone(
                "SELECT simkl_id FROM seasons WHERE simkl_id=? LIMIT 1",
                (int(simkl_id),),
            )
        else:
            row = self.fetchone(
                "SELECT simkl_id FROM seasons WHERE simkl_show_id=? LIMIT 1",
                (int(simkl_show_id),),
            )
        return bool(row)

    def _has_episode_rows(
        self,
        simkl_show_id,
        *,
        season_num=None,
        simkl_id=None,
        season_row_id=None,
    ) -> bool:
        if simkl_id is not None:
            row = self.fetchone(
                "SELECT simkl_id FROM episodes WHERE simkl_id=? LIMIT 1",
                (int(simkl_id),),
            )
        elif season_num is not None:
            row = self.fetchone(
                "SELECT simkl_id FROM episodes WHERE simkl_show_id=? AND season=? LIMIT 1",
                (int(simkl_show_id), int(season_num)),
            )
        elif season_row_id is not None:
            row = self.fetchone(
                "SELECT simkl_id FROM episodes WHERE simkl_season_id=? LIMIT 1",
                (int(season_row_id),),
            )
        else:
            row = self.fetchone(
                "SELECT simkl_id FROM episodes WHERE simkl_show_id=? LIMIT 1",
                (int(simkl_show_id),),
            )
        return bool(row)

    @guard_against_none(list, 1)
    def get_season_list(self, simkl_show_id, simkl_id=None, season=None, **params):
        """
        Fetches a list of seasons from database for a given show with full meta
        :param simkl_show_id: Simkl ID of show
        :param simkl_id: Legacy internal season row id (prefer season= number)
        :param season: Season number (1, 2, …)
        """
        g.log("Fetching season list from sync database and updating", "debug")
        skip_update = params.pop("skip_update", False)
        season_row_id = simkl_id
        if season is not None and simkl_id is None:
            from resources.lib.simkl.ids import season_key

            season_row_id = season_key(simkl_show_id, int(season))
        simkl_pulled = False
        seasons_need_format = False
        if skip_update:
            simkl_pulled = self._ensure_simkl_episode_tree(
                simkl_show_id,
                season_num=season,
            )
            seasons_need_format = self._seasons_need_format(
                simkl_show_id,
                season_num=season,
                season_row_id=season_row_id,
            )
        if not skip_update or simkl_pulled or seasons_need_format:
            self._try_update_seasons(simkl_show_id, season_row_id)
        g.log("Updated requested seasons", "debug")
        statement = """SELECT s.simkl_id, s.season, s.info, s.cast, s.art, s.args, s.watched_episodes, s.unwatched_episodes,
        s.episode_count, s.air_date, s.user_rating FROM seasons AS s WHERE """
        if season is not None:
            statement += f"s.simkl_show_id = {simkl_show_id} AND s.season = {int(season)}"
        elif simkl_id is not None:
            statement += f"s.simkl_id == {simkl_id}"
        else:
            statement += f"s.simkl_show_id = {simkl_show_id}"
        if params.pop("hide_unaired", self.hide_unaired):
            statement += (
                f" AND (s.air_date IS NULL OR Datetime(s.air_date) < Datetime('{self._get_aired_cutoff()}'))"
            )
        if params.pop("hide_specials", self.hide_specials):
            statement += " AND s.season != 0"
        if params.pop("hide_watched", self.hide_watched):
            statement += " AND (s.episode_count = 0 OR s.watched_episodes < s.episode_count)"
        statement += " order by s.Season"
        rows = self.fetchall(statement)
        for row in rows or []:
            info = row.get("info") or {}
            info_season = info.get("season") if isinstance(info, dict) else None
            g.log(
                f"[season trace] get_season_list show={simkl_show_id} "
                f"db.season={row.get('season')} info.season={info_season} "
                f"title={info.get('title') if isinstance(info, dict) else None} row_id={row.get('simkl_id')}",
                "debug",
            )
        if skip_update:
            from resources.lib.meta.enrichment import MetaEnrichmentQueue

            if not simkl_pulled and not seasons_need_format:
                MetaEnrichmentQueue.schedule_show_children(
                    int(simkl_show_id),
                    kind="season_list",
                    season_row_id=season_row_id if (season is not None or simkl_id is not None) else None,
                )
        return rows

    @guard_against_none(list, 1, 2, 4)
    def get_episode_list(
        self,
        simkl_show_id,
        simkl_season_id=None,
        simkl_id=None,
        season=None,
        minimum_episode=None,
        **params,
    ):
        """
        Retrieves episodes for a show, optionally filtered by season number or episode simkl_id.
        :param simkl_show_id: Show simkl_id
        :param season: Season number (preferred public filter)
        :param simkl_id: Single episode simkl_id
        :param simkl_season_id: Legacy internal season row id (DB only)
        """
        from resources.lib.simkl.ids import resolve_season_filter, season_key

        _, season_num = resolve_season_filter(
            simkl_show_id, season=season, season_row_id=simkl_season_id
        )
        season_row_id = simkl_season_id
        if season_num is not None and season_row_id is None:
            season_row_id = season_key(simkl_show_id, season_num)

        g.log("Fetching Episode list from sync database and updating", "debug")
        skip_update = params.pop("skip_update", False)
        simkl_pulled = False
        episodes_need_format = False
        if skip_update:
            simkl_pulled = self._ensure_simkl_episode_tree(
                simkl_show_id,
                season_num=season_num,
                simkl_id=simkl_id,
                season_row_id=season_row_id,
            )
            if not simkl_pulled:
                episodes_need_format = self._episodes_scope_need_format(
                    simkl_show_id,
                    season_num=season_num,
                    simkl_id=simkl_id,
                    season_row_id=season_row_id,
                )
        if not skip_update or simkl_pulled or episodes_need_format:
            self._try_update_episodes(simkl_show_id, season_row_id, simkl_id)
        g.log("Updated required episodes", "debug")
        statement = """SELECT e.simkl_id, e.simkl_show_id, e.simkl_season_id, e.info, e.cast, e.art, e.args, e.watched as play_count,
         b.resume_time as resume_time, b.percent_played as percent_played, e.user_rating FROM episodes as e
         LEFT JOIN bookmarks as b on e.simkl_id = b.simkl_id WHERE """

        if simkl_id is not None:
            statement += f"e.simkl_id = {simkl_id} "
        elif season_num is not None:
            statement += f"e.simkl_show_id = {simkl_show_id} AND e.season = {int(season_num)} "
        elif simkl_season_id is not None:
            statement += f"e.simkl_season_id = {simkl_season_id} "
        else:
            statement += f"e.simkl_show_id = {simkl_show_id} "
        if params.pop("hide_unaired", self.hide_unaired):
            statement += (
                f" AND (e.air_date IS NULL OR Datetime(e.air_date) < Datetime('{self._get_aired_cutoff()}')) "
            )
        if params.pop("hide_specials", self.hide_specials):
            statement += " AND e.season != 0"
        if params.pop("hide_watched", self.hide_watched):
            statement += " AND e.watched = 0"
        if minimum_episode:
            statement += f" AND e.number >= {int(minimum_episode)}"
        statement += " order by e.season, e.number "
        rows = self.fetchall(statement)
        if rows and any(self._episode_row_needs_format(row) for row in rows):
            self._format_episodes(
                [{"simkl_id": row["simkl_id"]} for row in rows if self._episode_row_needs_format(row)]
            )
            rows = self.fetchall(statement)
        if skip_update:
            from resources.lib.meta.enrichment import MetaEnrichmentQueue

            if not simkl_pulled and not episodes_need_format:
                episode_ids = [int(row["simkl_id"]) for row in rows or [] if row.get("simkl_id") is not None]
                MetaEnrichmentQueue.schedule_show_children(
                    int(simkl_show_id),
                    kind="episode_list",
                    season_row_id=season_row_id,
                    episode_ids=episode_ids if simkl_id is not None else None,
                )
        return rows

    def _episode_coords_from_list_item(self, item: dict) -> tuple[int, int, int] | None:
        if not isinstance(item, dict):
            return None
        show_id = item.get("simkl_show_id")
        if show_id is None:
            from resources.lib.simkl.ids import show_id_from_item

            show_id = show_id_from_item(item)
        season = item.get("season_x")
        if season is None:
            season = item.get("season")
        if season is None:
            nested = item.get("episode")
            if isinstance(nested, dict):
                season = MetadataHandler.get_simkl_info(nested, "season")
        ep_num = item.get("episode_x")
        if ep_num is None and isinstance(item.get("episode"), (int, float)):
            ep_num = item.get("episode")
        if ep_num is None:
            nested = item.get("episode")
            if isinstance(nested, dict):
                ep_num = MetadataHandler.get_simkl_info(nested, "episode") or MetadataHandler.get_simkl_info(
                    nested, "number"
                )
        if show_id is None or season is None or ep_num is None:
            return None
        return int(show_id), int(season), int(ep_num)

    def _resolve_episode_list_ids(self, media_items):
        resolved = []
        for item in media_items or []:
            if not isinstance(item, dict):
                resolved.append(item)
                continue
            item = dict(item)
            coords = self._episode_coords_from_list_item(item)
            if coords:
                show_id, season, ep_num = coords
                row = self.fetchone(
                    """
                    SELECT simkl_id, simkl_season_id
                    FROM episodes
                    WHERE simkl_show_id = ?
                      AND season = ?
                      AND number = ?
                    """,
                    (show_id, season, ep_num),
                )
                if row:
                    item["simkl_id"] = int(row["simkl_id"])
                    if row.get("simkl_season_id") is not None:
                        item["simkl_season_id"] = int(row["simkl_season_id"])
                    item.setdefault("season_x", season)
                    item.setdefault("episode_x", ep_num)
                    item["simkl_show_id"] = show_id
            resolved.append(item)
        return resolved


    @staticmethod
    def _episode_row_needs_format(row: dict | None) -> bool:
        """True when episode DB row lacks display-ready title (sync stubs, cold open)."""
        if not row or not isinstance(row, dict):
            return True
        info = row.get("info")
        if not isinstance(info, dict) or not info:
            return True
        return not (info.get("title") or info.get("name"))

    def _fetch_episode_scope_rows(
        self,
        simkl_show_id,
        *,
        season_num=None,
        simkl_id=None,
        season_row_id=None,
    ) -> list[dict]:
        if simkl_id is not None:
            return self.fetchall(
                "SELECT simkl_id, info FROM episodes WHERE simkl_id = ?",
                (int(simkl_id),),
            )
        if season_num is not None:
            return self.fetchall(
                "SELECT simkl_id, info FROM episodes WHERE simkl_show_id = ? AND season = ?",
                (int(simkl_show_id), int(season_num)),
            )
        if season_row_id is not None:
            return self.fetchall(
                "SELECT simkl_id, info FROM episodes WHERE simkl_season_id = ?",
                (int(season_row_id),),
            )
        return self.fetchall(
            "SELECT simkl_id, info FROM episodes WHERE simkl_show_id = ?",
            (int(simkl_show_id),),
        )

    @staticmethod
    def _season_row_needs_format(row: dict | None) -> bool:
        """True when season DB row lacks display-ready title (sync stubs after watchlist ingest)."""
        if not row or not isinstance(row, dict):
            return True
        info = row.get("info")
        if not isinstance(info, dict) or not info:
            return True
        return not (info.get("title") or info.get("name"))

    def _fetch_season_scope_rows(
        self,
        simkl_show_id,
        *,
        season_num=None,
        season_row_id=None,
    ) -> list[dict]:
        if season_num is not None:
            return self.fetchall(
                "SELECT simkl_id, season, info FROM seasons WHERE simkl_show_id = ? AND season = ?",
                (int(simkl_show_id), int(season_num)),
            )
        if season_row_id is not None:
            return self.fetchall(
                "SELECT simkl_id, season, info FROM seasons WHERE simkl_id = ?",
                (int(season_row_id),),
            )
        return self.fetchall(
            "SELECT simkl_id, season, info FROM seasons WHERE simkl_show_id = ?",
            (int(simkl_show_id),),
        )

    def _seasons_need_format(
        self,
        simkl_show_id,
        *,
        season_num=None,
        season_row_id=None,
    ) -> bool:
        if not self._has_season_rows(
            simkl_show_id,
            season=season_num,
            simkl_id=season_row_id,
        ):
            return False
        rows = self._fetch_season_scope_rows(
            simkl_show_id,
            season_num=season_num,
            season_row_id=season_row_id,
        )
        return any(self._season_row_needs_format(row) for row in rows)

    def _episodes_scope_need_format(
        self,
        simkl_show_id,
        *,
        season_num=None,
        simkl_id=None,
        season_row_id=None,
    ) -> bool:
        if not self._has_episode_rows(
            simkl_show_id,
            season_num=season_num,
            simkl_id=simkl_id,
            season_row_id=season_row_id,
        ):
            return False
        rows = self._fetch_episode_scope_rows(
            simkl_show_id,
            season_num=season_num,
            simkl_id=simkl_id,
            season_row_id=season_row_id,
        )
        return any(self._episode_row_needs_format(row) for row in rows)

    def _needs_simkl_episode_pull(
        self,
        simkl_show_id,
        *,
        season_num=None,
        simkl_id=None,
        season_row_id=None,
    ) -> bool:
        """True when drill-in should call Simkl episodes API (discover cold-open parity)."""
        if not self._has_episode_rows(
            simkl_show_id,
            season_num=season_num,
            simkl_id=simkl_id,
            season_row_id=season_row_id,
        ):
            return True
        rows = self._fetch_episode_scope_rows(
            simkl_show_id,
            season_num=season_num,
            simkl_id=simkl_id,
            season_row_id=season_row_id,
        )
        if not rows:
            return True
        if any(self._episode_row_needs_format(row) for row in rows):
            return True
        if simkl_id is None and season_num is None and season_row_id is None:
            show_row = self.fetchone(
                "SELECT episode_count FROM shows WHERE simkl_id = ?",
                (int(simkl_show_id),),
            )
            expected = int(show_row["episode_count"] or 0) if show_row else 0
            if expected > 0 and len(rows) < expected:
                return True
        return False

    def _ensure_simkl_episode_tree(
        self,
        simkl_show_id,
        *,
        season_num=None,
        simkl_id=None,
        season_row_id=None,
    ) -> bool:
        """Pull seasons/episodes from Simkl when local sync stubs would paint blank."""
        if not self._needs_simkl_episode_pull(
            simkl_show_id,
            season_num=season_num,
            simkl_id=simkl_id,
            season_row_id=season_row_id,
        ):
            return False
        show_meta = self._get_single_show_meta(simkl_show_id)
        if not show_meta:
            show_meta = {"simkl_id": int(simkl_show_id)}
        g.log(
            f"Drill-in Simkl episode pull for show {simkl_show_id}",
            "info",
        )
        self.force_mill_shows(show_meta, mill_episodes=True)
        return True

    def _mixed_episodes_missing_rows(self, media_items) -> bool:
        """True when a listed episode has no row in the local episodes table."""
        if not media_items:
            return False
        for item in self._resolve_episode_list_ids(media_items):
            simkl_id = item.get("simkl_id") if isinstance(item, dict) else None
            coords = self._episode_coords_from_list_item(item) if isinstance(item, dict) else None
            row = None
            if simkl_id is not None:
                row = self.fetchone(
                    "SELECT 1 AS ok FROM episodes WHERE simkl_id = ?",
                    (int(simkl_id),),
                )
            if row is None and coords:
                show_id, season, ep_num = coords
                row = self.fetchone(
                    """
                    SELECT 1 AS ok FROM episodes
                    WHERE simkl_show_id = ? AND season = ? AND number = ?
                    """,
                    (show_id, season, ep_num),
                )
            if row is None:
                return True
        return False

    def _mixed_episodes_need_sync(self, media_items) -> bool:
        if not media_items:
            return False
        for item in self._resolve_episode_list_ids(media_items):
            simkl_id = item.get("simkl_id") if isinstance(item, dict) else None
            coords = self._episode_coords_from_list_item(item) if isinstance(item, dict) else None
            row = None
            if simkl_id is not None:
                row = self.fetchone(
                    """
                    SELECT e.info, em.id AS meta_id
                    FROM episodes AS e
                    LEFT JOIN episodes_meta AS em ON em.id = e.simkl_id AND em.type = 'simkl'
                    WHERE e.simkl_id = ?
                    """,
                    (int(simkl_id),),
                )
            if row is None and coords:
                show_id, season, ep_num = coords
                row = self.fetchone(
                    """
                    SELECT e.info, em.id AS meta_id
                    FROM episodes AS e
                    LEFT JOIN episodes_meta AS em ON em.id = e.simkl_id AND em.type = 'simkl'
                    WHERE e.simkl_show_id = ?
                      AND e.season = ?
                      AND e.number = ?
                    """,
                    (show_id, season, ep_num),
                )
            if row is None:
                return True
            if row.get("meta_id") is None:
                return True
            if self._episode_row_needs_format(row):
                return True
        return False

    @guard_against_none(list)
    def get_mixed_episode_list(self, media_items, **params):
        """
        Returns a list of mixed episodes from different or same show
        :param media_items: List of show & episodes object pairs
        :type media_items: list
        :return: List of episode objects with full meta
        :rtype: list
        """
        g.log("Fetching mixed episode list from sync database", "debug")
        skip_update = params.pop("skip_update", False)
        params.pop("skip_mill", False)
        media_items = self._resolve_episode_list_ids(media_items)
        missing_rows = self._mixed_episodes_missing_rows(media_items)
        if missing_rows and not skip_update:
            g.log(
                "Mixed episode list: syncing listed episodes before paint",
                "debug",
            )
            self._try_update_mixed_episodes(media_items)
            media_items = self._resolve_episode_list_ids(media_items)
        elif missing_rows:
            show_ids = sorted(
                {int(item["simkl_show_id"]) for item in media_items if item.get("simkl_show_id") is not None}
            )
            if show_ids:
                from resources.lib.meta.enrichment import MetaEnrichmentQueue

                MetaEnrichmentQueue.schedule_run_plugin(
                    [{"simkl_id": show_id} for show_id in show_ids],
                    "tvshow",
                    reason="mixed_episode_list",
                )
        in_predicate = ",".join([str(i["simkl_id"]) for i in media_items if i.get("simkl_id") is not None])
        if not in_predicate:
            return []
        if g.get_bool_setting("general.showRemainingUnwatched"):
            query = f"""
                SELECT e.simkl_id,
                       e.info,
                       e.cast,
                       e.art,
                       e.args,
                       e.watched        AS play_count,
                       b.resume_time    AS resume_time,
                       b.percent_played AS percent_played,
                       se.watched_episodes,
                       se.unwatched_episodes,
                       se.episode_count,
                       e.user_rating
                FROM episodes AS e
                         INNER JOIN seasons se
                                    ON e.simkl_season_id = se.simkl_id
                         LEFT JOIN bookmarks AS b
                                   ON e.simkl_id = b.simkl_id
                WHERE e.simkl_id IN ({in_predicate})
                """
        else:
            query = f"""
                SELECT e.simkl_id, e.info, e.cast, e.art, e.args, e.watched AS play_count, b.resume_time AS resume_time,
                    b.percent_played AS percent_played, e.user_rating
                FROM episodes AS e LEFT JOIN bookmarks AS b ON e.simkl_id = b.simkl_id
                WHERE e.simkl_id IN ({in_predicate})
                """
        if params.pop("hide_unaired", self.hide_unaired):
            query += (
                f" AND (e.air_date IS NULL OR Datetime(e.air_date) < Datetime('{self._get_aired_cutoff()}')) "
            )
        if params.pop("hide_specials", self.hide_specials):
            query += " AND e.season != 0"
        if params.pop("hide_watched", self.hide_watched):
            query += " AND e.watched = 0"

        rows = self.fetchall(query)
        if rows and any(self._episode_row_needs_format(row) for row in rows):
            self._format_episodes(
                [{"simkl_id": row["simkl_id"]} for row in rows if self._episode_row_needs_format(row)]
            )
            rows = self.fetchall(query)
        if skip_update:
            from collections import defaultdict

            from resources.lib.meta.enrichment import MetaEnrichmentQueue

            groups: dict[tuple[int, int | None], list[int]] = defaultdict(list)
            for item in media_items:
                if not isinstance(item, dict):
                    continue
                show_id = item.get("simkl_show_id")
                season_id = item.get("simkl_season_id")
                episode_id = item.get("simkl_id")
                if show_id is None or episode_id is None:
                    continue
                groups[(int(show_id), int(season_id) if season_id is not None else None)].append(int(episode_id))
            for (show_id, season_row_id), episode_ids in groups.items():
                MetaEnrichmentQueue.schedule_show_children(
                    show_id,
                    kind="episode_list",
                    season_row_id=season_row_id,
                    episode_ids=episode_ids,
                )
        return MetadataHandler.sort_list_items(rows, media_items)

    @guard_against_none()
    def _get_single_show_meta(self, simkl_id):
        return self._get_single_meta(simkl_id, "shows")

    @guard_against_none(list)
    def get_show(self, simkl_id):
        """
        Returns a single show record from the database with full meta
        :param simkl_id: Shows Simkl ID
        :type simkl_id: int
        :return: Show item with full meta
        :rtype: dict
        """
        result = self.get_show_list([self._get_single_show_meta(simkl_id)], hide_unaired=False, hide_watched=False)
        return result[0] if len(result) > 0 else []

    @guard_against_none(list)
    def get_season(self, simkl_id, simkl_show_id, season=None):
        """
        Returns a single season record from the database with full meta.
        Prefer season= (number) with simkl_show_id; simkl_id is legacy internal row id.
        """
        if season is not None:
            result = self.get_season_list(
                simkl_show_id, season=int(season), hide_unaired=False, hide_watched=False
            )
        else:
            result = self.get_season_list(simkl_show_id, simkl_id, hide_unaired=False, hide_watched=False)
        return result[0] if len(result) > 0 else []

    @guard_against_none(list)
    def get_episode(self, simkl_id, simkl_show_id):
        """
        Returns a single episode record from the database with full meta
        :param simkl_id: Simkl ID of episode
        :type simkl_id: int
        :param simkl_show_id: Simkl ID of show
        :type simkl_show_id: int
        :return: Episode object with full meta
        :rtype: dict
        """
        result = self.get_episode_list(simkl_show_id, simkl_id=simkl_id, hide_unaired=False, hide_watched=False)
        if len(result) > 0:
            result = result[0]
            result.update(
                self.fetchone(
                    f"""
                    SELECT s.season_count,
                           s.episode_count AS show_episode_count,
                           se.episode_count,
                           se.is_airing,
                           a.absoluteNumber,
                           e.user_rating
                    FROM episodes AS e
                             INNER JOIN seasons AS se
                                        ON se.simkl_id = e.simkl_season_id
                             INNER JOIN shows AS s ON s.simkl_id = e.simkl_show_id
                             INNER JOIN (SELECT e.simkl_show_id, count(DISTINCT e.simkl_id) AS absoluteNumber
                                         FROM episodes AS e
                                                  INNER JOIN (SELECT e.simkl_show_id,
                                                                     (e.season * 10 + e.number) AS identifier
                                                              FROM episodes AS e
                                                              WHERE e.simkl_id = {simkl_id}) AS agg
                                                             ON agg.simkl_show_id = e.simkl_show_id
                                                                 AND agg.identifier >= (e.season * 10 + number)
                                         GROUP BY e.simkl_show_id) AS a
                                        ON a.simkl_show_id = e.simkl_show_id
                    WHERE e.simkl_id = {simkl_id}
                    """
                )
            )
        return result

    @guard_against_none(list)
    def _update_objects(self, db_list_to_update, media_type):

        threadpool = ThreadPool()
        for i in db_list_to_update:
            threadpool.put(self.metadataHandler.update, i)
        updated_items = threadpool.wait_completion()

        if updated_items is None:
            return

        threadpool.put(
            self.save_to_meta_table,
            (i for i in updated_items if i and "simkl_object" in i),
            media_type,
            "simkl",
            "simkl_id",
        )
        threadpool.put(
            self.save_to_meta_table,
            (i for i in updated_items if i and "tmdb_object" in i),
            media_type,
            "tmdb",
            "tmdb_id",
        )
        threadpool.put(
            self.save_to_meta_table,
            (i for i in updated_items if i and "tvdb_object" in i),
            media_type,
            "tvdb",
            "tvdb_id",
        )
        threadpool.put(
            self.save_to_meta_table,
            (i for i in updated_items if i and "fanart_object" in i),
            media_type,
            "fanart",
            "tvdb_id",
        )
        threadpool.wait_completion()

        return updated_items

    def _format_objects(self, updated_items):
        return self.metadataHandler.format_db_object(updated_items)

    @guard_against_none_or_empty()
    def _update_shows(self, list_to_update):
        get = MetadataHandler.get_simkl_info
        sql_statement = f"""
            WITH requested(simkl_id, last_updated) AS (VALUES
                {','.join("({},'{}')".format(i.get('simkl_show_id', i.get('simkl_id')), get(i, 'dateadded'))
                          for i in list_to_update)})
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
                   s.needs_update
            FROM requested AS r
                     LEFT JOIN shows AS s ON r.simkl_id = s.simkl_id
                     LEFT JOIN shows_meta AS simkl_meta ON simkl_meta.id = s.simkl_id AND simkl_meta.type = 'simkl'
                     LEFT JOIN shows_meta AS tmdb ON tmdb.id = s.tmdb_id AND tmdb.type = 'tmdb'
                     LEFT JOIN shows_meta AS tvdb ON tvdb.id = s.tvdb_id AND tvdb.type = 'tvdb'
                     LEFT JOIN shows_meta AS fanart ON fanart.id = s.tvdb_id AND fanart.type = 'fanart'
            """

        db_list_to_update = self.fetchall(sql_statement)
        self._apply_request_force_update(db_list_to_update, list_to_update)
        updated_items = self._update_objects(db_list_to_update, "shows")

        formatted_items = self._format_objects(updated_items)

        if formatted_items is None:
            return

        self.execute_sql(
            self.upsert_show_query,
            (
                (
                    i["info"]["simkl_id"],
                    i["info"],
                    i.get("art"),
                    i.get("cast"),
                    i["info"].get("aired"),
                    i["info"].get("dateadded"),
                    i["info"].get("tmdb_id"),
                    i["info"].get("tvdb_id"),
                    i["info"].get("imdb_id"),
                    self.metadataHandler.meta_hash,
                    i["info"].get("season_count"),
                    i["info"].get("episode_count"),
                    self._create_args(i),
                    i["info"].get("is_airing"),
                    i["info"].get("last_watched_at"),
                    i["info"].get("last_collected_at"),
                    i["info"].get("user_rating"),
                    self.get_library_status(i["info"]["simkl_id"], "show", i["info"]),
                )
                for i in formatted_items
            ),
        )
        self.update_shows_statistics({"simkl_id": i["info"]["simkl_id"]} for i in formatted_items)

    def _update_mill_format_shows(self, media_list, mill_episodes=False, skip_mill=False):
        if not media_list:
            return
        media_list = media_list if isinstance(media_list, list) else [media_list]
        self.insert_simkl_shows(media_list)
        self._update_shows(media_list)
        if not skip_mill:
            self._mill_if_needed(media_list, None, mill_episodes)

    @guard_against_none_or_empty()
    def _identify_seasons_to_update(self, list_to_update):
        get = MetadataHandler.get_simkl_info
        sql_statement = f"""
            WITH requested(simkl_id, last_updated) AS (VALUES
                    {','.join(f"({i.get('simkl_id')},'{get(i, 'dateadded')}')" for i in list_to_update)})
            SELECT r.simkl_id       AS simkl_id,
                   simkl_meta.value      AS simkl_object,
                   simkl_meta.meta_hash  AS simkl_meta_hash,
                   sh.tmdb_id       AS tmdb_show_id,
                   se.tmdb_id       AS tmdb_id,
                   tmdb.value       AS tmdb_object,
                   tmdb.meta_hash   AS tmdb_meta_hash,
                   sh.tvdb_id       AS tvdb_show_id,
                   se.tvdb_id       AS tvdb_id,
                   tvdb.value       AS tvdb_object,
                   tvdb.meta_hash   AS tvdb_meta_hash,
                   fanart.value     AS fanart_object,
                   fanart.meta_hash AS fanart_meta_hash,
                   sh.info          AS show_info,
                   sh.art           AS show_art,
                   sh.cast          AS show_cast,
                   se.needs_update
            FROM requested AS r
                     LEFT JOIN seasons AS se ON r.simkl_id = se.simkl_id
                     LEFT JOIN shows AS sh ON sh.simkl_id = se.simkl_show_id
                     LEFT JOIN seasons_meta AS simkl_meta ON simkl_meta.id = se.simkl_id AND simkl_meta.type = 'simkl'
                     LEFT JOIN seasons_meta AS tmdb ON tmdb.id = se.tmdb_id AND tmdb.type = 'tmdb'
                     LEFT JOIN seasons_meta AS tvdb ON tvdb.id = se.tvdb_id AND tvdb.type = 'tvdb'
                     LEFT JOIN seasons_meta AS fanart ON fanart.id = se.tvdb_id AND fanart.type = 'fanart'
            """

        return self.fetchall(sql_statement)

    @guard_against_none_or_empty()
    def _update_seasons(self, list_to_update):
        db_list_to_update = self._identify_seasons_to_update(list_to_update)
        if db_list_to_update is None:
            db_list_to_update = []

        return self._update_objects(db_list_to_update, "seasons")

    @guard_against_none_or_empty()
    def _format_seasons(self, list_to_update):
        from resources.lib.simkl.ids import season_key, show_id_from_info

        formatted_items = self._format_objects(self._identify_seasons_to_update(list_to_update))

        if formatted_items is None:
            return

        season_rows = []
        for i in formatted_items:
            show_id = show_id_from_info(i["info"]) or i["info"].get("simkl_show_id")
            season_num = i["info"].get("season")
            if show_id is None or season_num is None:
                continue
            g.log(
                f"[season trace] _format_seasons show={show_id} season={season_num} title={i['info'].get('title')}",
                "debug",
            )
            row_id = season_key(int(show_id), int(season_num))
            i["info"]["simkl_id"] = row_id
            i["info"]["simkl_season_id"] = row_id
            i["info"]["simkl_show_id"] = int(show_id)
            season_rows.append(
                (
                    int(show_id),
                    row_id,
                    i["info"],
                    i.get("art"),
                    i.get("cast"),
                    i["info"].get("aired"),
                    i["info"].get("dateadded"),
                    i["info"].get("tmdb_id"),
                    i["info"].get("tvdb_id"),
                    self.metadataHandler.meta_hash,
                    i["info"].get("episode_count") or i["info"].get("aired_episodes"),
                    int(season_num),
                    self._create_args(i),
                    i["info"].get("last_watched_at"),
                    i["info"].get("last_collected_at"),
                    i["info"].get("user_rating"),
                )
            )

        if not season_rows:
            return

        self.execute_sql(self.upsert_season_query, season_rows)
        self.update_season_statistics({"simkl_id": i["info"]["simkl_id"]} for i in formatted_items)

    @guard_against_none_or_empty()
    def _identify_episodes_to_update(self, list_to_update):
        get = MetadataHandler.get_simkl_info
        query = f"""
            WITH requested(simkl_id, last_updated) AS (VALUES
                    {','.join(f"({i.get('simkl_id')},'{get(i, 'dateadded')}')" for i in list_to_update)})
            SELECT r.simkl_id       AS simkl_id,
                   ep.simkl_season_id,
                   ep.simkl_show_id,
                   ep.season,
                   ep.number          AS episode,
                   simkl_meta.value      AS simkl_object,
                   simkl_meta.meta_hash  AS simkl_meta_hash,
                   ep.tmdb_id       AS tmdb_id,
                   tmdb.value       AS tmdb_object,
                   tmdb.meta_hash   AS tmdb_meta_hash,
                   ep.tvdb_id       AS tvdb_id,
                   tvdb.value       AS tvdb_object,
                   tvdb.meta_hash   AS tvdb_meta_hash,
                   fanart.value     AS fanart_object,
                   fanart.meta_hash AS fanart_meta_hash,
                   sh.tmdb_id       AS tmdb_show_id,
                   sh.tvdb_id       AS tvdb_show_id,
                   sh.info          AS show_info,
                   sh.art           AS show_art,
                   sh.cast          AS show_cast,
                   ep.simkl_season_id,
                   se.tmdb_id       AS tmdb_season_id,
                   sh.tvdb_id       AS tvdb_season_id,
                   se.info          AS season_info,
                   se.art           AS season_art,
                   se.cast          AS season_cast,
                   ep.needs_update
            FROM requested AS r
                     LEFT JOIN episodes AS ep ON r.simkl_id = ep.simkl_id
                     LEFT JOIN shows AS sh ON sh.simkl_id = ep.simkl_show_id
                     LEFT JOIN seasons AS se ON se.simkl_id = ep.simkl_season_id
                     LEFT JOIN episodes_meta AS simkl_meta ON simkl_meta.id = ep.simkl_id AND simkl_meta.type = 'simkl'
                     LEFT JOIN episodes_meta AS tmdb ON tmdb.id = ep.tmdb_id AND tmdb.type = 'tmdb'
                     LEFT JOIN episodes_meta AS tvdb ON tvdb.id = ep.tvdb_id AND tvdb.type = 'tvdb'
                     LEFT JOIN episodes_meta AS fanart ON fanart.id = ep.tvdb_id AND fanart.type = 'fanart'
            """

        return self.fetchall(query)

    @guard_against_none_or_empty()
    def _update_episodes(self, list_to_update):
        db_list_to_update = self._identify_episodes_to_update(list_to_update)

        if db_list_to_update is None:
            db_list_to_update = []

        return self._update_objects(db_list_to_update, "episodes")

    @guard_against_none_or_empty()
    def _format_episodes(self, list_to_update):
        from resources.lib.simkl.ids import episode_num_from_info

        formatted_items = self._format_objects(self._identify_episodes_to_update(list_to_update))

        if formatted_items is None:
            return

        episode_rows = [
            i
            for i in formatted_items
            if i.get("info", {}).get("simkl_id") is not None and episode_num_from_info(i["info"]) is not None
        ]
        if not episode_rows:
            return

        self.execute_sql(
            self.upsert_episode_query,
            (
                (
                    i["info"]["simkl_id"],
                    i["info"]["simkl_show_id"],
                    i["info"]["simkl_season_id"],
                    None,
                    None,
                    i["info"].get("aired"),
                    i["info"].get("dateadded"),
                    i["info"].get("season"),
                    episode_num_from_info(i["info"]),
                    i["info"].get("tmdb_id"),
                    i["info"].get("tvdb_id"),
                    i["info"].get("imdb_id"),
                    i["info"],
                    i.get("art"),
                    i.get("cast"),
                    self._create_args(i),
                    None,
                    None,
                    None,
                    self.metadataHandler.meta_hash,
                )
                for i in episode_rows
            ),
        )

    @guard_against_none(None, 1)
    def _try_update_seasons(self, simkl_show_id, simkl_season_id=None):
        show_meta = self._get_single_show_meta(simkl_show_id)
        self._update_mill_format_shows(show_meta, True)

        if simkl_season_id is not None:
            where_clause = f"WHERE s.simkl_id = {simkl_season_id}"
        else:
            where_clause = f"WHERE sh.simkl_id = {simkl_show_id}"
        query = f"""
            SELECT s.simkl_id,
                   value      AS simkl_object,
                   s.simkl_show_id,
                   sh.tmdb_id AS tmdb_show_id,
                   sh.tvdb_id AS tvdb_show_id
            FROM seasons AS s
                     INNER JOIN shows AS sh ON s.simkl_show_id = sh.simkl_id
                     LEFT JOIN seasons_meta AS m ON m.id = s.simkl_id AND m.type = 'simkl'
            {where_clause}
            """

        seasons_to_update = self.fetchall(query)

        self._update_seasons(seasons_to_update)
        self._format_seasons(seasons_to_update)

    @guard_against_none(None, 1)
    def _backfill_simkl_episode_stills(self, simkl_show_id):
        """Merge Simkl `img` paths into cached episode meta when stills were milled before we stored them."""
        rows = self.fetchall(
            """
            SELECT e.simkl_id, m.value AS simkl_object
            FROM episodes AS e
                     INNER JOIN episodes_meta AS m ON m.id = e.simkl_id AND m.type = 'simkl'
            WHERE e.simkl_show_id = ?
            """,
            (int(simkl_show_id),),
        )
        if not rows:
            return

        def _needs_still(row):
            obj = row.get("simkl_object")
            if not isinstance(obj, dict):
                return True
            info = obj.get("info") or {}
            art = obj.get("art") or {}
            return not info.get("simkl_img") and not art.get("thumb") and not info.get("thumb")

        if not any(_needs_still(row) for row in rows):
            return

        from resources.lib.indexers.simkl import SimklAPI
        from resources.lib.simkl.images import attach_episode_still

        catalog = self._infer_show_catalog(simkl_show_id)
        slug = self._meta_slug(simkl_show_id, "shows")
        api = SimklAPI()
        if catalog == "anime":
            raw_episodes = api.get_anime_episodes(int(simkl_show_id), slug=slug) or []
        else:
            raw_episodes = api.get_tv_episodes(int(simkl_show_id), slug=slug) or []

        by_simkl_id = {}
        for ep in raw_episodes:
            if not isinstance(ep, dict) or not ep.get("img"):
                continue
            ids = ep.get("ids") or {}
            ep_id = ids.get("simkl_id") or ids.get("simkl")
            if ep_id is not None:
                by_simkl_id[int(ep_id)] = ep

        if not by_simkl_id:
            return

        updates = []
        for row in rows:
            if not _needs_still(row):
                continue
            raw_ep = by_simkl_id.get(int(row["simkl_id"]))
            if not raw_ep:
                continue
            obj = dict(row.get("simkl_object") or {})
            info = dict(obj.get("info") or {})
            art = attach_episode_still(info, raw_ep)
            if not art:
                continue
            obj["info"] = info
            obj["art"] = {**(obj.get("art") or {}), **art}
            updates.append({"simkl_id": row["simkl_id"], "simkl_object": obj})

        if updates:
            g.log(f"Backfilling Simkl episode stills for show {simkl_show_id}: {len(updates)}", "debug")
            self.save_to_meta_table(updates, "episodes", "simkl", "simkl_id")

    @guard_against_none(None, 1, 2)
    def _try_update_episodes(self, simkl_show_id, simkl_season_id=None, simkl_id=None):
        show_meta = self._get_single_show_meta(simkl_show_id)
        self._update_mill_format_shows(show_meta, True)
        self._backfill_simkl_episode_stills(simkl_show_id)
        if simkl_id is not None:
            where_clause = f"WHERE e.simkl_id = {simkl_id}"
        elif simkl_season_id is not None:
            where_clause = f"WHERE e.simkl_season_id = {simkl_season_id}"
        else:
            where_clause = f"WHERE sh.simkl_id = {simkl_show_id}"
        query = f"""
            SELECT m.value      AS simkl_object,
                   e.simkl_id,
                   e.simkl_show_id,
                   sh.tmdb_id AS tmdb_show_id,
                   sh.tvdb_id
                              AS tvdb_show_id
            FROM episodes AS e
                     INNER JOIN shows AS sh ON e.simkl_show_id = sh.simkl_id
                     INNER JOIN episodes_meta AS m ON m.id = e.simkl_id AND m.type = 'simkl'
            {where_clause}
            """

        episodes_to_update = self.fetchall(query)

        self._update_episodes(episodes_to_update)
        self._format_episodes(episodes_to_update)

    @guard_against_none()
    def _try_update_mixed_episodes(self, media_items):
        media_items = self._resolve_episode_list_ids(media_items)
        show_ids = sorted({int(i["simkl_show_id"]) for i in media_items if i.get("simkl_show_id")})
        if not show_ids:
            return

        self.insert_simkl_shows([i["show"] for i in media_items if i.get("show")])

        for i in media_items:
            if not i.get("show") and i.get("simkl_show_id"):
                self.task_queue.put(self._get_single_show_meta, i["simkl_show_id"])
        self.task_queue.wait_completion()

        show_predicate = ",".join(str(i) for i in show_ids)
        shows = self.fetchall(
            f"""
            SELECT m.value AS simkl_object,
                   s.simkl_id,
                   s.tvdb_id,
                   s.tmdb_id
            FROM shows AS s
                     LEFT JOIN shows_meta AS m ON m.id = s.simkl_id AND m.type = 'simkl'
            WHERE s.simkl_id IN ({show_predicate})
            """
        )
        if not shows:
            shows = [{"simkl_id": show_id} for show_id in show_ids]

        self._update_mill_format_shows(shows, True)
        media_items = self._resolve_episode_list_ids(media_items)

        episode_ids = [str(i.get("simkl_id")) for i in media_items if i.get("simkl_id") is not None]
        if not episode_ids:
            return
        episode_predicate = ",".join(episode_ids)

        seasons_to_update = self.fetchall(
            f"""
                SELECT sm.value AS simkl_object,
                       se.simkl_id,
                       se.simkl_show_id,
                       sh.tmdb_id AS tmdb_show_id,
                       sh.tvdb_id AS tvdb_show_id
                FROM seasons AS se
                         INNER JOIN shows AS sh ON se.simkl_show_id = sh.simkl_id
                         LEFT JOIN seasons_meta AS sm ON sm.id = se.simkl_id AND sm.type = 'simkl'
                WHERE se.simkl_id IN (SELECT e.simkl_season_id
                                      FROM episodes e
                                      WHERE e.simkl_id IN ({episode_predicate}))
            """
        )

        episodes_to_update = self.fetchall(
            f"""
            SELECT em.value AS simkl_object,
                   e.simkl_id,
                   e.simkl_show_id,
                   sh.tmdb_id AS tmdb_show_id,
                   sh.tvdb_id AS tvdb_show_id
            FROM episodes AS e
                     INNER JOIN shows AS sh
                                ON e.simkl_show_id = sh.simkl_id
                     LEFT JOIN episodes_meta AS em
                                ON em.id = e.simkl_id AND em.type = 'simkl'
            WHERE e.simkl_id IN ({episode_predicate})
            """
        )

        self._update_seasons(seasons_to_update)
        self._update_episodes(episodes_to_update)

        self._format_seasons(seasons_to_update)
        self._format_episodes(episodes_to_update)

    def _watching_shows_needing_episode_mill(self, catalog: str | None = None) -> list[dict]:
        """Watching shows whose stub rows lack the next unwatched episode (Next Up / progress)."""
        rows = self.fetchall(
            """
            SELECT s.simkl_id,
                   m.value AS simkl_object,
                   s.info AS show_info,
                   s.simkl_status,
                   s.tmdb_id,
                   s.tvdb_id,
                   count(e.simkl_id) AS total,
                   sum(CASE WHEN e.watched = 0 AND e.season > 0 THEN 1 ELSE 0 END) AS unwatched
            FROM shows AS s
                     LEFT JOIN shows_meta AS m ON m.id = s.simkl_id AND m.type = 'simkl'
                     LEFT JOIN episodes AS e ON e.simkl_show_id = s.simkl_id
            GROUP BY s.simkl_id
            HAVING total = 0 OR unwatched = 0
            """
        )
        watching = []
        for row in rows or []:
            status = row.get("simkl_status")
            if not status:
                info = row.get("show_info")
                if isinstance(info, dict):
                    status = info.get("simkl_status")
            if not status:
                obj = row.get("simkl_object") or {}
                info = obj.get("info") if isinstance(obj, dict) else {}
                if isinstance(info, dict):
                    status = info.get("simkl_status")
            if status != "watching":
                continue
            if catalog and self.show_catalog(row["simkl_id"]) != catalog:
                continue
            watching.append(row)
        return watching

    def ensure_watching_shows_milled(self, catalog: str | None = None) -> None:
        shows = self._watching_shows_needing_episode_mill(catalog)
        if not shows:
            return
        self.force_mill_shows(shows, mill_episodes=True)

    def get_nextup_episodes(self, sort_by_last_watched=False, catalog=None):
        """
        Fetches items that a user should watch next for each show.
        :param sort_by_last_watched: Sort by last watched timestamp
        :param catalog: ``tv``, ``anime``, or None for all
        """
        if sort_by_last_watched:
            order_by = "ORDER BY inner_episodes.last_watched_at DESC"
        else:
            order_by = "ORDER BY e.air_date DESC"
        query = f"""
            SELECT e.simkl_id,
                   e.number  AS episode_x,
                   e.season  AS season_x,
                   e.simkl_show_id,
                   em.value  AS episode,
                   sm.value  AS show,
                   s.tmdb_id AS tmdb_show_id,
                   s.tvdb_id AS tvdb_show_id,
                   inner_episodes.last_watched_at,
                   e.air_date
            FROM episodes AS e
                     INNER JOIN shows AS s
                                ON s.simkl_id = e.simkl_show_id
                     INNER JOIN (SELECT e.simkl_show_id,
                                        Min(e.season)      AS season,
                                        Min(e.number)      AS number,
                                        nw.last_watched_at AS last_watched_at
                                 FROM episodes AS e
                                      INNER JOIN (SELECT e.simkl_show_id,
                                                         CASE
                                                             WHEN Max(e.season) == max_watched_season AND
                                                                  Max(e.number) == max_watched_episode_number
                                                                 THEN 1
                                                             ELSE Min(e.season)
                                                             END            AS season,
                                                         CASE
                                                             WHEN Max(e.season) == max_watched_season AND
                                                                  Max(e.number) == max_watched_episode_number
                                                                 THEN 1
                                                             ELSE Max(e.number)
                                                             END            AS number,
                                                         mw.last_watched_at AS last_watched_at
                                                  FROM episodes e
                                                       LEFT JOIN (SELECT mw_se.simkl_show_id,
                                                                         Max(mw_se.season) AS max_watched_season,
                                                                         mw_ep.number     AS max_watched_episode_number,
                                                                         mw_ep.last_watched_at AS last_watched_at
                                                                  FROM episodes AS mw_se
                                                                       INNER JOIN (SELECT simkl_show_id,
                                                                                          season,
                                                                                          Max(number)         AS number,
                                                                                          Max(last_watched_at)
                                                                                                AS last_watched_at
                                                                                   FROM episodes
                                                                                   WHERE watched >= 1 AND season > 0
                                                                                   GROUP BY simkl_show_id, season
                                                                       ) AS mw_ep
                                                                          ON mw_se.simkl_show_id = mw_ep.simkl_show_id
                                                                              AND mw_se.season = mw_ep.season
                                                                  GROUP BY mw_se.simkl_show_id) AS mw
                                                            ON e.simkl_show_id = mw.simkl_show_id
                                                  WHERE (e.season = mw.max_watched_season AND
                                                         e.number = mw.max_watched_episode_number + 1
                                                      AND watched = 0)
                                                     OR (e.season = mw.max_watched_season + 1 AND e.number = 1)
                                                  GROUP BY e.simkl_show_id) AS nw
                                                 ON (e.simkl_show_id == nw.simkl_show_id
                                                     AND e.season == nw.season
                                                     AND e.number >= nw.number)
                                 WHERE e.season > 0
                                   AND watched = 0
                                   AND e.simkl_show_id NOT IN (SELECT simkl_id AS simkl_show_id
                                                               FROM hidden
                                                               WHERE SECTION IN ('progress_watched'))
                                   AND (e.air_date IS NULL OR Datetime(e.air_date) < Datetime('{self._get_aired_cutoff()}'))
                                 GROUP BY e.simkl_show_id) AS inner_episodes
                            ON e.simkl_show_id == inner_episodes.simkl_show_id
                                AND e.season == inner_episodes.season
                                AND e.number == inner_episodes.number
                     LEFT JOIN episodes_meta AS em ON e.simkl_id = em.id AND em.type = 'simkl'
                     LEFT JOIN shows_meta AS sm ON e.simkl_show_id = sm.id AND sm.type = 'simkl'
            {order_by}
            """

        rows = self.fetchall(query)
        rows = self._filter_episode_rows_by_catalog(rows, catalog)
        if not rows:
            rows = self._get_nextup_episodes_fallback(sort_by_last_watched, catalog)
        return self.wrap_in_simkl_object(rows)

    def _get_nextup_episodes_fallback(self, sort_by_last_watched=False, catalog=None):
        """Per-watching-show next episode when the aggregate Next Up SQL finds nothing."""
        watching = self.get_shows_by_simkl_status("watching", catalog=catalog)
        if not watching:
            return []

        show_ids = [int(ref["simkl_id"]) for ref in watching if ref.get("simkl_id") is not None]
        if not show_ids:
            return []

        hidden = {
            row["simkl_id"]
            for row in self.fetchall(
                "SELECT simkl_id FROM hidden WHERE SECTION IN ('progress_watched')"
            )
        }
        now = self._get_aired_cutoff()
        rows = []
        for show_id in show_ids:
            if show_id in hidden:
                continue
            coords = self.get_next_episode_for_show(show_id)
            if not coords:
                continue
            season, number = coords
            row = self.fetchone(
                f"""
                SELECT e.simkl_id,
                       e.number  AS episode_x,
                       e.season  AS season_x,
                       e.simkl_show_id,
                       em.value  AS episode,
                       sm.value  AS show,
                       s.tmdb_id AS tmdb_show_id,
                       s.tvdb_id AS tvdb_show_id,
                       e.last_watched_at,
                       e.air_date
                FROM episodes AS e
                         INNER JOIN shows AS s ON s.simkl_id = e.simkl_show_id
                         LEFT JOIN episodes_meta AS em ON e.simkl_id = em.id AND em.type = 'simkl'
                         LEFT JOIN shows_meta AS sm ON e.simkl_show_id = sm.id AND sm.type = 'simkl'
                WHERE e.simkl_show_id = ?
                  AND e.season = ?
                  AND e.number = ?
                  AND e.watched = 0
                  AND (e.air_date IS NULL OR Datetime(e.air_date) < Datetime('{now}'))
                """,
                (show_id, season, number),
            )
            if row:
                rows.append(row)

        if sort_by_last_watched:
            rows.sort(
                key=lambda row: row.get("last_watched_at") or "",
                reverse=True,
            )
        else:
            rows.sort(key=lambda row: row.get("air_date") or "", reverse=True)
        return rows

    def get_next_episode_for_show(self, simkl_show_id: int) -> tuple[int, int] | None:
        """Next unwatched aired episode for one show (same progression as Next Up)."""
        simkl_show_id = int(simkl_show_id)
        now = self._get_aired_cutoff()
        last_watched = self.fetchone(
            """
            SELECT season, number
            FROM episodes
            WHERE simkl_show_id = ?
              AND watched >= 1
              AND season > 0
            ORDER BY season DESC, number DESC
            LIMIT 1
            """,
            (simkl_show_id,),
        )

        if not last_watched:
            first = self.fetchone(
                f"""
                SELECT season, number
                FROM episodes
                WHERE simkl_show_id = ?
                  AND season > 0
                  AND watched = 0
                  AND (air_date IS NULL OR Datetime(air_date) < Datetime('{now}'))
                ORDER BY season ASC, number ASC
                LIMIT 1
                """,
                (simkl_show_id,),
            )
            if not first or first.get("season") is None or first.get("number") is None:
                return None
            return int(first["season"]), int(first["number"])

        max_season = int(last_watched["season"])
        max_episode = int(last_watched["number"])
        same_season = self.fetchone(
            f"""
            SELECT season, number
            FROM episodes
            WHERE simkl_show_id = ?
              AND season = ?
              AND number = ?
              AND watched = 0
              AND (air_date IS NULL OR Datetime(air_date) < Datetime('{now}'))
            """,
            (simkl_show_id, max_season, max_episode + 1),
        )
        if same_season and same_season.get("season") is not None:
            return int(same_season["season"]), int(same_season["number"])

        next_season = self.fetchone(
            f"""
            SELECT season, number
            FROM episodes
            WHERE simkl_show_id = ?
              AND season = ?
              AND number = 1
              AND watched = 0
              AND (air_date IS NULL OR Datetime(air_date) < Datetime('{now}'))
            """,
            (simkl_show_id, max_season + 1),
        )
        if next_season and next_season.get("season") is not None:
            return int(next_season["season"]), int(next_season["number"])
        return None

    def get_watched_episodes(self, page=1, catalog=None):
        """
        Get watched episodes from database.
        :param catalog: ``tv``, ``anime``, or None for all
        """
        rows = self.fetchall(
            f"""
                SELECT e.simkl_id,
                       e.number  AS episode_x,
                       e.season  AS season_x,
                       e.simkl_show_id,
                       em.value  AS episode,
                       sm.value  AS show,
                       s.tmdb_id AS tmdb_show_id,
                       s.tvdb_id AS tvdb_show_id,
                       e.last_watched_at
                FROM episodes AS e
                         INNER JOIN shows AS s
                             ON s.simkl_id = e.simkl_show_id
                         LEFT JOIN episodes_meta AS em
                             ON e.simkl_id = em.id
                         LEFT JOIN shows_meta AS sm
                             ON e.simkl_show_id = sm.id
                WHERE e.watched > 0
                ORDER BY e.last_watched_at DESC
                """
        )
        rows = self._filter_episode_rows_by_catalog(rows, catalog)
        offset = self.page_limit * (page - 1)
        rows = rows[offset : offset + self.page_limit]
        return self.wrap_in_simkl_object(rows)

    def get_unfinished_collected_shows(self, page=1):
        """
        Returns a list of shows the user has collected but not completed watching
        :param page: Page to request
        :type page: int
        :return: List of show objects
        :rtype: list
        """
        paginate = True
        sort = 0

        order_by = "ORDER BY collected_at DESC" if sort == 0 else ""
        limit = f" LIMIT {self.page_limit} OFFSET {self.page_limit * (page - 1)}" if paginate and sort != 1 else ""

        query = f"""
            SELECT m.id AS simkl_id, value AS simkl_object
            FROM shows_meta AS m
                     INNER JOIN(SELECT ep.simkl_show_id, max(ep.collected_at) AS collected_at
                                FROM episodes AS ep
                                WHERE ep.season != 0
                                  AND ep.watched = 0
                                  AND ep.collected = 1
                                GROUP BY ep.simkl_show_id
                                HAVING count(*) > 0) AS u
                         ON u.simkl_show_id = m.id AND m.type = 'simkl'
            {order_by}
            {limit}
            """

        return self.fetchall(query)

    @guard_against_none()
    def get_season_action_args(self, simkl_show_id, season):
        """
        Returns action_args for a given season
        :param simkl_show_id: Simkl ID of show
        :type simkl_show_id: int
        :param season: Season number
        :type season: int
        :return: Action Args in a dictionary format
        :rtype: dict
        """
        show = [self._get_single_show_meta(simkl_show_id)]
        self.insert_simkl_shows(show)
        self._mill_if_needed(show)
        return self.fetchone(
            "SELECT simkl_id, simkl_show_id FROM seasons WHERE simkl_show_id=? AND season =?",
            (simkl_show_id, season),
        )

    @guard_against_none()
    def get_episode_action_args(self, simkl_show_id, season, episode):
        """
        Fetches action args for a given episode
        :param simkl_show_id: Simkl ID of show
        :type simkl_show_id: int
        :param season: Season number of episode
        :type season: int
        :param episode: Number of requested episode
        :type episode: int
        :return: Action Args in a dictionary format
        :rtype: dict
        """
        show = [self._get_single_show_meta(simkl_show_id)]
        self.insert_simkl_shows(show)
        self._mill_if_needed(show)
        return self.fetchone(
            """SELECT simkl_id, simkl_show_id FROM episodes WHERE simkl_show_id=? AND season=? AND number=?""",
            (simkl_show_id, season, episode),
        )

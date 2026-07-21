from __future__ import annotations

from resources.lib.database.simkl_sync import database


class SimklSyncDatabase(database.SimklSyncDatabase):
    def get_bookmark(self, simkl_id):
        return self.fetchone("SELECT * FROM bookmarks WHERE simkl_id=?", (simkl_id,))

    def set_bookmark(self, simkl_id, time_in_seconds, media_type, percent_played, catalog=None):
        paused_at = self._get_datetime_now()
        if catalog is None:
            catalog = "movie" if media_type == "movie" else "tv"
        self.execute_sql(
            "REPLACE INTO bookmarks (simkl_id, resume_time, percent_played, type, paused_at, catalog) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (simkl_id, time_in_seconds, percent_played, media_type, paused_at, catalog),
        )

    def remove_bookmark(self, simkl_id):
        self.execute_sql("DELETE FROM bookmarks WHERE simkl_id=?", (simkl_id,))

    def get_all_bookmark_items(self, mediatype):
        """Legacy accessor — prefer get_continue_watching(catalog)."""
        if mediatype == "movie":
            return self._continue_watching_movies(set())
        rows = self.fetchall(
            """
            SELECT ep.simkl_show_id   AS simkl_show_id,
                   ep.simkl_id        AS simkl_id,
                   ep.simkl_season_id AS simkl_season_id,
                   ep.season          AS season_x,
                   ep.number          AS episode_x,
                   bm.resume_time     AS progress,
                   em.value           AS episode,
                   sm.value           AS show
            FROM bookmarks AS bm
                     INNER JOIN episodes AS ep ON bm.simkl_id = ep.simkl_id
                     LEFT JOIN episodes_meta AS em
                               ON ep.simkl_id = em.id AND em.type = 'simkl'
                     LEFT JOIN shows_meta AS sm
                               ON ep.simkl_show_id = sm.id AND sm.type = 'simkl'
            WHERE bm.type = 'episode'
            ORDER BY Datetime(bm.paused_at) DESC
            """
        )
        return self.wrap_in_simkl_object(rows)

    def get_bookmarked_episode_for_show(self, simkl_show_id: int) -> tuple[int, int] | None:
        """Most recent in-progress episode for a show (resume helper)."""
        row = self.fetchone(
            """
            SELECT e.season, e.number
            FROM bookmarks AS bm
                     INNER JOIN episodes AS e ON bm.simkl_id = e.simkl_id
            WHERE e.simkl_show_id = ?
              AND bm.type = 'episode'
            ORDER BY Datetime(bm.paused_at) DESC
            LIMIT 1
            """,
            (int(simkl_show_id),),
        )
        if not row or row.get("season") is None or row.get("number") is None:
            return None
        return int(row["season"]), int(row["number"])

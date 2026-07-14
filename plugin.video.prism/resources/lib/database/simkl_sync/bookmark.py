from __future__ import annotations

from resources.lib.database.simkl_sync import database


class SimklSyncDatabase(database.SimklSyncDatabase):
    def get_bookmark(self, simkl_id):
        return self.fetchone("SELECT * FROM bookmarks WHERE simkl_id=?", (simkl_id,))

    def set_bookmark(self, simkl_id, time_in_seconds, media_type, percent_played):
        paused_at = self._get_datetime_now()
        self.execute_sql(
            "REPLACE INTO bookmarks Values (?, ?, ?, ?, ?)",
            (simkl_id, time_in_seconds, percent_played, media_type, paused_at),
        )

    def remove_bookmark(self, simkl_id):
        self.execute_sql("DELETE FROM bookmarks WHERE simkl_id=?", (simkl_id,))

    def get_all_bookmark_items(self, mediatype):
        if mediatype == "episode":
            query = """
                SELECT ep.simkl_show_id   AS simkl_show_id,
                       bm.simkl_id        AS simkl_id,
                       ep.simkl_season_id AS simkl_season_id,
                       bm.resume_time     AS progress,
                       em.value           AS episode,
                       sm.value           AS show
                FROM bookmarks AS bm
                         INNER JOIN episodes AS ep
                                    ON bm.simkl_id = ep.simkl_id
                         INNER JOIN episodes_meta AS em
                                    ON ep.simkl_id = em.id AND em.type = 'simkl'
                         LEFT JOIN shows_meta AS sm
                                   ON ep.simkl_show_id = sm.id AND sm.type = 'simkl'
                WHERE bm.type = 'episode'
                GROUP BY ep.simkl_show_id
                ORDER BY Datetime(bm.paused_at) DESC
                """
        else:
            query = """
                SELECT bm.simkl_id,
                       bm.resume_time AS progress,
                       mm.value       AS simkl_object
                FROM bookmarks AS bm
                         LEFT JOIN movies_meta AS mm
                                   ON bm.simkl_id = mm.id
                WHERE bm.type = 'movie'
                ORDER BY bm.paused_at DESC
                """

        return self.wrap_in_simkl_object(self.fetchall(query))

    def get_bookmarked_episode_for_show(self, simkl_show_id: int) -> tuple[int, int] | None:
        """Most recent in-progress episode for a show (Continue Watching)."""
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

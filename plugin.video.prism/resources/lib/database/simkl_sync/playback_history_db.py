"""Global playback history queries (My Watch History main menu)."""
from __future__ import annotations

from resources.lib.database.simkl_sync import database
from resources.lib.modules.guard_decorators import guard_against_none


class SimklSyncDatabase(database.SimklSyncDatabase):
    def stamp_local_playback(self, simkl_id: int, media_type: str) -> None:
        """Record Prism playback only — never written by Simkl cloud sync."""
        now = self._get_datetime_now()
        if media_type == "movie":
            self.execute_sql(
                "UPDATE movies SET local_playback_at=? WHERE simkl_id=?",
                (now, int(simkl_id)),
            )
            return
        if media_type == "episode":
            ep_id = int(simkl_id)
            self.execute_sql(
                "UPDATE episodes SET local_playback_at=? WHERE simkl_id=? AND catalog IN ('tv', 'anime')",
                (now, ep_id),
            )

    def touch_playback_activity(self, simkl_id: int, media_type: str) -> None:
        """Stamp local playback when the user pauses or stops mid-watch."""
        self.stamp_local_playback(simkl_id, media_type)

    @staticmethod
    def _playback_entry_from_bookmark(row: dict) -> dict | None:
        if not row or row.get("simkl_id") is None:
            return None
        media_type = row.get("type") or row.get("media_type")
        if media_type == "movie":
            return {
                "kind": "movie",
                "simkl_id": int(row["simkl_id"]),
                "simkl_show_id": None,
                "season": None,
                "episode": None,
                "catalog": row.get("catalog") or "movie",
                "activity_at": row.get("paused_at"),
                "resume_time": row.get("resume_time"),
                "percent_played": row.get("percent_played"),
                "in_progress": True,
            }
        if media_type == "episode":
            show_id = row.get("simkl_show_id")
            if show_id is None:
                return None
            catalog = row.get("catalog")
            if not catalog:
                catalog = "tv"
            return {
                "kind": "episode",
                "simkl_id": int(row["simkl_id"]),
                "simkl_show_id": int(show_id),
                "season": row.get("season_x") if row.get("season_x") is not None else row.get("season"),
                "episode": row.get("episode_x") if row.get("episode_x") is not None else row.get("number"),
                "catalog": catalog,
                "activity_at": row.get("paused_at"),
                "resume_time": row.get("resume_time"),
                "percent_played": row.get("percent_played"),
                "in_progress": True,
            }
        return None

    @staticmethod
    def _playback_entry_from_episode_row(row: dict) -> dict | None:
        if not row or row.get("simkl_id") is None:
            return None
        show_id = row.get("simkl_show_id")
        if show_id is None:
            return None
        return {
            "kind": "episode",
            "simkl_id": int(row["simkl_id"]),
            "simkl_show_id": int(show_id),
            "season": row.get("season_x") if row.get("season_x") is not None else row.get("season"),
            "episode": row.get("episode_x") if row.get("episode_x") is not None else row.get("number"),
            "catalog": row.get("catalog"),
            "activity_at": row.get("local_playback_at"),
            "resume_time": row.get("progress") or row.get("resume_time"),
            "percent_played": row.get("percent_played"),
            "in_progress": False,
            "sync_row": row if isinstance(row, dict) else None,
        }

    @staticmethod
    def _playback_entry_from_movie_row(row: dict) -> dict | None:
        if not row or row.get("simkl_id") is None:
            return None
        return {
            "kind": "movie",
            "simkl_id": int(row["simkl_id"]),
            "simkl_show_id": None,
            "season": None,
            "episode": None,
            "catalog": "movie",
            "activity_at": row.get("local_playback_at"),
            "resume_time": row.get("resume_time") or row.get("progress"),
            "percent_played": row.get("percent_played"),
            "in_progress": False,
            "sync_row": row if isinstance(row, dict) else None,
        }

    def _bookmark_meta_by_simkl_id(self) -> dict[int, dict]:
        meta: dict[int, dict] = {}
        for row in self.fetchall(
            "SELECT simkl_id, resume_time, percent_played, type, paused_at, catalog FROM bookmarks"
        ) or []:
            simkl_id = row.get("simkl_id")
            if simkl_id is not None:
                meta[int(simkl_id)] = row
        return meta

    def _entry_from_continue_watching_movie(self, row: dict, bookmark: dict) -> dict:
        return {
            "kind": "movie",
            "simkl_id": int(row["simkl_id"]),
            "simkl_show_id": None,
            "season": None,
            "episode": None,
            "catalog": "movie",
            "activity_at": bookmark.get("paused_at"),
            "resume_time": row.get("progress") or bookmark.get("resume_time"),
            "percent_played": row.get("percent_played") or bookmark.get("percent_played"),
            "in_progress": True,
        }

    def _entry_from_continue_watching_episode(
        self, row: dict, bookmark: dict, catalog: str
    ) -> dict | None:
        show_id = row.get("simkl_show_id")
        if show_id is None:
            return None
        season = row.get("season_x") if row.get("season_x") is not None else row.get("season")
        episode = row.get("episode_x") if row.get("episode_x") is not None else row.get("number")
        return {
            "kind": "episode",
            "simkl_id": int(row["simkl_id"]),
            "simkl_show_id": int(show_id),
            "season": season,
            "episode": episode,
            "catalog": catalog,
            "activity_at": bookmark.get("paused_at"),
            "resume_time": row.get("progress") or bookmark.get("resume_time"),
            "percent_played": row.get("percent_played") or bookmark.get("percent_played"),
            "in_progress": True,
            "sync_row": row if isinstance(row, dict) else None,
        }

    @guard_against_none(list)
    def get_global_continue_watching(self) -> list[dict]:
        """In-progress bookmarks across all catalogs, newest first."""
        bookmark_meta = self._bookmark_meta_by_simkl_id()
        entries: list[dict] = []

        for row in self._continue_watching_movies(set()) or []:
            simkl_id = row.get("simkl_id")
            if simkl_id is None:
                continue
            bookmark = bookmark_meta.get(int(simkl_id), {})
            entries.append(self._entry_from_continue_watching_movie(row, bookmark))

        for catalog in ("tv", "anime"):
            for row in self._continue_watching_episodes(catalog, set()) or []:
                simkl_id = row.get("simkl_id")
                if simkl_id is None:
                    continue
                bookmark = bookmark_meta.get(int(simkl_id), {})
                entry = self._entry_from_continue_watching_episode(row, bookmark, catalog)
                if not entry:
                    continue
                entries.append(entry)

        entries.sort(key=lambda item: str(item.get("activity_at") or ""), reverse=True)
        return entries

    @guard_against_none(list)
    def get_global_playback_history(self, page: int = 1) -> list[dict]:
        """Mixed movie + episode history from local Prism playback (excludes in-progress bookmarks)."""
        page = max(int(page or 1), 1)
        page_limit = self.page_limit
        offset = page_limit * (page - 1)

        bookmark_ids = {
            int(row["simkl_id"])
            for row in self.fetchall("SELECT simkl_id FROM bookmarks")
            if row.get("simkl_id") is not None
        }
        bookmark_clause = ""
        bookmark_params: tuple = ()
        if bookmark_ids:
            placeholders = ",".join("?" * len(bookmark_ids))
            bookmark_clause = f" AND e.simkl_id NOT IN ({placeholders})"
            bookmark_params = tuple(sorted(bookmark_ids))

        episode_select = f"""
            SELECT e.simkl_id,
                   e.number  AS episode_x,
                   e.season  AS season_x,
                   e.simkl_show_id,
                   em.value  AS episode,
                   sm.value  AS show,
                   s.tmdb_id AS tmdb_show_id,
                   s.tvdb_id AS tvdb_show_id,
                   e.local_playback_at
            FROM {{episode}} AS e
                     INNER JOIN {{show}} AS s ON s.simkl_id = e.simkl_show_id
                     LEFT JOIN {{episode_meta}} AS em
                               ON e.simkl_id = em.id AND em.type = 'simkl'
                     LEFT JOIN {{show_meta}} AS sm
                               ON e.simkl_show_id = sm.id AND sm.type = 'simkl'
            WHERE e.local_playback_at IS NOT NULL
              AND e.catalog = '{{catalog}}'
              AND s.catalog = '{{catalog}}'
            {bookmark_clause}
        """
        tv_episode_rows = self.fetchall(
            episode_select.format(
                episode="episodes",
                show="shows",
                episode_meta="episodes_meta",
                show_meta="shows_meta",
                catalog="tv",
            ),
            bookmark_params if bookmark_params else None,
        ) or []
        anime_episode_rows = self.fetchall(
            episode_select.format(
                episode="episodes",
                show="shows",
                episode_meta="episodes_meta",
                show_meta="shows_meta",
                catalog="anime",
            ),
            bookmark_params if bookmark_params else None,
        ) or []
        episode_rows = sorted(
            tv_episode_rows + anime_episode_rows,
            key=lambda row: str(row.get("local_playback_at") or ""),
            reverse=True,
        )

        movie_bookmark_clause = ""
        movie_bookmark_params: tuple = ()
        if bookmark_ids:
            placeholders = ",".join("?" * len(bookmark_ids))
            movie_bookmark_clause = f" AND m.simkl_id NOT IN ({placeholders})"
            movie_bookmark_params = tuple(sorted(bookmark_ids))

        movie_rows = self.fetchall(
            f"""
            SELECT m.simkl_id,
                   meta.value AS simkl_object,
                   m.info,
                   m.art,
                   m.tmdb_id,
                   m.tvdb_id,
                   m.imdb_id,
                   m.local_playback_at,
                   b.resume_time,
                   b.percent_played
            FROM movies AS m
                     LEFT JOIN movies_meta AS meta
                               ON m.simkl_id = meta.id AND meta.type = 'simkl'
                     LEFT JOIN bookmarks AS b
                               ON m.simkl_id = b.simkl_id AND b.type = 'movie'
            WHERE m.local_playback_at IS NOT NULL
            {movie_bookmark_clause}
            ORDER BY m.local_playback_at DESC
            """,
            movie_bookmark_params if movie_bookmark_params else None,
        ) or []

        episode_rows = self.wrap_in_simkl_object(episode_rows)
        entries: list[dict] = []

        for row in episode_rows:
            entry = self._playback_entry_from_episode_row(row)
            if not entry:
                continue
            if entry.get("simkl_show_id") is not None:
                entry["catalog"] = self._infer_show_catalog(int(entry["simkl_show_id"]))
            entries.append(entry)

        for row in movie_rows:
            entry = self._playback_entry_from_movie_row(row)
            if entry:
                entries.append(entry)

        entries.sort(key=lambda item: str(item.get("activity_at") or ""), reverse=True)
        return entries[offset : offset + page_limit]


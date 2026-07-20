"""Simkl public CDN — trending, DVD, calendar JSON (no user auth)."""
from __future__ import annotations

import json
from functools import cached_property
from urllib import parse

from resources.lib.database.cache import use_cache
from resources.lib.indexers.simkl import SimklAPI
from resources.lib.modules.globals import g

SIMKL_CDN_BASE = "https://data.simkl.in"


class SimklCDN:
    def __init__(self):
        self._simkl = SimklAPI()

    @cached_property
    def _query(self) -> str:
        return parse.urlencode(self._simkl._cdn_query())

    def build_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        q = self._query
        return f"{SIMKL_CDN_BASE}{path}?{q}" if q else f"{SIMKL_CDN_BASE}{path}"

    @use_cache(cache_hours=1)
    def fetch_json(self, path: str):
        import requests

        url = self.build_url(path)
        try:
            response = requests.get(
                url,
                headers={"User-Agent": f"{g.ADDON_ID}/{g.ADDON.getAddonInfo('version')}"},
                timeout=60,
            )
            if response.status_code != 200:
                g.log(f"Simkl CDN HTTP {response.status_code}: {path}", "warning")
                return None
            return response.json()
        except Exception:
            g.log_stacktrace()
            return None

    def trending_list(self, catalog: str, window: str, size: int = 500):
        """
        catalog: movie | tv | anime
        window: today | week | month
        Returns list of items in CDN order.
        """
        slug = {"movie": "movies", "tv": "tv", "anime": "anime"}.get(catalog, catalog)
        path = f"/discover/trending/{slug}/{window}_{size}.json"
        data = self.fetch_json(path)
        if isinstance(data, list):
            return data
        return []

    def trending_dvd(self, size: int = 500):
        data = self.fetch_json(f"/discover/dvd/releases_{size}.json")
        return data if isinstance(data, list) else []

    def trending_combined(self, window: str, size: int = 500):
        """Combined file with movies/tv/anime keys."""
        path = f"/discover/trending/{window}_{size}.json"
        return self.fetch_json(path)

    def calendar_bundle(self, catalog: str) -> dict:
        """Simkl calendar v2: {calendar: [...], metadata: {simkl_id: {...}}}."""
        paths = {
            "movie": "/calendar/v2/movie_release.json",
            "tv": "/calendar/v2/tv.json",
            "anime": "/calendar/v2/anime.json",
        }
        path = paths.get(catalog)
        if not path:
            return {"calendar": [], "metadata": {}}
        data = self.fetch_json(path)
        if isinstance(data, dict) and isinstance(data.get("calendar"), list):
            metadata = data.get("metadata")
            return {
                "calendar": data["calendar"],
                "metadata": metadata if isinstance(metadata, dict) else {},
            }
        if isinstance(data, list):
            return {"calendar": data, "metadata": {}}
        return {"calendar": [], "metadata": {}}

    def calendar_list(self, catalog: str) -> list:
        """Flatten v2 calendar bundle into legacy row dicts (calendar entry + show metadata)."""
        from resources.lib.calendar.simkl_calendar import merge_v2_calendar_rows

        bundle = self.calendar_bundle(catalog)
        return merge_v2_calendar_rows(
            bundle.get("calendar") or [],
            bundle.get("metadata") or {},
            catalog,
        )

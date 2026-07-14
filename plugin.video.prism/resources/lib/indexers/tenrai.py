"""Tenrai API client — Jikan v4-compatible MAL catalogue (anime multi-select browse)."""
from __future__ import annotations

import threading
import time
from functools import cached_property
from urllib import parse

from resources.lib.database.cache import use_cache
from resources.lib.indexers.apibase import ApiBase
from resources.lib.modules.globals import g

TENRAI_PAGE_SIZE = 25
TENRAI_MAX_RPS = 3
TENRAI_MAX_RPM = 60


class TenraiAPI(ApiBase):
    baseUrl = "https://api.tenrai.org/v1/"

    _rate_lock = threading.Lock()
    _second_timestamps: list[float] = []
    _minute_timestamps: list[float] = []

    http_codes = {
        200: "OK",
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        429: "Too Many Requests",
        500: "Internal Server Error",
    }

    @classmethod
    def _throttle(cls) -> None:
        while True:
            wait_for = 0.0
            with cls._rate_lock:
                now = time.monotonic()
                cls._second_timestamps = [t for t in cls._second_timestamps if (now - t) < 1.0]
                cls._minute_timestamps = [t for t in cls._minute_timestamps if (now - t) < 60.0]

                if len(cls._second_timestamps) < TENRAI_MAX_RPS and len(cls._minute_timestamps) < TENRAI_MAX_RPM:
                    cls._second_timestamps.append(now)
                    cls._minute_timestamps.append(now)
                    return

                second_wait = 0.0
                if len(cls._second_timestamps) >= TENRAI_MAX_RPS:
                    second_wait = max(0.0, 1.0 - (now - cls._second_timestamps[0]))
                minute_wait = 0.0
                if len(cls._minute_timestamps) >= TENRAI_MAX_RPM:
                    minute_wait = max(0.0, 60.0 - (now - cls._minute_timestamps[0]))
                wait_for = max(second_wait, minute_wait)

            if wait_for > 0:
                time.sleep(wait_for + 0.05)

    @cached_property
    def session(self):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        session = requests.Session()
        session.headers.update({"User-Agent": f"{g.ADDON_ID}/{g.ADDON.getAddonInfo('version')}"})
        server_key = (g.get_setting("tenrai.server_key") or "").strip()
        if server_key:
            session.headers["X-Server-Key"] = server_key
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 503, 504],
        )
        session.mount("https://", HTTPAdapter(max_retries=retries, pool_maxsize=20))
        return session

    def get(self, url, **params):
        self._throttle()
        timeout = params.pop("timeout", 15)
        try:
            response = self.session.get(
                parse.urljoin(self.baseUrl, url),
                params=params,
                headers={"Accept": "application/json"},
                timeout=timeout,
            )
        except Exception as exc:
            g.log(f"Tenrai request failed: {exc}", "debug")
            return None

        if response.status_code == 200:
            return response

        code = self.http_codes.get(response.status_code, str(response.status_code))
        g.log(
            f"Tenrai returned {response.status_code} ({code}): {response.url}",
            "warning" if response.status_code != 404 else "debug",
        )
        return None

    def get_json(self, url, raw=False, **params):
        response = self.get(url, **params)
        if response is None:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if raw else payload

    @use_cache(cache_hours=24)
    def get_anime_genres_cached(self, genre_filter: str) -> list[dict]:
        payload = self.get_json("genres/anime", raw=True, **{"filter": genre_filter})
        if not payload:
            return []
        rows: list[dict] = []
        for row in payload.get("data") or []:
            mal_id = row.get("mal_id")
            name = row.get("name")
            if mal_id is None or not name:
                continue
            rows.append({"mal_id": int(mal_id), "name": str(name)})
        return sorted(rows, key=lambda item: item["name"].lower())

    def search_anime(
        self,
        *,
        page: int = 1,
        limit: int = TENRAI_PAGE_SIZE,
        sfw: bool = True,
        **filters,
    ) -> dict | None:
        params: dict = {
            "page": max(1, int(page)),
            "limit": min(50, max(1, int(limit))),
        }
        # Tenrai/Jikan: sfw=true or sfw= (empty) strips NSFW genres; omit sfw to include them.
        if sfw:
            params["sfw"] = "true"
        params.update(filters)
        return self.get_json("anime", raw=True, **params)

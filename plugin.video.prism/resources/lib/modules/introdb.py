import threading
import time
from functools import cached_property

from resources.lib.database.cache import use_cache
from resources.lib.modules.globals import g

API_BASE = "https://api.theintrodb.org/v3"

SEGMENT_TYPES = ("intro", "recap", "credits", "preview")

MIN_REQUEST_GAP = 0.4

_rate_lock = threading.Lock()
_last_request_time = 0.0
_rate_limit_until = 0.0


def _normalize_imdb(imdb_id):
    if not imdb_id:
        return None
    value = str(imdb_id).strip()
    return value if value.startswith("tt") else None


def _valid_tmdb(tmdb_id):
    try:
        return int(str(tmdb_id)) > 0
    except (ValueError, TypeError):
        return False


def _valid_int(value):
    try:
        return int(value) > 0
    except (ValueError, TypeError):
        return False


# Episodes carry the parent show's external ids under these keys (see field_map / simkl_sync).
_EPISODE_SHOW_ID_KEYS = {
    "tmdb_id": ("tmdb_show_id", "tvshow.tmdb_id"),
    "tvdb_id": ("tvdb_show_id", "tvshow.tvdb_id"),
    "imdb_id": ("tvshow.imdb_id", "imdb_show_id"),
}


def _info_id(info, key):
    """Resolve an id, preferring the parent show id for episodes."""
    if info.get("mediatype") == "episode":
        for show_key in _EPISODE_SHOW_ID_KEYS.get(key, ()):
            value = info.get(show_key)
            if value:
                return value
    return info.get(key)


def _wait_rate_limit():
    """Honour a minimum gap between requests and any active 429 cooldown."""
    global _last_request_time
    with _rate_lock:
        now = time.time()
        if now < _rate_limit_until:
            return False
        gap = now - _last_request_time
        if gap < MIN_REQUEST_GAP:
            time.sleep(MIN_REQUEST_GAP - gap)
        _last_request_time = time.time()
    return True


def _set_rate_limit(headers):
    global _rate_limit_until
    retry = 300
    for header in ("X-UsageLimit-Reset", "X-RateLimit-Reset", "Retry-After"):
        value = headers.get(header) if headers else None
        if value:
            try:
                retry = int(value)
            except (ValueError, TypeError):
                pass
            break
    with _rate_lock:
        _rate_limit_until = time.time() + retry


class IntroDB:
    """Read-only client for TheIntroDB segment lookups."""

    @cached_property
    def session(self):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3 import Retry

        session = requests.Session()
        retries = Retry(
            total=2,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504, 520, 521, 522, 524],
        )
        session.mount("https://", HTTPAdapter(max_retries=retries, pool_maxsize=10))
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": f"{g.ADDON_NAME} Kodi Addon",
            }
        )
        return session

    def get_segments(self, item_information):
        """Return a list of normalized skip segments for the given item.

        Each segment is a dict: {"type": str, "start": float|None, "end": float|None}
        Times are in seconds. Returns [] when disabled, unidentifiable, or on error.
        """
        if not g.get_bool_setting("introdb.enabled"):
            return []

        info = (item_information or {}).get("info", {})
        params = self._build_params(info)
        if not params:
            return []

        return self._fetch_segments(**params)

    def _build_params(self, info):
        if not info:
            return None

        is_movie = info.get("mediatype") == "movie"

        params = {"is_movie": is_movie}

        tmdb_id = _info_id(info, "tmdb_id")
        tvdb_id = _info_id(info, "tvdb_id")
        imdb_id = _normalize_imdb(_info_id(info, "imdb_id"))

        if _valid_tmdb(tmdb_id):
            params["tmdb_id"] = int(str(tmdb_id).strip())
        elif _valid_int(tvdb_id):
            params["tvdb_id"] = int(str(tvdb_id).strip())
        elif imdb_id:
            params["imdb_id"] = imdb_id
        else:
            return None

        if not is_movie:
            season = info.get("season")
            episode = info.get("episode")
            if not (_valid_int(season) and _valid_int(episode)):
                return None
            params["season"] = int(season)
            params["episode"] = int(episode)

        duration = info.get("duration")
        if _valid_int(duration):
            params["duration_ms"] = int(duration) * 1000

        return params

    @use_cache(cache_hours=72)
    def _fetch_segments(self, **params):
        data = self._request(params)
        if not data or "error" in data:
            return []
        return self._normalize(data)

    def _request(self, params):
        is_movie = params.pop("is_movie", False)
        query = {k: v for k, v in params.items() if v is not None}

        if not _wait_rate_limit():
            g.log("IntroDB: skipping request, rate limited", "warning")
            return None

        try:
            import requests

            response = self.session.get(f"{API_BASE}/media", params=query, timeout=8)
            if response.status_code == 429:
                _set_rate_limit(response.headers)
                g.log("IntroDB: rate limited (429)", "warning")
                return None
            if response.status_code == 404:
                return {}
            if response.status_code not in (200, 201):
                g.log(f"IntroDB returned HTTP {response.status_code}", "warning")
                return None
            return response.json()
        except requests.exceptions.RequestException as error:
            g.log(f"IntroDB request error: {error}", "warning")
            return None
        except Exception:
            g.log_stacktrace()
            return None

    def _normalize(self, data):
        segments = []
        for segment_type in SEGMENT_TYPES:
            best = self._pick_best(data.get(segment_type, []), segment_type)
            if best is not None:
                segments.append(best)
        segments.sort(key=lambda s: (s["start"] if s["start"] is not None else 0))
        return segments

    @staticmethod
    def _pick_best(raw_segments, segment_type):
        if not isinstance(raw_segments, list):
            return None

        best = None
        best_score = -1.0
        for segment in raw_segments:
            if not isinstance(segment, dict):
                continue

            start = segment.get("start_ms")
            end = segment.get("end_ms")

            if segment_type in ("intro", "recap"):
                # start optional (null -> 0), end required
                if end is None:
                    continue
                if start is None:
                    start = 0
            else:  # credits, preview: start required, end optional (null -> end of media)
                if start is None:
                    continue

            if end is not None and end <= start:
                continue

            confidence = segment.get("confidence")
            confidence = 0.5 if confidence is None else float(confidence)
            count = segment.get("submission_count", 1) or 1
            score = confidence + count * 0.001

            if score > best_score:
                best_score = score
                best = {
                    "type": segment_type,
                    "start": start / 1000.0 if start is not None else None,
                    "end": end / 1000.0 if end is not None else None,
                }

        return best

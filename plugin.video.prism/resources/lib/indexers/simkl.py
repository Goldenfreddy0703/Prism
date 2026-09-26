"""Simkl API client — auth, sync, search, scrobble. Keys from context.prism/info.db or settings."""
from __future__ import annotations

import json
import threading
import time
from functools import cached_property, wraps
from typing import Any
from urllib import parse

import xbmcgui

from resources.lib.common import tools
from resources.lib.database.cache import use_cache
from resources.lib.database.keys import SIMKL_PUBLIC_API_NAME, get_client_id
from resources.lib.modules.exceptions import RanOnceAlready
from resources.lib.modules.global_lock import GlobalLock
from resources.lib.modules.globals import g

SIMKL_API_URL = "https://api.simkl.com"
# Simkl-required app identification (https://api.simkl.org/conventions/headers)
SIMKL_APP_NAME = "prism"
SIMKL_APP_VERSION = "1.0"
SIMKL_OAUTH_SCOPE = "media:read media:write"
SIMKL_AUTH_VERSION = "v2"
SIMKL_REFRESH_SETTING = "simkl.refresh"
SIMKL_TOKEN_EXPIRES_SETTING = "simkl.token_expires"
SIMKL_USER_ID_SETTING = "simkl.user_id"
SIMKL_SCOPE_SETTING = "simkl.scope"
SIMKL_AUTH_VERSION_SETTING = "simkl.auth_version"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

_thread_local = threading.local()


def thread_simkl_api() -> "SimklAPI":
    """One Simkl client + HTTP connection pool per worker thread (safe for parallel milling)."""
    api = getattr(_thread_local, "simkl_api", None)
    if api is None:
        api = SimklAPI()
        _thread_local.simkl_api = api
    return api


# Simkl path segments for GET /sync/playback/{type}
PLAYBACK_PATH_TYPES = {
    "movie": "movies",
    "movies": "movies",
    "episode": "episodes",
    "episodes": "episodes",
}


def simkl_guard_response(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        import requests

        try:
            return func(*args, **kwargs)
        except requests.exceptions.ConnectionError:
            return None
        except Exception:
            xbmcgui.Dialog().notification(g.ADDON_NAME, g.get_language_string(30024).format("Simkl"))
            if g.get_runtime_setting("run.mode") == "test":
                raise
            g.log_stacktrace()
            return None

    return wrapper


class SimklAPI:
    ApiUrl = SIMKL_API_URL
    username_setting_key = "simkl.username"

    http_codes = {
        200: "OK",
        201: "Created",
        204: "No Content",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        429: "Too Many Requests",
        500: "Internal Server Error",
    }

    def __init__(self):
        self._load_settings()

    @cached_property
    def session(self):
        import requests
        from requests.adapters import HTTPAdapter

        g.ensure_addon()
        session = requests.Session()
        session.headers.update({"User-Agent": f"{SIMKL_APP_NAME}/{SIMKL_APP_VERSION}"})
        adapter = HTTPAdapter(pool_maxsize=50, pool_connections=10)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    @cached_property
    def client_id(self) -> str:
        return get_client_id("Simkl") or ""

    @cached_property
    def public_client_id(self) -> str:
        return get_client_id(SIMKL_PUBLIC_API_NAME) or ""

    @cached_property
    def meta_hash(self):
        return tools.md5_hash([self.client_id, g.get_language_code()])

    def _load_settings(self):
        self.access_token = g.get_setting("simkl.auth")
        self.refresh_token = g.get_setting(SIMKL_REFRESH_SETTING)
        self.token_expires = g.get_float_setting(SIMKL_TOKEN_EXPIRES_SETTING)
        self.username = g.get_setting(self.username_setting_key)
        self.user_id = g.get_setting(SIMKL_USER_ID_SETTING)
        self.scope = g.get_setting(SIMKL_SCOPE_SETTING)

    def _has_auth_credentials(self) -> bool:
        return bool(self.access_token or self.refresh_token)

    def _clear_token_settings(self):
        for key in (
            "simkl.auth",
            SIMKL_REFRESH_SETTING,
            SIMKL_TOKEN_EXPIRES_SETTING,
            SIMKL_USER_ID_SETTING,
            SIMKL_SCOPE_SETTING,
            SIMKL_AUTH_VERSION_SETTING,
            self.username_setting_key,
        ):
            g.set_setting(key, "")
        self.access_token = None
        self.refresh_token = None
        self.token_expires = 0.0
        self.username = None
        self.user_id = None
        self.scope = None

    def _build_headers(
        self,
        *,
        authorized: bool = True,
        api_key: bool = True,
        api_key_client_id: str | None = None,
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        key_id = (api_key_client_id or self.client_id) if api_key else None
        if key_id:
            headers["simkl-api-key"] = key_id
        if authorized and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _get_headers(self, authorized: bool = True) -> dict:
        return self._build_headers(authorized=authorized, api_key=True)

    def _app_query(self, client_id: str) -> dict:
        return {
            "client_id": client_id,
            "app-name": SIMKL_APP_NAME,
            "app-version": SIMKL_APP_VERSION,
        }

    def _cdn_query(self) -> dict:
        return self._app_query(self.client_id)

    def _merge_user_query(self, params: dict | None) -> dict:
        query = dict(params or {})
        for key, value in self._cdn_query().items():
            query.setdefault(key, value)
        return query

    def _merge_app_query(self, params: dict | None, client_id: str) -> dict:
        query = dict(params or {})
        if client_id:
            for key, value in self._app_query(client_id).items():
                query.setdefault(key, value)
        return query

    def _anonymous_app_client_id(self, *, require_public: bool = False) -> str:
        """Client id for requests without a user bearer token."""
        if require_public:
            return self.public_client_id or ""
        return self.client_id or self.public_client_id or ""

    def _app_client_id_for_request(self) -> str:
        """V2 ``client_id`` for sync/watchlist; required on every Simkl API call."""
        return self.client_id or ""

    @staticmethod
    def _strip_client_id(params: dict | None) -> dict:
        query = dict(params or {})
        query.pop("client_id", None)
        return query

    @staticmethod
    def _must_strip_bearer_token(url: str) -> bool:
        """Cloudflare-cached catalog paths — never send Authorization (Simkl docs)."""
        path = (url or "").split("?")[0].rstrip("/")
        if path.startswith("/movies/") or path.startswith("/tv/") or path.startswith("/anime/"):
            return True
        if path.endswith("/episodes") and ("/tv/" in path or "/anime/" in path):
            return True
        return False

    def _log_http_failure(self, response, *, quiet: bool = False) -> None:
        if quiet:
            return
        g.log(
            f"Simkl HTTP {response.status_code} for {response.url.split('?')[0]}",
            "warning" if response.status_code != 404 else "debug",
        )

    def _should_retry_authorized(self, response) -> bool:
        if response is None or response.status_code != 401:
            return False
        if not self.refresh_token:
            return False
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            return True
        if isinstance(body, dict) and body.get("error") == "invalid_client":
            return False
        return True

    def _request(
        self,
        method: str,
        url: str,
        *,
        authorized: bool = True,
        api_key: bool = True,
        merge_cdn: bool = False,
        merge_public: bool = False,
        api_key_client_id: str | None = None,
        quiet_errors: bool = False,
        retry_auth: bool = True,
        **kwargs,
    ):
        params = kwargs.pop("params", None)
        if merge_cdn and authorized:
            params = self._merge_user_query(params)
        elif merge_public:
            app_id = api_key_client_id or self.public_client_id or self.client_id
            params = self._merge_app_query(params, app_id) if app_id else dict(params or {})
        elif params:
            params = dict(params)
        else:
            params = None

        send_bearer = authorized and self._has_auth_credentials()
        if send_bearer and self._must_strip_bearer_token(url):
            send_bearer = False

        headers = kwargs.pop("headers", None) or self._build_headers(
            authorized=send_bearer,
            api_key=api_key,
            api_key_client_id=api_key_client_id,
        )

        if send_bearer and retry_auth:
            self.try_refresh_token()

        request = getattr(self.session, method)
        response = request(
            parse.urljoin(self.ApiUrl, url),
            params=params,
            headers=headers,
            **kwargs,
        )

        if (
            retry_auth
            and send_bearer
            and self._should_retry_authorized(response)
            and self.try_refresh_token(force=True)
        ):
            headers = self._build_headers(
                authorized=True,
                api_key=api_key,
                api_key_client_id=api_key_client_id,
            )
            response = request(
                parse.urljoin(self.ApiUrl, url),
                params=params,
                headers=headers,
                **kwargs,
            )

        if response.status_code in (200, 201, 204):
            return response

        self._log_http_failure(response, quiet=quiet_errors)
        if send_bearer and response.status_code == 401 and self._has_auth_credentials():
            self._notify_reauth_if_needed()
        return None

    def _anonymous_get(
        self,
        url: str,
        *,
        require_public: bool = False,
        allow_bare_catalog: bool = False,
        **params,
    ):
        """GET with app ``client_id`` params and no bearer (search, genres, catalog detail)."""
        timeout = params.pop("timeout", 15)
        app_id = self._anonymous_app_client_id(require_public=require_public)
        if require_public and not app_id:
            g.log(
                "Simkl-Public client_id missing from context.prism/info.db (search/genres)",
                "warning",
            )
            return None
        if not app_id:
            g.log(
                "Simkl client_id missing — cannot call API (set Simkl in context.prism/info.db)",
                "warning",
            )
            if not allow_bare_catalog:
                return None
            return self._request(
                "get",
                url,
                authorized=False,
                api_key=False,
                params=self._strip_client_id(params),
                timeout=timeout,
                retry_auth=False,
            )
        return self._request(
            "get",
            url,
            authorized=False,
            api_key=True,
            api_key_client_id=app_id,
            merge_public=True,
            params=params or None,
            timeout=timeout,
            retry_auth=False,
        )

    def _anonymous_post(self, url: str, json_data=None, **params):
        """POST with app params and no bearer (rare public POST endpoints)."""
        timeout = params.pop("timeout", 15)
        app_id = self._anonymous_app_client_id(require_public=False)
        if not app_id:
            g.log("Simkl client_id missing for public POST", "warning")
            return None
        return self._request(
            "post",
            url,
            authorized=False,
            api_key=True,
            api_key_client_id=app_id,
            merge_public=True,
            params=params or None,
            json=json_data,
            timeout=timeout,
            retry_auth=False,
        )

    @simkl_guard_response
    def get(self, url, authorized: bool = True, catalog: bool = False, public_api: bool = False, **params):
        timeout = params.pop("timeout", 15)
        if catalog:
            params["timeout"] = timeout
            return self._anonymous_get(url, allow_bare_catalog=True, **params)
        if public_api:
            params["timeout"] = timeout
            return self._anonymous_get(url, require_public=True, **params)
        app_id = self._app_client_id_for_request()
        if authorized and not app_id:
            g.log("Simkl V2 client_id missing for authenticated API call", "warning")
        return self._request(
            "get",
            url,
            authorized=authorized,
            api_key=True,
            merge_cdn=authorized,
            params=params or None,
            timeout=timeout,
        )

    @simkl_guard_response
    def post(self, url, json_data=None, authorized: bool = True, catalog: bool = False, **params):
        timeout = params.pop("timeout", 15)
        if catalog:
            params["timeout"] = timeout
            return self._anonymous_post(url, json_data=json_data, **params)
        return self._request(
            "post",
            url,
            authorized=authorized,
            api_key=True,
            merge_cdn=authorized,
            params=params or None,
            json=json_data,
            timeout=timeout,
        )

    def _post_form(
        self,
        url: str,
        data: dict[str, str],
        *,
        authorized: bool = False,
        api_key: bool = False,
        quiet_errors: bool = False,
    ):
        headers = self._build_headers(authorized=authorized, api_key=api_key)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            response = self.session.post(
                parse.urljoin(self.ApiUrl, url),
                data=data,
                headers=headers,
                timeout=15,
            )
        except Exception:
            if not quiet_errors:
                g.log_stacktrace()
            return None
        return response

    def get_json(
        self,
        url,
        authorized: bool = True,
        catalog: bool = False,
        public_api: bool = False,
        **params,
    ):
        response = self.get(
            url,
            authorized=authorized,
            catalog=catalog,
            public_api=public_api,
            **params,
        )
        if response is None or not response.text:
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            return None

    def get_catalog_json(self, url: str, **params):
        """Cached catalog (detail, episodes, /changes) — V2 ``client_id``, no bearer."""
        return self.get_json(url, catalog=True, **params)

    def get_public_json(self, url: str, **params):
        """Search, genres, and other V1-public endpoints (client_id only, no user token)."""
        return self.get_json(url, public_api=True, **params)

    @staticmethod
    def parse_pagination_headers(response) -> dict[str, int]:
        """Parse Simkl ``X-Pagination-*`` headers from an HTTP response."""
        if response is None:
            return {}
        mapping = (
            ("X-Pagination-Page", "page"),
            ("X-Pagination-Limit", "limit"),
            ("X-Pagination-Page-Count", "page_count"),
            ("X-Pagination-Item-Count", "item_count"),
        )
        parsed: dict[str, int] = {}
        for header_name, key in mapping:
            value = response.headers.get(header_name)
            if value is None:
                continue
            try:
                parsed[key] = int(value)
            except (TypeError, ValueError):
                continue
        return parsed

    def get_json_with_pagination(
        self,
        url,
        authorized: bool = True,
        catalog: bool = False,
        public_api: bool = False,
        **params,
    ) -> tuple[Any, dict[str, int]]:
        """Return ``(json_body, pagination)`` with Simkl pagination headers when present."""
        response = self.get(
            url,
            authorized=authorized,
            catalog=catalog,
            public_api=public_api,
            **params,
        )
        if response is None or not response.text:
            return None, {}
        try:
            body = response.json()
        except json.JSONDecodeError:
            return None, SimklAPI.parse_pagination_headers(response)
        return body, SimklAPI.parse_pagination_headers(response)

    def get_catalog_json_with_pagination(self, url: str, **params) -> tuple[Any, dict[str, int]]:
        return self.get_json_with_pagination(url, catalog=True, **params)

    def get_public_json_with_pagination(self, url: str, **params) -> tuple[Any, dict[str, int]]:
        return self.get_json_with_pagination(url, public_api=True, **params)

    @use_cache(cache_hours=300 / 3600)
    def get_json_cached(self, url, authorized: bool = True, catalog: bool = False, **params):
        return self.get_json(url, authorized=authorized, catalog=catalog, **params)

    def _save_token_response(self, response: dict) -> None:
        access_token = response.get("access_token")
        if not access_token:
            return
        g.set_setting("simkl.auth", access_token)
        self.access_token = access_token

        refresh_token = response.get("refresh_token")
        if refresh_token:
            g.set_setting(SIMKL_REFRESH_SETTING, refresh_token)
            self.refresh_token = refresh_token

        expires_in = response.get("expires_in")
        if expires_in is not None:
            try:
                expiry = time.time() + int(expires_in)
            except (TypeError, ValueError):
                expiry = 0.0
            g.set_setting(SIMKL_TOKEN_EXPIRES_SETTING, expiry)
            self.token_expires = expiry

        scope = response.get("scope")
        if scope:
            g.set_setting(SIMKL_SCOPE_SETTING, str(scope))
            self.scope = str(scope)
            if "media:write" not in str(scope):
                g.log(f"Simkl token missing media:write scope: {scope}", "warning")

        g.set_setting(SIMKL_AUTH_VERSION_SETTING, SIMKL_AUTH_VERSION)

    def _apply_user_settings(self) -> None:
        settings_response = self.post("/users/settings", json_data={})
        if settings_response is None:
            return
        try:
            payload = settings_response.json()
        except json.JSONDecodeError:
            return
        user = payload.get("user") if isinstance(payload, dict) else None
        if not isinstance(user, dict):
            return
        name = user.get("name") or user.get("username")
        if name:
            g.set_setting(self.username_setting_key, str(name))
            self.username = str(name)
        user_id = user.get("id")
        if user_id is not None:
            g.set_setting(SIMKL_USER_ID_SETTING, str(int(user_id)))
            self.user_id = str(int(user_id))

    def _oauth_token_request(self, payload: dict[str, str], *, quiet: bool = True):
        data = {"client_id": self.client_id, **payload}
        response = self._post_form("/oauth2/token", data, quiet_errors=quiet)
        if response is None or not response.text:
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            return None

    def try_refresh_token(self, force: bool = False) -> bool:
        if not self.refresh_token or not self.client_id:
            return False
        if not force and self.token_expires and self.token_expires > time.time() + 3600:
            return True

        try:
            with GlobalLock("SimklAPI.refresh", True, self.refresh_token):
                if not force and self.token_expires and self.token_expires > time.time() + 3600:
                    return True
                payload = self._oauth_token_request(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                    }
                )
                if not isinstance(payload, dict) or not payload.get("access_token"):
                    error = (payload or {}).get("error")
                    g.log(f"Simkl token refresh failed: {error or payload}", "warning")
                    return False
                self._save_token_response(payload)
                return True
        except RanOnceAlready:
            self._load_settings()
            return bool(self.access_token)

    def _notify_reauth_if_needed(self) -> None:
        if g.get_runtime_setting("simkl.reauth.notified"):
            return
        g.set_runtime_setting("simkl.reauth.notified", True)
        xbmcgui.Dialog().notification(
            g.ADDON_NAME,
            "Simkl login updated — please sign in again in Prism settings.",
            time=6000,
        )

    def auth(self):
        """AUTH V2 device flow with QR dialog."""
        if not self.client_id:
            xbmcgui.Dialog().ok(g.ADDON_NAME, "Simkl client_id missing from context.prism/info.db")
            return False

        from resources.lib.modules.qr_auth import auth_progress_percent, open_auth_dialog, wait_auth_interval

        device_response = self._post_form(
            "/oauth2/device",
            {
                "client_id": self.client_id,
                "scope": SIMKL_OAUTH_SCOPE,
            },
        )
        if device_response is None:
            return False

        try:
            device_payload = device_response.json()
        except json.JSONDecodeError:
            g.log("Simkl device authorization response was not valid JSON", "error")
            return False

        if not isinstance(device_payload, dict):
            g.log(f"Simkl device authorization failed: {device_payload}", "error")
            xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30023))
            return False

        if device_response.status_code == 401:
            g.log(f"Simkl device authorization invalid_client: {device_payload}", "error")
            xbmcgui.Dialog().ok(
                g.ADDON_NAME,
                "Simkl client_id is not enabled for OAuth V2. Register a V2 app and update info.db.",
            )
            return False

        if device_response.status_code != 200:
            g.log(f"Simkl device authorization failed: {device_payload}", "error")
            xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30023))
            return False

        user_code = str(device_payload.get("user_code") or "").strip()
        poll_code = str(device_payload.get("device_code") or "").strip()
        if not user_code or not poll_code:
            g.log(f"Simkl device authorization missing codes: {device_payload}", "error")
            xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30023))
            return False

        qr_url = (
            device_payload.get("verification_uri_complete")
            or device_payload.get("verification_uri")
            or device_payload.get("verification_url")
            or "https://simkl.com/pin"
        )
        display_url = "https://simkl.com/pin"

        interval = int(device_payload.get("interval", 5))
        expires_in = int(device_payload.get("expires_in", 900))
        attempts = max(1, expires_in // max(interval, 1))

        heading = f"{g.ADDON_NAME}: {g.get_language_string(30131).rstrip('.')}"
        progress = open_auth_dialog(
            heading,
            display_url,
            user_code=user_code,
            qr_url=qr_url,
        )

        try:
            for i in range(attempts):
                if progress.iscanceled():
                    return False
                progress.update(auth_progress_percent(attempts - i, attempts))

                token_payload = self._oauth_token_request(
                    {
                        "grant_type": DEVICE_CODE_GRANT,
                        "device_code": poll_code,
                    }
                )
                if isinstance(token_payload, dict) and token_payload.get("access_token"):
                    self._save_token_response(token_payload)
                    self._apply_user_settings()
                    if not self.username:
                        g.set_setting(self.username_setting_key, "Simkl User")
                        self.username = "Simkl User"
                    g.set_runtime_setting("simkl.reauth.notified", False)
                    xbmcgui.Dialog().notification(g.ADDON_NAME, g.get_language_string(30273))
                    self._queue_sync_after_auth()
                    return True

                error = (token_payload or {}).get("error") if isinstance(token_payload, dict) else None
                if error == "slow_down":
                    interval += 5
                elif error in ("expired_token", "access_denied"):
                    break

                if not wait_auth_interval(interval, progress):
                    return False
        finally:
            progress.close()

        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30023))
        return False

    @staticmethod
    def _queue_sync_after_auth():
        """Pull Simkl library + playback state immediately after a successful login."""
        import xbmc

        xbmc.executebuiltin(
            'RunPlugin("plugin://plugin.video.prism/?action=syncSimklActivities&force=true")'
        )

    def revoke(self):
        token = self.refresh_token or self.access_token
        if token and self.client_id:
            self._post_form(
                "/oauth2/revoke",
                {
                    "client_id": self.client_id,
                    "token": token,
                },
                quiet_errors=True,
            )
        self._clear_token_settings()

    def is_authenticated(self) -> bool:
        return self._has_auth_credentials()

    def search(self, query: str, media_type: str = "movie", limit: int = 25, *, exact: bool | None = None):
        """Search Simkl. media_type: movie, tv, anime."""
        from resources.lib.simkl.search import simkl_search_exact_enabled

        if exact is None:
            exact = simkl_search_exact_enabled()
        endpoint = {"movie": "movie", "tv": "tv", "anime": "anime"}.get(media_type, "movie")
        params: dict[str, str | int] = {
            "q": query,
            "limit": limit,
            "extended": "full",
        }
        if exact:
            params["exact"] = "true"
        return self.get_public_json(f"/search/{endpoint}", **params)

    def get_activities(self):
        return self.get_json("/sync/activities")

    def get_changes(self, date_from: str | None = None, media_types: str | None = None):
        """Catalog IDs whose metadata changed recently (public; pair with watchlist intersect)."""
        params: dict[str, str] = {}
        if date_from:
            params["date_from"] = date_from
        if media_types:
            params["type"] = media_types
        return self.get_catalog_json("/changes", **params)

    def get_all_items(
        self,
        media_type: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        **params,
    ):
        url = "/sync/all-items/"
        if media_type:
            url += f"{media_type}/"
            if status:
                url += f"{status}/"
        query = dict(params)
        if date_from:
            query["date_from"] = date_from
        query.update(self._cdn_query())
        return self.get_json(url, **query)

    @use_cache(cache_hours=24)
    def get_tv_episodes(self, simkl_id: int, slug: str | None = None):
        from resources.lib.simkl.ids import tv_episodes_api_path

        return self.get_catalog_json(tv_episodes_api_path(simkl_id, slug))

    @use_cache(cache_hours=24)
    def get_anime_episodes(self, simkl_id: int, extended: str | None = None, slug: str | None = None):
        from resources.lib.simkl.ids import anime_episodes_api_path

        params: dict[str, str] = {}
        if extended:
            params["extended"] = extended
        return self.get_catalog_json(anime_episodes_api_path(simkl_id, slug), **params)

    def get_show_json(self, simkl_id: int, slug: str | None = None, **params):
        from resources.lib.simkl.ids import show_api_path

        return self.get_catalog_json(show_api_path(simkl_id, slug), **params)

    def get_movie_json(self, simkl_id: int, slug: str | None = None, **params):
        from resources.lib.simkl.ids import movie_api_path

        return self.get_catalog_json(movie_api_path(simkl_id, slug), **params)

    def post_json(self, url, json_data=None, authorized: bool = True, **params):
        response = self.post(url, json_data=json_data, authorized=authorized, **params)
        if response is None or not response.text:
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            return {}

    @simkl_guard_response
    def delete(self, url, authorized: bool = True, **params):
        timeout = params.pop("timeout", 15)
        return self._request(
            "delete",
            url,
            authorized=authorized,
            api_key=True,
            merge_cdn=authorized,
            params=params or None,
            timeout=timeout,
        )

    def delete_request(self, url, authorized: bool = True, **params):
        return self.delete(url, authorized=authorized, **params)

    @staticmethod
    def _premium_only_payload(body: Any) -> bool:
        return isinstance(body, dict) and body.get("error") == "premium_only"

    def get_user_lists(self, user_id: int, **params):
        """List custom lists for a Simkl user (beta, read-only)."""
        return self.get_json(f"/lists/user/{int(user_id)}", **params)

    def get_custom_list(self, list_id: int, **params):
        """Fetch one custom list and its items (beta, read-only; PRO/VIP for real items)."""
        return self.get_json(f"/lists/{int(list_id)}", **params)

    def add_to_history(self, payload: dict):
        return self.post_json("/sync/history", payload)

    def remove_from_history(self, payload: dict):
        return self.post_json("/sync/history/remove", payload)

    def add_to_list(self, payload: dict):
        return self.post_json("/sync/add-to-list", payload)

    def add_ratings(self, payload: dict):
        return self.post_json("/sync/ratings", payload)

    def remove_ratings(self, payload: dict):
        return self.post_json("/sync/ratings/remove", payload)

    def scrobble_start(self, payload: dict):
        return self.post("/scrobble/start", json_data=payload)

    def scrobble_pause(self, payload: dict):
        return self.post("/scrobble/pause", json_data=payload)

    def scrobble_stop(self, payload: dict):
        return self.post("/scrobble/stop", json_data=payload)

    def delete_playback(self, playback_id):
        return self.delete(f"/sync/playback/{playback_id}")

    def get_playback(self, media_type: str | None = None, date_from: str | None = None, **params):
        if media_type:
            segment = PLAYBACK_PATH_TYPES.get(media_type, media_type)
            url = f"/sync/playback/{segment}"
        else:
            url = "/sync/playback"
        query = dict(params)
        if date_from:
            query["date_from"] = date_from
        query.setdefault("hide_watched", "false")
        return self.get_json(url, **query)

    @use_cache(cache_hours=168)
    def redirect_simkl_id(
        self,
        *,
        imdb: str | None = None,
        type: str | None = None,
        tmdb: int | None = None,
    ) -> tuple[int, str] | None:
        """Resolve external id via GET /redirect (read Location header, do not follow)."""
        import re

        params = dict(self._cdn_query())
        params["to"] = "simkl"
        if imdb:
            from resources.lib.simkl.field_map import _normalize_imdb_id

            normalized = _normalize_imdb_id(imdb)
            if normalized:
                params["imdb"] = normalized
        if tmdb is not None:
            params["tmdb"] = int(tmdb)
        if type in ("movie", "tv"):
            params["type"] = type
        if not any(key in params for key in ("imdb", "tmdb")):
            return None
        try:
            response = self.session.get(
                parse.urljoin(self.ApiUrl, "/redirect"),
                params=params,
                headers=self._build_headers(
                    authorized=bool(self.access_token),
                    api_key=True,
                    api_key_client_id=self.client_id,
                ),
                allow_redirects=False,
                timeout=15,
            )
        except Exception:
            g.log_stacktrace()
            return None
        if response is None or response.status_code not in (301, 302, 303, 307, 308):
            return None
        location = response.headers.get("Location") or ""
        match = re.search(r"/(movies|tv|anime)/(\d+)", location)
        if not match:
            return None
        segment, simkl_id = match.group(1), int(match.group(2))
        catalog = {"movies": "movie", "tv": "tv", "anime": "anime"}.get(segment, "tv")
        return simkl_id, catalog

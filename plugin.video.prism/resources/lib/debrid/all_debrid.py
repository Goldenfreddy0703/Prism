import time
from functools import cached_property
from functools import wraps
from urllib import parse

import xbmc
import xbmcgui

from resources.lib.common import tools
from resources.lib.database.cache import use_cache
from resources.lib.modules.globals import g

AD_AUTH_KEY = "alldebrid.apikey"
AD_ENABLED_KEY = "alldebrid.enabled"
V4_BASE_URL = "https://api.alldebrid.com/v4/"
V41_BASE_URL = "https://api.alldebrid.com/v4.1/"
_AUTH_NOTICE_SHOWN = False
_DEVICE_AUTH_NOTICE_SHOWN = False


def alldebrid_guard_response(func):
    @wraps(func)
    def wrapper(*args, **kwarg):
        import requests

        try:
            response = func(*args, **kwarg)
            if response is None:
                return None
            if response.status_code in [200, 201]:
                return response

            if response.status_code == 429:
                g.log("Alldebrid Throttling Applied, Sleeping for 1 seconds")
                xbmc.sleep(1 * 1000)
                response = func(*args, **kwarg)
                if response is not None and response.status_code in [200, 201]:
                    return response

            g.log(
                f"AllDebrid returned a {response.status_code} ({AllDebrid.http_codes.get(response.status_code, 'Unknown')}): "
                f"while requesting {response.url}",
                "warning",
            )
            return None
        except requests.exceptions.ConnectionError:
            return None
        except Exception:
            xbmcgui.Dialog().notification(g.ADDON_NAME, g.get_language_string(30024).format("AllDebrid"))
            raise

    return wrapper


class AllDebrid:
    http_codes = {
        200: "Success",
        400: "Bad Request, The request was unacceptable, often due to missing a required parameter",
        401: "Unauthorized",
        404: "Not Found, Api endpoint doesn't exist",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
        524: "Internal Server Error",
    }

    def __init__(self):
        self.apikey = (g.get_setting(AD_AUTH_KEY) or "").strip()
        self.last_error_code = None
        self.last_error_message = None
        self.last_verification_token = None

    @cached_property
    def session(self):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3 import Retry

        session = requests.Session()
        retries = Retry(total=5, backoff_factor=0.1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retries, pool_maxsize=100))
        return session

    def _auth_headers(self):
        if self.apikey:
            return {"Authorization": f"Bearer {self.apikey}"}
        return {}

    def _extract_data(self, response):
        if not isinstance(response, dict):
            return response
        if response.get("status") == "error":
            error = response.get("error") or {}
            self.last_error_code = error.get("code")
            self.last_error_message = error.get("message")
            self.last_verification_token = error.get("token")
            g.log(
                f"AllDebrid API error: {error.get('code')}: {error.get('message')}",
                "warning",
            )
            if self.is_device_location_block():
                self._notify_device_auth_block_once()
            elif self.is_auth_error():
                self._notify_auth_failure_once()
            return None
        return response["data"] if "data" in response else response

    def _json_response(self, response):
        if response is None:
            return None
        try:
            return self._extract_data(response.json())
        except (AttributeError, ValueError, TypeError):
            return None

    @alldebrid_guard_response
    def _request(self, method, base_url, endpoint, *, data=None, params=None, auth=True):
        if not g.get_bool_setting(AD_ENABLED_KEY):
            return None
        if auth and not self.apikey:
            return None
        return self.session.request(
            method,
            parse.urljoin(base_url, endpoint),
            params=params or None,
            data=data,
            headers=self._auth_headers() if auth else {},
        )

    def get_v4(self, endpoint, *, auth=True, **params):
        return self._request("GET", V4_BASE_URL, endpoint, params=params or None, auth=auth)

    def post_v4(self, endpoint, post_data=None, *, auth=True, **params):
        return self._request(
            "POST",
            V4_BASE_URL,
            endpoint,
            data=post_data,
            params=params or None,
            auth=auth,
        )

    def get_v41(self, endpoint, *, auth=True, **params):
        return self._request("GET", V41_BASE_URL, endpoint, params=params or None, auth=auth)

    def post_v41(self, endpoint, post_data=None, *, auth=True, **params):
        return self._request(
            "POST",
            V41_BASE_URL,
            endpoint,
            data=post_data,
            params=params or None,
            auth=auth,
        )

    def get_json(self, endpoint, *, auth=True, **params):
        return self._json_response(self.get_v4(endpoint, auth=auth, **params))

    def post_json(self, endpoint, post_data=None, *, auth=True, **params):
        return self._json_response(self.post_v4(endpoint, post_data, auth=auth, **params))

    def post_v41_json(self, endpoint, post_data=None, *, auth=True):
        return self._json_response(self.post_v41(endpoint, post_data, auth=auth))

    @staticmethod
    def _normalize_magnets_list(magnets):
        if not magnets:
            return []
        if isinstance(magnets, dict):
            if "id" in magnets and ("status" in magnets or "statusCode" in magnets):
                return [magnets]
            return [value for value in magnets.values() if isinstance(value, dict)]
        if isinstance(magnets, list):
            return [item for item in magnets if isinstance(item, dict)]
        return []

    @staticmethod
    def _find_magnet(magnets, magnet_id):
        for magnet in AllDebrid._normalize_magnets_list(magnets):
            if str(magnet.get("id")) == str(magnet_id):
                return magnet
        return None

    @staticmethod
    def _flatten_files_to_links(files, path_parts=None):
        """Convert v4.1 magnet/files tree nodes into legacy v4 link objects."""
        path_parts = path_parts or []
        links = []
        for entry in files or []:
            name = entry.get("n") or ""
            if entry.get("l"):
                file_path = "/".join(path_parts + [name]) if path_parts else name
                links.append(
                    {
                        "link": entry["l"],
                        "filename": name,
                        "path": file_path,
                        "size": entry.get("s", 0),
                        "files": [{"n": file_path}],
                    }
                )
            elif entry.get("e"):
                links.extend(AllDebrid._flatten_files_to_links(entry["e"], path_parts + [name]))
        return links

    def _magnet_files_payload(self, magnet_ids):
        magnet_ids = [magnet_id for magnet_id in magnet_ids if magnet_id is not None]
        if not magnet_ids:
            return {}
        post_data = [("id[]", magnet_id) for magnet_id in magnet_ids]
        payload = self.post_v41_json("magnet/files", post_data=post_data)
        if not isinstance(payload, dict):
            return {}
        links_by_id = {}
        for magnet in self._normalize_magnets_list(payload.get("magnets")):
            if magnet.get("error"):
                continue
            magnet_id = magnet.get("id")
            links_by_id[str(magnet_id)] = self._flatten_files_to_links(magnet.get("files"))
        return links_by_id

    def get_magnet_links(self, magnet_id):
        return self._magnet_files_payload([magnet_id]).get(str(magnet_id)) or []

    def get_magnet_files_tree(self, magnet_id):
        """Return the raw magnet/files tree for a single magnet id."""
        payload = self.post_v41_json("magnet/files", post_data=[("id[]", magnet_id)])
        if not isinstance(payload, dict):
            return []
        for magnet in self._normalize_magnets_list(payload.get("magnets")):
            if magnet.get("error"):
                continue
            if str(magnet.get("id")) == str(magnet_id):
                return magnet.get("files") or []
        magnets = self._normalize_magnets_list(payload.get("magnets"))
        if len(magnets) == 1 and not magnets[0].get("error"):
            return magnets[0].get("files") or []
        return []

    def _attach_magnet_links(self, magnet):
        if not isinstance(magnet, dict):
            return magnet
        magnet = dict(magnet)
        if magnet.get("status") == "Ready" or magnet.get("statusCode") == 4:
            links_by_id = self._magnet_files_payload([magnet.get("id")])
            magnet["links"] = links_by_id.get(str(magnet.get("id"))) or []
        else:
            magnet.setdefault("links", [])
        return magnet

    def auth(self):
        from resources.lib.modules.qr_auth import (
            auth_progress_percent,
            capped_auth_timeout,
            open_auth_dialog,
            show_auth_timeout,
        )

        resp = self._json_response(self.get_v41("pin/get", auth=False))
        if not resp:
            return
        pin_ttl = capped_auth_timeout(resp["expires_in"])
        expiry = pin_ttl
        auth_complete = False
        auth_check = None
        cancelled = False
        progress = open_auth_dialog(
            f"{g.ADDON_NAME}: {g.get_language_string(30334)}",
            resp.get("base_url") or resp.get("user_url") or "https://alldebrid.com/pin/",
            user_code=resp["pin"],
        )
        try:
            xbmc.sleep(5 * 1000)

            while not auth_complete and expiry > 0 and not progress.iscanceled():
                auth_check = self.post_v41_json(
                    "pin/check",
                    post_data={"pin": resp["pin"], "check": resp["check"]},
                    auth=False,
                )
                if auth_check and auth_check.get("activated"):
                    auth_complete = True
                    break
                progress.update(auth_progress_percent(expiry, pin_ttl))
                xbmc.sleep(1 * 1000)
                expiry -= 1

            if auth_complete and not progress.iscanceled() and auth_check is not None:
                g.set_setting(AD_AUTH_KEY, auth_check["apikey"])
                self.apikey = auth_check["apikey"].strip()
                self.store_user_info()
            cancelled = progress.iscanceled()
        finally:
            progress.close()

        if auth_complete:
            global _AUTH_NOTICE_SHOWN
            _AUTH_NOTICE_SHOWN = False
            from resources.lib.debrid import external_cache

            external_cache.prime_ad_cache_checker_devices()
            xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(31119))
        elif not cancelled:
            show_auth_timeout("AllDebrid")

    def get_user_info(self):
        user_payload = self.get_json("user")
        if not isinstance(user_payload, dict):
            return {}
        return user_payload.get("user", {})

    def store_user_info(self):
        user_information = self.get_user_info()
        if user_information:
            g.set_setting("alldebrid.username", user_information["username"])
            g.set_setting("alldebrid.premiumstatus", self.get_account_status().title())

    def is_device_location_block(self):
        return self.last_error_code == "AUTH_BLOCKED"

    def is_auth_error(self):
        return self.last_error_code in {
            "AUTH_BAD_APIKEY",
            "AUTH_MISSING_APIKEY",
            "AUTH_BLOCKED",
            "AUTH_BLOCKED_ACCOUNT",
            "AUTH_USER_BANNED",
        }

    def _notify_device_auth_block_once(self):
        global _DEVICE_AUTH_NOTICE_SHOWN
        if _DEVICE_AUTH_NOTICE_SHOWN:
            return
        _DEVICE_AUTH_NOTICE_SHOWN = True
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(31114))

    def poll_device_verification(self, token=None, timeout=300):
        """Poll /user/verif until the user approves the device on AllDebrid."""
        token = token or self.last_verification_token
        if not token:
            return False
        deadline = time.time() + max(int(timeout), 5)
        while time.time() < deadline and not g.abort_requested():
            payload = self.post_json("user/verif", post_data={"token": token}, auth=False)
            if not isinstance(payload, dict):
                return False
            status = payload.get("verif")
            if status == "allowed":
                if payload.get("apikey"):
                    g.set_setting(AD_AUTH_KEY, payload["apikey"])
                    self.apikey = payload["apikey"].strip()
                global _DEVICE_AUTH_NOTICE_SHOWN
                _DEVICE_AUTH_NOTICE_SHOWN = False
                return True
            if status == "denied":
                return False
            xbmc.sleep(5000)
        return False

    def _notify_auth_failure_once(self):
        global _AUTH_NOTICE_SHOWN
        if _AUTH_NOTICE_SHOWN:
            return
        _AUTH_NOTICE_SHOWN = True
        xbmcgui.Dialog().ok(
            g.ADDON_NAME,
            "AllDebrid authorization failed.\nPlease re-authorize AllDebrid in Prism settings.",
        )

    def upload_magnet(self, magnet_ref):
        self.last_error_code = None
        self.last_error_message = None
        return self.post_json("magnet/upload", post_data=[("magnets[]", magnet_ref)])

    def wait_for_magnet_ready(self, magnet_id, timeout=180):
        """Poll magnet/status until Ready or timeout."""
        status = {}
        deadline = time.time() + timeout
        while time.time() < deadline and not g.abort_requested():
            payload = self.magnet_status(magnet_id)
            status = payload.get("magnets") if isinstance(payload, dict) else {}
            if not isinstance(status, dict):
                status = {}
            if status.get("status") == "Ready" or status.get("statusCode") == 4:
                return status
            if status.get("status") in ("Error", "Magnet error", "Failed"):
                break
            xbmc.sleep(1000)
        return status

    def fetch_magnet_file_links(self, magnet_ref, timeout=180):
        """
        Upload a magnet/hash, wait until cached, and return flattened file links.
        :return: (magnet_id, links)
        """
        from resources.lib.modules.exceptions import AuthFailure
        from resources.lib.modules.exceptions import GeneralCachingFailure
        from resources.lib.modules.exceptions import UnexpectedResponse

        upload = self.upload_magnet(magnet_ref)
        if not upload or not upload.get("magnets"):
            if self.is_auth_error():
                raise AuthFailure(
                    f"{self.last_error_code}: {self.last_error_message}"
                )
            raise UnexpectedResponse(upload or "AllDebrid magnet upload failed")

        entry = upload["magnets"][0]
        if entry.get("error"):
            raise UnexpectedResponse(entry["error"])

        magnet_id = entry.get("id")
        if not magnet_id:
            raise UnexpectedResponse(entry)

        if entry.get("ready"):
            links = self.get_magnet_links(magnet_id)
            if links:
                return magnet_id, links

        status = self.wait_for_magnet_ready(magnet_id, timeout)
        if status.get("status") != "Ready" and status.get("statusCode") != 4:
            raise GeneralCachingFailure(status)

        links = status.get("links") or self.get_magnet_links(magnet_id)
        if not links:
            raise UnexpectedResponse(status or "AllDebrid returned no files for magnet")
        return magnet_id, links

    @use_cache(1)
    def update_relevant_hosters(self):
        return self.get_json("hosts")

    def get_hosters(self, hosters):
        host_list = self.update_relevant_hosters()
        if host_list is not None:
            hosters["premium"]["all_debrid"] = [
                (d, d.split(".")[0])
                for l in host_list["hosts"].values()
                if "status" in l and l["status"]
                for d in l["domains"]
            ]
        else:
            g.log_stacktrace()
            hosters["premium"]["all_debrid"] = []

    def _poll_delayed_link(self, delayed_id, timeout=120):
        """Poll /link/delayed until the download link is ready."""
        deadline = time.time() + max(int(timeout), 5)
        while time.time() < deadline and not g.abort_requested():
            payload = self.post_json("link/delayed", post_data={"id": delayed_id})
            if not isinstance(payload, dict):
                return None
            if payload.get("link"):
                return payload["link"]
            if payload.get("status") not in (1, None):
                break
            xbmc.sleep(5000)
        return None

    def _resolve_stream_link(self, unlock_payload):
        streams = unlock_payload.get("streams") or []
        if not streams:
            return unlock_payload.get("link")
        stream = max(
            streams,
            key=lambda item: int(item.get("quality") or item.get("filesize") or 0),
        )
        stream_payload = self.post_json(
            "link/streaming",
            post_data={"id": unlock_payload.get("id"), "stream": stream.get("id")},
        )
        if not isinstance(stream_payload, dict):
            return None
        if stream_payload.get("link"):
            return stream_payload["link"]
        if stream_payload.get("delayed"):
            return self._poll_delayed_link(stream_payload["delayed"])
        return None

    def resolve_hoster(self, url):
        """Unlock an AllDebrid link (POST /v4/link/unlock per current API)."""
        resolve = self.post_json("link/unlock", post_data={"link": url})
        if not isinstance(resolve, dict):
            return None
        if resolve.get("delayed"):
            return self._poll_delayed_link(resolve["delayed"])
        if resolve.get("streams"):
            return self._resolve_stream_link(resolve)
        return resolve.get("link")

    def magnet_status(self, magnet_id=None, status_filter=None):
        """
        v4.1 magnet/status wrapper.

        When magnet_id is provided, returns {"magnets": <single magnet dict>} for legacy callers.
        Otherwise returns {"magnets": [<magnet dict>, ...]}.
        """
        post_data = {}
        if magnet_id is not None:
            post_data["id"] = magnet_id
        if status_filter:
            post_data["status"] = status_filter

        payload = self.post_v41_json("magnet/status", post_data=post_data or None)
        if not isinstance(payload, dict):
            return {"magnets": [] if magnet_id is None else {}}

        magnets = self._normalize_magnets_list(payload.get("magnets"))
        if magnet_id is not None:
            magnet = self._find_magnet(magnets, magnet_id) or (magnets[0] if len(magnets) == 1 else None)
            if magnet is None:
                return {"magnets": {}}
            return {"magnets": self._attach_magnet_links(magnet)}

        ready_ids = [magnet.get("id") for magnet in magnets if magnet.get("status") == "Ready"]
        links_by_id = self._magnet_files_payload(ready_ids) if ready_ids else {}
        enriched = []
        for magnet in magnets:
            item = dict(magnet)
            if item.get("status") == "Ready":
                item["links"] = links_by_id.get(str(item.get("id"))) or []
            else:
                item["links"] = []
            enriched.append(item)
        return {"magnets": enriched}

    def saved_magnets(self):
        payload = self.magnet_status(status_filter="ready")
        if not isinstance(payload, dict):
            return []
        return self._normalize_magnets_list(payload.get("magnets"))

    def delete_magnet(self, magnet_id):
        return self.post_json("magnet/delete", post_data={"id": magnet_id})

    def saved_links(self):
        payload = self.get_json("user/links")
        if isinstance(payload, dict):
            payload.setdefault("links", [])
            return payload
        return {"links": []}

    @staticmethod
    def is_service_enabled():
        return g.get_bool_setting(AD_ENABLED_KEY) and bool((g.get_setting(AD_AUTH_KEY) or "").strip())

    def get_account_status(self):
        user_info = self.get_user_info()
        if not isinstance(user_info, dict):
            return "unknown"

        premium = user_info.get("isPremium")
        premium_until = user_info.get("premiumUntil", 0)
        subscribed = user_info.get("isSubscribed")
        trial = user_info.get("isTrial")

        if premium and premium_until > time.time():
            return "premium"
        if subscribed:
            return "subscribed"
        if trial:
            return "trial"
        return "unknown"

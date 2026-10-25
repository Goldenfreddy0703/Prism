"""Sync HTTP entry points for indexers and menu code."""
from __future__ import annotations

import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from resources.lib.modules.globals import g

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504, 520, 521, 522, 524})


def http_gateway_enabled() -> bool:
    return True


def build_session(provider: str) -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.15,
        status_forcelist=list(_RETRY_STATUS),
        allowed_methods=frozenset(["GET", "POST", "HEAD", "PUT", "DELETE", "OPTIONS"]),
    )
    adapter = HTTPAdapter(max_retries=retries, pool_maxsize=50, pool_connections=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if provider == "simkl":
        from resources.lib.indexers.simkl import SIMKL_APP_NAME, SIMKL_APP_VERSION

        session.headers.update({"User-Agent": f"{SIMKL_APP_NAME}/{SIMKL_APP_VERSION}"})
    return session


def session_request_with_retries(
    session: requests.Session,
    provider: str,
    method: str,
    url: str,
    *,
    kind: str | None = None,
    max_attempts: int = 3,
    **kwargs: Any,
) -> requests.Response | None:
    from resources.lib.net.http_ledger import record_http, record_http_response

    kind = kind or method.lower()
    from resources.lib.net.request_policy import get_request_policy

    policy = get_request_policy()
    budget_exempt = policy._budget_exempt(provider, url=url, method=method)
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        started = time.time()
        try:
            response = session.request(method, url, **kwargs)
        except requests.RequestException:
            record_http(
                provider,
                kind,
                (time.time() - started) * 1000.0,
                budget_exempt=budget_exempt,
            )
            if attempt >= max_attempts:
                return None
            time.sleep(min(2.0 ** attempt * 0.1, 2.0))
            continue
        record_http_response(provider, kind, started, response, budget_exempt=budget_exempt)
        if response.status_code in _RETRY_STATUS and attempt < max_attempts:
            time.sleep(min(2.0 ** attempt * 0.15, 3.0))
            continue
        return response
    return None


def _perform_sync_request(
    provider: str,
    method: str,
    url: str,
    *,
    kind: str,
    session: requests.Session | None,
    max_attempts: int,
    kwargs: dict[str, Any],
) -> requests.Response | None:
    from resources.lib.net.http_sessions import get_http_sessions

    sess = session or get_http_sessions().session_for(provider)
    return session_request_with_retries(
        sess,
        provider,
        method,
        url,
        kind=kind,
        max_attempts=max_attempts,
        **kwargs,
    )


def sync_http_request(
    provider: str,
    method: str,
    url: str,
    *,
    kind: str | None = None,
    session: requests.Session | None = None,
    max_attempts: int = 3,
    **kwargs: Any,
) -> requests.Response | None:
    """Policy + shared sessions; blocking requests only."""
    kind = kind or method.lower()
    from resources.lib.net.request_policy import get_request_policy

    policy = get_request_policy()
    use_policy = http_gateway_enabled()
    budgeted = use_policy and not policy._budget_exempt(provider, url=url, method=method)
    if use_policy and not policy.consume_budget(provider, url=url, method=method):
        return None

    params = kwargs.get("params")
    dedupe_get = use_policy and method.upper() == "GET"

    try:
        if dedupe_get:
            key = policy._dedupe_key(provider, method, url, params)

            def _do() -> requests.Response | None:
                return _perform_sync_request(
                    provider,
                    method,
                    url,
                    kind=kind,
                    session=session,
                    max_attempts=max_attempts,
                    kwargs=kwargs,
                )

            return policy.dedupe_or_run_sync(key, _do)

        return _perform_sync_request(
            provider,
            method,
            url,
            kind=kind,
            session=session,
            max_attempts=max_attempts,
            kwargs=kwargs,
        )
    except Exception:
        g.log_stacktrace()
        if session is not None:
            return session_request_with_retries(
                session,
                provider,
                method,
                url,
                kind=kind,
                max_attempts=max_attempts,
                **kwargs,
            )
        return session_request_with_retries(
            build_session(provider),
            provider,
            method,
            url,
            kind=kind,
            max_attempts=max_attempts,
            **kwargs,
        )
    finally:
        if budgeted:
            policy.release_provider_slot(provider)

"""Central caps and in-flight dedupe for outbound HTTP."""
from __future__ import annotations

import concurrent.futures
import hashlib
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from resources.lib.common.concurrency import (
    http_concurrent_cap,
    menu_http_budget,
    per_provider_caps,
)
from resources.lib.modules.globals import g

T = TypeVar("T")


def _build_policy() -> RequestPolicy:
    max_menu = menu_http_budget()
    return RequestPolicy(
        max_concurrent=http_concurrent_cap(),
        max_per_menu_open=max_menu,
        per_provider_cap=per_provider_caps(),
        menu_budget_remaining=max_menu,
    )


@dataclass
class RequestPolicy:
    max_concurrent: int = 20
    max_per_menu_open: int = 80
    per_provider_cap: dict[str, int] = field(default_factory=dict)
    menu_budget_remaining: int = 80
    _inflight: dict[str, concurrent.futures.Future] = field(default_factory=dict, repr=False)
    _provider_counts: dict[str, int] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reset_menu_budget(self) -> None:
        self.menu_budget_remaining = int(self.max_per_menu_open)
        with self._lock:
            self._provider_counts.clear()

    def _dedupe_key(self, provider: str, method: str, url: str, params: Any) -> str:
        raw = f"{provider}|{method}|{url}|{params!r}"
        return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()

    def allow_request(
        self,
        provider: str,
        *,
        url: str | None = None,
        method: str = "GET",
    ) -> bool:
        if self._budget_exempt(provider, url=url, method=method):
            return True
        if self.menu_budget_remaining <= 0:
            return False
        cap = self.per_provider_cap.get(provider) or self.per_provider_cap.get("default", 16)
        with self._lock:
            used = self._provider_counts.get(provider, 0)
        return used < cap

    @staticmethod
    def _budget_exempt(provider: str, *, url: str | None, method: str) -> bool:
        if provider != "simkl" or not url:
            return False
        from resources.lib.net.simkl_policy import simkl_menu_budget_exempt

        return simkl_menu_budget_exempt(url, method)

    def consume_budget(
        self,
        provider: str,
        *,
        url: str | None = None,
        method: str = "GET",
    ) -> bool:
        if self._budget_exempt(provider, url=url, method=method):
            return True
        if not self.allow_request(provider, url=url, method=method):
            g.log(f"RequestPolicy: blocked {provider} (budget or cap)", "debug")
            return False
        self.menu_budget_remaining -= 1
        with self._lock:
            self._provider_counts[provider] = self._provider_counts.get(provider, 0) + 1
        return True

    def release_provider_slot(self, provider: str) -> None:
        with self._lock:
            count = self._provider_counts.get(provider, 0)
            if count > 1:
                self._provider_counts[provider] = count - 1
            elif provider in self._provider_counts:
                del self._provider_counts[provider]

    def dedupe_or_run_sync(self, key: str, fn: Callable[[], T], *, timeout: float = 120.0) -> T:
        """Share one in-flight call per dedupe key."""
        with self._lock:
            existing = self._inflight.get(key)
            if existing is not None and not existing.done():
                waiter = existing
                owner = False
            else:
                waiter = concurrent.futures.Future()
                self._inflight[key] = waiter
                owner = True

        if not owner:
            return waiter.result(timeout=timeout)

        try:
            result = fn()
            waiter.set_result(result)
            return result
        except BaseException as exc:
            waiter.set_exception(exc)
            raise
        finally:
            with self._lock:
                if self._inflight.get(key) is waiter:
                    del self._inflight[key]


_policy: RequestPolicy | None = None
_policy_lock = threading.Lock()


def get_request_policy() -> RequestPolicy:
    global _policy
    with _policy_lock:
        if _policy is None:
            _policy = _build_policy()
        return _policy


def policy_from_settings() -> RequestPolicy:
    """Rebuild policy when threadpool scale changes or menu budget resets."""
    global _policy
    with _policy_lock:
        _policy = _build_policy()
        return _policy

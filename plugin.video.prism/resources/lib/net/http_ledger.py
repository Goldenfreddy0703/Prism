"""Per-menu-open HTTP accounting (debug + menu_perf)."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

_ledger_lock = threading.Lock()
_scope_stack: list[HttpLedger] = []


class HttpLedger:
    """Accumulates outbound HTTP for the current menu scope."""

    __slots__ = ("action", "path", "count", "total_ms", "json_bytes", "_by_kind")

    def __init__(self, action: str = "", path: str = "") -> None:
        self.action = action
        self.path = path
        self.count = 0
        self.total_ms = 0.0
        self.json_bytes = 0
        self._by_kind: dict[str, int] = {}

    def record(
        self,
        provider: str,
        kind: str,
        elapsed_ms: float,
        *,
        response_bytes: int = 0,
        budget_exempt: bool = False,
    ) -> None:
        self.count += 1
        self.total_ms += max(0.0, float(elapsed_ms))
        if response_bytes > 0:
            self.json_bytes += int(response_bytes)
        key = f"{provider}:{kind}"
        if budget_exempt:
            key = f"{key}:cdn_exempt"
        self._by_kind[key] = self._by_kind.get(key, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "http_count": self.count,
            "http_ms": round(self.total_ms, 1),
            "json_bytes": self.json_bytes,
            "http_by_kind": dict(self._by_kind),
        }


def current_ledger() -> HttpLedger | None:
    with _ledger_lock:
        return _scope_stack[-1] if _scope_stack else None


def record_http(
    provider: str,
    kind: str,
    elapsed_ms: float,
    *,
    response_bytes: int = 0,
    budget_exempt: bool = False,
) -> None:
    ledger = current_ledger()
    if ledger is None:
        return
    ledger.record(
        provider,
        kind,
        elapsed_ms,
        response_bytes=response_bytes,
        budget_exempt=budget_exempt,
    )


def record_http_response(
    provider: str,
    kind: str,
    started: float,
    response: Any,
    *,
    budget_exempt: bool = False,
) -> None:
    elapsed_ms = (time.time() - started) * 1000.0
    nbytes = 0
    if response is not None:
        try:
            nbytes = len(response.content or b"")
        except Exception:
            try:
                nbytes = len(response.text or "")
            except Exception:
                nbytes = 0
    record_http(
        provider,
        kind,
        elapsed_ms,
        response_bytes=nbytes,
        budget_exempt=budget_exempt,
    )


@contextmanager
def menu_http_scope(action: str, path: str = "") -> Iterator[HttpLedger]:
    ledger = HttpLedger(action=action, path=path)
    with _ledger_lock:
        _scope_stack.append(ledger)
    try:
        yield ledger
    finally:
        with _ledger_lock:
            if _scope_stack and _scope_stack[-1] is ledger:
                _scope_stack.pop()

"""Per-provider requests.Session pools (Seren-style, sync only)."""
from __future__ import annotations

import threading

import requests

_sessions: HttpSessions | None = None
_singleton_lock = threading.Lock()


class HttpSessions:
    def __init__(self) -> None:
        self._sessions: dict[str, requests.Session] = {}
        self._session_lock = threading.Lock()

    def session_for(self, provider: str) -> requests.Session:
        with self._session_lock:
            session = self._sessions.get(provider)
            if session is None:
                from resources.lib.net.sync_bridge import build_session

                session = build_session(provider)
                self._sessions[provider] = session
            return session

    def close_all(self) -> None:
        with self._session_lock:
            for session in list(self._sessions.values()):
                try:
                    session.close()
                except Exception:
                    pass
            self._sessions.clear()


def get_http_sessions() -> HttpSessions:
    global _sessions
    if _sessions is None:
        with _singleton_lock:
            if _sessions is None:
                _sessions = HttpSessions()
    return _sessions


def close_all_sessions() -> None:
    global _sessions
    if _sessions is not None:
        _sessions.close_all()

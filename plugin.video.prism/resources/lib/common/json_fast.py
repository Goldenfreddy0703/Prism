"""JSON parse/dump with optional orjson/ujson on Kodi Python."""
from __future__ import annotations

import json
from typing import Any

_ORJSON = None
_UJSON = None

try:
    import orjson as _orjson_mod

    _ORJSON = _orjson_mod
except ImportError:
    pass

try:
    import ujson as _ujson_mod

    _UJSON = _ujson_mod
except ImportError:
    pass


def loads(payload: str | bytes) -> Any:
    if _ORJSON is not None:
        return _ORJSON.loads(payload)
    if _UJSON is not None:
        return _UJSON.loads(payload)
    return json.loads(payload)


def dumps(obj: Any) -> str:
    if _ORJSON is not None:
        return _ORJSON.dumps(obj).decode("utf-8")
    if _UJSON is not None:
        return _UJSON.dumps(obj)
    return json.dumps(obj)

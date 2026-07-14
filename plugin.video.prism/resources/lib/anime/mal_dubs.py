"""MAL-Dubs dub lookup (https://github.com/MAL-Dubs/MAL-Dubs)."""
from __future__ import annotations

import json
import os
import time

from resources.lib.modules.globals import g

MAL_DUBS_URL = "https://raw.githubusercontent.com/MAL-Dubs/MAL-Dubs/main/data/dubInfo.json"
MAL_DUB_FILENAME = "mal_dub.json"
MAL_DUBS_REFRESH_DAYS = 7

_dub_ids: set[str] | None = None


def _mal_dub_path() -> str:
    return os.path.join(g.ADDON_USERDATA_PATH, MAL_DUB_FILENAME)


def _load_dub_ids() -> set[str]:
    global _dub_ids
    if _dub_ids is not None:
        return _dub_ids

    _dub_ids = set()
    try:
        with open(_mal_dub_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return _dub_ids

    if isinstance(payload, dict):
        dubbed = payload.get("dubbed")
        if isinstance(dubbed, list):
            _dub_ids = {str(item) for item in dubbed if item is not None}
        else:
            for key, value in payload.items():
                if str(key).startswith("_"):
                    continue
                if value is True or (isinstance(value, dict) and value.get("dub")):
                    _dub_ids.add(str(key))
    return _dub_ids


def has_dub(mal_id) -> bool:
    try:
        return str(int(mal_id)) in _load_dub_ids()
    except (TypeError, ValueError):
        return False


def update_mal_dub_list() -> bool:
    """Refresh MAL-Dubs JSON in addon userdata."""
    global _dub_ids

    dub_file = _mal_dub_path()
    if os.path.exists(dub_file):
        age_days = (time.time() - os.path.getmtime(dub_file)) / 86400
        if age_days < MAL_DUBS_REFRESH_DAYS:
            return True

    try:
        import requests

        response = requests.get(
            MAL_DUBS_URL,
            timeout=15,
            headers={"User-Agent": f"{g.ADDON_ID}/{g.ADDON.getAddonInfo('version')}"},
        )
        if not response.ok:
            g.log(f"MAL-Dubs download failed: HTTP {response.status_code}", "warning")
            return False

        dubbed = (response.json() or {}).get("dubbed") or []
        mal_dub = {str(item): {"dub": True} for item in dubbed if item is not None}

        os.makedirs(g.ADDON_USERDATA_PATH, exist_ok=True)
        with open(dub_file, "w", encoding="utf-8") as handle:
            json.dump(mal_dub, handle)

        _dub_ids = set(mal_dub)
        g.log(f"MAL-Dubs list updated: {len(mal_dub)} entries", "info")
        return True
    except Exception as exc:
        g.log(f"MAL-Dubs update failed: {exc}", "warning")
        return False

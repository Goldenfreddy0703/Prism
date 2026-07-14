"""action_args normalization — delegates to plugin.video.prism when available."""

from __future__ import annotations

import sys

import xbmcaddon

PRISM_ADDON_ID = "plugin.video.prism"

# Re-exported for tools.py (synthetic season helpers used outside normalize_action_args).
SEASON_ID_FACTOR = 100_000
MAX_SYNTHETIC_SEASON = 999


def season_key(show_id, season_num):
    return int(show_id) * SEASON_ID_FACTOR + int(season_num)


def is_synthetic_season_id(value):
    if value is None:
        return False
    value = int(value)
    if value <= 0:
        return False
    show_id, season_num = split_synthetic_season_id(value)
    if show_id <= 0 or season_num < 0 or season_num > MAX_SYNTHETIC_SEASON:
        return False
    if season_key(show_id, season_num) != value:
        return False
    return value >= show_id * SEASON_ID_FACTOR


def split_synthetic_season_id(season_row_id):
    season_row_id = int(season_row_id)
    return season_row_id // SEASON_ID_FACTOR, season_row_id % SEASON_ID_FACTOR


def _load_prism_normalize():
    try:
        addon = xbmcaddon.Addon(PRISM_ADDON_ID)
        lib_path = addon.getAddonInfo("path") + "/resources/lib"
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)
        from simkl.ids import normalize_action_args as prism_normalize

        return prism_normalize
    except Exception:
        return None


_prism_normalize = _load_prism_normalize()


def normalize_action_args(action_args):
    if _prism_normalize is not None:
        return _prism_normalize(action_args)
    return _normalize_action_args_fallback(action_args)


def _normalize_action_args_fallback(action_args):
    if not action_args or not isinstance(action_args, dict):
        return action_args

    args = dict(action_args)
    mediatype = args.get("mediatype")

    if mediatype == "tvshow":
        args.pop("simkl_show_id", None)
        args.pop("simkl_season_id", None)
        args.pop("season", None)
        return args

    if mediatype == "movie":
        args.pop("simkl_show_id", None)
        args.pop("simkl_season_id", None)
        return args

    if mediatype == "season":
        show_id = args.get("simkl_show_id")
        season_num = args.get("season")
        item_id = args.get("simkl_id")

        if show_id is None and item_id is not None and season_num is not None:
            explicit_show = int(item_id)
            explicit_season = int(season_num)
            if is_synthetic_season_id(explicit_show):
                split_show, split_season = split_synthetic_season_id(explicit_show)
                if explicit_season != split_season:
                    args["simkl_id"] = explicit_show
                    args["season"] = explicit_season
                else:
                    args["simkl_id"] = split_show
                    args["season"] = split_season
            else:
                args["simkl_id"] = explicit_show
                args["season"] = explicit_season
            args.pop("simkl_show_id", None)
            args.pop("simkl_season_id", None)
            return args

        if show_id is not None:
            show_id = int(show_id)
            if season_num is None and item_id is not None and is_synthetic_season_id(item_id):
                _, season_num = split_synthetic_season_id(int(item_id))
            if season_num is not None:
                args["simkl_id"] = show_id
                args["season"] = int(season_num)
        elif item_id is not None and is_synthetic_season_id(item_id):
            show_id, season_num = split_synthetic_season_id(int(item_id))
            args["simkl_id"] = show_id
            args["season"] = season_num

        args.pop("simkl_show_id", None)
        args.pop("simkl_season_id", None)
        return args

    if mediatype == "episode":
        args.pop("simkl_show_id", None)
        args.pop("simkl_season_id", None)
        return args

    return args

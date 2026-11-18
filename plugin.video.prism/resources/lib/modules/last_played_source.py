"""Digit-position last-played source matching for Smart Play auto-resolve."""
from __future__ import annotations

import json
import re
from typing import Any

from resources.lib.modules.globals import g

_SETTING_ID = "general.last_played_source"
_SHOW_ID_SETTING = "general.last_played_show_id"
_PACK_SETTING = "general.last_played_pack"
_PACK_PACKAGES = frozenset({"show", "season"})
_DEBRID_READY = {
    "premiumize": "premiumize_enabled",
    "real_debrid": "real_debrid_enabled",
    "all_debrid": "all_debrid_enabled",
    "torbox": "torbox_enabled",
    "offcloud": "offcloud_enabled",
}
_PLAYSTYLE_EPISODES = "general.playstyleEpisodes"
_PLAYSTYLE_SOURCE_SELECT = 1
_PLAYSTYLE_GUIDED_AUTO = 2
_DIRECT_TYPES = frozenset({"direct"})
_TORRENT_STYLE_TYPES = frozenset(
    {"torrent", "torrent (uncached)", "cloud", "hoster", "local", "adaptive"}
)


def guided_auto_play_template_active(info: dict[str, Any] | None) -> bool:
    """True when Guided Auto Play may auto-resolve for this episode (same show template)."""
    if g.get_int_setting(_PLAYSTYLE_EPISODES) != _PLAYSTYLE_GUIDED_AUTO:
        return False
    if not isinstance(info, dict):
        return False
    from resources.lib.simkl.ids import show_id_from_info

    show_id = show_id_from_info(info)
    if show_id is None:
        return False
    lp = (g.get_setting(_SETTING_ID) or "").strip()
    if not lp:
        return False
    stored_show = (g.get_setting(_SHOW_ID_SETTING) or "").strip()
    if not stored_show:
        return False
    return str(show_id) == stored_show


def episode_wants_source_select(
    info: dict[str, Any] | None,
    *,
    source_select_param: str | None = None,
    explicit_source_select: bool = False,
) -> bool:
    """Whether getSources should open Source Select for an episode."""
    if source_select_param in ("true", "false"):
        return source_select_param == "true"
    if explicit_source_select:
        return True
    playstyle = g.get_int_setting(_PLAYSTYLE_EPISODES)
    if playstyle == _PLAYSTYLE_SOURCE_SELECT:
        return True
    if playstyle == _PLAYSTYLE_GUIDED_AUTO:
        return not guided_auto_play_template_active(info)
    return False


def episode_pre_scrape_should_resolve(info: dict[str, Any] | None) -> bool:
    """Silent pre-scrape resolve for episodes (never opens Source Select)."""
    playstyle = g.get_int_setting(_PLAYSTYLE_EPISODES)
    if playstyle == 0:
        return True
    if playstyle == _PLAYSTYLE_GUIDED_AUTO:
        return guided_auto_play_template_active(info)
    return False


def is_smart_play_reorder_context(
    item_information: dict[str, Any],
    *,
    action: str | None = None,
    smart_url_arg: bool = False,
) -> bool:
    """True when Smart Play digit reorder should run (episodes only)."""
    info = item_information.get("info") if isinstance(item_information, dict) else None
    if not isinstance(info, dict) or info.get("mediatype") != g.MEDIA_EPISODE:
        return False
    if guided_auto_play_template_active(info):
        return True
    if action == "preScrape":
        return True
    if smart_url_arg:
        return True
    if not g.get_bool_setting("smartplay.playlistcreate"):
        return False
    try:
        if g.PLAYLIST.size() > 1:
            return True
    except Exception:
        pass
    return False


def clear_last_played_source() -> None:
    g.set_setting(_SETTING_ID, "")
    g.set_setting(_SHOW_ID_SETTING, "")


def _pack_magnet(source: dict[str, Any]) -> str:
    magnet = str(source.get("magnet") or "").strip()
    if magnet:
        return magnet
    info_hash = str(source.get("hash") or "").strip()
    if info_hash:
        return f"magnet:?xt=urn:btih:{info_hash}"
    return ""


def _is_reusable_pack(source: dict[str, Any], *, pack_select: bool) -> bool:
    if source.get("type") != "torrent":
        return False
    if not source.get("debrid_provider") or not _pack_magnet(source):
        return False
    package = str(source.get("package") or "").lower()
    if package in _PACK_PACKAGES or pack_select:
        return True
    files = source.get("_prism_cached_files")
    return isinstance(files, list) and len(files) > 1


def _load_played_pack() -> dict[str, Any] | None:
    raw = g.get_setting(_PACK_SETTING) or ""
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        g.set_setting(_PACK_SETTING, "")
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def clear_played_pack() -> None:
    g.set_setting(_PACK_SETTING, "")


def remember_played_pack(
    source: dict[str, Any] | None,
    *,
    show_id: int | None,
    pack_select: bool = False,
) -> None:
    """Keep a season/show pack for the next episode, or drop it when a single file plays."""
    if show_id is None or not isinstance(source, dict):
        return
    if not _is_reusable_pack(source, pack_select=pack_select):
        current = _load_played_pack()
        if current and str(current.get("show_id")) == str(show_id):
            clear_played_pack()
        return

    payload = {
        "show_id": str(show_id),
        "hash": str(source.get("hash") or ""),
        "magnet": _pack_magnet(source),
        "debrid_provider": str(source.get("debrid_provider") or ""),
        "package": str(source.get("package") or ""),
        "release_title": str(source.get("release_title") or ""),
        "type": "torrent",
    }
    g.set_setting(_PACK_SETTING, json.dumps(payload))
    g.log(f"Saved pack for the next episode: {payload['release_title']}", "info")


def _debrid_ready(provider: str) -> bool:
    method_name = _DEBRID_READY.get(provider)
    if not method_name:
        return False
    return bool(getattr(g, method_name)())


def saved_pack_for_show(show_id: int | str | None) -> dict[str, Any] | None:
    """Saved pack for this show, when its debrid account is still enabled."""
    if show_id is None:
        return None
    pack = _load_played_pack()
    if not pack or str(pack.get("show_id")) != str(show_id):
        return None
    if not _debrid_ready(str(pack.get("debrid_provider") or "")):
        return None
    return pack


def _saved_pack_for_episode(item_information: dict[str, Any]) -> dict[str, Any] | None:
    info = item_information.get("info") if isinstance(item_information, dict) else None
    if not isinstance(info, dict) or info.get("mediatype") != g.MEDIA_EPISODE:
        action_args = item_information.get("action_args") if isinstance(item_information, dict) else None
        if isinstance(action_args, dict) and action_args.get("mediatype") == g.MEDIA_EPISODE:
            return saved_pack_for_show(action_args.get("simkl_show_id"))
        return None

    from resources.lib.simkl.ids import show_id_from_info

    show_id = show_id_from_info(info)
    if show_id is None:
        action_args = item_information.get("action_args")
        if isinstance(action_args, dict):
            show_id = action_args.get("simkl_show_id")
    return saved_pack_for_show(show_id)


def saved_pack_pending(item_information: dict[str, Any]) -> bool:
    """True when the next episode should try the saved pack instead of scraping."""
    return _saved_pack_for_episode(item_information) is not None


def take_saved_pack_stream(item_information: dict[str, Any]) -> str | None:
    """Play this episode from the saved pack. None means the caller should scrape."""
    pack = _saved_pack_for_episode(item_information)
    if not pack:
        return None

    provider = str(pack.get("debrid_provider") or "")

    source = {
        "type": "torrent",
        "hash": pack.get("hash") or "",
        "magnet": pack.get("magnet") or "",
        "debrid_provider": provider,
        "package": pack.get("package") or "show",
        "release_title": pack.get("release_title") or "",
    }
    from resources.lib.modules.resolver import Resolver

    try:
        stream_link, _release_title = Resolver().resolve_single_source(
            source,
            item_information,
            pack_select=False,
            silent=True,
            allow_manual_prompt=False,
            quiet_failure=True,
        )
    except Exception:
        g.log_stacktrace()
        return None

    if not stream_link or stream_link == "none":
        g.log("Saved pack has no file for this episode, scraping", "info")
        return None

    g.log(f"Saved pack has this episode: {source['release_title']}", "info")
    return stream_link


def _info_tokens(info) -> list[str]:
    if isinstance(info, set):
        return sorted(str(token) for token in info)
    if isinstance(info, (list, tuple)):
        return [str(token) for token in info]
    if info is None:
        return []
    return [str(info)]


def _direct_source_key(source: dict[str, Any]) -> str:
    return source.get("provider", "") + " " + " ".join(_info_tokens(source.get("info")))


def save_last_played_source(source: dict[str, Any], *, show_id: int | None = None) -> None:
    if not isinstance(source, dict):
        return
    source_type = source.get("type")
    if source_type in _DIRECT_TYPES:
        g.set_setting(_SETTING_ID, _direct_source_key(source))
    elif source_type in _TORRENT_STYLE_TYPES:
        g.set_setting(_SETTING_ID, str(source.get("release_title") or ""))
    else:
        return
    if show_id is not None:
        g.set_setting(_SHOW_ID_SETTING, str(show_id))


def reorder_sources(
    sources: list[dict[str, Any]],
    episode,
    *,
    source_select: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """Move the best last-played match to index 0. Returns (sources, matched)."""
    if len(sources) <= 1 or source_select:
        return sources, False

    lp = g.get_setting(_SETTING_ID) or ""
    lp = re.sub(r"\[[0-9A-Fa-f]{8,}\]", "", lp).strip()
    if not lp:
        return sources, False

    ep = str(episode)
    length = len(ep)
    digit_positions = [
        index for index in range(len(lp) - length + 1) if lp[index : index + length].isdigit()
    ]

    for idx, source in enumerate(sources):
        source_type = source.get("type")

        if source_type in _DIRECT_TYPES:
            if _direct_source_key(source) == lp:
                sources[0], sources[idx] = sources[idx], sources[0]
                return sources, True

        elif source_type in _TORRENT_STYLE_TYPES:
            rel = str(source.get("release_title") or "")
            rel = re.sub(r"\[[0-9A-Fa-f]{8,}\]", "", rel).strip()

            if rel == lp:
                sources[0], sources[idx] = sources[idx], sources[0]
                return sources, True

            for pos in digit_positions:
                if rel.startswith(lp[:pos]) and rel.endswith(lp[pos + length :]):
                    sources[0], sources[idx] = sources[idx], sources[0]
                    return sources, True

    return sources, False

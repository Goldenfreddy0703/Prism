"""Sync Kodi Mark as Watched / Mark as Unwatched on Prism plugin URLs into simklSync.db.

Only reacts to explicit playCount toggles on episode and movie rows.
Playback progress, resume (lastPlayed), and Simkl scrobble completion are ignored.
"""
from __future__ import annotations

import json
import time
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, quote

import xbmc

from resources.lib.common import tools
from resources.lib.modules.globals import g
from resources.lib.simkl.ids import (
    encode_action_args,
    is_synthetic_episode_id,
    normalize_action_args,
    parse_stored_action_args,
    show_id_for_episode_action,
    split_synthetic_episode_id,
)
from resources.lib.simkl.library_status import _library_info
from resources.lib.simkl.watch_toggle import apply_mark_unwatched, apply_mark_watched

_PRISM_URL_MARKER = "plugin.video.prism"
_ROW_SNAPSHOT_KEY = "kodi_watched_bridge.row_snapshot"
_SNAPSHOT_READY_KEY = "kodi_watched_bridge.snapshot_ready"
_SYNC_DEBOUNCE_KEY = "kodi_watched_bridge.sync_debounce"
_DEBOUNCE_SECONDS = 2.0
_POLL_INTERVAL_SECONDS = 2.0
_LAST_SCAN_KEY = "kodi_watched_bridge.last_scan"
_PRISM_PLAYBACK_ACTIVE_KEY = "kodi_watched_bridge.prism_playback_active"
_SUPPRESS_UNTIL_KEY = "kodi_watched_bridge.suppress_until"
_POST_PLAYBACK_SUPPRESS_SECONDS = 15.0
_BRIDGE_ITEM_MEDIATYPES = frozenset({"movie", "episode"})


def bridge_enabled() -> bool:
    return g.get_bool_setting("general.kodiWatchedBridge", True)


def set_prism_playback_active(active: bool) -> None:
    """Mark Prism-controlled playback so the bridge ignores transient MyVideos updates."""
    if active:
        g.set_runtime_setting(_PRISM_PLAYBACK_ACTIVE_KEY, True)
        g.set_runtime_setting(_SUPPRESS_UNTIL_KEY, 0)
    else:
        g.clear_runtime_setting(_PRISM_PLAYBACK_ACTIVE_KEY)


def arm_post_playback_suppression(seconds: float = _POST_PLAYBACK_SUPPRESS_SECONDS) -> None:
    """Ignore bridge scans briefly after playback ends (Kodi may bump playcount on stop)."""
    if seconds <= 0:
        return
    g.set_runtime_setting(_SUPPRESS_UNTIL_KEY, time.time() + float(seconds))


def bridge_suppressed() -> bool:
    """True while playback is active or in the post-playback cooldown window."""
    if g.get_bool_runtime_setting(_PRISM_PLAYBACK_ACTIVE_KEY, False):
        return True
    try:
        if xbmc.getCondVisibility("Player.Playing | Player.Paused"):
            return True
    except Exception:
        pass
    suppress_until = float(g.get_float_runtime_setting(_SUPPRESS_UNTIL_KEY, 0) or 0)
    return time.time() < suppress_until


def scan_kodi_watched_bridge(*, force: bool = False, trigger: str = "poll") -> None:
    """Detect Kodi/Prism watched mismatches on Prism plugin URLs and sync."""
    if not bridge_enabled():
        return
    suppressed = bridge_suppressed()
    g.clear_runtime_setting("kodi_watched_bridge.pending_first_sight")
    if not force and not suppressed:
        last_scan = float(g.get_float_runtime_setting(_LAST_SCAN_KEY, 0) or 0)
        if time.time() - last_scan < _POLL_INTERVAL_SECONDS:
            return
    if not suppressed:
        g.set_runtime_setting(_LAST_SCAN_KEY, time.time())

    try:
        rows = _fetch_prism_file_rows()
    except Exception as exc:
        if "locked" not in str(exc).lower():
            g.log_stacktrace()
        return

    snapshot = _load_row_snapshot()
    sync_debounce = _load_sync_debounce_cache()
    snapshot_ready = g.get_bool_runtime_setting(_SNAPSHOT_READY_KEY, False)
    now = time.time()
    queued = 0
    seen_ids: set[str] = set()

    for row in rows:
        id_file = str(row.get("idFile") or row.get("idfile") or "")
        if not id_file:
            continue
        seen_ids.add(id_file)

        filename = (row.get("strFilename") or row.get("strfilename") or "").strip()
        play_count = _normalize_play_count(row.get("playCount") if "playCount" in row else row.get("playcount"))
        last_played = _normalize_last_played(row.get("lastPlayed") if "lastPlayed" in row else row.get("lastplayed"))

        url = _row_plugin_url(row)
        action_args = action_args_from_prism_url(url)
        if not action_args:
            continue
        action_args = _resolve_bridge_action_args(action_args)
        if not action_args:
            continue
        mediatype = (action_args.get("mediatype") or "").lower()
        if mediatype not in _BRIDGE_ITEM_MEDIATYPES:
            continue

        prev_state = snapshot.get(id_file)
        prev_play_count = _normalize_play_count((prev_state or {}).get("play_count"))
        row_state = _row_state_tuple(play_count, mediatype)

        if prev_state is None:
            snapshot[id_file] = _snapshot_entry(filename, play_count, last_played)
            # First sight of an idFile is always baseline-only (Kodi may recreate rows on play/stop).
            continue
        elif _snapshot_tuple(prev_state, mediatype) == row_state:
            continue
        else:
            snapshot[id_file] = _snapshot_entry(filename, play_count, last_played)

        if suppressed:
            continue

        if prev_state is not None and prev_play_count == play_count:
            continue

        kodi_watched = _kodi_row_is_watched(play_count, mediatype)
        prism_watched = _prism_is_watched_lite(action_args)
        if kodi_watched == prism_watched:
            continue

        debounce_key = f"{id_file}:{int(kodi_watched)}"
        if sync_debounce.get(debounce_key, 0) > now - _DEBOUNCE_SECONDS:
            continue

        queue_kodi_watched_sync(action_args, watched=kodi_watched, id_file=id_file)
        sync_debounce[debounce_key] = now
        queued += 1

    for stale_id in set(snapshot) - seen_ids:
        snapshot.pop(stale_id, None)

    _save_row_snapshot(snapshot)
    _save_sync_debounce_cache(sync_debounce)
    if rows and not snapshot_ready:
        g.set_runtime_setting(_SNAPSHOT_READY_KEY, True)
    if queued:
        g.log(f"Kodi watched bridge: queued {queued} sync(s)", "info")


def _normalize_play_count(raw) -> int:
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _normalize_last_played(raw) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _row_state_tuple(play_count: int, mediatype: str | None = None) -> tuple[int, ...]:
    """Bridge items track playCount only — lastPlayed/resume must not trigger sync."""
    if (mediatype or "").lower() in _BRIDGE_ITEM_MEDIATYPES:
        return (play_count,)
    return (play_count,)


def _snapshot_entry(filename: str, play_count: int, last_played: str | None) -> dict:
    return {
        "str_filename": filename,
        "play_count": play_count,
        "last_played": last_played,
    }


def _snapshot_tuple(entry: dict, mediatype: str | None = None) -> tuple[int, ...]:
    return _row_state_tuple(_normalize_play_count(entry.get("play_count")), mediatype)


def _kodi_row_is_watched(play_count: int, mediatype: str | None = None) -> bool:
    """Kodi Mark as Watched / Mark as Unwatched toggles playCount on bridge items."""
    if (mediatype or "").lower() not in _BRIDGE_ITEM_MEDIATYPES:
        return play_count > 0
    return play_count > 0


def _resolve_bridge_action_args(action_args: dict | None) -> dict | None:
    """Map synthetic milled episode ids to canonical Simkl episode ids for sync."""
    action_args = normalize_action_args(action_args)
    if not action_args:
        return None
    if (action_args.get("mediatype") or "").lower() != "episode":
        return action_args

    episode_id = action_args.get("simkl_id")
    if episode_id is None:
        return action_args
    try:
        episode_id = int(episode_id)
    except (TypeError, ValueError):
        return action_args

    show_id = action_args.get("simkl_show_id")
    season = action_args.get("season")
    episode = action_args.get("episode")
    if is_synthetic_episode_id(episode_id):
        split_show, split_season, split_episode = split_synthetic_episode_id(episode_id)
        show_id = int(show_id or split_show)
        season = int(season if season is not None else split_season)
        episode = int(episode if episode is not None else split_episode)
    elif show_id is None:
        show_id = show_id_for_episode_action(action_args)

    if show_id is None:
        return action_args

    from resources.lib.database.session import get_sync_database

    db = get_sync_database()
    row = None
    if season is not None and episode is not None and is_synthetic_episode_id(episode_id):
        row = db.fetchone(
            "SELECT simkl_id FROM episodes WHERE simkl_show_id = ? AND season = ? AND number = ?",
            (int(show_id), int(season), int(episode)),
        )
    if not row:
        row = db.fetchone(
            "SELECT simkl_id, simkl_show_id, season, number FROM episodes WHERE simkl_id = ?",
            (episode_id,),
        )

    resolved = dict(action_args)
    if show_id is not None:
        resolved["simkl_show_id"] = int(show_id)
    if season is not None:
        resolved["season"] = int(season)
    if episode is not None:
        resolved["episode"] = int(episode)
    if row and row.get("simkl_id") is not None:
        resolved["simkl_id"] = int(row["simkl_id"])
        if row.get("simkl_show_id") is not None:
            resolved["simkl_show_id"] = int(row["simkl_show_id"])
        if row.get("season") is not None:
            resolved["season"] = int(row["season"])
        if row.get("number") is not None:
            resolved["episode"] = int(row["number"])
    return normalize_action_args(resolved)


def _prism_is_watched_lite(action_args: dict) -> bool:
    """Lightweight watched lookup for bridge polling (avoids episode re-mill)."""
    mediatype = (action_args.get("mediatype") or "").lower()
    if mediatype == "episode":
        from resources.lib.database.session import get_sync_database

        db = get_sync_database()
        episode_id = action_args.get("simkl_id")
        show_id = action_args.get("simkl_show_id") or show_id_for_episode_action(action_args)
        season = action_args.get("season")
        episode = action_args.get("episode")
        row = None
        if episode_id is not None:
            try:
                episode_id = int(episode_id)
            except (TypeError, ValueError):
                episode_id = None
        if episode_id is not None and is_synthetic_episode_id(episode_id) and show_id is not None:
            if season is None or episode is None:
                _, season, episode = split_synthetic_episode_id(episode_id)
            row = db.fetchone(
                "SELECT watched FROM episodes WHERE simkl_show_id = ? AND season = ? AND number = ?",
                (int(show_id), int(season), int(episode)),
            )
        elif episode_id is not None:
            row = db.fetchone("SELECT watched FROM episodes WHERE simkl_id = ?", (episode_id,))
        if row is not None:
            try:
                return int(row.get("watched") or 0) > 0
            except (TypeError, ValueError):
                return False
        return False

    if mediatype == "movie":
        simkl_id = action_args.get("simkl_id")
        if simkl_id is None:
            return False
        from resources.lib.database.session import get_sync_database

        row = get_sync_database().fetchone(
            "SELECT watched, simkl_status, history_cleared FROM movies WHERE simkl_id = ?",
            (int(simkl_id),),
        )
        if not row:
            return False
        if int(row.get("history_cleared") or 0) > 0:
            return int(row.get("watched") or 0) > 0
        if row.get("simkl_status") == "completed":
            return True
        return int(row.get("watched") or 0) > 0

    try:
        item_information = tools.get_item_information(action_args)
    except Exception:
        return False
    if not item_information:
        return False
    return _prism_is_watched(item_information)


def _movie_prism_is_watched(info: dict, item_information: dict) -> bool:
    """Match Simkl Manager movie watched state (completed list + history_cleared)."""
    sid = info.get("simkl_id")
    history_cleared = bool(info.get("watch_history_cleared"))
    simkl_status = info.get("simkl_status")

    if sid is not None:
        try:
            from resources.lib.database.session import get_sync_database

            row = get_sync_database().fetchone(
                "SELECT watched, simkl_status, history_cleared FROM movies WHERE simkl_id=?",
                (int(sid),),
            )
            if row:
                history_cleared = history_cleared or int(row.get("history_cleared") or 0) > 0
                if row.get("simkl_status"):
                    simkl_status = row.get("simkl_status")
                if history_cleared:
                    return int(row.get("watched") or 0) > 0
        except Exception:
            pass

    if history_cleared:
        play_count = item_information.get("play_count")
        if play_count is None:
            play_count = info.get("playcount")
        try:
            return int(play_count or 0) > 0
        except (TypeError, ValueError):
            return False

    if simkl_status == "completed":
        return True

    play_count = item_information.get("play_count")
    if play_count is None:
        play_count = info.get("playcount")
    try:
        return int(play_count or 0) > 0
    except (TypeError, ValueError):
        return False


def _prism_is_watched(item_information: dict) -> bool:
    info = _library_info(item_information)
    mediatype = (info.get("mediatype") or "").lower()
    if mediatype == "movie":
        return _movie_prism_is_watched(info, item_information)

    play_count = item_information.get("play_count")
    if play_count is None:
        play_count = info.get("playcount")
    try:
        if play_count is not None and int(play_count) > 0:
            return True
    except (TypeError, ValueError):
        pass
    if mediatype in ("tvshow", "season"):
        watched_eps = item_information.get("watched_episodes")
        if watched_eps is None:
            watched_eps = info.get("watched_episodes")
        ep_count = item_information.get("episode_count") or info.get("episode_count") or 0
        try:
            if int(ep_count) > 0 and int(watched_eps or 0) >= int(ep_count):
                return True
        except (TypeError, ValueError):
            pass
    return False


def apply_pending_transition(action_args: dict, *, watched: bool, id_file: str | None = None) -> None:
    """Router entry: resolve item metadata and apply watched state."""
    _apply_transition(action_args, watched=watched, id_file=id_file)


def _apply_transition(action_args: dict, *, watched: bool, id_file: str | None = None) -> bool:
    action_args = _resolve_bridge_action_args(action_args) or action_args
    item_information = tools.get_item_information(action_args)
    if not item_information:
        return False
    info = item_information.get("info") if isinstance(item_information, dict) else None
    if not isinstance(info, dict) or info.get("simkl_id") is None:
        return False

    if watched:
        ok = apply_mark_watched(item_information, silent=False, refresh=True)
    else:
        ok = apply_mark_unwatched(item_information, silent=False, refresh=True)

    if ok and id_file:
        snapshot = _load_row_snapshot()
        filename = ""
        play_count = 1 if watched else 0
        last_played = None
        try:
            for row in _fetch_prism_file_rows():
                if str(row.get("idFile") or row.get("idfile") or "") == str(id_file):
                    filename = (row.get("strFilename") or row.get("strfilename") or "").strip()
                    play_count = _normalize_play_count(
                        row.get("playCount") if "playCount" in row else row.get("playcount")
                    )
                    last_played = _normalize_last_played(
                        row.get("lastPlayed") if "lastPlayed" in row else row.get("lastplayed")
                    )
                    break
        except Exception:
            pass
        snapshot[str(id_file)] = _snapshot_entry(filename, play_count, last_played)
        _save_row_snapshot(snapshot)

    return ok


def action_args_from_prism_url(url: str | None) -> dict | None:
    if not url or _PRISM_URL_MARKER not in url:
        return None
    if not url.startswith("plugin://"):
        idx = url.find("plugin://")
        if idx >= 0:
            url = url[idx:]
        else:
            return None

    query = urlparse(url).query
    if not query:
        return None

    params = dict(parse_qsl(query, keep_blank_values=True))
    raw = params.get("action_args")
    if not raw:
        return None

    parsed = parse_stored_action_args(raw)
    if parsed:
        return parsed

    decoded = raw
    for _ in range(4):
        try:
            candidate = json.loads(unquote(decoded))
            if isinstance(candidate, dict):
                return normalize_action_args(candidate)
        except (ValueError, TypeError):
            pass
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    return None


def _fetch_prism_file_rows() -> list[dict]:
    with g.get_kodi_video_db_connection(max_lock_retries=5, read_only=True) as video_database:
        config = g.get_kodi_video_db_config()
        if config.get("type") == "mysql":
            return video_database.fetchall(
                """
                SELECT f.idFile, f.strFilename, f.playCount, f.lastPlayed, p.strPath
                FROM files f
                LEFT JOIN path p ON p.idPath = f.idPath
                WHERE f.strFilename LIKE %s OR p.strPath LIKE %s
                """,
                (f"%{_PRISM_URL_MARKER}%", f"%{_PRISM_URL_MARKER}%"),
            )
        return video_database.fetchall(
            """
            SELECT f.idFile, f.strFilename, f.playCount, f.lastPlayed, p.strPath
            FROM files f
            LEFT JOIN path p ON p.idPath = f.idPath
            WHERE f.strFilename LIKE '%plugin.video.prism%'
               OR p.strPath LIKE '%plugin://plugin.video.prism%'
               OR f.strFilename LIKE 'plugin://plugin.video.prism%'
            """
        )


def _row_plugin_url(row: dict) -> str | None:
    filename = (row.get("strFilename") or row.get("strfilename") or "").strip()
    path = (row.get("strPath") or row.get("strpath") or "").strip()
    if filename.startswith("plugin://"):
        return filename
    if path.startswith("plugin://"):
        return f"{path}{filename}" if filename else path
    if _PRISM_URL_MARKER in filename:
        return filename
    combined = f"{path}{filename}"
    return combined if _PRISM_URL_MARKER in combined else None


def _load_row_snapshot() -> dict[str, dict]:
    cached = g.get_runtime_setting(_ROW_SNAPSHOT_KEY, {})
    if not isinstance(cached, dict) or not cached:
        legacy = g.get_runtime_setting("kodi_watched_bridge.playcount_snapshot", {})
        if isinstance(legacy, dict) and legacy:
            cached = {
                str(key): _snapshot_entry("", _normalize_play_count(value), None)
                for key, value in legacy.items()
            }
    snapshot: dict[str, dict] = {}
    for key, value in (cached or {}).items():
        if isinstance(value, dict):
            snapshot[str(key)] = value
        else:
            snapshot[str(key)] = _snapshot_entry("", _normalize_play_count(value), None)
    return snapshot


def _save_row_snapshot(snapshot: dict[str, dict]) -> None:
    g.set_runtime_setting(_ROW_SNAPSHOT_KEY, snapshot)


def _load_sync_debounce_cache() -> dict[str, float]:
    cached = g.get_runtime_setting(_SYNC_DEBOUNCE_KEY, {})
    return cached if isinstance(cached, dict) else {}


def _save_sync_debounce_cache(snapshot: dict[str, float]) -> None:
    g.set_runtime_setting(_SYNC_DEBOUNCE_KEY, snapshot)


def queue_kodi_watched_sync(action_args: dict, *, watched: bool, id_file: str) -> None:
    """Run sync in plugin context (GUI-safe notifications and container refresh)."""
    args = {
        "action": "kodiWatchedSync",
        "action_args": encode_action_args(action_args),
        "watched": "1" if watched else "0",
        "kodi_id_file": str(id_file),
    }
    plugin_url = f'plugin://plugin.video.prism/?{urlencode(args, quote_via=quote)}'
    xbmc.executebuiltin(f'RunPlugin("{plugin_url}")')

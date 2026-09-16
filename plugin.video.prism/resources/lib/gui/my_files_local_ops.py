"""Context-menu file operations for My Files local browsers."""
from __future__ import annotations

import contextlib
import os
import time
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.common import tools
from resources.lib.modules.download_paths import manual_move_to_local_library, move_vfs_path, sanitize_path_component
from resources.lib.modules.globals import g

# String IDs — see strings.po #31089+
S_RENAME = 31089
S_MOVE_TO_FOLDER = 31090
S_COPY_TO_FOLDER = 31091
S_ITEM_INFO = 31093
S_DELETE = 31095
S_MOVE_TO_LIBRARY = 31096
S_CREATE_SUBFOLDER = 31097
S_DELETE_FILE_CONFIRM = 31098
S_DELETE_FOLDER_CONFIRM = 31099
S_RENAME_HEADING = 31100
S_NEW_FOLDER_HEADING = 31101
S_PICK_FOLDER_HEADING = 31102
S_OP_FAILED = 31103
S_OP_SUCCESS = 31104
S_LOCAL_LIBRARY_NOT_SET = 31105
S_OP_PLEASE_WAIT = 31106
S_OP_COPYING = 31107
S_OP_MOVING = 31108
S_OP_DELETING = 31109
S_OP_RENAMING = 31110
S_OP_CREATING_FOLDER = 31111
S_OP_COPYING_BYTES = 31112

_COPY_CHUNK_SIZE = 1024 * 1024


def _join_vfs_path(base: str, name: str) -> str:
    if base.endswith(('/', '\\')):
        return f"{base}{name}"
    if '/' in base:
        return f"{base}/{name}"
    return f"{base}\\{name}"


def _action_args(item: dict, browse_path: str) -> dict:
    path = item.get("path") or ""
    is_folder = path.endswith(("/", "\\"))
    return {
        "debrid_provider": item.get("debrid_provider", ""),
        "path": path,
        "name": item.get("name") or "",
        "parent_path": browse_path,
        "is_folder": is_folder,
    }


def build_context_menu(item: dict, browse_path: str, *, is_downloads: bool) -> list[tuple[str, str]]:
    """Build Kodi context menu tuples for a local file or folder row."""
    base = _action_args(item, browse_path)
    is_folder = bool(base["is_folder"])

    def plugin(op: str) -> str:
        args = dict(base)
        args["op"] = op
        url = g.create_url(g.BASE_URL, {"action": "myFilesLocalAction", "action_args": args})
        return f"RunPlugin({url})"

    menu: list[tuple[str, str]] = [
        (g.get_language_string(S_RENAME), plugin("rename")),
    ]
    if is_downloads:
        menu.append((g.get_language_string(S_MOVE_TO_LIBRARY), plugin("move_to_library")))
    menu.extend(
        [
            (g.get_language_string(S_MOVE_TO_FOLDER), plugin("move")),
            (g.get_language_string(S_COPY_TO_FOLDER), plugin("copy")),
        ]
    )
    menu.append((g.get_language_string(S_CREATE_SUBFOLDER), plugin("create_subfolder")))
    menu.append((g.get_language_string(S_ITEM_INFO), plugin("info")))
    menu.append((g.get_language_string(S_DELETE), plugin("delete")))
    return menu


def dispatch_local_action(args: dict) -> None:
    op = (args or {}).get("op")
    handlers = {
        "rename": _handle_rename,
        "delete": _handle_delete,
        "move": _handle_move,
        "copy": _handle_copy,
        "move_to_library": _handle_move_to_library,
        "create_subfolder": _handle_create_subfolder,
        "info": _handle_info,
    }
    handler = handlers.get(op)
    if handler:
        handler(args)


def _normalize_vfs(path: str) -> str:
    return os.path.normpath(tools.validate_path(path))


def _is_folder_path(path: str) -> bool:
    return path.endswith(("/", "\\"))


def _entry_name(path: str, is_folder: bool) -> str:
    trimmed = path.rstrip("/\\")
    return os.path.basename(trimmed)


def _parent_dir(path: str) -> str:
    trimmed = path.rstrip("/\\")
    parent = os.path.dirname(trimmed)
    return parent or trimmed


def _pick_destination_folder(start_path: str) -> str | None:
    start = start_path or (g.get_setting("local.location") or g.get_setting("download.location") or "")
    picked = xbmcgui.Dialog().browse(
        3,
        g.get_language_string(S_PICK_FOLDER_HEADING),
        "files",
        "",
        False,
        False,
        start,
    )
    return picked or None


def _confirm_delete(path: str, is_folder: bool) -> bool:
    name = _entry_name(path, is_folder)
    if is_folder:
        message = g.get_language_string(S_DELETE_FOLDER_CONFIRM).format(name)
    else:
        message = g.get_language_string(S_DELETE_FILE_CONFIRM).format(name)
    return bool(xbmcgui.Dialog().yesno(g.ADDON_NAME, message))


def _delete_path(path: str, is_folder: bool) -> bool:
    if not xbmcvfs.exists(path):
        return False
    if is_folder:
        return bool(xbmcvfs.rmdir(path, True))
    return bool(xbmcvfs.delete(path))


def _is_subpath(parent: str, child: str) -> bool:
    parent_norm = _normalize_vfs(parent).lower()
    child_norm = _normalize_vfs(child).lower()
    if parent_norm == child_norm:
        return True
    sep = os.sep
    if not parent_norm.endswith(sep):
        parent_norm = f"{parent_norm}{sep}"
    return child_norm.startswith(parent_norm)


def _provider_root_path(provider: str) -> str:
    if provider == "local_files":
        return tools.ensure_path_is_dir((g.get_setting("local.location") or "").strip())
    if provider == "local_downloads":
        return tools.ensure_path_is_dir((g.get_setting("download.location") or "").strip())
    return ""


def _myfiles_folder_url(args: dict) -> str | None:
    """Build a myFilesFolder URL for the browse page that owns the selected item."""
    provider = args.get("debrid_provider") or ""
    if provider not in ("local_files", "local_downloads"):
        return None
    parent_path = args.get("parent_path") or ""
    browse_path = tools.ensure_path_is_dir(parent_path) if parent_path else ""
    root = _provider_root_path(provider)
    if not browse_path or (
        root
        and _normalize_vfs(browse_path).lower() == _normalize_vfs(root).lower()
    ):
        folder_args = {"debrid_provider": provider, "id": None}
    else:
        folder_args = {"debrid_provider": provider, "path": browse_path}
    return g.create_url(g.BASE_URL, {"action": "myFilesFolder", "action_args": folder_args})


def _refresh_listing(args: dict | None = None) -> None:
    """Reload the visible My Files folder without breaking folder back-navigation."""
    folder_path = xbmc.getInfoLabel("Container.FolderPath") or ""
    rebuilt_url = _myfiles_folder_url(args) if args else None
    plugin_handle = getattr(g, "PLUGIN_HANDLE", 0)

    if folder_path.startswith("plugin://plugin.video.prism"):
        parsed = urlparse(folder_path)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if query.get("action") in ("myFilesFolder", "myFiles"):
            if plugin_handle <= 0:
                xbmc.executebuiltin("Container.Refresh")
                return
            query["prism_reload"] = "true"
            query["_cb"] = str(int(time.time()))
            new_path = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
            escaped = new_path.replace("\\", "\\\\").replace('"', '\\"')
            xbmc.executebuiltin(f'Container.Update("{escaped}",replace)')
            return

    if rebuilt_url:
        escaped = rebuilt_url.replace("\\", "\\\\").replace('"', '\\"')
        xbmc.executebuiltin(f'Container.Update("{escaped}",replace)')
        return

    if not g.refresh_visible_container():
        g.container_refresh()


@contextmanager
def _file_op_progress(title: str) -> Iterator[xbmcgui.DialogProgressBG]:
    """Simkl-style background progress dialog for long local file operations."""
    dialog = xbmcgui.DialogProgressBG()
    dialog.create(g.ADDON_NAME, title)
    try:
        yield dialog
    finally:
        try:
            dialog.close()
        except Exception:
            pass


def _vfs_file_size(path: str) -> int:
    try:
        return int(xbmcvfs.Stat(path).st_size())
    except (OSError, AttributeError, TypeError, ValueError):
        return 0


def _summarize_vfs_tree(path: str) -> tuple[int, int, int]:
    """Return recursive (folder_count, file_count, total_bytes) under a folder."""
    folder = tools.ensure_path_is_dir(path)
    try:
        dirs, files = xbmcvfs.listdir(folder)
    except OSError:
        return 0, 0, 0

    folder_count = len(dirs)
    file_count = len(files)
    base = folder.rstrip("/\\")
    total_bytes = sum(_vfs_file_size(_join_vfs_path(base, filename)) for filename in files)
    for dirname in dirs:
        sub_folders, sub_files, sub_bytes = _summarize_vfs_tree(
            tools.ensure_path_is_dir(_join_vfs_path(base, dirname))
        )
        folder_count += sub_folders
        file_count += sub_files
        total_bytes += sub_bytes
    return folder_count, file_count, total_bytes


def _measure_vfs_tree_bytes(path: str) -> int:
    """Total byte size of all files under a folder (recursive)."""
    _, _, total_bytes = _summarize_vfs_tree(path)
    return total_bytes


def _copy_progress_percent(copied_bytes: int, total_bytes: int) -> int:
    total_bytes = max(int(total_bytes), 1)
    return min(99, int(int(copied_bytes) / total_bytes * 100))


def _read_vfs_chunk(handle, size: int) -> bytes:
    """Read a binary chunk via readBytes (returns bytearray; never use read() on video)."""
    if not hasattr(handle, "readBytes"):
        return b""
    chunk = handle.readBytes(size)
    if not chunk:
        return b""
    return bytes(chunk)


def _report_copy_progress(
    progress: xbmcgui.DialogProgressBG | None,
    progress_state: dict | None,
    copied_bytes: int,
) -> None:
    if progress is None or progress_state is None:
        return
    total_bytes = progress_state.get("total_bytes", 1)
    folder_label = str(progress_state.get("label") or "")
    current_file = str(progress_state.get("current_file") or folder_label)
    progress_state["copied_bytes"] = copied_bytes
    percent = _copy_progress_percent(copied_bytes, total_bytes)
    copying_line = g.get_language_string(S_OP_COPYING).format(current_file)
    # update(percent, heading, message): heading = top line (+ ": XX%"), message = bottom line.
    progress.update(percent, folder_label, copying_line)


def _copy_vfs_file_chunked(
    source: str,
    dest: str,
    *,
    progress: xbmcgui.DialogProgressBG | None = None,
    progress_state: dict | None = None,
) -> bool:
    """Copy one file in chunks (download-manager style) with live byte progress."""
    if xbmcvfs.exists(dest):
        return False

    dest_parent = os.path.dirname(dest.rstrip("/\\"))
    if dest_parent and not xbmcvfs.exists(dest_parent):
        xbmcvfs.mkdirs(tools.ensure_path_is_dir(dest_parent))

    file_start = progress_state.get("copied_bytes", 0) if progress_state else 0
    current_file = os.path.basename(source.rstrip("/\\"))
    if progress_state is not None:
        progress_state["current_file"] = current_file
        _report_copy_progress(progress, progress_state, file_start)
    src_handle = None
    dst_handle = None
    bytes_copied = 0

    try:
        src_handle = xbmcvfs.File(source, "rb")
        dst_handle = xbmcvfs.File(dest, "wb")
        while not g.abort_requested():
            chunk = _read_vfs_chunk(src_handle, _COPY_CHUNK_SIZE)
            if not chunk:
                break
            if not dst_handle.write(chunk):
                with contextlib.suppress(Exception):
                    xbmcvfs.delete(dest)
                return False
            bytes_copied += len(chunk)
            _report_copy_progress(progress, progress_state, file_start + bytes_copied)
    except (OSError, ValueError, UnicodeDecodeError):
        g.log_stacktrace()
        with contextlib.suppress(Exception):
            xbmcvfs.delete(dest)
        return False
    finally:
        for handle in (src_handle, dst_handle):
            if handle is not None:
                with contextlib.suppress(Exception):
                    handle.close()

    if g.abort_requested():
        with contextlib.suppress(Exception):
            xbmcvfs.delete(dest)
        return False

    if not xbmcvfs.exists(dest):
        return False

    if progress_state is not None:
        progress_state["copied_bytes"] = file_start + max(bytes_copied, _vfs_file_size(source))
    return True


def _copy_vfs_tree(
    source: str,
    dest: str,
    *,
    progress: xbmcgui.DialogProgressBG | None = None,
    progress_state: dict[str, int] | None = None,
) -> bool:
    """Recursively copy a folder via xbmcvfs."""
    source = tools.ensure_path_is_dir(source)
    dest = tools.ensure_path_is_dir(dest)
    if xbmcvfs.exists(dest):
        return False
    if not xbmcvfs.mkdirs(dest):
        return False
    try:
        dirs, files = xbmcvfs.listdir(source)
    except OSError:
        return False
    for filename in files:
        src_file = _join_vfs_path(source, filename)
        dst_file = _join_vfs_path(dest.rstrip("/\\"), filename)
        if not _copy_vfs_file_chunked(
            src_file,
            dst_file,
            progress=progress,
            progress_state=progress_state,
        ):
            return False
    for dirname in dirs:
        src_dir = tools.ensure_path_is_dir(_join_vfs_path(source, dirname))
        dst_dir = tools.ensure_path_is_dir(_join_vfs_path(dest.rstrip("/\\"), dirname))
        if not _copy_vfs_tree(src_dir, dst_dir, progress=progress, progress_state=progress_state):
            return False
    return True


def _notify_failed() -> None:
    g.notification(g.ADDON_NAME, g.get_language_string(S_OP_FAILED))


def _notify_success(message: str | None = None) -> None:
    g.notification(g.ADDON_NAME, message or g.get_language_string(S_OP_SUCCESS))


def _handle_rename(args: dict) -> None:
    path = args.get("path") or ""
    if not path or not xbmcvfs.exists(path):
        _notify_failed()
        return
    is_folder = bool(args.get("is_folder")) or _is_folder_path(path)
    current_name = args.get("name") or _entry_name(path, is_folder)
    new_name = g.get_keyboard_input(g.get_language_string(S_RENAME_HEADING), default=current_name)
    if not new_name or new_name == current_name:
        return
    new_name = sanitize_path_component(new_name)
    if is_folder:
        new_name = tools.ensure_path_is_dir(new_name).rstrip("/\\")
    parent = _parent_dir(path)
    dest = _join_vfs_path(parent, new_name)
    if is_folder:
        dest = tools.ensure_path_is_dir(dest)
    if xbmcvfs.exists(dest):
        _notify_failed()
        return
    with _file_op_progress(g.get_language_string(S_OP_RENAMING).format(current_name)) as progress:
        progress.update(25, g.get_language_string(S_OP_PLEASE_WAIT))
        success = move_vfs_path(path, dest)
        progress.update(100, g.get_language_string(S_OP_PLEASE_WAIT))
    if success:
        _notify_success()
        _refresh_listing(args)
    else:
        _notify_failed()


def _handle_delete(args: dict) -> None:
    path = args.get("path") or ""
    if not path or not xbmcvfs.exists(path):
        _notify_failed()
        return
    is_folder = bool(args.get("is_folder")) or _is_folder_path(path)
    if not _confirm_delete(path, is_folder):
        return
    item_name = _entry_name(path, is_folder)
    with _file_op_progress(g.get_language_string(S_OP_DELETING).format(item_name)) as progress:
        progress.update(50, g.get_language_string(S_OP_PLEASE_WAIT))
        success = _delete_path(path, is_folder)
        progress.update(100, g.get_language_string(S_OP_PLEASE_WAIT))
    if success:
        _notify_success()
        _refresh_listing(args)
    else:
        _notify_failed()


def _handle_move(args: dict) -> None:
    path = args.get("path") or ""
    if not path or not xbmcvfs.exists(path):
        _notify_failed()
        return
    is_folder = bool(args.get("is_folder")) or _is_folder_path(path)
    dest_dir = _pick_destination_folder(args.get("parent_path") or _parent_dir(path))
    if not dest_dir:
        return
    name = _entry_name(path, is_folder)
    dest = _join_vfs_path(dest_dir, name)
    if is_folder:
        dest = tools.ensure_path_is_dir(dest)
    if _is_subpath(path, dest_dir) or _normalize_vfs(path).lower() == _normalize_vfs(dest).lower():
        _notify_failed()
        return
    if xbmcvfs.exists(dest):
        _notify_failed()
        return
    item_name = _entry_name(path, is_folder)
    with _file_op_progress(g.get_language_string(S_OP_MOVING).format(item_name)) as progress:
        progress.update(25, g.get_language_string(S_OP_PLEASE_WAIT))
        success = move_vfs_path(path, dest)
        progress.update(100, g.get_language_string(S_OP_PLEASE_WAIT))
    if success:
        _notify_success()
        _refresh_listing(args)
    else:
        _notify_failed()


def _handle_copy(args: dict) -> None:
    path = args.get("path") or ""
    if not path or not xbmcvfs.exists(path):
        _notify_failed()
        return
    is_folder = bool(args.get("is_folder")) or _is_folder_path(path)
    dest_dir = _pick_destination_folder(args.get("parent_path") or _parent_dir(path))
    if not dest_dir:
        return
    name = _entry_name(path, is_folder)
    dest = _join_vfs_path(dest_dir, name)
    success = False
    with _file_op_progress(g.get_language_string(S_OP_COPYING).format(name)) as progress:
        if is_folder:
            dest = tools.ensure_path_is_dir(dest)
            if not _is_subpath(path, dest_dir):
                total_bytes = _measure_vfs_tree_bytes(path)
                progress_state = {
                    "copied_bytes": 0,
                    "total_bytes": max(total_bytes, 1),
                    "label": name,
                    "current_file": name,
                }
                progress.update(0, name, g.get_language_string(S_OP_COPYING).format(name))
                success = _copy_vfs_tree(path, dest, progress=progress, progress_state=progress_state)
        elif not xbmcvfs.exists(dest):
            file_size = max(_vfs_file_size(path), 1)
            progress_state = {
                "copied_bytes": 0,
                "total_bytes": file_size,
                "label": name,
                "current_file": name,
            }
            progress.update(0, name, g.get_language_string(S_OP_COPYING).format(name))
            success = _copy_vfs_file_chunked(
                path,
                dest,
                progress=progress,
                progress_state=progress_state,
            )
        if success:
            progress.update(100, name, g.get_language_string(S_OP_SUCCESS))
    if success:
        _notify_success()
        _refresh_listing(args)
    else:
        _notify_failed()


def _handle_move_to_library(args: dict) -> None:
    path = args.get("path") or ""
    if not path or not xbmcvfs.exists(path):
        _notify_failed()
        return
    is_folder = bool(args.get("is_folder")) or _is_folder_path(path)
    if not g.configured_directory_path("local.location"):
        g.notification(g.ADDON_NAME, g.get_language_string(S_LOCAL_LIBRARY_NOT_SET))
        return
    item_name = _entry_name(path, is_folder)
    with _file_op_progress(g.get_language_string(S_OP_MOVING).format(item_name)) as progress:
        progress.update(25, g.get_language_string(S_OP_PLEASE_WAIT))
        dest = manual_move_to_local_library(path, is_folder=is_folder)
        progress.update(100, g.get_language_string(S_OP_PLEASE_WAIT))
    if dest:
        _notify_success()
        _refresh_listing(args)
    else:
        _notify_failed()


def _handle_create_subfolder(args: dict) -> None:
    """Create a new folder on the current browse page (sibling of the selected item)."""
    parent_path = args.get("parent_path") or ""
    browse_dir = tools.ensure_path_is_dir(parent_path) if parent_path else ""
    if not browse_dir or not xbmcvfs.exists(browse_dir):
        _notify_failed()
        return
    folder_name = g.get_keyboard_input(g.get_language_string(S_NEW_FOLDER_HEADING))
    if not folder_name:
        return
    folder_name = sanitize_path_component(folder_name)
    dest = tools.ensure_path_is_dir(_join_vfs_path(browse_dir, folder_name))
    if xbmcvfs.exists(dest):
        _refresh_listing(args)
        _notify_failed()
        return
    with _file_op_progress(g.get_language_string(S_OP_CREATING_FOLDER).format(folder_name)) as progress:
        progress.update(50, g.get_language_string(S_OP_PLEASE_WAIT))
        success = bool(xbmcvfs.mkdirs(dest))
        if not success and xbmcvfs.exists(dest):
            success = True
        progress.update(100, g.get_language_string(S_OP_PLEASE_WAIT))
    if success:
        _notify_success()
        _refresh_listing(args)
    else:
        _notify_failed()


def _format_timestamp(epoch: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))
    except (OSError, OverflowError, ValueError):
        return str(epoch)


def _handle_info(args: dict) -> None:
    path = args.get("path") or ""
    if not path or not xbmcvfs.exists(path):
        _notify_failed()
        return
    is_folder = bool(args.get("is_folder")) or _is_folder_path(path)
    lines = [path]
    try:
        stat = xbmcvfs.Stat(path)
        size = stat.st_size()
        if is_folder:
            folder_count, file_count, tree_bytes = _summarize_vfs_tree(path)
            lines.append(f"Folders: {folder_count}")
            lines.append(f"Files: {file_count}")
            if tree_bytes > 0:
                lines.append(tools.bytes_size_display(tree_bytes))
        else:
            lines.append(tools.bytes_size_display(size))
        try:
            mtime = stat.st_mtime()
            lines.append(_format_timestamp(mtime))
        except (AttributeError, OSError, TypeError):
            pass
    except OSError:
        pass
    xbmcgui.Dialog().ok(g.get_language_string(S_ITEM_INFO), "[CR]".join(lines))

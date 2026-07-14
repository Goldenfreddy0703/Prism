from __future__ import annotations

import contextlib
import json
import os
import time
import zipfile
from io import BytesIO

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.common import tools
from resources.lib.database import cache
from resources.lib.database.premiumizeTransfers import PremiumizeTransfers
from resources.lib.database.skinManager import SkinManager
from resources.lib.debrid import all_debrid
from resources.lib.debrid import premiumize
from resources.lib.debrid import real_debrid
from resources.lib.indexers.simkl import SimklAPI
from resources.lib.indexers.tvdb import TVDBAPI
from resources.lib.modules.globals import g
from resources.lib.modules.providers.install_manager import ProviderInstallManager

BACKUP_FORMAT = "prism-userdata-backup"
BACKUP_FORMAT_VERSION = 1
MANIFEST_NAME = "prism-backup-manifest.json"
SKIP_BACKUP_FILENAMES = frozenset({"qr_code.png"})
SKIP_BACKUP_SUFFIXES = (".db-wal", ".db-shm", ".temp")


def _vfs_join(base: str, filename: str) -> str:
    base = (base or "").replace("\\", "/").rstrip("/")
    return f"{base}/{filename}"


def _write_bytes_to_vfs(path: str, data: bytes) -> bool:
    handle = None
    try:
        handle = xbmcvfs.File(tools.validate_path(path), "wb")
        handle.write(data)
        return True
    except OSError:
        g.log_stacktrace()
        return False
    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                handle.close()


def _read_bytes_from_vfs(path: str) -> bytes | None:
    handle = None
    try:
        handle = xbmcvfs.File(tools.validate_path(path))
        return handle.readBytes()
    except OSError:
        return None
    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                handle.close()


def _open_zip_archive(path: str) -> zipfile.ZipFile:
    data = _read_bytes_from_vfs(path)
    if not data:
        raise OSError(f"Unable to read zip archive: {path}")
    return zipfile.ZipFile(BytesIO(data))


def _backup_export_filename() -> str:
    stamp = time.strftime("%Y-%m-%d")
    return f"prism-backup-{stamp}.zip"


def _should_skip_backup_path(relative_path: str) -> bool:
    basename = os.path.basename(relative_path.replace("\\", "/"))
    if basename in SKIP_BACKUP_FILENAMES:
        return True
    lowered = relative_path.replace("\\", "/").lower()
    return lowered.endswith(SKIP_BACKUP_SUFFIXES)


def _build_backup_manifest() -> dict:
    return {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "addon_id": g.ADDON_ID,
        "addon_version": g.ADDON.getAddonInfo("version"),
        "kodi_version": getattr(g, "KODI_FULL_VERSION", None) or str(getattr(g, "KODI_VERSION", "")),
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _iter_userdata_files(root_path: str):
    root_path = tools.translate_path(root_path)
    if not os.path.isdir(root_path):
        return
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
        for name in filenames:
            full_path = os.path.join(dirpath, name)
            relative_path = os.path.relpath(full_path, root_path).replace("\\", "/")
            if _should_skip_backup_path(relative_path):
                continue
            yield full_path, relative_path


def _create_userdata_zip(dest_path: str) -> bool:
    userdata_path = tools.translate_path(g.ADDON_USERDATA_PATH)
    file_count = 0
    try:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(_build_backup_manifest(), indent=2, sort_keys=True),
            )
            for full_path, relative_path in _iter_userdata_files(userdata_path):
                archive.write(full_path, relative_path)
                file_count += 1
        if not _write_bytes_to_vfs(dest_path, buffer.getvalue()):
            return False
    except OSError:
        g.log_stacktrace()
        return False

    return file_count > 0 or os.path.isdir(userdata_path) or xbmcvfs.exists(userdata_path)


def _zip_member_is_safe(member: str) -> bool:
    if not member or member.startswith("/") or ".." in member.replace("\\", "/").split("/"):
        return False
    return True


def _resolve_zip_target(dest_root: str, member: str) -> str | None:
    if not _zip_member_is_safe(member):
        return None
    normalized_member = member.replace("\\", "/").rstrip("/")
    if not normalized_member or normalized_member == MANIFEST_NAME:
        return None
    dest_root = tools.translate_path(dest_root)
    dest_root = os.path.abspath(dest_root)
    target = os.path.abspath(os.path.join(dest_root, normalized_member.replace("/", os.sep)))
    if target != dest_root and not target.startswith(dest_root + os.sep):
        return None
    return target


def _is_prism_backup_zip(path: str) -> bool:
    if not path or not xbmcvfs.exists(path):
        return False
    try:
        with _open_zip_archive(path) as archive:
            names = archive.namelist()
            if MANIFEST_NAME in names:
                manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
                return (
                    manifest.get("format") == BACKUP_FORMAT
                    and manifest.get("addon_id") == g.ADDON_ID
                )
            if "settings.xml" in names:
                return _is_prism_settings_file(path, member_name="settings.xml", archive=archive)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError, ValueError):
        return False
    return False


def _is_prism_settings_file(path: str, *, member_name: str | None = None, archive=None) -> bool:
    if not path and archive is None:
        return False
    try:
        if archive is not None and member_name:
            head = archive.read(member_name)[:4096]
        else:
            with xbmcvfs.File(path, "r") as handle:
                head = handle.read(4096)
    except OSError:
        return False
    if not isinstance(head, str):
        try:
            head = head.decode("utf-8", errors="ignore")
        except Exception:
            return False
    return "<settings" in head and 'id="plugin.video.prism"' in head


def _should_skip_zip_extract_member(member: str) -> bool:
    normalized = member.replace("\\", "/").rstrip("/")
    return normalized == MANIFEST_NAME


def _extract_backup_zip(source_path: str, dest_root: str) -> bool:
    dest_root = tools.translate_path(dest_root)
    if not xbmcvfs.exists(dest_root):
        xbmcvfs.mkdir(dest_root)

    try:
        with _open_zip_archive(source_path) as archive:
            for member in archive.namelist():
                if _should_skip_zip_extract_member(member):
                    continue
                if member.endswith("/"):
                    target_dir = _resolve_zip_target(dest_root, member)
                    if target_dir:
                        xbmcvfs.mkdirs(target_dir)
                    continue
                target_path = _resolve_zip_target(dest_root, member)
                if not target_path:
                    raise ValueError(f"Unsafe zip member: {member}")
                parent = os.path.dirname(target_path)
                if parent and not xbmcvfs.exists(parent):
                    xbmcvfs.mkdirs(parent)
                with archive.open(member) as source, open(target_path, "wb") as target:
                    target.write(source.read())
    except (OSError, zipfile.BadZipFile, ValueError):
        g.log_stacktrace()
        return False
    return True


def _pre_import_backup_path() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    parent = os.path.dirname(tools.validate_path(g.ADDON_USERDATA_PATH))
    return os.path.join(parent, f"prism-pre-import-{stamp}.zip")


def _prompt_restart_after_import() -> None:
    if xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(30904)):
        xbmc.executebuiltin("RestartApp")
        return
    xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30905))


def export_settings() -> None:
    userdata_path = tools.validate_path(g.ADDON_USERDATA_PATH)
    if not xbmcvfs.exists(userdata_path):
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30906))
        return

    export_dir = xbmcgui.Dialog().browse(
        3,
        f"{g.ADDON_NAME}: {g.get_language_string(30892)}",
        "files",
    )
    if not export_dir:
        return

    filename = _backup_export_filename()
    dest = _vfs_join(export_dir, filename)
    if not xbmcgui.Dialog().yesno(
        g.ADDON_NAME,
        g.get_language_string(30901).format(filename),
    ):
        return

    if _create_userdata_zip(dest):
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30902).format(dest))
    else:
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30898))


def import_settings() -> None:
    source = xbmcgui.Dialog().browse(
        1,
        f"{g.ADDON_NAME}: {g.get_language_string(30891)}",
        "files",
        "",
        False,
        False,
    )
    if not source:
        return

    source = tools.validate_path(source)
    lowered = source.lower()
    if lowered.endswith(".zip"):
        _import_backup_zip(source)
        return
    if lowered.endswith(".xml"):
        _import_settings_xml(source)
        return
    xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30903))


def _import_backup_zip(source: str) -> None:
    if not _is_prism_backup_zip(source):
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30903))
        return

    if not xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(30900)):
        return

    userdata_path = tools.validate_path(g.ADDON_USERDATA_PATH)
    pre_import_path = None
    if xbmcvfs.exists(userdata_path) and any(_iter_userdata_files(userdata_path)):
        pre_import_path = _pre_import_backup_path()
        if not _create_userdata_zip(pre_import_path):
            xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30898))
            return

    if xbmcvfs.exists(userdata_path):
        xbmcvfs.rmdir(userdata_path, True)
    xbmcvfs.mkdir(userdata_path)

    if not _extract_backup_zip(source, userdata_path):
        if pre_import_path and xbmcvfs.exists(pre_import_path):
            xbmcvfs.rmdir(userdata_path, True)
            xbmcvfs.mkdir(userdata_path)
            _extract_backup_zip(pre_import_path, userdata_path)
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30898))
        return

    _prompt_restart_after_import()


def _import_settings_xml(source: str) -> None:
    if not _is_prism_settings_file(source):
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30893))
        return

    if not xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(30894)):
        return

    userdata_path = tools.validate_path(g.ADDON_USERDATA_PATH)
    if not xbmcvfs.exists(userdata_path):
        xbmcvfs.mkdir(userdata_path)

    backup_path = f"{g.SETTINGS_PATH}.bak"
    if xbmcvfs.exists(g.SETTINGS_PATH):
        if xbmcvfs.exists(backup_path):
            xbmcvfs.delete(backup_path)
        xbmcvfs.copy(g.SETTINGS_PATH, backup_path)

    if xbmcvfs.exists(g.SETTINGS_PATH):
        xbmcvfs.delete(g.SETTINGS_PATH)

    if xbmcvfs.copy(source, g.SETTINGS_PATH):
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30897))
        return

    if xbmcvfs.exists(backup_path):
        xbmcvfs.copy(backup_path, g.SETTINGS_PATH)
    xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30898))


def update_themes():
    """
    Performn checks for any theme updates
    :return: None
    :rtype: None
    """
    if g.get_bool_setting("skin.updateAutomatic"):
        SkinManager().check_for_updates(silent=True)


def update_provider_packages():
    """
    Perform checks for provider package updates
    :return: None
    :rtype: None
    """
    provider_check_stamp = g.get_float_runtime_setting("provider.updateCheckTimeStamp", 0)
    automatic = g.get_bool_setting("providers.autoupdates")
    if time.time() > (provider_check_stamp + (24 * (60 * 60))):
        available_updates = ProviderInstallManager().check_for_updates(silent=True, automatic=automatic)
        if not automatic and len(available_updates) > 0:
            g.notification(g.ADDON_NAME, g.get_language_string(30253))
        g.set_runtime_setting("provider.updateCheckTimeStamp", str(time.time()))


def refresh_apis():
    """
    Refresh common API tokens
    :return: None
    :rtype: None
    """
    if g.get_setting("simkl.auth"):
        SimklAPI().get_activities()
    real_debrid.RealDebrid().try_refresh_token()
    TVDBAPI().try_refresh_token()


def wipe_install():
    """
    Destroys Prism's user_data folder for current user resetting addon to default
    :return: None
    :rtype: None
    """
    confirm = xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(30083))
    if confirm == 0:
        return

    confirm = xbmcgui.Dialog().yesno(
        g.ADDON_NAME,
        f"{g.get_language_string(30034)}{g.color_string(g.get_language_string(30035))}",
    )
    if confirm == 0:
        return

    path = tools.validate_path(g.ADDON_USERDATA_PATH)
    if xbmcvfs.exists(path):
        xbmcvfs.rmdir(path, True)
    xbmcvfs.mkdir(g.ADDON_USERDATA_PATH)


def premiumize_transfer_cleanup():
    """
    Cleanup transfers created by Prism at Premiumize
    :return: None
    :rtype: NOne
    """
    service = premiumize.Premiumize()
    premiumize_transfers = PremiumizeTransfers()
    fair_usage = service.get_used_space()
    threshold = g.get_float_setting("premiumize.threshold")

    if fair_usage < threshold:
        g.log("Premiumize Fair Usage below threshold, no cleanup required")
        return
    prism_transfers = premiumize_transfers.get_premiumize_transfers()
    if prism_transfers is None:
        g.log("Failed to cleanup transfers, API error", "error")
        return
    if len(prism_transfers) == 0:
        g.log("No Premiumize transfers have been created")
        return
    g.log("Premiumize Fair Usage is above threshold, cleaning up Prism transfers")
    for i in prism_transfers:
        service.delete_transfer(i["transfer_id"])
        premiumize_transfers.remove_premiumize_transfer(i["transfer_id"])


def account_premium_status_checks():
    """
    Updates premium status settings to reflect current state and advises users of expiries if enabled
    :return: None
    :rtype: None
    """

    def set_settings_status(debrid_provider, status):
        """
        Ease of use method to set premium status setting
        :param debrid_provider: setting prefix for debrid provider
        :type debrid_provider: str
        :param is_premium: Status of premium status
        :type is_premium: bool
        :return: None
        :rtype: None
        """
        g.set_setting(f"{debrid_provider}.premiumstatus", status.title())

    def display_expiry_notification(display_debrid_name):
        """
        Ease of use method to notify user of expiry of debrid premium status
        :param display_debrid_name: Debrid providers full display name
        :type display_debrid_name: str
        :return: None
        :rtype: None
        """
        if g.get_bool_setting("general.accountNotifications"):
            g.notification(
                f"{g.ADDON_NAME}",
                g.get_language_string(30036).format(display_debrid_name),
            )

    valid_debrid_providers = [
        ("Real Debrid", real_debrid.RealDebrid, "rd"),
        ("Premiumize", premiumize.Premiumize, "premiumize"),
        ("All Debrid", all_debrid.AllDebrid, "alldebrid"),
    ]

    for service in valid_debrid_providers:
        service_module = service[1]()
        if service_module.is_service_enabled():
            status = service_module.get_account_status()
            if status == "expired":
                display_expiry_notification(service[0])
            g.log(f"{service[0]}: {status}")
            set_settings_status(service[2], status)


def toggle_reuselanguageinvoker(forced_state=None):
    def _store_and_reload(output):
        with open(file_path, "w+") as addon_xml:
            addon_xml.writelines(output)
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30531))
        g.reload_profile()

    file_path = os.path.join(g.ADDON_DATA_PATH, "addon.xml")

    with open(file_path) as addon_xml:
        file_lines = addon_xml.readlines()

    for i in range(len(file_lines)):
        line_string = file_lines[i]
        if "reuselanguageinvoker" in file_lines[i]:
            if ("false" in line_string and forced_state is None) or ("false" in line_string and forced_state):
                file_lines[i] = file_lines[i].replace("false", "true")
                g.set_setting("reuselanguageinvoker.status", "Enabled")
                _store_and_reload(file_lines)
            elif ("true" in line_string and forced_state is None) or ("true" in line_string and forced_state is False):
                file_lines[i] = file_lines[i].replace("true", "false")
                g.set_setting("reuselanguageinvoker.status", "Disabled")
                _store_and_reload(file_lines)
            break


# def clean_deprecated_settings():
#     """
#     Removes settings no longer defined in the settings.xml file from the users user_data settings file
#     :return: None
#     :rtype: None
#     """
#     settings_helper = SettingsHelper()
#     settings_helper.create_and_clean_settings()
#     if len(settings_helper.valid_settings) != len(
#         settings_helper.current_user_settings
#     ):
#         g.log(
#             "Mismatch in valid settings, cancelling the removal of deprecated settings",
#             "warning",
#         )
#         return
#     if len(settings_helper.removed_settings) == 0:
#         return
#     settings_helper.save_settings()
#     g.log(
#         "Filtered settings, removed {} deprecated settings".format(
#             len(settings_helper.removed_settings)
#         )
#     )


def run_maintenance():
    """
    Entry point for background maintenance cycle
    :return: None
    :rtype: None
    """
    g.log("Performing Maintenance")
    # ADD COMMON HOUSE KEEPING ITEMS HERE #

    # Refresh API tokens

    try:
        refresh_apis()
    except Exception as e:
        g.log(f"Failed to update API keys: {e}", 'error')

    try:
        account_premium_status_checks()
    except Exception as e:
        g.log(f"Failed to check account status: {e}", 'error')
    ProviderInstallManager()
    update_provider_packages()
    update_themes()

    try:
        from resources.lib.anime.mal_dubs import update_mal_dub_list

        update_mal_dub_list()
    except Exception as e:
        g.log(f"Failed to update MAL-Dubs list: {e}", "warning")

    # Check Premiumize Fair Usage for cleanup
    if g.get_bool_setting("premiumize.enabled") and g.get_bool_setting("premiumize.autodelete"):
        try:
            premiumize_transfer_cleanup()
        except Exception as e:
            g.log(f"Failed to cleanup PM transfers: {e}", 'error')

    # clean_deprecated_settings()
    cache.Cache().check_cleanup()
    try:
        from resources.lib.database.sync_meta_cache import SyncMetaCache

        SyncMetaCache().prefetch()
    except Exception as e:
        g.log(f"Failed to prefetch sync meta cache: {e}", "warning")
    try:
        from resources.lib.modules.cache_maintenance import run_cache_maintenance

        run_cache_maintenance()
    except Exception as e:
        g.log(f"Failed cache maintenance: {e}", "warning")

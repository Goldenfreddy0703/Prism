from __future__ import annotations

import os
import shutil
import time

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

_DEFERRED_WIPE_FLAG = "special://profile/prism_wipe_pending"


def _deferred_wipe_flag_path() -> str:
    return tools.translate_path(_DEFERRED_WIPE_FLAG)


def stop_prism_background_services() -> None:
    """Best-effort shutdown of provider services and DB handles before deleting addon_data."""
    g.set_runtime_setting("prism.wipe_in_progress", True)

    try:
        import resources.lib.modules.monkey_requests as monkey_requests

        monkey_requests.allow_provider_requests = False
        monkey_requests.PRE_TERM_BLOCK = True
    except Exception:
        pass

    try:
        from resources.lib.modules.providers.service_manager import ProvidersServiceManager

        manager = ProvidersServiceManager()
        for package in manager.known_packages:
            pack_name = package.get("pack_name")
            if pack_name:
                manager.stop_package_services(pack_name)
        for _ in range(30):
            messages = manager.get_messages()
            if not messages:
                break
            manager._handle_messages(messages)
    except Exception:
        g.log_stacktrace()

    from resources.lib.common.backup_restore import release_userdata_locks

    release_userdata_locks()


def schedule_deferred_wipe() -> None:
    flag = _deferred_wipe_flag_path()
    try:
        with open(flag, "w", encoding="utf-8") as handle:
            handle.write(str(int(time.time())))
        g.log(f"Prism: scheduled deferred addon_data wipe ({flag})", "info")
    except OSError:
        g.log_stacktrace()


def consume_deferred_wipe_at_startup() -> bool:
    """Run before any Prism DB init on service start (no background threads yet)."""
    flag = _deferred_wipe_flag_path()
    if not os.path.isfile(flag):
        return False
    try:
        os.remove(flag)
    except OSError:
        g.log(f"Prism: could not remove deferred wipe flag {flag}", "warning")
    g.log("Prism: performing deferred addon_data wipe at cold service start", "info")
    return _wipe_userdata_folder_core()


def export_settings() -> None:
    from resources.lib.common.backup_restore import export_backup

    export_backup()


def import_settings() -> None:
    from resources.lib.common.backup_restore import import_backup

    import_backup()


def update_themes():
    """
    Performn checks for any theme updates
    :return: None
    :rtype: None
    """
    automatic = g.get_bool_setting("skin.updateAutomatic")
    if automatic:
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
        SimklAPI().try_refresh_token()
        # Activities sync is owned by syncSimklActivities (throttled); do not force-fetch here.
    real_debrid.RealDebrid().try_refresh_token()
    TVDBAPI().try_refresh_token()


def _userdata_file_count(userdata_path: str) -> int:
    native = tools.translate_path(userdata_path)
    if not os.path.isdir(native):
        return 0
    total = 0
    for _root, _dirs, files in os.walk(native):
        total += len(files)
    return total


def _wipe_userdata_folder_core() -> bool:
    path = tools.validate_path(g.ADDON_USERDATA_PATH)
    native = tools.translate_path(path)
    before_count = _userdata_file_count(path)
    g.log(f"Wipe addon data: {before_count} file(s) under {path}", "info")

    try:
        if xbmcvfs.exists(path):
            if not xbmcvfs.rmdir(path, True):
                g.log("Wipe addon data: xbmcvfs.rmdir returned false (files may be locked)", "warning")

        if os.path.isdir(native):
            shutil.rmtree(native, ignore_errors=False)

        xbmcvfs.mkdir(g.ADDON_USERDATA_PATH)

        after_count = _userdata_file_count(path)
        ok = after_count == 0
        g.log(f"Wipe addon data: complete, {after_count} file(s) remaining", "info" if ok else "error")
        return ok
    except OSError:
        g.log_stacktrace()
        return False


def wipe_userdata_folder() -> bool:
    """Stop services, delete addon_data, or schedule a deferred wipe if files stay locked."""
    stop_prism_background_services()
    ok = _wipe_userdata_folder_core()
    g.clear_runtime_setting("prism.wipe_in_progress")
    if ok:
        return True
    schedule_deferred_wipe()
    return False


def prompt_restart_to_finish_wipe() -> None:
    if xbmcgui.Dialog().yesno(
        g.ADDON_NAME,
        "Prism must restart to finish removing old data (files were still in use). Restart now?",
    ):
        xbmc.executebuiltin("RestartApp")
    else:
        notify_wipe_incomplete()


def perform_addon_data_wipe() -> bool:
    """
    Wipe addon_data after stopping services. On failure, schedules wipe on next Kodi start
    and prompts to restart.
    """
    if wipe_userdata_folder():
        return True
    g.log("Prism: addon_data wipe incomplete — restart required", "warning")
    prompt_restart_to_finish_wipe()
    return False


def perform_migration_wipe() -> None:
    """
    5.0.57 migration wipe: stop services, try delete now, always defer + restart prompt
    (service has not opened databases yet, but provider threads may still lock files).
    """
    stop_prism_background_services()
    if not _wipe_userdata_folder_core():
        g.log("Prism: migration inline wipe incomplete — will finish after restart", "warning")
    g.clear_runtime_setting("prism.wipe_in_progress")
    schedule_deferred_wipe()
    prompt_restart_to_finish_wipe()


def prompt_restart_after_wipe() -> None:
    if xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(31271)):
        xbmc.executebuiltin("RestartApp")


def notify_wipe_incomplete() -> None:
    xbmcgui.Dialog().ok(
        g.ADDON_NAME,
        "Some Prism data files could not be removed (still in use). Restart Kodi and run Wipe Addon Data again.",
    )


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

    if perform_addon_data_wipe():
        prompt_restart_after_wipe()


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
    g.log("Performing Maintenance", "debug")
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

    # Check Premiumize Fair Usage for cleanup
    if g.get_bool_setting("premiumize.enabled") and g.get_bool_setting("premiumize.autodelete"):
        try:
            premiumize_transfer_cleanup()
        except Exception as e:
            g.log(f"Failed to cleanup PM transfers: {e}", 'error')

    # clean_deprecated_settings()
    cache.Cache().check_cleanup()


def run_prism_idle_maintenance():
    """
    Prism-only background work (throttled, idle-only). Invoked via RunPlugin when not playing.
    Seren-equivalent cache work stays in run_maintenance() via check_cleanup().
    """
    from resources.lib.common.background_coordinator import (
        background_work_guard,
        idle_ok_for_background_work,
        mark_throttle,
        throttle_elapsed,
    )

    if not idle_ok_for_background_work():
        g.log("Prism idle maintenance: deferred — foreground or playback active", "debug")
        return

    with background_work_guard():
        try:
            from resources.lib.calendar.simkl_calendar import (
                prefetch_all_calendars,
                prefetch_calendars_enabled,
                weekly_cache_warm,
            )

            if (
                prefetch_calendars_enabled()
                and not weekly_cache_warm()
                and throttle_elapsed("prism.idle.calendar_last_run")
            ):
                warmed = prefetch_all_calendars()
                mark_throttle("prism.idle.calendar_last_run")
                if warmed:
                    g.log(f"Calendar prefetch warmed {warmed} weekly rows", "debug")
        except Exception as e:
            g.log(f"Failed to prefetch weekly calendars: {e}", "warning")

        try:
            from resources.lib.anime.mal_dubs import update_mal_dub_list

            if throttle_elapsed("prism.idle.mal_dubs_last_run"):
                if update_mal_dub_list():
                    mark_throttle("prism.idle.mal_dubs_last_run")
        except Exception as e:
            g.log(f"Failed to update MAL-Dubs list: {e}", "warning")

        try:
            from resources.lib.meta.enrichment import MetaEnrichmentQueue

            scheduled = MetaEnrichmentQueue.schedule_needs_update()
            if scheduled:
                g.log(f"Queued {scheduled} items for background meta enrichment", "debug")
            MetaEnrichmentQueue.process_idle()
        except Exception as e:
            g.log(f"Failed meta enrichment idle work: {e}", "warning")

        try:
            from resources.lib.discover.browse_catalog_seed import process_idle_browse_catalog_seed

            process_idle_browse_catalog_seed()
        except Exception as e:
            g.log(f"Failed browse catalog seed idle work: {e}", "warning")

"""Temporarily apply per-catalog Kodi locale settings during Prism playback."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import xbmc
import xbmcgui

from resources.lib.modules.catalog_profiles import normalize_catalog, resolve_catalog_from_item_information
from resources.lib.modules.globals import g

KODI_AUDIO_SETTING = "locale.audiolanguage"
KODI_SUBTITLE_SETTING = "locale.subtitlelanguage"

DEFAULT_AUDIO = "mediadefault"
DEFAULT_SUBTITLE = "original"

AUDIO_SPECIAL = (
    ("mediadefault", 307),
    ("original", 308),
    ("default", 309),
)

SUBTITLE_SPECIAL = (
    ("none", 231),
    ("forced_only", 13207),
    ("original", 308),
    ("default", 309),
)

ISO639_1_CODES = (
    "aa", "ab", "ae", "af", "ak", "am", "an", "ar", "as", "av", "ay", "az", "ba", "be", "bg", "bh", "bi", "bm", "bn",
    "bo", "br", "bs", "ca", "ce", "ch", "co", "cr", "cs", "cu", "cv", "cy", "da", "de", "dv", "dz", "ee", "el", "en",
    "eo", "es", "et", "eu", "fa", "ff", "fi", "fj", "fo", "fr", "fy", "ga", "gd", "gl", "gn", "gu", "gv", "ha", "he",
    "hi", "ho", "hr", "ht", "hu", "hy", "hz", "ia", "id", "ie", "ig", "ii", "ik", "io", "is", "it", "iu", "ja", "jv",
    "ka", "kg", "ki", "kj", "kk", "kl", "km", "kn", "ko", "kr", "ks", "ku", "kv", "kw", "ky", "la", "lb", "lg", "li",
    "ln", "lo", "lt", "lu", "lv", "mg", "mh", "mi", "mk", "ml", "mn", "mr", "ms", "mt", "my", "na", "nb", "nd", "ne",
    "ng", "nl", "nn", "no", "nr", "nv", "ny", "oc", "oj", "om", "or", "os", "pa", "pi", "pl", "ps", "pt", "qu", "rm",
    "rn", "ro", "ru", "rw", "sa", "sc", "sd", "se", "sg", "si", "sk", "sl", "sm", "sn", "so", "sq", "sr", "ss", "st",
    "su", "sv", "sw", "ta", "te", "tg", "th", "ti", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw", "ty", "ug", "uk",
    "ur", "uz", "ve", "vi", "vo", "wa", "wo", "xh", "yi", "yo", "za", "zh", "zu",
)


def catalog_from_item(item_information: dict | None) -> str:
    return normalize_catalog(resolve_catalog_from_item_information(item_information))


def _use_kodi_key(catalog: str) -> str:
    return f"playback.locale.usekodi.{normalize_catalog(catalog)}"


def _audio_key(catalog: str) -> str:
    return f"playback.audiolanguage.{normalize_catalog(catalog)}"


def _subtitle_key(catalog: str) -> str:
    return f"playback.subtitlelanguage.{normalize_catalog(catalog)}"


def _kodi_core_string(message_id: int) -> str:
    return g.get_language_string(message_id, addon=False)


@lru_cache(maxsize=1)
def _stream_language_names() -> tuple[str, ...]:
    names = []
    seen = set()
    for code in ISO639_1_CODES:
        try:
            name = xbmc.convertLanguage(code, xbmc.ENGLISH_NAME)
        except Exception:
            continue
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    names.sort(key=str.casefold)
    return tuple(names)


def _special_options(kind: str) -> tuple[tuple[str, str], ...]:
    special = AUDIO_SPECIAL if kind == "audio" else SUBTITLE_SPECIAL
    return tuple((_kodi_core_string(message_id), value) for value, message_id in special)


def language_options(kind: str) -> tuple[tuple[str, str], ...]:
    """Return (label, stored value) pairs matching Kodi locale language pickers."""
    options = list(_special_options(kind))
    options.extend((name, name) for name in _stream_language_names())
    return tuple(options)


def display_label_for_value(value: str | None, kind: str) -> str:
    if not value:
        return ""
    special = AUDIO_SPECIAL if kind == "audio" else SUBTITLE_SPECIAL
    for code, message_id in special:
        if code == value:
            return _kodi_core_string(message_id)
    return value


def get_catalog_audio(catalog: str) -> str:
    return g.get_setting(_audio_key(catalog), DEFAULT_AUDIO) or DEFAULT_AUDIO


def get_catalog_subtitle(catalog: str) -> str:
    return g.get_setting(_subtitle_key(catalog), DEFAULT_SUBTITLE) or DEFAULT_SUBTITLE


def set_use_kodi_defaults(catalog: str, enabled: bool) -> None:
    g.set_setting(_use_kodi_key(catalog), bool(enabled))


def set_catalog_audio(catalog: str, value: str) -> None:
    g.set_setting(_audio_key(catalog), value)


def set_catalog_subtitle(catalog: str, value: str) -> None:
    g.set_setting(_subtitle_key(catalog), value)


def reset_catalog_locale(catalog: str) -> None:
    catalog = normalize_catalog(catalog)
    set_use_kodi_defaults(catalog, True)
    set_catalog_audio(catalog, DEFAULT_AUDIO)
    set_catalog_subtitle(catalog, DEFAULT_SUBTITLE)


def uses_kodi_defaults(catalog: str) -> bool:
    return g.get_bool_setting(_use_kodi_key(catalog), True)


def resolve_catalog_locale(catalog: str) -> tuple[str, str] | None:
    """Return (audio, subtitle) Kodi setting values for catalog, or None to skip override."""
    catalog = normalize_catalog(catalog)
    if uses_kodi_defaults(catalog):
        return None
    audio = g.get_setting(_audio_key(catalog), DEFAULT_AUDIO) or DEFAULT_AUDIO
    subtitle = g.get_setting(_subtitle_key(catalog), DEFAULT_SUBTITLE) or DEFAULT_SUBTITLE
    return audio, subtitle


def get_kodi_setting_value(setting_id: str) -> str | None:
    result = g.json_rpc("Settings.GetSettingValue", {"setting": setting_id})
    if not isinstance(result, dict):
        return None
    value = result.get("value")
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def set_kodi_setting_value(setting_id: str, value: str) -> bool:
    if value is None:
        return False
    result = g.json_rpc(
        "Settings.SetSettingValue",
        {"setting": setting_id, "value": value},
    )
    if result is True:
        return True
    if isinstance(result, dict) and result.get("success") is True:
        return True
    return bool(result)


def apply_catalog_locale(catalog: str) -> dict[str, Any] | None:
    """Snapshot Kodi locale settings and apply per-catalog overrides."""
    locale = resolve_catalog_locale(catalog)
    if locale is None:
        return None

    audio_value, subtitle_value = locale
    backup = {
        KODI_AUDIO_SETTING: get_kodi_setting_value(KODI_AUDIO_SETTING),
        KODI_SUBTITLE_SETTING: get_kodi_setting_value(KODI_SUBTITLE_SETTING),
        "_restored": False,
        "_catalog": normalize_catalog(catalog),
    }

    if backup[KODI_AUDIO_SETTING] == audio_value and backup[KODI_SUBTITLE_SETTING] == subtitle_value:
        backup["_restored"] = True
        g.log(
            f"Locale playback: catalog={backup['_catalog']} already matches Kodi settings",
            "debug",
        )
        return backup

    audio_ok = set_kodi_setting_value(KODI_AUDIO_SETTING, audio_value)
    subtitle_ok = set_kodi_setting_value(KODI_SUBTITLE_SETTING, subtitle_value)
    if not audio_ok or not subtitle_ok:
        g.log(
            f"Locale playback: failed to apply catalog={backup['_catalog']} "
            f"(audio={audio_ok}, subtitle={subtitle_ok})",
            "warning",
        )
        restore_catalog_locale(backup)
        return None

    g.log(
        f"Locale playback: catalog={backup['_catalog']} audio={audio_value!r} subtitle={subtitle_value!r}",
        "debug",
    )
    return backup


def restore_catalog_locale(backup: dict[str, Any] | None) -> None:
    """Restore Kodi locale settings from a backup created by apply_catalog_locale."""
    if not backup or backup.get("_restored"):
        return

    audio_value = backup.get(KODI_AUDIO_SETTING)
    subtitle_value = backup.get(KODI_SUBTITLE_SETTING)
    if audio_value is not None:
        set_kodi_setting_value(KODI_AUDIO_SETTING, audio_value)
    if subtitle_value is not None:
        set_kodi_setting_value(KODI_SUBTITLE_SETTING, subtitle_value)

    backup["_restored"] = True
    g.log(
        f"Locale playback: restored Kodi settings after catalog={backup.get('_catalog')}",
        "debug",
    )

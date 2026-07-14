"""Shared air-date cutoff for release-day delay (general.datedelay)."""
from __future__ import annotations

import datetime

from resources.lib.common import tools
from resources.lib.modules.globals import g


def air_date_delay_enabled() -> bool:
    return g.get_bool_setting("general.datedelay")


def aired_cutoff_datetime() -> datetime.datetime:
    """UTC cutoff for treating an item as aired (now, or now - 1 day when delay is on)."""
    cutoff = datetime.datetime.utcnow()
    if air_date_delay_enabled():
        cutoff -= datetime.timedelta(days=1)
    return cutoff


def aired_cutoff_datetime_string() -> str:
    return g.datetime_to_string(aired_cutoff_datetime())


def item_has_aired(air_date) -> bool:
    """True when *air_date* is before the aired cutoff."""
    if not air_date:
        return False

    if int(str(air_date)[:4]) < 1970:
        return True

    parsed = tools.parse_datetime(air_date, False)
    return parsed < aired_cutoff_datetime()

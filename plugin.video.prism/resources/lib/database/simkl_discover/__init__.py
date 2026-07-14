"""Legacy package — discover rows now live in ``discover.cdn_store``."""

from resources.lib.discover.cdn_store import get_row, get_rows_by_ids, rows_for_catalog

__all__ = ("get_row", "get_rows_by_ids", "rows_for_catalog")

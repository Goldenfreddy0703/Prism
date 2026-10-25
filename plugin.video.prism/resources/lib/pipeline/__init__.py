"""Menu catalog pipelines (rewrite entry points)."""

from resources.lib.pipeline.catalog_page import CatalogPagePipeline
from resources.lib.pipeline.library_sync_service import LibrarySyncService

__all__ = ["CatalogPagePipeline", "LibrarySyncService"]

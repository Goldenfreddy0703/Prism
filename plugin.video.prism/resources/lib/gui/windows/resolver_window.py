import xbmc

from . import set_info_properties
from resources.lib.common import tools
from resources.lib.gui.windows.single_item_window import SingleItemWindow
from resources.lib.modules.exceptions import NoFileSelectionAvailable
from resources.lib.modules.exceptions import UserCancelledSelection
from resources.lib.modules.globals import g
from resources.lib.modules.resolver import Resolver


class ResolverWindow(SingleItemWindow):
    """
    Window for Resolver
    """

    def __init__(self, xml_file, location=None, item_information=None, close_callback=None):
        super().__init__(xml_file, location, item_information=item_information)
        self.return_data = None, None
        self.progress = 1
        self.resolver = None
        self.sources = None
        self.pack_select = False
        self.resolve_finished = False
        self.user_cancelled = False
        self._resolve_ran = False
        self._close_requested = False
        self.item_information = item_information
        self.close_callback = close_callback

    def handle_action(self, action_id, control_id=None):
        if control_id == 9999:
            self.close()

    def _request_close(self):
        if self._close_requested:
            return
        self._close_requested = True
        try:
            xbmc.executebuiltin(f"SendClick({self.getId()},9999)")
        except Exception:
            g.log_stacktrace()
        if not g.wait_for_abort(0.05):
            try:
                self.close()
            except Exception:
                g.log_stacktrace()

    def onInit(self):
        """
        Show resolver UI first, then resolve on the main thread so dialogs stack correctly.
        """
        super().onInit()
        if self._resolve_ran or not self.sources:
            return
        self._resolve_ran = True
        self._resolve_source()
        self._request_close()

    def _resolve_source(self):
        stream_link = None
        release_title = None
        total = len(self.sources)

        try:
            for index, source in enumerate(self.sources, start=1):
                if self.canceled:
                    return None, None
                self._update_window_properties(source)
                provider = source.get("debrid_provider") or source.get("provider") or "source"
                self.setProperty(
                    "notification_text",
                    f"{g.get_language_string(30603)} {index}/{total} — {provider}",
                )
                try:
                    stream_link, release_title = self.resolver.resolve_single_source(
                        source, self.item_information, self.pack_select
                    )
                    if stream_link:
                        break
                except (UserCancelledSelection, NoFileSelectionAvailable):
                    self.user_cancelled = True
                    break
                except Exception:
                    g.log_stacktrace()
                    continue
            if stream_link is None:
                self.return_data = None, None
            else:
                self.return_data = stream_link, release_title
        finally:
            self.resolve_finished = True

    def get_return_data(self):
        return (None, None) if self.canceled else self.return_data

    def _update_window_properties(self, source):
        debrid_provider = source.get("debrid_provider", "None").replace("_", " ")
        if "size" in source and source["size"] != "Variable":
            self.setProperty("source_size", tools.source_size_display(source["size"]))

        self.setProperty("release_title", source["release_title"])
        self.setProperty("debrid_provider", debrid_provider)
        self.setProperty("source_provider", source["provider"])
        self.setProperty("source_resolution", source["quality"])
        set_info_properties(source.get("info", {}), self)
        self.setProperty("source_type", source["type"])

        provider_imports = source.get("provider_imports", [])
        source_icon = self.provider_class.get_icon(provider_imports)
        if source_icon is not None:
            self.setProperty("source.icon", source_icon)

    def doModal(
        self,
        sources=None,
        pack_select=False,
    ):
        """
        Opens resolver UI, runs resolve work in onInit, then closes before returning.
        """
        self.sources = sources or []
        self.pack_select = pack_select
        self.resolve_finished = False
        self.user_cancelled = False
        self._resolve_ran = False
        self.return_data = None, None

        if not self.sources:
            return None, None

        self.resolver = Resolver()
        self._update_window_properties(self.sources[0])
        super().doModal()
        return self.get_return_data()

    def close(self):
        super().close()

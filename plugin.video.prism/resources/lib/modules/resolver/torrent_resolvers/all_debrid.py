from resources.lib.debrid.all_debrid import AllDebrid
from resources.lib.modules.exceptions import GeneralCachingFailure
from resources.lib.modules.globals import g
from resources.lib.modules.resolver.torrent_resolvers.base_resolver import (
    TorrentResolverBase,
)


class AllDebridResolver(TorrentResolverBase):
    """
    Resolver for All Debrid
    """

    def __init__(self):
        super().__init__()
        self.debrid_module = AllDebrid()
        self._source_normalization = (
            ("size", "size", lambda k: (k / 1024) / 1024),
            ("path", "path", None),
            ("filename", "release_title", None),
            ("id", "id", None),
            ("link", "link", None),
        )
        self.magnet_id = None

    def _fetch_source_files(self, torrent, item_information):
        magnet_ref = torrent.get("magnet") or torrent.get("hash")
        try:
            self.magnet_id, links = self.debrid_module.fetch_magnet_file_links(magnet_ref)
        except GeneralCachingFailure as exc:
            status = exc.args[0] if exc.args else {}
            failed_id = self.magnet_id or (status.get("id") if isinstance(status, dict) else None)
            if failed_id:
                self.debrid_module.delete_magnet(failed_id)
            raise exc
        return links

    def resolve_stream_url(self, file_info):
        """
        Convert provided source file into a link playable through debrid service
        :param file_info: Normalised information on source file
        :return: streamable link
        """
        return self.debrid_module.resolve_hoster(file_info["link"])

    def _do_post_processing(self, item_information, torrent, identified_file):
        if g.get_bool_setting("alldebrid.autodelete") or identified_file is None:
            self.debrid_module.delete_magnet(self.magnet_id)

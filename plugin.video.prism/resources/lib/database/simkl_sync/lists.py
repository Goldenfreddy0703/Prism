from itertools import repeat

from resources.lib.database.simkl_sync import database
from resources.lib.modules.metadataHandler import MetadataHandler


class SimklSyncDatabase(database.SimklSyncDatabase):
    def extract_browse_page(self, url, media_type, **params):
        result = []
        page_number = params.get("page", 1)
        no_paging = params.get("no_paging", False)
        pull_all = params.pop("pull_all", False)
        params["limit"] = self.page_limit
        get = MetadataHandler.get_simkl_info
        for page in self.simkl_api.get_all_pages_json(url, **params):
            if results := self.task_queue.map_results(
                self._indexed_list_contents,
                ((get(i, "username"), get(i, "simkl_id"), media_type) for i in page),
                kwargs_iterable=repeat(params),
            ):
                result.extend(
                    i for i in page if results.get(i.get("simkl_id")) and len(results.get(i.get("simkl_id"))) != 0
                )
                if not pull_all and len(result) >= (self.page_limit * page_number):
                    return result[self.page_limit * (page_number - 1) : self.page_limit * page_number]

        if pull_all and no_paging:
            return result
        else:
            return result[self.page_limit * (page_number - 1) : self.page_limit * page_number]

    def _indexed_list_contents(self, username, simkl_id, media_type, **params):
        params["page"] = 1
        return {simkl_id: self.get_list_content(username, simkl_id, media_type, **params)}

    def get_list_content(self, username, simkl_id, media_type, **params):
        list_item_url = f"users/{username}/lists/{simkl_id}/items/{media_type}"
        params["pull_all"] = True
        return self._extract_browse_page(list_item_url, media_type, extended="full", **params)

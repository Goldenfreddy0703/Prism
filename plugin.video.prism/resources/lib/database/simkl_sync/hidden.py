from resources.lib.database.simkl_sync import database


class SimklSyncDatabase(database.SimklSyncDatabase):
    @property
    def insert_query(self):
        return "REPLACE INTO hidden (simkl_id, mediatype, section) VALUES (?, ?, ?)"

    def add_hidden_item(self, simkl_id, media_type, section):
        self.execute_sql(self.insert_query, (simkl_id, media_type, section))

    def get_hidden_items(self, section, media_type=None):

        if media_type is None:
            return self.fetchall("SELECT simkl_id FROM hidden WHERE section=?", (section,))
        else:
            return self.fetchall(
                "SELECT simkl_id FROM hidden WHERE section=? and mediatype=?",
                (section, media_type),
            )

    def remove_item(self, section, simkl_id):
        self.execute_sql(
            "DELETE FROM hidden WHERE section=? AND simkl_id=?",
            (str(section), int(simkl_id)),
        )

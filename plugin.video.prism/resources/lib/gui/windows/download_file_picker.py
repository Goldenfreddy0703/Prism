"""Custom multi-file download picker with select all / clear all."""
from __future__ import annotations

import xbmcgui

from resources.lib.gui.windows.base_window import BaseWindow
from resources.lib.modules.globals import g

LIST_CONTROL = 1000
SELECT_ALL_CONTROL = 2001
CLEAR_ALL_CONTROL = 2002
CONFIRM_CONTROL = 2003
CANCEL_CONTROL = 2999


def pick_download_files(entries: list[dict]) -> list[tuple] | None:
    """Show the picker and return selected ``(file_dict, filename)`` rows, or None if cancelled."""
    if not entries:
        return []

    from resources.lib.database.skinManager import SkinManager

    xml_file, skin_path = SkinManager().confirm_skin_path("download_file_picker.xml")
    window = DownloadFilePicker(xml_file, skin_path)
    window.entries = [dict(entry) for entry in entries]
    window.doModal()
    result = list(window.selected_files) if window.confirmed else None
    del window
    return result


class DownloadFilePicker(BaseWindow):
    def __init__(self, xml_file, location):
        super().__init__(xml_file, location)
        self.entries = []
        self.list_control = None
        self.selected_files: list[tuple] = []
        self.confirmed = False

    def onInit(self):
        self.list_control = self.getControlList(LIST_CONTROL)
        self._populate_list()
        self._update_summary()
        self.set_default_focus(self.list_control, LIST_CONTROL, control_list_reset=True)
        super().onInit()

    @staticmethod
    def _set_item_properties(menu_item: xbmcgui.ListItem, entry: dict) -> None:
        menu_item.setProperty("filename", entry.get("filename") or "")
        menu_item.setProperty("path", entry.get("path") or "")
        menu_item.setProperty("filesize", entry.get("size_label") or "-")
        menu_item.setProperty("selected", str(bool(entry.get("selected"))))

    def _populate_list(self):
        if not self.list_control:
            return

        for idx, entry in enumerate(self.entries):
            label = entry.get("filename") or entry.get("path") or ""
            if idx < self.list_control.size():
                item = self.list_control.getListItem(idx)
                item.setLabel(label)
                self._set_item_properties(item, entry)
            else:
                item = xbmcgui.ListItem(label=label)
                self._set_item_properties(item, entry)
                self.list_control.addItem(item)

        while self.list_control.size() > len(self.entries):
            self.list_control.removeItem(self.list_control.size() - 1)

    def _update_summary(self):
        selected_count = sum(1 for entry in self.entries if entry.get("selected"))
        self.setProperty("picker.selected_count", str(selected_count))
        self.setProperty("picker.total_count", str(len(self.entries)))

    def _toggle_row(self, index: int):
        if index < 0 or index >= len(self.entries):
            return
        entry = self.entries[index]
        entry["selected"] = not entry.get("selected")
        if index < self.list_control.size():
            item = self.list_control.getListItem(index)
            self._set_item_properties(item, entry)
        self._update_summary()

    def _set_all(self, selected: bool):
        for idx, entry in enumerate(self.entries):
            entry["selected"] = selected
            if idx < self.list_control.size():
                self._set_item_properties(self.list_control.getListItem(idx), entry)
        self._update_summary()

    def _confirm(self):
        selected = [entry for entry in self.entries if entry.get("selected")]
        if not selected:
            g.notification(g.ADDON_NAME, g.get_language_string(30951))
            return
        self.selected_files = [(entry["file"], entry["filename"]) for entry in selected]
        self.confirmed = True
        self.close()

    def handle_action(self, action, control_id=None):
        if action == 7:
            if control_id == LIST_CONTROL:
                self._toggle_row(self.list_control.getSelectedPosition())
            elif control_id == SELECT_ALL_CONTROL:
                self._set_all(True)
            elif control_id == CLEAR_ALL_CONTROL:
                self._set_all(False)
            elif control_id == CONFIRM_CONTROL:
                self._confirm()
            elif control_id == CANCEL_CONTROL:
                self.close()

    def close(self):
        super().close()

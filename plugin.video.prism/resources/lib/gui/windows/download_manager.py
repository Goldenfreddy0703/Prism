import time

import xbmc
import xbmcgui

from resources.lib.gui.windows.base_window import BaseWindow
from resources.lib.modules.download_manager import Manager
from resources.lib.modules.globals import g

CONTEXT_MENU_ACTIONS = {
    117,  # ACTION_CONTEXT_MENU
    101,  # ACTION_MOUSE_RIGHT_CLICK
    108,  # ACTION_MOUSE_LONG_CLICK
    163,  # ACTION_MENU
}

CONTEXT_MENU_SUPPRESS_SECONDS = 0.5


class DownloadManager(BaseWindow):
    def __init__(self, xml_file, location, item_information=None):
        super().__init__(xml_file, location, item_information=item_information)
        self.manager = Manager()
        self.list_control = None
        self.exit_requested = False
        self._menu_open = False
        self._context_menu_cooldown = 0
        self.downloads = []

    def onInit(self):
        self.list_control = self.getControlList(1000)

        self._populate_menu_items()
        self.set_default_focus(self.list_control, 2999, control_list_reset=True)
        super().onInit()
        self._background_info_updater()

    def _context_menu_suppressed(self):
        return time.time() < self._context_menu_cooldown

    def onAction(self, action):
        action_id = action.getId()

        if action_id in CONTEXT_MENU_ACTIONS:
            if not self._context_menu_suppressed():
                self._show_download_context_menu(self._list_position())
            return

        if action_id in self.action_exitkeys_id:
            self.close()
            return

        if action_id != 7:
            self.handle_action(action_id, self.getFocusId())

    def onClick(self, control_id):
        if control_id == 1000:
            if not self._context_menu_suppressed():
                self._show_download_context_menu(self._list_position())
            return
        self.handle_action(7, control_id)

    def update_download_info(self):
        self.downloads = self.manager.get_all_tasks_info()

    @staticmethod
    def _set_menu_item_properties(menu_item, download_info):
        menu_item.setProperty('speed', download_info.get('speed', '-'))
        menu_item.setProperty('progress', str(download_info.get('progress', 0)))
        menu_item.setProperty('filename', download_info.get('filename', ''))
        menu_item.setProperty('eta', download_info.get('eta', ''))
        menu_item.setProperty('filesize', str(download_info.get('filesize', '')))
        menu_item.setProperty('downloaded', str(download_info.get('downloaded', '')))
        menu_item.setProperty('hash', str(download_info.get('hash', '')))
        menu_item.setProperty('state', str(download_info.get('state', 'downloading')))

    def _populate_menu_items(self):
        if self._menu_open or not self.list_control:
            return

        def create_menu_item(download_item):
            new_item = xbmcgui.ListItem(label=f"{download_item['filename']}")
            self._set_menu_item_properties(new_item, download_item)
            return new_item

        self.update_download_info()

        if len(self.downloads) < self.list_control.size():
            while len(self.downloads) < self.list_control.size():
                self.list_control.removeItem(self.list_control.size() - 1)

        for idx, download in enumerate(self.downloads):
            if idx < self.list_control.size():
                menu_item = self.list_control.getListItem(idx)
                self._set_menu_item_properties(menu_item, download)
            else:
                menu_item = create_menu_item(download)
                self.list_control.addItem(menu_item)

    def _background_info_updater(self):
        while not self.exit_requested and not g.abort_requested():
            xbmc.sleep(1000)
            if not self._menu_open:
                self._populate_menu_items()

    def _list_position(self):
        if not self.list_control:
            return -1
        position = self.list_control.getSelectedPosition()
        if position > -1:
            return position
        if self.list_control.getSelectedItem() is not None:
            return self.list_control.getSelectedPosition()
        return -1

    def _show_download_context_menu(self, position):
        if self._menu_open or not self.list_control or position < 0:
            return

        item = self.list_control.getListItem(position)
        if not item:
            return

        url_hash = item.getProperty('hash')
        if not url_hash:
            return

        state = item.getProperty('state') or 'downloading'
        try:
            progress = int(item.getProperty('progress') or 0)
        except ValueError:
            progress = 0
        if progress >= 100:
            state = 'complete'

        options = []
        actions = []

        if state in ('waiting', 'downloading', 'paused'):
            options.append(g.get_language_string(30930))
            actions.append('cancel')

        if state == 'downloading':
            options.append(g.get_language_string(30931))
            actions.append('pause')
        elif state == 'paused':
            options.append(g.get_language_string(30932))
            actions.append('resume')
        elif state == 'complete':
            options.append(g.get_language_string(30936))
            actions.append('remove')

        if not options:
            return

        self._menu_open = True
        try:
            response = xbmcgui.Dialog().contextmenu(options)
        finally:
            self._menu_open = False
            self._context_menu_cooldown = time.time() + CONTEXT_MENU_SUPPRESS_SECONDS

        if response == -1:
            return

        action = actions[response]
        if action == 'cancel':
            self.manager.cancel_task(url_hash)
        elif action == 'pause':
            self.manager.pause_task(url_hash)
        elif action == 'resume':
            self.manager.resume_task(url_hash)
        elif action == 'remove':
            self.manager.remove_download_task(url_hash)

        self._populate_menu_items()

    def close(self):
        self.exit_requested = True
        super().close()

    def handle_action(self, action_id, control_id=None):
        if action_id == 7:
            if control_id == 2002:
                self.manager.pause_all()
            elif control_id == 2003:
                self.manager.resume_all()
            elif control_id == 2004:
                if xbmcgui.Dialog().yesno(
                    g.get_language_string(30938),
                    g.get_language_string(30939),
                ):
                    self.manager.cancel_all()
            elif control_id == 2001:
                self.manager.clear_complete()
            elif control_id == 2999:
                self.close()
            if not self._menu_open:
                self._populate_menu_items()

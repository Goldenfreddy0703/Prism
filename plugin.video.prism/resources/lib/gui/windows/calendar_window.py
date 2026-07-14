# -*- coding: utf-8 -*-
import os
import time

import xbmcgui

from resources.lib.gui.windows.base_window import (
    ACTION_NAV_BACK,
    ACTION_PLAYER_STOP,
    ACTION_PREVIOUS_MENU,
    BaseWindow,
)
from resources.lib.modules.globals import g

_ICON_MAP = {
    "texture.aver": "calendar-icon-smile.png",
    "texture.avernone": "calendar-icon-none.png",
    "texture.averstr": "calendar-icon-null.png",
    "texture.aversad": "calendar-icon-frown.png",
    "texture.popular": "calendar-icon-popular.png",
    "texture.mal": "calendar-icon-mal.png",
    "texture.imdb": "calendar-icon-imdb.png",
    "texture.trakt": "calendar-icon-trakt.png",
    "texture.tmdb": "calendar-icon-tmdb.png",
    "texture.simkl": "calendar-icon-simkl.png",
}


class CalendarWindow(BaseWindow):
    def __init__(self, xml_file, location, calendar_items=None, catalog="anime", week_label=None):
        super().__init__(xml_file, location)
        self.calendar_items = calendar_items or []
        self.catalog = catalog
        self.display_list = None
        self.position = -1
        self.last_action_time = 0
        self.last_touch_position = -1
        self._selection = None

        for prop, filename in _ICON_MAP.items():
            self.setProperty(prop, os.path.join(g.IMAGES_PATH, filename))

        titles = {
            "movie": "Weekly Movie Calendar",
            "tv": "Weekly Show Calendar",
            "anime": "Weekly Anime Calendar",
        }
        title = titles.get(catalog, "Weekly Calendar")
        if week_label:
            title = f"{title} — {week_label}"
        self.setProperty("calendar.title", title)
        if week_label:
            self.setProperty("calendar.week_range", week_label)

    def onInit(self):
        self.display_list = self.getControl(1000)
        menu_items = []

        g.log(f"[CALENDAR] Initializing {self.catalog} with {len(self.calendar_items)} items", "info")

        for item in self.calendar_items:
            if not item:
                continue

            menu_item = xbmcgui.ListItem(label=str(item.get("release_title") or item.get("title") or ""))
            for key, value in item.items():
                if key == "_raw":
                    continue
                try:
                    if isinstance(value, list):
                        value = " ".join(sorted(str(k) for k in value))
                    text = str(value)
                    # Keep URLs and poster paths intact (_m.webp etc. breaks Simkl art).
                    if key not in ("poster", "plot") and "://" not in text:
                        text = text.replace("_", " ")
                    menu_item.setProperty(key, text)
                except UnicodeEncodeError:
                    menu_item.setProperty(key, value)

            menu_items.append(menu_item)
            self.display_list.addItem(menu_item)

        g.log(f"[CALENDAR] Added {len(menu_items)} items to panel", "info")
        self.setFocusId(1000)
        super().onInit()

    def doModal(self):
        super().doModal()
        return self._selection

    def onDoubleClick(self, control_id):
        if control_id == 1000:
            self._activate_selection()

    def onAction(self, action):
        action_id = action.getId()

        if action_id in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU, ACTION_PLAYER_STOP, xbmcgui.ACTION_BACKSPACE):
            self.close()
            return

        if action_id == xbmcgui.ACTION_SELECT_ITEM:
            self._activate_selection()
        elif action_id in (xbmcgui.ACTION_TOUCH_TAP, xbmcgui.ACTION_MOUSE_LEFT_CLICK):
            current_time = time.time()
            current_position = self.display_list.getSelectedPosition() if self.getFocusId() == 1000 else -1
            time_diff = current_time - self.last_action_time
            is_double_tap = (
                time_diff < 0.5
                and current_position == self.last_touch_position
                and current_position != -1
            )
            if is_double_tap:
                self._activate_selection()
                self.last_action_time = 0
                self.last_touch_position = -1
            else:
                self.last_action_time = current_time
                self.last_touch_position = current_position
        elif action_id == xbmcgui.ACTION_MOUSE_DOUBLE_CLICK:
            self._activate_selection()

    def handle_action(self, action_id, control_id=None):
        if action_id in (7, xbmcgui.ACTION_SELECT_ITEM):
            self._activate_selection()

    def _activate_selection(self):
        if self.getFocusId() != 1000 or not self.display_list:
            return

        self.position = self.display_list.getSelectedPosition()
        if self.position < 0 or self.position >= len(self.calendar_items):
            return

        selected = self.calendar_items[self.position]
        g.log(f"[CALENDAR] Selected {selected.get('release_title')} ({self.catalog})", "info")
        self._selection = selected
        self.close()

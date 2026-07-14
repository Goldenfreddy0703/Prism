# -*- coding: utf-8 -*-
"""
Color picker ported from script.skin.helper.colorpicker (ColorPicker.py).
"""
import math
import os
from contextlib import contextmanager
from xml.dom.minidom import parse

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.common import tools
from resources.lib.modules.globals import g

SUPPORTS_PIL = False


@contextmanager
def busy_dialog():
    xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
    try:
        yield
    finally:
        xbmc.executebuiltin("Dialog.Close(busydialognocancel)")


try:
    from PIL import Image

    Image.new("RGB", (1, 1))
    SUPPORTS_PIL = True
except Exception as exc:
    g.log(f"Color picker PIL unavailable: {exc}", "debug")
    try:
        import Image  # type: ignore

        Image.new("RGB", (1, 1))
        SUPPORTS_PIL = True
    except Exception as exc2:
        g.log(f"Color picker legacy PIL unavailable: {exc2}", "debug")


class ColorPicker(xbmcgui.WindowXMLDialog):
    """Original Skin Helper color picker dialog."""

    def __init__(self, xml_file, location, default_skin="Default", default_res="1080i"):
        super().__init__(xml_file, location, default_skin, default_res)
        self.action_exitkeys_id = [10, 13]
        self.win = xbmcgui.Window(10000)
        self.colors_list = None
        self.skinstring = None
        self.win_property = None
        self.shortcut_property = None
        self.colors_path = None
        self.saved_color = None
        self.current_window = None
        self.header_label = None
        self.colors_file = None
        self.all_colors = {}
        self.all_palettes = []
        self.active_palette = None
        self.result = -1

        self.colorfiles_path = tools.translate_path(f"special://profile/addon_data/{g.ADDON_ID}/colors/")
        self.skincolorfiles_path = tools.translate_path(f"special://profile/addon_data/{xbmc.getSkinDir()}/colors/")
        self.skincolorfile = tools.translate_path("special://skin/extras/colors/colors.xml")
        self.addon_path = g.ADDON_PATH

        self.build_colors_list()

        if xbmcvfs.exists(self.skincolorfile) and not xbmcvfs.exists(self.skincolorfiles_path):
            xbmcvfs.mkdirs(self.skincolorfiles_path)
        if not xbmcvfs.exists(self.colorfiles_path):
            xbmcvfs.mkdirs(self.colorfiles_path)

    def add_color_to_list(self, colorname, colorstring):
        if not colorname:
            colorname = colorstring
        color_image_file = self.create_color_swatch_image(colorstring)
        listitem = xbmcgui.ListItem(label=colorname)
        if color_image_file:
            listitem.setArt({"icon": color_image_file})
        listitem.setProperty("colorstring", colorstring)
        self.colors_list.addItem(listitem)

    def build_colors_list(self):
        if xbmcvfs.exists(self.skincolorfile):
            colors_file = self.skincolorfile
            self.colors_path = self.skincolorfiles_path
        else:
            colors_file = os.path.join(self.addon_path, "resources", "colors", "colors.xml")
            self.colors_path = self.colorfiles_path

        doc = parse(colors_file)
        palette_listing = doc.documentElement.getElementsByTagName("palette")
        if palette_listing:
            for item in palette_listing:
                palette_name = item.attributes["name"].nodeValue
                self.all_colors[palette_name] = self.get_colors_from_xml(item)
                self.all_palettes.append(palette_name)
        else:
            self.all_colors["all"] = self.get_colors_from_xml(doc.documentElement)
            self.all_palettes.append("all")

    def load_colors_palette(self, palette_name=""):
        self.colors_list.reset()
        if not palette_name:
            palette_name = self.all_palettes[0]
        if palette_name != "all":
            self.setProperty("palettename", palette_name)
            if self.current_window:
                self.current_window.setProperty("palettename", palette_name)
        if not self.all_colors.get(palette_name):
            g.log(f"Color picker palette not found: {palette_name}", "error")
            return
        for colorname, colorstring in self.all_colors[palette_name]:
            self.add_color_to_list(colorname, colorstring)

    def onInit(self):
        with busy_dialog():
            self.current_window = xbmcgui.Window(xbmcgui.getCurrentWindowDialogId())
            self.colors_list = self.getControl(3110)
            try:
                self.getControl(1).setLabel(self.header_label)
            except Exception:
                pass

            curvalue = ""
            curvalue_name = ""
            if self.skinstring:
                curvalue = xbmc.getInfoLabel(f"Skin.String({self.skinstring})")
                curvalue_name = xbmc.getInfoLabel(f"Skin.String({self.skinstring}.name)")
            if self.win_property:
                curvalue = self.win.getProperty(self.win_property)
                curvalue_name = xbmc.getInfoLabel(f"{self.win_property}.name")

            if curvalue:
                self.current_window.setProperty("colorstring", curvalue)
                if curvalue != curvalue_name:
                    self.current_window.setProperty("colorname", curvalue_name)
                self.current_window.setProperty("current.colorstring", curvalue)
                if curvalue != curvalue_name:
                    self.current_window.setProperty("current.colorname", curvalue_name)

            self.load_colors_palette(self.active_palette)

            if self.current_window.getProperty("colorstring"):
                self.current_window.setFocusId(3010)
            else:
                self.current_window.setFocusId(3110)
                self.colors_list.selectItem(0)
                selected = self.colors_list.getSelectedItem()
                if selected:
                    self.current_window.setProperty("colorstring", selected.getProperty("colorstring"))
                    self.current_window.setProperty("colorname", selected.getLabel())

            if self.current_window.getProperty("colorstring"):
                self.set_opacity_slider()

    def _update_preview(self, colorname, colorstring):
        if not colorstring:
            return
        if not colorname:
            colorname = colorstring
        self.setProperty("colorname", colorname)
        self.setProperty("colorstring", colorstring)
        if self.current_window:
            self.current_window.setProperty("colorname", colorname)
            self.current_window.setProperty("colorstring", colorstring)
        try:
            self.set_opacity_slider()
        except Exception:
            pass

    def onFocus(self, control_id):
        if control_id != 3110 or not self.colors_list:
            return
        item = self.colors_list.getSelectedItem()
        if not item:
            return
        self._update_preview(item.getLabel(), item.getProperty("colorstring"))

    def onAction(self, action):
        if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
            self.save_color_setting(restoreprevious=True)
            self.close_dialog()

    def close_dialog(self):
        self.close()

    def set_opacity_slider(self):
        colorstring = self.current_window.getProperty("colorstring")
        try:
            if colorstring and colorstring.lower() != "none":
                alpha, red, green, blue = (
                    colorstring[:2],
                    colorstring[2:4],
                    colorstring[4:6],
                    colorstring[6:8],
                )
                alpha, red, green, blue = [int(value, 16) for value in (alpha, red, green, blue)]
                self.getControl(3015).setPercent(float(100.0 * alpha / 255))
        except Exception:
            pass

    def save_color_setting(self, restoreprevious=False):
        if restoreprevious:
            colorname = self.current_window.getProperty("current.colorname")
            colorstring = self.current_window.getProperty("current.colorstring")
        else:
            colorname = self.current_window.getProperty("colorname")
            colorstring = self.current_window.getProperty("colorstring")

        if not colorname:
            colorname = colorstring

        self.create_color_swatch_image(colorstring)

        if self.skinstring and (not colorstring or colorstring == "None"):
            xbmc.executebuiltin(f"Skin.SetString({self.skinstring}.name, {g.get_language_string(30857)})")
            xbmc.executebuiltin(f"Skin.SetString({self.skinstring}, None)")
            xbmc.executebuiltin(f"Skin.Reset({self.skinstring}.base)")

        elif self.skinstring and colorstring:
            xbmc.executebuiltin(f"Skin.SetString({self.skinstring}.name, {colorname})")
            xbmc.executebuiltin(f"Skin.SetString({self.skinstring}, {colorstring})")
            colorbase = "ff" + colorstring[2:]
            xbmc.executebuiltin(f"Skin.SetString({self.skinstring}.base, {colorbase})")

        elif self.win_property:
            self.win.setProperty(self.win_property, colorstring)
            self.win.setProperty(f"{self.win_property}.name", colorname)

    def onClick(self, control_id):
        if control_id == 3110:
            item = self.colors_list.getSelectedItem()
            colorstring = item.getProperty("colorstring")
            self._update_preview(item.getLabel(), colorstring)
            self.current_window.setFocusId(3012)
            self.current_window.setProperty("color_chosen", "true")
            self.save_color_setting()
        elif control_id == 3010:
            colorstring = xbmcgui.Dialog().input(
                g.get_language_string(30856),
                self.getProperty("colorstring") or self.current_window.getProperty("colorstring"),
                type=xbmcgui.INPUT_ALPHANUM,
            )
            if colorstring:
                self._update_preview(g.get_language_string(30859), colorstring.strip().lower())
            self.save_color_setting()
        elif control_id == 3011:
            preview = g.get_user_text_color()
            self._update_preview(g.get_language_string(30857), preview)
            self.save_color_setting()
            if self.shortcut_property:
                self.result = ("", g.get_language_string(30857))
                self.close_dialog()
            return

        if control_id in (3012,):
            if self.skinstring or self.win_property:
                self.close_dialog()
            elif self.shortcut_property:
                self.result = (
                    self.current_window.getProperty("colorstring"),
                    self.current_window.getProperty("colorname"),
                )
                self.close_dialog()

        elif control_id == 3015:
            try:
                colorstring = self.current_window.getProperty("colorstring")
                opacity = self.getControl(3015).getPercent()
                num = opacity / 100.0 * 255
                alpha = int(math.floor(num)) if (num - math.floor(num)) < 0.5 else int(math.ceil(num))
                colorstring = colorstring.strip()
                red, green, blue = colorstring[2:4], colorstring[4:6], colorstring[6:8]
                red, green, blue = [int(value, 16) for value in (red, green, blue)]
                colorstringvalue = f"{alpha:02x}{red:02x}{green:02x}{blue:02x}"
                self._update_preview(self.getProperty("colorname"), colorstringvalue)
                self.save_color_setting()
            except Exception:
                pass

        elif control_id == 3030:
            choice = xbmcgui.Dialog().select(g.get_language_string(30855), self.all_palettes)
            if choice != -1:
                self.load_colors_palette(self.all_palettes[choice])

    def create_color_swatch_image(self, colorstring):
        color_image_file = None
        if not colorstring:
            return color_image_file

        paths = [f"{self.colorfiles_path}{colorstring}.png"]
        if xbmcvfs.exists(self.skincolorfile):
            paths.append(f"{self.skincolorfiles_path}{colorstring}.png")

        for color_image_file in paths:
            if xbmcvfs.exists(color_image_file):
                return color_image_file
            if SUPPORTS_PIL:
                try:
                    value = colorstring.strip()
                    if value.startswith("#"):
                        value = value[1:]
                    alpha, red, green, blue = value[:2], value[2:4], value[4:6], value[6:8]
                    alpha, red, green, blue = [int(channel, 16) for channel in (alpha, red, green, blue)]
                    img = Image.new("RGBA", (16, 16), (red, green, blue, alpha))
                    img.save(color_image_file)
                    del img
                    return color_image_file
                except Exception as exc:
                    g.log(f"Color swatch PIL failed for {colorstring}: {exc}", "error")
            else:
                try:
                    xbmcvfs.copy(
                        f"https://dummyimage.com/16/{colorstring[2:]}/{colorstring[2:]}.png",
                        color_image_file,
                    )
                    g.log("Color picker using dummyimage.com for swatches (PIL unavailable)", "warning")
                    return color_image_file
                except Exception as exc:
                    g.log(f"Color swatch fallback failed for {colorstring}: {exc}", "error")
        return color_image_file

    @staticmethod
    def get_colors_from_xml(xmlelement):
        items = []
        for color in xmlelement.getElementsByTagName("color"):
            name = color.attributes["name"].nodeValue.lower()
            colorstring = color.childNodes[0].nodeValue.lower()
            items.append((name, colorstring))
        return items


class ColorPickerWindow(ColorPicker):
    """Prism wrapper around the Skin Helper color picker."""

    def __init__(self, xml_file, location):
        super().__init__(xml_file, location, "Default", "1080i")
        self.shortcut_property = "prism"
        self.header_label = g.get_language_string(30854)
        # Fixed accent for button focus — not tied to the color being picked in the grid.
        self.setProperty("settings.color", "deepskyblue")

    def _apply_initial_preview(self, colorname, colorstring):
        self.setProperty("colorname", colorname)
        self.setProperty("colorstring", colorstring)
        if self.current_window:
            self.current_window.setProperty("colorname", colorname)
            self.current_window.setProperty("current.colorstring", colorstring if colorname != g.get_language_string(30857) else "")
            self.current_window.setProperty("current.colorname", colorname if colorname != g.get_language_string(30857) else "")
            self.current_window.setProperty("colorstring", colorstring)

    def onInit(self):
        with busy_dialog():
            self.current_window = xbmcgui.Window(xbmcgui.getCurrentWindowDialogId())
            self.colors_list = self.getControl(3110)
            try:
                self.getControl(1).setLabel(self.header_label)
            except Exception:
                pass

            current = g.get_setting("general.displayColor") or "None"
            if current in (None, "None", "inherit"):
                preview = g.get_user_text_color()
                self._apply_initial_preview(g.get_language_string(30857), preview)
            else:
                self._apply_initial_preview(current, current)
                if self.current_window:
                    self.current_window.setProperty("current.colorstring", current)
                    self.current_window.setProperty("current.colorname", current)

            self.load_colors_palette(self.active_palette)

            if current not in (None, "None", "inherit"):
                needle = current.lower()
                for index in range(self.colors_list.size()):
                    item = self.colors_list.getListItem(index)
                    if item.getProperty("colorstring").lower() == needle or item.getLabel().lower() == needle:
                        self.colors_list.selectItem(index)
                        self._update_preview(item.getLabel(), item.getProperty("colorstring"))
                        break
            elif self.colors_list.size() > 0:
                item = self.colors_list.getSelectedItem() or self.colors_list.getListItem(0)
                if item:
                    self.colors_list.selectItem(0)
                    self._update_preview(item.getLabel(), item.getProperty("colorstring"))

            self.current_window.setFocusId(3110)

            if self.getProperty("colorstring"):
                self.set_opacity_slider()

    def onAction(self, action):
        if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
            self.result = -1
            self.close_dialog()

    def doModal(self):
        super(ColorPicker, self).doModal()
        if self.result == -1 or not isinstance(self.result, tuple):
            return None
        colorstring, _colorname = self.result
        if not colorstring or colorstring == "None":
            return "None"
        return colorstring

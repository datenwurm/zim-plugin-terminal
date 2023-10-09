#
# Copyright 2023 Thomas Engel <realdatenwurm@gmail.com>
# License:  same as zim (gpl)
#
# DESCRIPTION:
#
# Zim plugin to display terminal.
#
# CHANGELOG:
#
# 2020-08-13 1st working version
# 2020-09-09 Added copy-paste functionality
# 2023-10-10 Added context menu
#


import logging
import os
from pathlib import Path

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Vte', '2.91')
from gi.repository import Gdk, Gtk, GObject, GLib, Pango, Vte

from zim.plugins import PluginClass

from zim.gui.pageview import PageViewExtension

from zim.gui.preferencesdialog import PluginConfigureDialog

from zim.gui.widgets import BOTTOM_PANE, PANE_POSITIONS, \
    IconButton, ScrolledWindow, \
    WindowSidePaneWidget

logger = logging.getLogger('zim.plugins.terminal')

FONT_SIZE_MIN = 6
FONT_SIZE_MAX = 72
DEFAULT_FONT_SIZE = 9
DEFAULT_FONT_COLOR = "#FFFFFF"
DEFAULT_BACKGROUND_COLOR = "#000000"
DEFAULT_COMMAND_INTERPRETER = "/bin/bash"
CLEAR_COMMAND = "clear"

DEFAULT_AUTO_SWITCH_PATH_ON_PAGE_CHANGE = True


class TerminalPlugin(PluginClass):
    plugin_info = {
        'name': _('Terminal'),  # T: plugin name
        'description': _('This plugin shows a terminal at the bottom pane.'),  # T: plugin description
        'author': 'Thomas Engel <realdatenwurm@gmail.com>',
        'help': 'Plugins:Terminal',
    }

    plugin_preferences = (
        # key, type, label, default
        ('pane', 'choice', _('Position in the window'), BOTTOM_PANE, PANE_POSITIONS),
        ('font_size', 'int', _('Font size'), DEFAULT_FONT_SIZE, (FONT_SIZE_MIN, FONT_SIZE_MAX)),
        ('font_color', 'color', _('Font color'), DEFAULT_FONT_COLOR),
        ('background_color', 'color', _('Background color'), DEFAULT_BACKGROUND_COLOR),
        ('command_interpreter', 'string', _('Command interpreter'), DEFAULT_COMMAND_INTERPRETER),
        ('auto_switch_path_on_page_change', 'bool', _('Automatically switch to new path on page change'),
         DEFAULT_AUTO_SWITCH_PATH_ON_PAGE_CHANGE),
    )


class TerminalWindowExtension(PageViewExtension):

    def __init__(self, plugin, window):
        PageViewExtension.__init__(self, plugin, window)
        self.window = window
        self.preferences = plugin.preferences
        self._monitor = None

        # Init terminal widget
        self.widget = TerminalPluginWidget(plugin, window, self.uistate)

        if self.pageview.page is not None:
            self.on_page_changed(self.pageview, self.pageview.page)
        self.connectto(self.pageview, 'page-changed')

        self.add_sidepane_widget(self.widget, 'pane')

    def on_page_changed(self, pageview, page):
        self.widget.set_folder(
            pageview.notebook.get_attachments_dir(page)
        )


class ZimTerminal(Vte.Terminal):
    """
    A L{Vte.Terminal} with extra properties.
    see https://github.com/Guake/guake/blob/master/guake/terminal.py
    """

    def execute_command(self, command):
        if command[-1] != "\n":
            command += "\n"
        self.feed_child(command)

    def feed_child(self, resolved_cmdline):
        if (Vte.MAJOR_VERSION, Vte.MINOR_VERSION) >= (0, 42):
            encoded = resolved_cmdline.encode("utf-8")
            try:
                super().feed_child_binary(encoded)
            except TypeError:
                # The doc doest not say clearly at which version the feed_child* function has lost
                # the "len" parameter :(
                super().feed_child(resolved_cmdline, len(resolved_cmdline))
        else:
            super().feed_child(resolved_cmdline, len(resolved_cmdline))


class TerminalPluginWidget(Gtk.HBox, WindowSidePaneWidget):
    """ Wrapper around the L{Vte.Terminal} that implements the actual terminal. """

    title = _('Terminal')  # T: label for pane

    def __init__(self, plugin, window, uistate):
        GObject.GObject.__init__(self)
        self.plugin = plugin
        self.preferences = plugin.preferences
        self.window = window
        self.uistate = uistate
        self._close_button = None

        self.context_menu = self.create_context_menu()

        self.terminalview = ZimTerminal()
        self.terminalview.connect("button-press-event", self.on_button_press)
        self.terminalview.connect("key-press-event", self.on_key_press_event)
        self.terminalview.spawn_sync(
            Vte.PtyFlags.DEFAULT,
            os.environ['HOME'],
            [self.command_interpreter],
            [],
            GLib.SpawnFlags.DO_NOT_REAP_CHILD,
            None,
            None,
        )

        self.add(ScrolledWindow(self.terminalview, shadow=Gtk.ShadowType.NONE))

        self.on_preferences_changed()
        self.preferences.connect('changed', self.on_preferences_changed)

        self.buttonbox = Gtk.VBox()
        self.pack_end(self.buttonbox, False, True, 0)

        properties_button = IconButton(Gtk.STOCK_PROPERTIES, relief=False)
        properties_button.connect('clicked', lambda o: self.on_properties_button())
        self.buttonbox.pack_start(properties_button, False, True, 0)

        change_path_button = IconButton(Gtk.STOCK_REFRESH, relief=False)
        change_path_button.connect('clicked', lambda o: self.on_change_path_button())
        self.buttonbox.pack_start(change_path_button, False, True, 0)

    def create_context_menu(self):
        """Create the context menu for the terminal."""
        context_menu = Gtk.Menu()

        # Copy Menu Item
        copy_item = Gtk.MenuItem.new_with_label(_("Copy"))
        copy_item.connect('activate', lambda w: self.copy_clipboard())
        context_menu.append(copy_item)

        # Paste Menu Item
        paste_item = Gtk.MenuItem.new_with_label(_("Paste"))
        paste_item.connect('activate', lambda w: self.paste_clipboard())
        context_menu.append(paste_item)

        # Add a separator
        separator = Gtk.SeparatorMenuItem()
        context_menu.append(separator)

        # Reset Menu Item
        reset_item = Gtk.MenuItem.new_with_label(_("Reset"))
        reset_item.connect('activate', lambda w: self.reset_terminal())
        context_menu.append(reset_item)

        # Add a separator
        separator = Gtk.SeparatorMenuItem()
        context_menu.append(separator)

        # Preferences Menu Item
        preferences_item = Gtk.MenuItem.new_with_label(_("Preferences"))
        preferences_item.connect('activate', lambda w: self.show_properties())
        context_menu.append(preferences_item)

        context_menu.show_all()

        return context_menu

    def on_preferences_changed(self, *a):
        self.terminalview.set_color_foreground(self.font_color)
        self.terminalview.set_color_background(self.background_color)
        font = self.terminalview.get_font()
        font.set_size(self.font_size * Pango.SCALE)
        self.terminalview.set_font(font)

    def on_properties_button(self):
        self.show_properties()

    def on_change_path_button(self):
        self.reset_terminal()
        self.terminalview.grab_focus()

    def on_button_press(self, terminal, event):
        """Handle right click for context menu."""
        if event.button == 3:
            self.context_menu.popup(None, None, None, None, event.button, event.time)
            return True

    def on_key_press_event(self, widget, event):
        """ Implements copy (ctrl+shift+c) and paste (ctrl+shift+v) for the terminal. """
        if event.type == Gdk.EventType.KEY_PRESS:
            control_key = Gdk.ModifierType.CONTROL_MASK & event.state
            shift_key = Gdk.ModifierType.SHIFT_MASK & event.state
            if control_key and shift_key:  # control and shift
                if event.keyval == 67:  # C key
                    self.copy_clipboard()
                elif event.keyval == 86:  # V key
                    self.paste_clipboard()
                return True

    def copy_clipboard(self):
        """ Copies the selected text to the clipboard. """
        self.terminalview.copy_clipboard()
        self.terminalview.grab_focus()

    def paste_clipboard(self):
        """ Pastes the selected text into the terminal. """
        self.terminalview.paste_clipboard()
        self.terminalview.grab_focus()

    def clear_terminal(self):
        """Clear the terminal content."""
        self.terminalview.reset(True, True)

    def reset_terminal(self):
        """ Resets the terminal to the current path. """
        self.terminalview.spawn_sync(
            Vte.PtyFlags.DEFAULT,
            self.path,
            [self.command_interpreter],
            [],
            GLib.SpawnFlags.DO_NOT_REAP_CHILD,
            None,
            None,
        )
        # Clear screen after terminal refresh
        self.terminalview.execute_command(CLEAR_COMMAND)

    def show_properties(self):
        """ Shows the properties dialog and refreshes the path. """
        if PluginConfigureDialog(self.window, self.plugin).run() == Gtk.ResponseType.OK:
            self.reset_terminal()

    def set_folder(self, folder):
        self.folder = folder
        if self.preferences['auto_switch_path_on_page_change']:
            self.reset_terminal()

    @property
    def font_size(self):
        return self.preferences['font_size']

    @property
    def font_color(self):
        rgba = Gdk.RGBA()
        rgba.parse(self.preferences['font_color'])
        return rgba

    @property
    def background_color(self):
        rgba = Gdk.RGBA()
        rgba.parse(self.preferences['background_color'])
        return rgba

    @property
    def command_interpreter(self):
        return self.preferences["command_interpreter"]

    @property
    def path(self):
        """ Returns the path to the attachment folder. If it does not exist the path to the wiki page is returned
        instead. """
        _path = self.folder._inner_fs_object.path
        return _path if os.path.isdir(_path) else str(Path(_path).parent)

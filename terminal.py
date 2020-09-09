#
# Copyright 2020 Thomas Engel <thomas.engel.web@gmail.de>
# License:  same as zim (gpl)
#
#
# NOTE: 
#
# ChangeLog
# 2020-08-13 1st working version
# 2020-09-09 Added copy-paste functionality
#
# TODO:
# [ ] ...


'''Zim plugin to display terminal.'''

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
	WindowSidePaneWidget, uistate_property


logger = logging.getLogger('zim.plugins.terminal')


FONT_SIZE_MIN = 6
FONT_SIZE_MAX = 72
DEFAULT_FONT_SIZE = 9
DEFAULT_FONT_COLOR = "#FFFFFF"
DEFAULT_BACKGROUND_COLOR = "#000000"
DEFAULT_COMMAND_INTERPRETER = "/bin/bash"
CLEAR_COMMAND = "clear\n"

DEFAULT_AUTO_SWITCH_PATH_ON_PAGE_CHANGE = True

class TerminalPlugin(PluginClass):

	plugin_info = {
		'name': _('Terminal'), # T: plugin name
		'description': _('This plugin shows a terminal at the bottom pane.'), # T: plugin description
		'author': 'Thomas Engel <thomas.engel.web@gmail.com>',
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


class TerminalPluginWidget(Gtk.HBox, WindowSidePaneWidget):
	""" Wrapper aroung the L{Vte.Terminal} that implements the actual terminal. """

	title = _('Terminal') # T: label for pane

	def __init__(self, plugin, window, uistate):
		GObject.GObject.__init__(self)
		self.plugin = plugin
		self.preferences = plugin.preferences
		self.window = window
		self.uistate = uistate
		self._close_button = None

		self.terminalview = Vte.Terminal()
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

	def on_preferences_changed(self, *a):
		self.terminalview.set_color_foreground(self.font_color)
		self.terminalview.set_color_background(self.background_color)
		font = self.terminalview.get_font()
		font.set_size(self.font_size * Pango.SCALE)
		self.terminalview.set_font(font)

	def on_properties_button(self):
		""" Writes the path to the current wiki page to the terminal. """
		PluginConfigureDialog(self.window, self.plugin).run()
		self.refresh_path()

	def on_change_path_button(self):
		self.refresh_path()

	def on_key_press_event(self, widget, event):
		""" Implements copy (ctrl+shift+c) and paste (ctrl+shift+v) for the terminal. """
		if event.type == Gdk.EventType.KEY_PRESS:
			control_key = Gdk.ModifierType.CONTROL_MASK & event.state
			shift_key = Gdk.ModifierType.SHIFT_MASK & event.state
			if shift_key and control_key:  # shift  and control
				if event.keyval == 67:  # C key
					self.copy_clipboard()
				elif event.keyval == 86:  # V key
					self.paste_clipboard()
				return True

	def copy_clipboard(self):
		""" Copies the selected text to the clipboard """
		self.terminalview.copy_clipboard()
		self.terminalview.grab_focus()

	def paste_clipboard(self):
		""" Pastes the selected text into the terminal """
		self.terminalview.paste_clipboard()
		self.terminalview.grab_focus()

	def refresh_path(self):
		""" Refresh the terminal and switch to the current path. """
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
		self.terminalview.feed_child(CLEAR_COMMAND, len(CLEAR_COMMAND))

	def set_folder(self, folder):
		self.folder = folder
		if self.preferences['auto_switch_path_on_page_change']:
			self.refresh_path()

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
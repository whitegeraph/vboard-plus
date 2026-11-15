import configparser
import importlib
import os
import sys

from .constants import (
    APP_DISPLAY_NAME,
    COMMAND_MODIFIER_KEYS,
    COLOR_CHOICES,
    DEFAULT_KEYBOARD_LAYOUT,
    ENHANCED_BACKGROUND_PRESET,
    FUNCTION_KEY_SECONDARY_ACTIONS,
    FUNCTION_ROW_KEYS,
    KEY_WIDTHS,
    LIGHT_BACKGROUND_COLORS,
    MODIFIER_KEYS,
    ONBOARD_BACKGROUND_PRESET,
    SUGGESTION_LIMIT,
    VERSION,
)
from .environment import DESKTOP_ENV
from .gtk import (
    APPINDICATOR_AVAILABLE,
    APPINDICATOR_BACKEND,
    AppIndicator3,
    Gdk,
    Gio,
    GLib,
    Gtk,
    Pango,
)
from .input_backends import NullInputBackend, UInputBackend
from .layouts import get_default_layout_key, get_layout_choices, load_keyboard_layouts
from .suggestions import HunspellSuggestionEngine


BUG_REPORT_URL = "https://github.com/archisman-panigrahi/vboard/issues/"

STATUS_NOTIFIER_ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
  </interface>
</node>
"""

DBUS_MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})"/>
      <arg name="removedProps" type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
  </interface>
</node>
"""


class StatusNotifierTrayIcon:
    OBJECT_PATH = "/StatusNotifierItem"
    MENU_PATH = "/StatusNotifierItem/Menu"
    INTERFACE_NAME = "org.kde.StatusNotifierItem"
    MENU_INTERFACE_NAME = "com.canonical.dbusmenu"
    WATCHER_NAME = "org.kde.StatusNotifierWatcher"
    WATCHER_PATH = "/StatusNotifierWatcher"
    DBUS_NAME = "org.freedesktop.DBus"
    DBUS_PATH = "/org/freedesktop/DBus"
    MENU_SEPARATOR_ID = 5
    MENU_LAYOUT_ID = 6
    MENU_SECOND_SEPARATOR_ID = 100
    MENU_LAYOUT_ID_OFFSET = 1000

    def __init__(self, window, icon_name):
        self.window = window
        self.icon_name = icon_name
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.bus_name = f"org.freedesktop.StatusNotifierItem-{os.getpid()}-1"
        self.registration_id = None
        self.menu_registration_id = None
        self.menu_revision = 1
        self.name_acquired = False
        try:
            request_result = self.connection.call_sync(
                self.DBUS_NAME,
                self.DBUS_PATH,
                self.DBUS_NAME,
                "RequestName",
                GLib.Variant("(su)", (self.bus_name, 0)),
                GLib.VariantType.new("(u)"),
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
            request_reply = request_result.unpack()[0]
            if request_reply not in (1, 4):
                raise RuntimeError(f"Could not acquire D-Bus name {self.bus_name}")
            self.name_acquired = True

            self.node_info = Gio.DBusNodeInfo.new_for_xml(STATUS_NOTIFIER_ITEM_XML)
            self.interface_info = self.node_info.interfaces[0]
            self.menu_node_info = Gio.DBusNodeInfo.new_for_xml(DBUS_MENU_XML)
            self.menu_interface_info = self.menu_node_info.interfaces[0]
            self.menu_registration_id = self.connection.register_object(
                self.MENU_PATH,
                self.menu_interface_info,
                self.on_menu_method_call,
                self.on_menu_get_property,
                None,
            )
            self.registration_id = self.connection.register_object(
                self.OBJECT_PATH,
                self.interface_info,
                self.on_method_call,
                self.on_get_property,
                None,
            )
            self.connection.call_sync(
                self.WATCHER_NAME,
                self.WATCHER_PATH,
                self.WATCHER_NAME,
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self.bus_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
        except Exception:
            self.unregister()
            raise

    def on_method_call(
        self,
        connection,
        sender,
        object_path,
        interface_name,
        method_name,
        parameters,
        invocation,
    ):
        if method_name == "Activate":
            GLib.idle_add(self.window.on_tray_activate, None)
            invocation.return_value(None)
            return

        if method_name == "ContextMenu":
            x, y = parameters.unpack()
            GLib.idle_add(self.window.popup_tray_menu_at_coordinates, x, y)
            invocation.return_value(None)
            return

        if method_name == "SecondaryActivate":
            invocation.return_value(None)
            return

        if method_name == "Scroll":
            invocation.return_value(None)
            return

        invocation.return_dbus_error(
            "org.kde.StatusNotifierItem.Error.NotSupported",
            f"Unsupported tray method: {method_name}",
        )

    def on_get_property(
        self,
        connection,
        sender,
        object_path,
        interface_name,
        property_name,
    ):
        property_values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "vboard"),
            "Title": GLib.Variant("s", APP_DISPLAY_NAME),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", self.icon_name),
            "IconThemePath": GLib.Variant("s", ""),
            "IconPixmap": GLib.Variant("a(iiay)", []),
            "OverlayIconName": GLib.Variant("s", ""),
            "OverlayIconPixmap": GLib.Variant("a(iiay)", []),
            "AttentionIconName": GLib.Variant("s", ""),
            "AttentionIconPixmap": GLib.Variant("a(iiay)", []),
            "AttentionMovieName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant(
                "(sa(iiay)ss)",
                (self.icon_name, [], APP_DISPLAY_NAME, "Virtual Keyboard"),
            ),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", self.MENU_PATH),
        }
        return property_values.get(property_name)

    def on_menu_method_call(
        self,
        connection,
        sender,
        object_path,
        interface_name,
        method_name,
        parameters,
        invocation,
    ):
        if method_name == "GetLayout":
            invocation.return_value(
                GLib.Variant(
                    "(u(ia{sv}av))",
                    (self.menu_revision, self.get_menu_layout()),
                )
            )
            return

        if method_name == "GetGroupProperties":
            ids, property_names = parameters.unpack()
            invocation.return_value(
                GLib.Variant(
                    "(a(ia{sv}))",
                    ([self.get_menu_properties(item_id) for item_id in ids],),
                )
            )
            return

        if method_name == "GetProperty":
            item_id, property_name = parameters.unpack()
            value = self.get_menu_properties(item_id).get(
                property_name,
                GLib.Variant("s", ""),
            )
            invocation.return_value(GLib.Variant("(v)", (value,)))
            return

        if method_name == "Event":
            item_id, event_id, data, timestamp = parameters.unpack()
            self.handle_menu_event(item_id, event_id)
            invocation.return_value(None)
            return

        if method_name == "EventGroup":
            for item_id, event_id, data, timestamp in parameters.unpack()[0]:
                self.handle_menu_event(item_id, event_id)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
            return

        if method_name == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
            return

        if method_name == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
            return

        invocation.return_dbus_error(
            "com.canonical.dbusmenu.Error.NotSupported",
            f"Unsupported menu method: {method_name}",
        )

    def on_menu_get_property(
        self,
        connection,
        sender,
        object_path,
        interface_name,
        property_name,
    ):
        property_values = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }
        return property_values.get(property_name)

    def menu_rows(self):
        rows = [
            (1, {"label": "Hide" if self.window.get_visible() else "Show"}),
            (
                2,
                {
                    "label": "Text Prediction",
                    "toggle-type": "checkmark",
                    "toggle-state": int(self.window.text_prediction_enabled),
                },
            ),
            (
                3,
                {
                    "label": "Touch Typing (requires app restart)",
                    "toggle-type": "checkmark",
                    "toggle-state": int(self.window.gesture_enabled),
                },
            ),
            (
                4,
                {
                    "label": "Visual Feedback",
                    "enabled": self.window.gesture_enabled,
                    "toggle-type": "checkmark",
                    "toggle-state": int(
                        self.window.gesture_visual_feedback_enabled
                    ),
                },
            ),
            (
                self.MENU_SEPARATOR_ID,
                {"type": "separator", "enabled": False},
            ),
            (
                self.MENU_LAYOUT_ID,
                {
                    "label": "Keyboard Layout",
                    "children-display": "submenu",
                },
            ),
            (
                self.MENU_SECOND_SEPARATOR_ID,
                {"type": "separator", "enabled": False},
            ),
            (8, {"label": "About"}),
            (10, {"label": "Report bugs"}),
            (9, {"label": "Quit"}),
        ]
        return rows

    def layout_item_id(self, index):
        return self.MENU_LAYOUT_ID_OFFSET + index

    def get_menu_properties(self, item_id):
        properties = {"enabled": True, "visible": True}
        for row_id, row_properties in self.menu_rows():
            if row_id == item_id:
                properties.update(row_properties)
                break
        else:
            for index, (layout_key, layout_label) in enumerate(
                self.window.keyboard_layout_choices
            ):
                if self.layout_item_id(index) == item_id:
                    properties.update(
                        {
                            "label": layout_label,
                            "toggle-type": "radio",
                            "toggle-state": int(
                                layout_key == self.window.keyboard_layout
                            ),
                        }
                    )
                    break

        return {
            name: self.menu_property_variant(value)
            for name, value in properties.items()
        }

    def menu_property_variant(self, value):
        if isinstance(value, bool):
            return GLib.Variant("b", value)
        if isinstance(value, int):
            return GLib.Variant("i", value)
        return GLib.Variant("s", value)

    def menu_layout_item(self, item_id, children=None):
        return GLib.Variant(
            "(ia{sv}av)",
            (item_id, self.get_menu_properties(item_id), children or []),
        )

    def get_menu_layout(self):
        layout_children = [
            self.menu_layout_item(self.layout_item_id(index))
            for index, _choice in enumerate(self.window.keyboard_layout_choices)
        ]
        children = []
        for item_id, _properties in self.menu_rows():
            if item_id == self.MENU_LAYOUT_ID:
                children.append(self.menu_layout_item(item_id, layout_children))
            else:
                children.append(self.menu_layout_item(item_id))
        return (0, {}, children)

    def handle_menu_event(self, item_id, event_id):
        if event_id not in ("clicked", "opened"):
            return
        if event_id == "opened":
            self.emit_menu_updated()
            return

        actions = {
            1: lambda: self.window.on_tray_activate(None),
            2: lambda: self.window.set_text_prediction_enabled(
                not self.window.text_prediction_enabled
            ),
            3: self.toggle_gesture_typing,
            4: lambda: self.window.set_gesture_visual_feedback_enabled(
                not self.window.gesture_visual_feedback_enabled
            ),
            8: lambda: self.window.on_tray_about(None),
            9: lambda: self.window.on_tray_quit(None),
            10: lambda: self.window.open_bug_report_url(),
        }
        if item_id in actions:
            GLib.idle_add(actions[item_id])
            return

        layout_index = item_id - self.MENU_LAYOUT_ID_OFFSET
        if 0 <= layout_index < len(self.window.keyboard_layout_choices):
            layout_key = self.window.keyboard_layout_choices[layout_index][0]
            GLib.idle_add(self.window.set_keyboard_layout, layout_key)

    def toggle_gesture_typing(self):
        if self.window.gesture_enabled:
            self.window.disable_gesture_typing()
        else:
            self.window.enable_gesture_typing()

    def emit_menu_updated(self):
        if self.menu_registration_id is None:
            return
        self.menu_revision += 1
        self.connection.emit_signal(
            None,
            self.MENU_PATH,
            self.MENU_INTERFACE_NAME,
            "LayoutUpdated",
            GLib.Variant("(ui)", (self.menu_revision, 0)),
        )

    def unregister(self):
        if self.menu_registration_id is not None:
            self.connection.unregister_object(self.menu_registration_id)
            self.menu_registration_id = None
        if self.registration_id is not None:
            self.connection.unregister_object(self.registration_id)
            self.registration_id = None
        if self.name_acquired:
            try:
                self.connection.call_sync(
                    self.DBUS_NAME,
                    self.DBUS_PATH,
                    self.DBUS_NAME,
                    "ReleaseName",
                    GLib.Variant("(s)", (self.bus_name,)),
                    GLib.VariantType.new("(u)"),
                    Gio.DBusCallFlags.NONE,
                    1000,
                    None,
                )
            except Exception:
                pass
            self.name_acquired = False


class ScalableGrid(Gtk.Grid):
    def do_get_preferred_width(self):
        return (1, 1)

    def do_get_preferred_height(self):
        return (1, 1)

    def do_get_preferred_width_for_height(self, height):
        return (1, 1)

    def do_get_preferred_height_for_width(self, width):
        return (1, 1)


class ScalableKeyButton(Gtk.Button):
    def __init__(self, key_event=None):
        super().__init__()
        self.key_event = key_event
        self.primary_label = None
        self.secondary_label = None

    def set_dual_labels(self, primary, secondary=""):
        if self.primary_label is not None:
            self.primary_label.set_label(primary)
        if self.secondary_label is not None:
            self.secondary_label.set_label(secondary)

    def set_label(self, label):
        if self.primary_label is not None:
            self.primary_label.set_label(label)
        else:
            super().set_label(label)

    def get_label(self):
        if self.primary_label is not None:
            return self.primary_label.get_label()
        return super().get_label()

    def do_get_preferred_width(self):
        return (1, 1)

    def do_get_preferred_height(self):
        return (1, 1)

    def do_get_preferred_width_for_height(self, height):
        return (1, 1)

    def do_get_preferred_height_for_width(self, width):
        return (1, 1)


class ScalableHeaderButton(Gtk.Button):
    def __init__(self, label="", min_w=14, nat_w=40, min_h=22, nat_h=24):
        super().__init__(label=label)
        self._min_w = min_w
        self._nat_w = nat_w
        self._min_h = min_h
        self._nat_h = nat_h
        if len(label) > 1:
            child = self.get_child()
            if isinstance(child, Gtk.Label):
                child.set_ellipsize(Pango.EllipsizeMode.END)
                child.set_width_chars(1)

    def set_target_size(self, nat_w=None, nat_h=None):
        if nat_w is not None:
            self._nat_w = max(self._min_w, int(nat_w))
        if nat_h is not None:
            self._nat_h = max(self._min_h, int(nat_h))

    def do_get_preferred_width(self):
        _min_width, natural_width = Gtk.Button.do_get_preferred_width(self)
        return (self._min_w, max(self._min_w, self._nat_w, natural_width))

    def do_get_preferred_height(self):
        return (self._min_h, self._nat_h)

    def do_get_preferred_width_for_height(self, height):
        return self.do_get_preferred_width()

    def do_get_preferred_height_for_width(self, width):
        return self.do_get_preferred_height()


class ScalableSuggestionButton(Gtk.Button):
    def __init__(self, target_height=34):
        super().__init__()
        self._target_height = target_height

    def set_target_height(self, height):
        self._target_height = max(12, int(height))

    def do_get_preferred_width(self):
        _min_width, natural_width = Gtk.Button.do_get_preferred_width(self)
        return (1, max(1, natural_width))

    def do_get_preferred_height(self):
        return (12, max(12, self._target_height))

    def do_get_preferred_width_for_height(self, height):
        return self.do_get_preferred_width()

    def do_get_preferred_height_for_width(self, width):
        return self.do_get_preferred_height()


class ScalableComboBoxText(Gtk.ComboBoxText):
    def __init__(self):
        super().__init__()
        self._nat_h = 24

    def set_target_height(self, nat_h):
        self._nat_h = max(22, int(nat_h))

    def do_get_preferred_width(self):
        _min_width, natural_width = Gtk.ComboBoxText.do_get_preferred_width(self)
        return (18, max(18, natural_width))

    def do_get_preferred_height(self):
        return (22, self._nat_h)

    def do_get_preferred_width_for_height(self, height):
        return self.do_get_preferred_width()

    def do_get_preferred_height_for_width(self, width):
        return self.do_get_preferred_height()


class ScalableHeaderBar(Gtk.HeaderBar):
    def __init__(self, title_label=None, menu_check_cb=None):
        super().__init__()
        self.title_label = title_label
        self.menu_check_cb = menu_check_cb
        self._nat_h = 28

    def set_target_height(self, nat_h):
        self._nat_h = max(28, int(nat_h))

    def do_get_preferred_width(self):
        _min_width, natural_width = Gtk.HeaderBar.do_get_preferred_width(self)
        return (120, max(120, natural_width))

    def do_get_preferred_height(self):
        return (28, self._nat_h)

    def do_get_preferred_width_for_height(self, height):
        return self.do_get_preferred_width()

    def do_get_preferred_height_for_width(self, width):
        return self.do_get_preferred_height()

    def do_size_allocate(self, allocation):
        if self.title_label is not None:
            menu_open = bool(self.menu_check_cb and self.menu_check_cb())
            min_title_width = 480 if menu_open else 320
            should_show = allocation.width >= min_title_width
            if self.title_label.get_visible() != should_show:
                self.title_label.set_visible(should_show)
        Gtk.HeaderBar.do_size_allocate(self, allocation)


class VirtualKeyboard(Gtk.Window):
    DEFAULT_WINDOW_WIDTH = 780
    DEFAULT_WINDOW_HEIGHT = 320
    MIN_WINDOW_WIDTH = 220
    MIN_WINDOW_HEIGHT = 110
    MIN_FUNCTION_ROW_HEIGHT = 124
    BASE_GRID_WIDTH = 720
    BASE_KEY_HEIGHT = 52
    BASE_KEY_FONT_SIZE = 19
    BASE_HEADER_FONT_SIZE = 14
    BASE_SUGGESTION_HEIGHT = 34
    BASE_SUGGESTION_FONT_SIZE = 15
    BASE_SUGGESTION_SPACING = 4
    BASE_SUGGESTION_MARGIN = 3
    BASE_SUGGESTION_MARGIN_BOTTOM = 1

    def __init__(self, application=None):
        super().__init__(title=APP_DISPLAY_NAME, name="toplevel")
        if application is not None:
            self.set_application(application)

        self.exiting = False
        self.set_border_width(0)
        self.set_resizable(True)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.stick()
        self.set_modal(False)
        self.set_focus_on_map(False)
        self.set_can_focus(False)
        self.set_accept_focus(False)
        self.set_deletable(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)

        self.connect("delete-event", self.on_delete_event)
        self.connect("map-event", self.on_map_keep_above)
        self.connect("window-state-event", self.on_window_state_changed)
        self._keep_above_retries = 0
        self._keep_above_timer_id = None
        self._save_settings_timer_id = None
        self.width = self.DEFAULT_WINDOW_WIDTH
        self.height = self.DEFAULT_WINDOW_HEIGHT
        self.pos_x = 0
        self.pos_y = 0
        self.config_pos_x = 0
        self.config_pos_y = 0
        self.set_position(Gtk.WindowPosition.NONE)

        self.CONFIG_DIR = os.path.expanduser("~/.config/vboard")
        self.CONFIG_FILE = os.path.join(self.CONFIG_DIR, "settings.conf")
        self.config = configparser.ConfigParser()
        self.keyboard_layouts = load_keyboard_layouts(
            os.path.join(self.CONFIG_DIR, "layouts")
        )
        self.keyboard_layout_choices = get_layout_choices(self.keyboard_layouts)

        self.bg_color = "0,0,0"
        self.opacity = "0.90"
        self.text_color = "white"
        self.style_variant = "onboard"
        self.text_prediction_enabled = True
        self.gesture_enabled = True
        self.gesture_visual_feedback_enabled = True
        self.start_minimized = False
        self.keyboard_layout = DEFAULT_KEYBOARD_LAYOUT
        self.show_function_row = True
        self.fn_locked = True
        self.fn_row_button = None
        self.settings_fn_row_check = None
        self.tray_fn_row_item = None
        self.read_settings()
        self.MIN_WINDOW_HEIGHT = (
            self.MIN_FUNCTION_ROW_HEIGHT if self.show_function_row else 110
        )

        self.modifiers = {mod_key: False for mod_key in MODIFIER_KEYS}
        self.color_map = dict(COLOR_CHOICES)
        self.apply_window_geometry_constraints()
        self.width, self.height = self.validate_window_size(self.width, self.height)
        self.set_default_size(self.width, self.height)
        self.resize(self.width, self.height)

        self.header_title_label = Gtk.Label(label=APP_DISPLAY_NAME)
        self.header_title_label.get_style_context().add_class("title")
        self.header_title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.header_title_label.set_width_chars(0)
        self.header = ScalableHeaderBar(
            title_label=self.header_title_label,
            menu_check_cb=lambda: (
                hasattr(self, "color_combobox")
                and self.color_combobox.get_visible()
            ),
        )
        self.header.set_property("spacing", 2)
        self.header.set_custom_title(self.header_title_label)
        self.header.set_show_close_button(True)
        self.buttons = []
        self.header_buttons = []
        self.key_buttons = {}
        self.modifier_buttons = {}
        self.current_word = ""
        self.suggestion_engine = HunspellSuggestionEngine()
        self.suggestion_buttons = []
        self.suggestion_override = None
        self.color_combobox = ScalableComboBoxText()
        self.tray_icon = None
        self.tray_menu = None
        self.tray_toggle_item = None
        self.tray_prediction_item = None
        self.tray_gesture_item = None
        self.tray_visual_feedback_item = None
        self.tray_start_minimized_item = None
        self.tray_layout_items = {}
        self.settings_dialog = None
        self.settings_gesture_check = None
        self.settings_visual_feedback_check = None
        self.css_provider = Gtk.CssProvider()
        self._css_provider_registered = False
        self._last_suggestion_scale = None
        self.caps_lock_active = False
        self._syncing_tray_items = False
        self.layout_character_lookup = {}
        self.key_font_size = self.BASE_KEY_FONT_SIZE
        self.secondary_key_font_size = max(
            5, int(round(self.BASE_KEY_FONT_SIZE * 0.65))
        )
        self.header_font_size = self.BASE_HEADER_FONT_SIZE
        self.suggestion_font_size = self.BASE_SUGGESTION_FONT_SIZE
        self.layout_scale = 1.0
        self.gesture_controller = None
        self.set_titlebar(self.header)
        self.set_name("vboard-main")
        self.set_default_icon_name(self.get_app_icon_name())

        self.create_settings()
        self.create_tray_icon()
        try:
            self.backend = UInputBackend()
        except Exception as exc:
            self.backend = NullInputBackend(
                f"Could not initialize uinput backend ({exc}); key output is disabled"
            )

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_hexpand(True)
        content.set_vexpand(True)
        self.content_box = content
        self.add(content)

        self.suggestion_revealer = Gtk.Revealer()
        self.suggestion_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.suggestion_revealer.set_no_show_all(True)
        self.suggestion_revealer.set_reveal_child(self.text_prediction_enabled)

        self.suggestion_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.suggestion_bar.set_name("suggestion-bar")
        self.suggestion_bar.set_hexpand(True)
        self.suggestion_bar.set_margin_start(3)
        self.suggestion_bar.set_margin_end(3)
        self.suggestion_bar.set_margin_top(3)
        self.suggestion_bar.set_margin_bottom(1)
        self.suggestion_revealer.add(self.suggestion_bar)
        self.create_suggestion_buttons()

        grid_overlay = Gtk.Overlay()
        grid_overlay.set_hexpand(True)
        grid_overlay.set_vexpand(True)
        self.grid_overlay = grid_overlay
        content.pack_start(self.suggestion_revealer, False, False, 0)
        self.update_suggestion_bar_visibility()
        content.pack_start(grid_overlay, True, True, 0)

        grid = ScalableGrid()
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(True)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        grid.set_halign(Gtk.Align.FILL)
        grid.set_valign(Gtk.Align.FILL)
        grid.set_margin_start(3)
        grid.set_margin_end(3)
        grid.set_margin_bottom(3)
        grid.set_name("grid")
        grid.connect("size-allocate", self.on_grid_size_allocate)
        self.grid = grid
        grid_overlay.add(grid)

        self.keyboard_layout = self.normalize_keyboard_layout(self.keyboard_layout)
        self.refresh_layout_character_lookup()

        for row_index, keys in enumerate(self.get_active_key_rows()):
            self.create_row(grid, row_index, keys)

        self.set_default_size(self.width, self.height)
        self.resize(self.width, self.height)
        self.update_suggestion_bar_scale()
        self.apply_css()
        if self.text_prediction_enabled:
            GLib.idle_add(self.preload_suggestions)
        GLib.idle_add(self.update_suggestion_bar_scale)

        if self.gesture_enabled:
            self.enable_gesture_typing(sync_controls=False, save=False)

        self.sync_caps_lock_from_system(connect=True)

    def apply_window_geometry_constraints(self):
        geometry = Gdk.Geometry()
        geometry.min_width = self.MIN_WINDOW_WIDTH
        geometry.min_height = self.MIN_WINDOW_HEIGHT
        self.set_geometry_hints(None, geometry, Gdk.WindowHints.MIN_SIZE)

    def get_screen_dimensions(self):
        screen_width = 0
        screen_height = 0
        try:
            display = self.get_display() if hasattr(self, "get_display") else None
            if display is None:
                display = Gdk.Display.get_default()
            if display is not None and hasattr(display, "get_n_monitors"):
                for index in range(display.get_n_monitors()):
                    monitor = display.get_monitor(index)
                    if monitor is not None:
                        geometry = monitor.get_geometry()
                        screen_width = max(
                            screen_width,
                            geometry.x + geometry.width,
                            geometry.width,
                        )
                        screen_height = max(
                            screen_height,
                            geometry.y + geometry.height,
                            geometry.height,
                        )
        except Exception:
            pass

        if screen_width <= 0 or screen_height <= 0:
            try:
                screen = self.get_screen() if hasattr(self, "get_screen") else None
                if screen is None:
                    screen = Gdk.Screen.get_default()
                if screen is not None:
                    screen_width = max(screen_width, screen.get_width())
                    screen_height = max(screen_height, screen.get_height())
            except Exception:
                pass

        if screen_width <= 0 or screen_height <= 0:
            return (3840, 2160)
        return (screen_width, screen_height)

    def validate_window_size(self, width, height):
        screen_width, screen_height = self.get_screen_dimensions()
        default_w = min(self.DEFAULT_WINDOW_WIDTH, screen_width)
        default_h = min(self.DEFAULT_WINDOW_HEIGHT, screen_height)
        if isinstance(width, bool) or isinstance(height, bool):
            return (default_w, default_h)
        try:
            parsed_w = int(width)
            parsed_h = int(height)
        except (ValueError, TypeError):
            return (default_w, default_h)

        if (
            parsed_w <= 0
            or parsed_h <= 0
            or parsed_w > screen_width
            or parsed_h > screen_height
        ):
            return (default_w, default_h)

        clamped_w = max(self.MIN_WINDOW_WIDTH, parsed_w)
        clamped_h = max(self.MIN_WINDOW_HEIGHT, parsed_h)
        return (min(clamped_w, screen_width), min(clamped_h, screen_height))

    def get_app_icon_name(self):
        icon_theme = Gtk.IconTheme.get_default()
        preferred_icon = "io.github.archisman-panigrahi.vboard"
        fallback_icon = "preferences-desktop-keyboard"
        if icon_theme and icon_theme.has_icon(preferred_icon):
            return preferred_icon
        return fallback_icon

    def create_tray_icon(self):
        icon_name = self.get_app_icon_name()
        if self.create_status_notifier_tray_icon(icon_name):
            return

        if APPINDICATOR_AVAILABLE:
            if APPINDICATOR_BACKEND == "ayatana":
                GLib.log_set_handler(
                    "libayatana-appindicator",
                    GLib.LogLevelFlags.LEVEL_WARNING,
                    lambda domain, level, message, user_data: None,
                    None,
                )

            self.tray_icon = AppIndicator3.Indicator.new(
                "vboard",
                icon_name,
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            self.tray_icon.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.tray_menu = self.build_tray_menu()
            self.tray_icon.set_menu(self.tray_menu)
            return

        if self.create_status_tray_icon(icon_name):
            return

        self.clear_tray_icon(
            "Warning: Could not create tray icon. Tray disabled."
        )

    def create_status_notifier_tray_icon(self, icon_name):
        try:
            self.tray_icon = StatusNotifierTrayIcon(self, icon_name)
            self.tray_menu = self.build_tray_menu()
            print("Using native StatusNotifierItem for system tray.")
            return True
        except Exception as exc:
            self.clear_tray_icon(
                f"Warning: Could not create native StatusNotifierItem tray icon ({exc})."
            )
            return False

    def create_status_tray_icon(self, icon_name):
        try:
            self.tray_icon = Gtk.StatusIcon()
            self.tray_icon.set_from_icon_name(icon_name)
            self.tray_icon.set_tooltip_text("Vboard - Virtual Keyboard")
            self.tray_icon.connect("activate", self.on_statusicon_activate)
            self.tray_icon.connect("popup-menu", self.on_statusicon_popup_menu)
            self.tray_menu = self.build_tray_menu()
            print("Using Gtk.StatusIcon for system tray.")
            return True
        except Exception as exc:
            self.clear_tray_icon(
                f"Warning: Could not create Gtk.StatusIcon tray icon ({exc})."
            )
            return False

    def clear_tray_icon(self, warning=None):
        if self.tray_icon is not None and hasattr(self.tray_icon, "unregister"):
            self.tray_icon.unregister()
        self.tray_icon = None
        self.tray_menu = None
        self.tray_toggle_item = None
        self.tray_prediction_item = None
        self.tray_gesture_item = None
        self.tray_visual_feedback_item = None
        self.tray_start_minimized_item = None
        self.tray_fn_row_item = None
        self.tray_layout_items = {}
        if warning:
            print(warning)

    def build_tray_menu(self):
        tray_menu = Gtk.Menu()
        self.tray_toggle_item = Gtk.MenuItem(label="Hide")
        self.tray_toggle_item.connect("activate", self.on_tray_toggle)
        tray_menu.append(self.tray_toggle_item)

        self.tray_prediction_item = Gtk.CheckMenuItem(label="Text Prediction")
        self.tray_prediction_item.connect("toggled", self.on_tray_prediction_toggled)
        tray_menu.append(self.tray_prediction_item)

        self.tray_gesture_item = Gtk.CheckMenuItem(
            label="Touch Typing (requires app restart)"
        )
        self.tray_gesture_item.connect("toggled", self.on_tray_gesture_toggled)
        tray_menu.append(self.tray_gesture_item)

        self.tray_visual_feedback_item = Gtk.CheckMenuItem(label="Visual Feedback")
        self.tray_visual_feedback_item.connect(
            "toggled", self.on_tray_visual_feedback_toggled
        )
        tray_menu.append(self.tray_visual_feedback_item)

        self.tray_start_minimized_item = Gtk.CheckMenuItem(label="Start Minimized")
        self.tray_start_minimized_item.connect(
            "toggled", self.on_tray_start_minimized_toggled
        )
        tray_menu.append(self.tray_start_minimized_item)

        self.tray_fn_row_item = Gtk.CheckMenuItem(label="Function Row (F1–F12)")
        self.tray_fn_row_item.connect("toggled", self.on_tray_fn_row_toggled)
        tray_menu.append(self.tray_fn_row_item)

        tray_menu.append(Gtk.SeparatorMenuItem())

        layout_item = Gtk.MenuItem(label="Keyboard Layout")
        layout_menu = Gtk.Menu()
        self.tray_layout_items = {}
        first_layout_item = None
        for layout_key, layout_label in self.keyboard_layout_choices:
            if first_layout_item is None:
                item = Gtk.RadioMenuItem.new_with_label(None, layout_label)
                first_layout_item = item
            else:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(
                    first_layout_item,
                    layout_label,
                )
            item.connect("toggled", self.on_tray_layout_toggled, layout_key)
            layout_menu.append(item)
            self.tray_layout_items[layout_key] = item
        layout_item.set_submenu(layout_menu)
        tray_menu.append(layout_item)

        tray_menu.append(Gtk.SeparatorMenuItem())

        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self.on_tray_about)
        tray_menu.append(about_item)

        report_bugs_item = Gtk.MenuItem(label="Report bugs")
        report_bugs_item.connect("activate", self.on_report_bugs)
        tray_menu.append(report_bugs_item)

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self.on_tray_quit)
        tray_menu.append(quit_item)

        tray_menu.show_all()
        self.sync_tray_items()
        return tray_menu

    def update_tray_menu(self):
        if self.tray_toggle_item is None:
            if hasattr(self.tray_icon, "emit_menu_updated"):
                self.tray_icon.emit_menu_updated()
            return

        self.tray_toggle_item.set_label("Hide" if self.get_visible() else "Show")
        if hasattr(self.tray_icon, "emit_menu_updated"):
            self.tray_icon.emit_menu_updated()

    def toggle_visibility(self):
        if self.get_visible():
            self.save_settings()
            self.hide()
        else:
            self.show_all()
            if self.width > 0 and self.height > 0:
                self.resize(self.width, self.height)
            self.present()
            self.request_keep_above()
        self.update_tray_menu()

    def on_tray_activate(self, icon):
        self.toggle_visibility()

    def on_statusicon_activate(self, widget):
        self.on_tray_activate(widget)

    def on_statusicon_popup_menu(self, widget, button, activate_time):
        self.popup_tray_menu(widget, button, activate_time)

    def popup_tray_menu_at_coordinates(self, x, y):
        if self.tray_menu:
            root_window = Gdk.get_default_root_window()
            if root_window is not None:
                rect = Gdk.Rectangle()
                rect.x = x
                rect.y = y
                rect.width = 1
                rect.height = 1
                self.tray_menu.popup_at_rect(
                    root_window,
                    rect,
                    Gdk.Gravity.SOUTH_EAST,
                    Gdk.Gravity.NORTH_WEST,
                    None,
                )
            else:
                self.tray_menu.popup_at_pointer(None)
        return False

    def popup_tray_menu(self, widget, button, activate_time):
        if self.tray_menu:
            self.tray_menu.popup(None, None, widget.position_menu, button, activate_time)

    def on_tray_toggle(self, widget):
        self.on_tray_activate(None)

    def on_tray_prediction_toggled(self, widget):
        if not self._syncing_tray_items:
            self.set_text_prediction_enabled(widget.get_active())

    def on_tray_gesture_toggled(self, widget):
        if self._syncing_tray_items:
            return
        if widget.get_active():
            self.enable_gesture_typing()
        else:
            self.disable_gesture_typing()

    def on_tray_visual_feedback_toggled(self, widget):
        if not self._syncing_tray_items:
            self.set_gesture_visual_feedback_enabled(widget.get_active())

    def on_tray_start_minimized_toggled(self, widget):
        if not self._syncing_tray_items:
            self.set_start_minimized(widget.get_active())

    def on_tray_fn_row_toggled(self, widget):
        if not self._syncing_tray_items:
            self.set_function_row_visible(widget.get_active())

    def on_tray_layout_toggled(self, widget, layout_key):
        if not self._syncing_tray_items and widget.get_active():
            self.set_keyboard_layout(layout_key)

    def sync_tray_items(self):
        self._syncing_tray_items = True
        try:
            if self.tray_prediction_item is not None:
                self.tray_prediction_item.set_active(self.text_prediction_enabled)
            if self.tray_gesture_item is not None:
                self.tray_gesture_item.set_active(self.gesture_enabled)
            if self.tray_visual_feedback_item is not None:
                self.tray_visual_feedback_item.set_active(
                    self.gesture_visual_feedback_enabled
                )
                self.tray_visual_feedback_item.set_sensitive(self.gesture_enabled)
            if self.tray_start_minimized_item is not None:
                self.tray_start_minimized_item.set_active(self.start_minimized)
            if self.tray_fn_row_item is not None:
                self.tray_fn_row_item.set_active(self.show_function_row)
            for layout_key, item in self.tray_layout_items.items():
                item.set_active(layout_key == self.keyboard_layout)
        finally:
            self._syncing_tray_items = False
        if hasattr(self.tray_icon, "emit_menu_updated"):
            self.tray_icon.emit_menu_updated()

    def normalize_keyboard_layout(self, layout_key):
        if layout_key in self.keyboard_layouts:
            return layout_key
        return get_default_layout_key(self.keyboard_layouts)

    def get_layout_config(self):
        return self.keyboard_layouts[self.keyboard_layout]

    def get_active_key_rows(self):
        base_rows = self.get_layout_config()["rows"]
        if getattr(self, "show_function_row", True):
            return [list(FUNCTION_ROW_KEYS)] + base_rows
        return base_rows

    @property
    def num_rows(self):
        return len(self.get_active_key_rows())

    def get_active_key_labels(self):
        return self.get_layout_config()["labels"]

    def get_active_shifted_map(self):
        return self.get_layout_config()["shifted"]

    def sync_caps_lock_from_system(self, keymap=None, connect=False):
        try:
            keymap = keymap or Gdk.Keymap.get_default()
            if keymap is None or not hasattr(keymap, "get_caps_lock_state"):
                return
            self.set_caps_lock_active(
                bool(keymap.get_caps_lock_state()),
                update_system=False,
            )
            if connect:
                keymap.connect("state-changed", self.sync_caps_lock_from_system)
        except (AttributeError, TypeError, RuntimeError):
            return

    def refresh_layout_character_lookup(self):
        lookup = {}
        key_labels = self.get_active_key_labels()
        shifted_map = self.get_active_shifted_map()

        for row in self.get_active_key_rows():
            for key_event in row:
                if key_event in MODIFIER_KEYS:
                    continue

                key_label = key_labels.get(key_event, key_event)
                if len(key_label) == 1:
                    if key_label.isalpha():
                        lookup[key_label.lower()] = (key_event, False)
                        lookup[key_label.upper()] = (key_event, True)
                    else:
                        lookup[key_label] = (key_event, False)

                shifted_label = shifted_map.get(key_event)
                if shifted_label is not None:
                    lookup[shifted_label] = (key_event, True)

        self.layout_character_lookup = lookup

    def rebuild_keyboard_grid(self):
        for child in self.grid.get_children():
            self.grid.remove(child)

        self.key_buttons = {}
        self.modifier_buttons = {}
        for row_index, keys in enumerate(self.get_active_key_rows()):
            self.create_row(self.grid, row_index, keys)

        self.grid.show_all()
        self.update_suggestion_bar_scale()

    def set_keyboard_layout(self, layout_key):
        normalized_layout = self.normalize_keyboard_layout(layout_key)
        if normalized_layout == self.keyboard_layout:
            return

        self.keyboard_layout = normalized_layout
        self.refresh_layout_character_lookup()
        self.rebuild_keyboard_grid()
        if self.gesture_controller is not None:
            self.gesture_controller.refresh_layout_cache()
            self.gesture_controller.queue_overlay_draw()

        self.clear_suggestion_override(update=False)
        self.current_word = ""
        self.update_suggestions()
        self.sync_tray_items()

        self.save_settings()

    def sync_function_row_controls(self):
        if self.fn_row_button is not None:
            ctx = self.fn_row_button.get_style_context()
            if self.show_function_row:
                ctx.add_class("active-header-toggle")
            else:
                ctx.remove_class("active-header-toggle")

        if (
            self.settings_fn_row_check is not None
            and self.settings_fn_row_check.get_active() != self.show_function_row
        ):
            self.settings_fn_row_check.set_active(self.show_function_row)

        if (
            self.tray_fn_row_item is not None
            and self.tray_fn_row_item.get_active() != self.show_function_row
        ):
            self.tray_fn_row_item.set_active(self.show_function_row)

    def set_function_row_visible(self, visible):
        visible = bool(visible)
        if visible == self.show_function_row:
            return

        self.show_function_row = visible
        self.MIN_WINDOW_HEIGHT = (
            self.MIN_FUNCTION_ROW_HEIGHT if self.show_function_row else 110
        )
        self.apply_window_geometry_constraints()

        cur_w, cur_h = self.get_size()
        if cur_h < self.MIN_WINDOW_HEIGHT:
            self.resize(cur_w, self.MIN_WINDOW_HEIGHT)

        self.rebuild_keyboard_grid()

        if self.gesture_controller is not None:
            self.gesture_controller.refresh_layout_cache()
            self.gesture_controller.schedule_layout_cache_refresh()
            self.gesture_controller.queue_overlay_draw()

        self._last_suggestion_scale = None
        self.update_suggestion_bar_scale()
        self.sync_function_row_controls()
        self.save_settings()

    def sync_gesture_controls(self):
        if (
            self.settings_gesture_check is not None
            and self.settings_gesture_check.get_active() != self.gesture_enabled
        ):
            self.settings_gesture_check.set_active(self.gesture_enabled)
        self.sync_tray_items()

    def sync_visual_feedback_controls(self):
        if self.settings_visual_feedback_check is not None:
            self.settings_visual_feedback_check.set_sensitive(self.gesture_enabled)
            if (
                self.settings_visual_feedback_check.get_active()
                != self.gesture_visual_feedback_enabled
            ):
                self.settings_visual_feedback_check.set_active(
                    self.gesture_visual_feedback_enabled
                )
        self.sync_tray_items()

    def set_gesture_visual_feedback_enabled(self, enabled, sync_controls=True):
        self.gesture_visual_feedback_enabled = bool(enabled)
        if self.gesture_controller is not None:
            self.gesture_controller.set_visual_feedback_enabled(
                self.gesture_visual_feedback_enabled
            )
        if sync_controls:
            self.sync_visual_feedback_controls()
        self.save_settings()

    def enable_gesture_typing(self, sync_controls=True, save=True):
        if self.gesture_controller is None:
            gesture_module = importlib.import_module(f"{__package__}.gesture")
            self.gesture_controller = gesture_module.GestureTypingController(
                self,
                self.grid_overlay,
            )
            self.gesture_controller.refresh_layout_cache()
            self.gesture_controller.queue_overlay_draw()
        self.gesture_controller.set_visual_feedback_enabled(
            self.gesture_visual_feedback_enabled
        )

        self.gesture_enabled = True
        if sync_controls:
            self.sync_gesture_controls()
            self.sync_visual_feedback_controls()
        if save:
            self.save_settings()

    def disable_gesture_typing(self, sync_controls=True, save=True):
        had_gesture_commit = (
            self.gesture_controller is not None and self.gesture_controller.has_committed_text()
        )

        if self.gesture_controller is not None:
            self.gesture_controller.destroy()
            self.gesture_controller = None

        self.gesture_enabled = False
        if had_gesture_commit:
            self.suggestion_override = None
            self.update_suggestions()

        sys.modules.pop(f"{__package__}.gesture", None)
        if sync_controls:
            self.sync_gesture_controls()
            self.sync_visual_feedback_controls()
        if save:
            self.save_settings()

    def on_tray_about(self, widget):
        about_dialog = Gtk.AboutDialog()
        about_dialog.set_modal(True)
        about_dialog.set_program_name(APP_DISPLAY_NAME)
        about_dialog.set_version(VERSION)
        about_dialog.set_comments(
            "A lightweight virtual keyboard for GNU/Linux with Wayland support.\n\n"
            "Originally created by mdev588. The original project was archived, "
            "and it is now maintained by Archisman Panigrahi.\n\n"
            "Original project: https://github.com/mdev588/vboard\n"
            "Special thanks to honjow for the icon and patches.\n"
            "Thanks to Yavuz Kagan Yadigar for the enhanced theme inspiration.\n"
            "Thanks to onboard developers for the droid theme inspiration.\n"
            "Thanks to the Hunspell project for the suggestion engine.\n"
            "This project is licensed under GPLv3."
        )
        about_dialog.set_copyright(
            "Copyright © 2025 mdev588\n"
            "Copyright © 2026 Archisman Panigrahi"
        )
        about_dialog.set_website("https://github.com/archisman-panigrahi/vboard")
        about_dialog.set_website_label("Homepage")
        about_dialog.set_logo_icon_name(self.get_app_icon_name())
        about_dialog.run()
        about_dialog.destroy()

    def on_tray_quit(self, widget):
        self.exiting = True
        self.save_settings()
        self.clear_tray_icon()
        self.destroy()

    def on_report_bugs(self, widget=None):
        self.open_bug_report_url()

    def open_bug_report_url(self):
        Gio.AppInfo.launch_default_for_uri(BUG_REPORT_URL, None)

    def on_delete_event(self, widget, event):
        if self.exiting:
            return False
        if self.tray_icon is None:
            return False
        self.save_settings()
        self.hide()
        self.update_tray_menu()
        return True

    def create_settings(self):
        self.esc_button = ScalableHeaderButton(
            label="ESC",
            min_w=18,
            nat_w=54,
            min_h=14,
            nat_h=28,
        )
        self.esc_button.connect("clicked", lambda widget: self.emit_key("Esc"))
        self.esc_button.set_name("esc-button")
        self.header.pack_start(self.esc_button)
        self.header_buttons.append(self.esc_button)

        self.create_button("☰", self.change_visibility, callbacks=1)
        self.create_button(
            "Options",
            self.open_settings_dialog,
            callbacks=1,
            hide_with_menu=False,
        )
        self.fn_row_button = self.create_button(
            "Fn Row",
            self.on_header_toggle_function_row,
            callbacks=1,
            hide_with_menu=True,
        )
        self.fn_row_button.set_tooltip_text("Toggle Function row (F1-F12)")
        self.create_button("+", self.change_opacity, True, 2)
        self.create_button("-", self.change_opacity, False, 2)
        self.create_button(f"{self.opacity}")
        self.color_combobox.append_text("Change Background")
        self.color_combobox.connect("changed", self.change_color)
        self.color_combobox.set_name("combobox")
        for renderer in self.color_combobox.get_cells():
            if isinstance(renderer, Gtk.CellRendererText):
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
                renderer.set_property("width-chars", 1)
        self.header.pack_end(self.color_combobox)

        for label, _color in COLOR_CHOICES:
            self.color_combobox.append_text(label)

        if self.style_variant == "onboard":
            active_label = "Onboard Droid Theme"
        else:
            active_label = None

        if self.style_variant == "enhanced":
            for label, color in COLOR_CHOICES:
                if (
                    isinstance(color, tuple)
                    and len(color) == 2
                    and color[0] == ENHANCED_BACKGROUND_PRESET
                    and color[1] == self.bg_color
                ):
                    active_label = label
                    break
        elif active_label is None:
            for label, color in COLOR_CHOICES:
                if color == self.bg_color:
                    active_label = label
                    break

        active_index = 0
        if active_label is not None:
            for index, (label, _color) in enumerate(COLOR_CHOICES, start=1):
                if label == active_label:
                    active_index = index
                    break

        self.color_combobox.set_active(active_index)
        self.sync_function_row_controls()

    def on_header_toggle_function_row(self, widget=None):
        self.set_function_row_visible(not self.show_function_row)

    def open_settings_dialog(self, widget=None):
        if self.settings_dialog is not None:
            self.settings_dialog.present()
            return

        dialog = Gtk.Dialog(
            title="Options for Vboard",
            transient_for=self,
            modal=True,
        )
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.connect("response", self.on_settings_dialog_response)
        dialog.connect("destroy", self.on_settings_dialog_destroy)

        content = dialog.get_content_area()
        content.set_border_width(12)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        content.add(grid)

        prediction_check = Gtk.CheckButton(label="Text Prediction")
        prediction_check.set_active(self.text_prediction_enabled)
        prediction_check.connect("toggled", self.on_settings_prediction_toggled)
        grid.attach(prediction_check, 0, 0, 2, 1)

        gesture_check = Gtk.CheckButton(
            label="Touch Typing (requires app restart)"
        )
        gesture_check.set_active(self.gesture_enabled)
        gesture_check.connect("toggled", self.on_settings_gesture_toggled)
        grid.attach(gesture_check, 0, 1, 2, 1)
        self.settings_gesture_check = gesture_check

        visual_feedback_check = Gtk.CheckButton(label="Visual Feedback")
        visual_feedback_check.set_active(self.gesture_visual_feedback_enabled)
        visual_feedback_check.set_sensitive(self.gesture_enabled)
        visual_feedback_check.connect(
            "toggled", self.on_settings_visual_feedback_toggled
        )
        grid.attach(visual_feedback_check, 0, 2, 2, 1)
        self.settings_visual_feedback_check = visual_feedback_check

        start_minimized_check = Gtk.CheckButton(label="Start Minimized")
        start_minimized_check.set_active(self.start_minimized)
        start_minimized_check.connect(
            "toggled", self.on_settings_start_minimized_toggled
        )
        grid.attach(start_minimized_check, 0, 3, 2, 1)

        fn_row_check = Gtk.CheckButton(label="Function Row (F1–F12)")
        fn_row_check.set_active(self.show_function_row)
        fn_row_check.connect(
            "toggled", lambda w: self.set_function_row_visible(w.get_active())
        )
        grid.attach(fn_row_check, 0, 4, 2, 1)
        self.settings_fn_row_check = fn_row_check

        layout_label = Gtk.Label(label="Keyboard Layout", xalign=0)
        layout_combo = Gtk.ComboBoxText()
        for layout_key, layout_name in self.keyboard_layout_choices:
            layout_combo.append(layout_key, layout_name)
        layout_combo.set_active_id(self.keyboard_layout)
        layout_combo.connect("changed", self.on_settings_layout_changed)
        grid.attach(layout_label, 0, 5, 1, 1)
        grid.attach(layout_combo, 1, 5, 1, 1)

        about_button = Gtk.Button(label="About")
        about_button.connect("clicked", self.on_settings_about_clicked)
        report_bugs_button = Gtk.Button(label="Report bugs")
        report_bugs_button.connect("clicked", self.on_settings_report_bugs_clicked)
        quit_button = Gtk.Button(label="Quit")
        quit_button.connect("clicked", self.on_settings_quit_clicked)
        grid.attach(about_button, 0, 6, 1, 1)
        grid.attach(report_bugs_button, 1, 6, 1, 1)
        grid.attach(quit_button, 2, 6, 1, 1)

        self.settings_dialog = dialog
        dialog.show_all()

    def on_settings_dialog_response(self, dialog, response_id):
        dialog.destroy()

    def on_settings_dialog_destroy(self, dialog):
        self.settings_dialog = None
        self.settings_gesture_check = None
        self.settings_visual_feedback_check = None
        self.settings_fn_row_check = None

    def on_settings_prediction_toggled(self, widget):
        self.set_text_prediction_enabled(widget.get_active())

    def on_settings_gesture_toggled(self, widget):
        if widget.get_active():
            self.enable_gesture_typing()
        else:
            self.disable_gesture_typing()
        if self.settings_visual_feedback_check is not None:
            self.settings_visual_feedback_check.set_sensitive(self.gesture_enabled)

    def on_settings_visual_feedback_toggled(self, widget):
        self.set_gesture_visual_feedback_enabled(widget.get_active())

    def on_settings_start_minimized_toggled(self, widget):
        self.set_start_minimized(widget.get_active())

    def on_settings_layout_changed(self, widget):
        layout_key = widget.get_active_id()
        if layout_key is not None:
            self.set_keyboard_layout(layout_key)

    def on_settings_about_clicked(self, widget):
        self.on_tray_about(widget)

    def on_settings_report_bugs_clicked(self, widget):
        self.open_bug_report_url()

    def on_settings_quit_clicked(self, widget):
        self.on_tray_quit(widget)

    def configure_compact_button_label(self, button):
        child = button.get_child()
        if isinstance(child, Gtk.Label):
            child.set_ellipsize(Pango.EllipsizeMode.END)
            child.set_width_chars(1)

    def create_suggestion_buttons(self):
        for _ in range(SUGGESTION_LIMIT):
            button = ScalableSuggestionButton(self.BASE_SUGGESTION_HEIGHT)
            button.set_name("suggestion-button")
            button.set_label(" ")
            button.set_sensitive(False)
            button.set_hexpand(True)
            self.configure_compact_button_label(button)
            button.connect("clicked", self.on_suggestion_clicked)
            self.suggestion_bar.pack_start(button, True, True, 0)
            self.suggestion_buttons.append(button)

    def update_suggestion_bar_visibility(self):
        self.suggestion_revealer.set_reveal_child(self.text_prediction_enabled)
        if self.text_prediction_enabled:
            self.suggestion_revealer.show()
            self.suggestion_bar.show_all()
        else:
            self.suggestion_revealer.hide()
        self._last_suggestion_scale = None
        self.update_suggestion_bar_scale()

    def set_text_prediction_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self.text_prediction_enabled:
            return

        self.text_prediction_enabled = enabled
        self.current_word = ""
        self.clear_suggestion_override(update=False)
        self.update_suggestion_bar_visibility()
        self.update_suggestions()
        if self.text_prediction_enabled:
            GLib.idle_add(self.preload_suggestions)
        self.sync_tray_items()

        self.save_settings()

    def set_start_minimized(self, enabled):
        enabled = bool(enabled)
        if enabled == self.start_minimized:
            return

        self.start_minimized = enabled
        self.sync_tray_items()
        self.save_settings()

    def preload_suggestions(self):
        self.suggestion_engine.ensure_loaded()
        return False

    def schedule_save_settings(self, delay_ms=250):
        if self._save_settings_timer_id is not None:
            GLib.source_remove(self._save_settings_timer_id)
        self._save_settings_timer_id = GLib.timeout_add(
            delay_ms,
            self._flush_scheduled_save_settings,
        )

    def _flush_scheduled_save_settings(self):
        self._save_settings_timer_id = None
        self.save_settings()
        return False

    def cancel_scheduled_save_settings(self):
        if self._save_settings_timer_id is not None:
            GLib.source_remove(self._save_settings_timer_id)
            self._save_settings_timer_id = None

    def on_resize(self, widget, event):
        width, height = self.get_size()
        if width > 0 and height > 0:
            self.width, self.height = self.validate_window_size(width, height)
        x, y = self.get_position()
        if x > 0 and y > 0:
            self.pos_x, self.pos_y = x, y
        if self.gesture_controller is not None:
            self.gesture_controller.refresh_layout_cache()
            self.gesture_controller.schedule_layout_cache_refresh()
        self.update_suggestion_bar_scale()
        self.schedule_save_settings()
        return False

    def on_grid_size_allocate(self, widget, allocation):
        if self.gesture_controller is not None:
            self.gesture_controller.refresh_layout_cache()
            self.gesture_controller.schedule_layout_cache_refresh()
            self.gesture_controller.queue_overlay_draw()
        self.update_suggestion_bar_scale()

    def update_suggestion_bar_scale(self):
        grid_width = self.grid.get_allocated_width() if hasattr(self, "grid") else 0
        grid_height = self.grid.get_allocated_height() if hasattr(self, "grid") else 0
        content_height = (
            self.content_box.get_allocated_height()
            if hasattr(self, "content_box")
            else 0
        )
        win_width, win_height = self.get_size()
        if grid_width <= 1:
            grid_width = max(
                1,
                (win_width or self.width or self.DEFAULT_WINDOW_WIDTH) - 6,
            )
        if content_height <= 1:
            est_win_h = win_height or self.height or self.DEFAULT_WINDOW_HEIGHT
            content_height = max(1, est_win_h - 38)

        num_rows = max(1, len(self.get_active_key_rows()))
        base_grid_height = num_rows * self.BASE_KEY_HEIGHT
        if self.text_prediction_enabled:
            base_total_height = (
                base_grid_height
                + self.BASE_SUGGESTION_HEIGHT
                + self.BASE_SUGGESTION_MARGIN
                + self.BASE_SUGGESTION_MARGIN_BOTTOM
            )
            height_scale = content_height / max(1, base_total_height)
        else:
            effective_grid_h = grid_height if grid_height > 1 else content_height
            height_scale = effective_grid_h / max(1, base_grid_height)

        width_scale = grid_width / max(1, self.BASE_GRID_WIDTH)
        font_scale = min(width_scale, height_scale)

        key_font_size = max(
            6,
            min(42, int(round(self.BASE_KEY_FONT_SIZE * font_scale))),
        )
        secondary_key_font_size = max(
            5,
            min(24, int(round(key_font_size * 0.65))),
        )
        header_font_size = max(
            8,
            min(
                18,
                int(round(self.BASE_HEADER_FONT_SIZE * min(1.15, font_scale))),
            ),
        )
        suggestion_height = max(
            14,
            int(round(self.BASE_SUGGESTION_HEIGHT * height_scale)),
        )
        suggestion_font_size = max(
            7,
            min(32, int(round(self.BASE_SUGGESTION_FONT_SIZE * font_scale))),
        )
        spacing = max(
            1,
            int(round(self.BASE_SUGGESTION_SPACING * font_scale)),
        )
        margin = max(
            1,
            int(round(self.BASE_SUGGESTION_MARGIN * font_scale)),
        )
        margin_bottom = max(
            0,
            int(round(self.BASE_SUGGESTION_MARGIN_BOTTOM * height_scale)),
        )
        quantized_scale = round(font_scale, 2)
        menu_open = (
            hasattr(self, "color_combobox")
            and self.color_combobox.get_visible()
        )
        min_title_w = 480 if menu_open else 320
        show_title = (win_width or grid_width) >= min_title_w

        scale_values = (
            key_font_size,
            secondary_key_font_size,
            header_font_size,
            suggestion_height,
            suggestion_font_size,
            spacing,
            margin,
            margin_bottom,
            quantized_scale,
            show_title,
            self.text_prediction_enabled,
        )

        if scale_values == self._last_suggestion_scale:
            return False

        self._last_suggestion_scale = scale_values
        self.key_font_size = key_font_size
        self.secondary_key_font_size = secondary_key_font_size
        self.header_font_size = header_font_size
        self.suggestion_font_size = suggestion_font_size
        self.layout_scale = quantized_scale

        if hasattr(self, "header_title_label") and self.header_title_label is not None:
            self.header_title_label.set_visible(show_title)

        for h_btn in getattr(self, "header_buttons", []):
            if isinstance(h_btn, ScalableHeaderButton):
                base_w = 54 if h_btn.get_name() == "esc-button" else (
                    52 if h_btn.get_label() in ("Options", "Fn Row") else 36
                )
                h_btn.set_target_size(
                    nat_w=max(14, int(round(base_w * min(1.0, width_scale)))),
                )
                h_btn.queue_resize()

        if hasattr(self, "grid") and self.grid is not None:
            self.grid.set_margin_start(margin)
            self.grid.set_margin_end(margin)
            self.grid.set_margin_bottom(margin)

        if hasattr(self, "suggestion_bar") and self.suggestion_bar is not None:
            self.suggestion_bar.set_spacing(spacing)
            self.suggestion_bar.set_margin_start(margin)
            self.suggestion_bar.set_margin_end(margin)
            self.suggestion_bar.set_margin_top(margin)
            self.suggestion_bar.set_margin_bottom(margin_bottom)

        for button in self.suggestion_buttons:
            if isinstance(button, ScalableSuggestionButton):
                button.set_target_height(suggestion_height)
                button.queue_resize()
            else:
                button.set_size_request(1, suggestion_height)

        self.apply_css()
        if self.gesture_controller is not None:
            self.gesture_controller.schedule_layout_cache_refresh()
        return False

    def on_map_keep_above(self, widget, event):
        self.request_keep_above()
        self._keep_above_retries = 30
        if self._keep_above_timer_id is None:
            self._keep_above_timer_id = GLib.timeout_add(500, self.keep_above_tick)
        return False

    def request_keep_above(self):
        self.set_keep_above(True)
        self.stick()

    def keep_above_tick(self):
        self.request_keep_above()
        self._keep_above_retries -= 1
        if self._keep_above_retries <= 0:
            self._keep_above_timer_id = None
            return False
        return True

    def on_window_state_changed(self, widget, event):
        self.request_keep_above()
        return False

    def create_button(
        self,
        label_="",
        callback=None,
        callback2=None,
        callbacks=0,
        hide_with_menu=True,
    ):
        nat_w = 52 if label_ in ("Options", "Fn Row") else (44 if len(label_) > 1 else 36)
        button = ScalableHeaderButton(
            label=label_,
            min_w=14,
            nat_w=nat_w,
            min_h=14,
            nat_h=28,
        )
        button.set_name("headbar-button")
        if callbacks == 1:
            button.connect("clicked", callback)
        elif callbacks == 2:
            button.connect("clicked", callback, callback2)

        if label_ == self.opacity:
            self.opacity_btn = button
            self.opacity_btn.set_tooltip_text("opacity")

        button.get_style_context().add_class("header-button")
        self.header.pack_end(button)
        self.header_buttons.append(button)
        if hide_with_menu:
            self.buttons.append(button)
        return button

    def change_visibility(self, widget=None):
        for button in self.buttons:
            if button.get_label() != "☰":
                button.set_visible(not button.get_visible())
        self.color_combobox.set_visible(not self.color_combobox.get_visible())
        self._last_suggestion_scale = None
        self.update_suggestion_bar_scale()

    def change_color(self, widget):
        selected_label = self.color_combobox.get_active_text()
        selected_color = self.color_map.get(selected_label)
        if selected_color is not None:
            if selected_color == ONBOARD_BACKGROUND_PRESET:
                self.style_variant = "onboard"
            elif (
                isinstance(selected_color, tuple)
                and len(selected_color) == 2
                and selected_color[0] == ENHANCED_BACKGROUND_PRESET
            ):
                self.style_variant = "enhanced"
                self.bg_color = selected_color[1]
            else:
                self.style_variant = "classic"
                self.bg_color = selected_color

        if self.bg_color in LIGHT_BACKGROUND_COLORS:
            self.text_color = "#1C1C1C"
        else:
            self.text_color = "white"
        self.apply_css()

    def change_opacity(self, widget, increase_opacity):
        if increase_opacity:
            self.opacity = str(round(min(1.0, float(self.opacity) + 0.01), 2))
        else:
            self.opacity = str(round(max(0.0, float(self.opacity) - 0.01), 2))
        self.opacity_btn.set_label(f"{self.opacity}")
        self.apply_css()

    def apply_css(self):
        gnome_specific = ""
        if "GNOME" in DESKTOP_ENV:
            gnome_specific = "background-image: none;"
        theme_opacity = max(0.0, min(1.0, float(self.opacity)))
        command_modifier_rgb = (
            (0, 0, 0)
            if self.style_variant == "classic" and self.bg_color == "255,0,0"
            else (194, 40, 40)
        )

        def rgba(rgb_values, alpha_scale=1.0):
            red, green, blue = rgb_values
            alpha = max(0.0, min(1.0, theme_opacity * alpha_scale))
            return f"rgba({red}, {green}, {blue}, {alpha:.3f})"

        def parse_rgb_value(value):
            try:
                parts = [int(component.strip()) for component in value.split(",")]
                if len(parts) == 3:
                    return tuple(max(0, min(255, component)) for component in parts)
            except (AttributeError, ValueError):
                pass
            return (0, 0, 0)

        def adjust_rgb(rgb_values, amount):
            return tuple(max(0, min(255, component + amount)) for component in rgb_values)

        def rgb_css(rgb_values):
            return f"{rgb_values[0]}, {rgb_values[1]}, {rgb_values[2]}"

        def luminance(rgb_values):
            red, green, blue = rgb_values
            return 0.299 * red + 0.587 * green + 0.114 * blue

        def contrast_text_rgb(rgb_values):
            return (28, 28, 28) if luminance(rgb_values) >= 128 else (255, 255, 255)

        def accent_color(rgb_values):
            red, green, blue = rgb_values
            maximum = max(rgb_values)
            minimum = min(rgb_values)
            if maximum == 0 or (maximum - minimum) / maximum < 0.25:
                return "#000000" if luminance(rgb_values) >= 128 else "#FFFFFF"

            color_range = maximum - minimum
            if maximum == red:
                hue = ((green - blue) / color_range) % 6
            elif maximum == green:
                hue = (blue - red) / color_range + 2
            else:
                hue = (red - green) / color_range + 4
            hue /= 6.0

            sector = int(hue * 6)
            fraction = hue * 6 - sector
            palette = (
                (1, fraction, 0),
                (1 - fraction, 1, 0),
                (0, 1, fraction),
                (0, 1 - fraction, 1),
                (fraction, 0, 1),
                (1, 0, 1 - fraction),
            )
            accent_rgb = palette[sector % 6]
            return "#{:02X}{:02X}{:02X}".format(
                int(accent_rgb[0] * 255),
                int(accent_rgb[1] * 255),
                int(accent_rgb[2] * 255),
            )

        scale = getattr(self, "layout_scale", 1.0)
        window_radius = max(6, min(16, int(round(16 * scale))))
        header_pad_v = 0 if scale < 0.65 else max(1, min(3, int(round(3 * scale))))
        header_pad_h = max(1, min(6, int(round(6 * scale))))
        header_btn_min_w = 0
        header_btn_min_h = 0
        header_btn_pad_v = 0 if scale < 0.7 else 1
        header_btn_pad_h = max(1, int(round(4 * min(1.0, scale))))
        header_btn_margin = 0 if scale < 0.65 else 1
        titlebtn_min_w = 0
        titlebtn_min_h = 0
        esc_min_w = 0
        btn_radius = max(3, min(8, int(round(8 * scale))))
        btn_radius_enhanced = max(3, min(6, int(round(6 * scale))))
        key_radius = max(3, min(8, int(round(8 * scale))))
        key_radius_enhanced = max(3, min(7, int(round(7 * scale))))
        key_padding = 0
        key_margin = 0 if scale < 0.45 else 1
        key_margin_enhanced = key_margin
        combo_padding = 0 if scale < 0.65 else max(1, min(4, int(round(4 * min(1.0, scale)))))
        sugg_pad_v = 0 if scale < 0.65 else (1 if scale < 0.85 else 2)
        sugg_pad_h = max(2, min(8, int(round(8 * min(1.0, scale)))))

        if self.style_variant == "onboard":
            css = f"""
            #vboard-main {{
                background-color: {rgba((18, 24, 33), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((28, 35, 46), 1.0)},
                    {rgba((18, 24, 33), 1.0)}
                );
                border: 1px solid {rgba((7, 11, 18), 0.95)};
                border-radius: {window_radius}px;
                color: {rgba((239, 243, 250), 1.0)};
            }}

            #vboard-main headerbar {{
                background-color: {rgba((31, 39, 53), 0.96)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((52, 61, 78), 0.96)},
                    {rgba((31, 39, 53), 0.96)}
                );
                border: 0px;
                border-bottom: 1px solid {rgba((8, 12, 19), 0.9)};
                box-shadow: none;
                min-height: 0px;
                padding: {header_pad_v}px {header_pad_h}px;
            }}

            #vboard-main headerbar button {{
                min-width: {header_btn_min_w}px;
                min-height: {header_btn_min_h}px;
                padding: {header_btn_pad_v}px {header_btn_pad_h}px;
                border: 1px solid {rgba((13, 21, 33), 1.0)};
                border-radius: {btn_radius}px;
                margin: 0px {header_btn_margin}px;
                color: {rgba((239, 243, 250), 1.0)};
                background-color: {rgba((38, 49, 66), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((69, 80, 101), 1.0)},
                    {rgba((40, 50, 68), 1.0)}
                );
                box-shadow: inset 0 1px {rgba((255, 255, 255), 0.08)};
                {gnome_specific};
            }}

            #vboard-main headerbar .titlebutton {{
                min-width: {titlebtn_min_w}px;
                min-height: {titlebtn_min_h}px;
            }}

            #vboard-main headerbar button:hover,
            #vboard-main #combobox button.combo:hover {{
                background-image: linear-gradient(
                    to bottom,
                    {rgba((81, 94, 118), 1.0)},
                    {rgba((49, 59, 79), 1.0)}
                );
            }}

            #vboard-main headerbar button:active,
            #vboard-main #combobox button.combo:active {{
                background-image: linear-gradient(
                    to bottom,
                    {rgba((41, 51, 68), 1.0)},
                    {rgba((75, 87, 112), 1.0)}
                );
            }}

            #vboard-main headerbar button label {{
                color: {rgba((239, 243, 250), 1.0)};
                font-size: {self.header_font_size}px;
            }}

            #vboard-main headerbar .title {{
                color: {rgba((239, 243, 250), 0.72)};
                font-size: {self.header_font_size}px;
                font-weight: 600;
            }}

            #vboard-main #headbar-button,
            #vboard-main #combobox button.combo {{
                background-color: {rgba((38, 49, 66), 1.0)};
            }}

            #vboard-main #grid button label {{
                color: {rgba((244, 247, 251), 1.0)};
                font-size: {self.key_font_size}px;
                font-weight: 500;
            }}

            #vboard-main #grid button label.key-primary-label {{
                color: {rgba((244, 247, 251), 1.0)};
                font-size: {self.key_font_size}px;
                font-weight: 500;
            }}

            #vboard-main #grid button label.key-secondary-label {{
                color: {rgba((186, 201, 224), 0.82)};
                font-size: {self.secondary_key_font_size}px;
                font-weight: 500;
            }}

            #vboard-main #grid button.media-mode-active label.key-primary-label {{
                color: {rgba((186, 201, 224), 0.55)};
            }}

            #vboard-main #grid button.media-mode-active label.key-secondary-label {{
                color: {rgba((255, 255, 255), 1.0)};
                font-weight: 600;
            }}

            #vboard-main #grid button {{
                min-width: 0px;
                min-height: 0px;
                border: 1px solid {rgba((12, 20, 32), 1.0)};
                border-radius: {key_radius}px;
                background-color: {rgba((48, 58, 76), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((75, 86, 109), 1.0)},
                    {rgba((42, 51, 69), 1.0)}
                );
                padding: {key_padding}px;
                margin: {key_margin}px;
                box-shadow:
                    inset 0 1px {rgba((255, 255, 255), 0.09)},
                    inset 0 -1px {rgba((0, 0, 0), 0.18)},
                    0 1px 2px {rgba((0, 0, 0), 0.25)};
            }}

            #vboard-main button {{
                color: {rgba((239, 243, 250), 1.0)};
            }}

            #vboard-main #grid button:hover {{
                border: 1px solid {rgba((110, 126, 151), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((86, 98, 123), 1.0)},
                    {rgba((50, 60, 81), 1.0)}
                );
            }}

            #vboard-main #grid button:active,
            #vboard-main #grid button:active:hover {{
                border: 1px solid {rgba((141, 164, 196), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((39, 48, 63), 1.0)},
                    {rgba((70, 81, 106), 1.0)}
                );
            }}

            #vboard-main #grid button.active-modifier {{
                border: 1px solid {rgba((138, 163, 200), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((96, 112, 141), 1.0)},
                    {rgba((55, 69, 90), 1.0)}
                );
                {gnome_specific};
            }}

            #vboard-main #grid button.locked-modifier {{
                border: 1px solid {rgba((118, 172, 255), 0.95)};
                background-color: {rgba((34, 52, 78), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((58, 86, 126), 1.0)},
                    {rgba((30, 46, 72), 1.0)}
                );
                box-shadow:
                    inset 0 1px {rgba((255, 255, 255), 0.16)},
                    0 0 3px {rgba((90, 150, 240), 0.4)};
                {gnome_specific};
            }}

            #vboard-main #grid button.locked-modifier label {{
                color: {rgba((240, 246, 255), 1.0)};
            }}

            #vboard-main headerbar button.active-header-toggle {{
                border: 1px solid {rgba((118, 172, 255), 0.9)};
                background-color: {rgba((48, 65, 92), 1.0)};
            }}

            #vboard-main #grid button.active-command-modifier {{
                border: 1px solid {rgba(command_modifier_rgb, 1.0)};
                color: {rgba((247, 248, 251), 1.0)};
                background-color: {rgba(command_modifier_rgb, 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba(command_modifier_rgb, 0.92)},
                    {rgba(command_modifier_rgb, 0.72)}
                );
                {gnome_specific};
            }}

            #vboard-main #grid button.active-command-modifier label {{
                color: {rgba((247, 248, 251), 1.0)};
            }}

            #vboard-main #esc-button {{
                min-width: {esc_min_w}px;
                min-height: {header_btn_min_h}px;
                padding: {header_btn_pad_v}px {header_btn_pad_h}px;
                border: 1px solid {rgba((17, 24, 36), 1.0)};
                border-radius: {btn_radius}px;
                color: {rgba((247, 248, 251), 1.0)};
                background-color: {rgba((51, 64, 89), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((86, 98, 123), 1.0)},
                    {rgba((48, 58, 78), 1.0)}
                );
                box-shadow: inset 0 1px {rgba((255, 255, 255), 0.1)};
            }}

            #vboard-main #esc-button:hover {{
                border: 1px solid {rgba((142, 166, 199), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((97, 112, 139), 1.0)},
                    {rgba((54, 65, 86), 1.0)}
                );
            }}

            #vboard-main tooltip {{
                color: white;
                padding: 5px;
            }}

            #vboard-main #combobox button.combo {{
                min-width: 0px;
                min-height: {header_btn_min_h}px;
                color: {rgba((239, 243, 250), 1.0)};
                padding: {combo_padding}px;
                border: 1px solid {rgba((13, 21, 33), 1.0)};
                border-radius: {btn_radius}px;
                background-image: linear-gradient(
                    to bottom,
                    {rgba((69, 80, 101), 1.0)},
                    {rgba((40, 50, 68), 1.0)}
                );
            }}

            #vboard-main #suggestion-bar {{
                background-color: transparent;
            }}

            #vboard-main #suggestion-button {{
                border: 1px solid {rgba((17, 25, 37), 1.0)};
                border-radius: {btn_radius}px;
                background-color: {rgba((32, 41, 56), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((51, 64, 85), 1.0)},
                    {rgba((32, 41, 56), 1.0)}
                );
                min-width: 0px;
                min-height: 0px;
                padding: {sugg_pad_v}px {sugg_pad_h}px;
                box-shadow: inset 0 1px {rgba((255, 255, 255), 0.06)};
            }}

            #vboard-main #suggestion-button label,
            #vboard-main #suggestion-button:disabled label {{
                color: {rgba((216, 223, 234), 1.0)};
                font-size: {self.suggestion_font_size}px;
            }}

            #vboard-main #suggestion-button.has-suggestion {{
                border: 1px solid {rgba((37, 49, 68), 1.0)};
            }}

            #vboard-main #suggestion-button.has-suggestion:hover {{
                border: 1px solid {rgba((115, 130, 154), 1.0)};
                background-image: linear-gradient(
                    to bottom,
                    {rgba((59, 73, 96), 1.0)},
                    {rgba((38, 49, 68), 1.0)}
                );
            }}
            """
        elif self.style_variant == "enhanced":
            base_rgb = parse_rgb_value(self.bg_color)
            window_rgb = adjust_rgb(base_rgb, -40)
            header_rgb = adjust_rgb(base_rgb, -18)
            key_rgb = adjust_rgb(base_rgb, 30)
            hover_rgb = adjust_rgb(base_rgb, 48)
            pressed_rgb = adjust_rgb(base_rgb, 78)
            suggestion_rgb = adjust_rgb(base_rgb, 18)
            text_rgb = contrast_text_rgb(key_rgb)
            accent = accent_color(base_rgb)
            css = f"""
            #vboard-main {{
                background-color: {rgba(window_rgb, 1.0)};
                color: rgb({rgb_css(text_rgb)});
            }}

            #vboard-main headerbar {{
                background-color: {rgba(header_rgb, 1.0)};
                border: 0px;
                box-shadow: none;
                min-height: 0px;
                padding: {header_pad_v}px {header_pad_h}px;
            }}

            #vboard-main headerbar button {{
                min-width: {header_btn_min_w}px;
                min-height: {header_btn_min_h}px;
                padding: {header_btn_pad_v}px {header_btn_pad_h}px;
                border: 1px solid transparent;
                border-radius: {btn_radius_enhanced}px;
                margin: 0px {header_btn_margin}px;
                color: rgb({rgb_css(text_rgb)});
                background-color: transparent;
                background-image: none;
                {gnome_specific};
            }}

            #vboard-main headerbar .titlebutton {{
                min-width: {titlebtn_min_w}px;
                min-height: {titlebtn_min_h}px;
            }}

            #vboard-main headerbar button:hover,
            #vboard-main #combobox button.combo:hover {{
                border: 1px solid {accent};
                background-color: {rgba(key_rgb, 0.85)};
                background-image: none;
            }}

            #vboard-main headerbar button:active,
            #vboard-main #combobox button.combo:active {{
                border: 1px solid rgb({rgb_css(text_rgb)});
                background-color: {rgba(pressed_rgb, 1.0)};
                background-image: none;
            }}

            #vboard-main headerbar button label,
            #vboard-main headerbar .title {{
                color: rgb({rgb_css(text_rgb)});
                font-size: {self.header_font_size}px;
            }}

            #vboard-main #headbar-button,
            #vboard-main #combobox button.combo {{
                background-image: none;
            }}

            #vboard-main #grid button label {{
                color: rgb({rgb_css(text_rgb)});
                font-size: {self.key_font_size}px;
                font-weight: 500;
            }}

            #vboard-main #grid button label.key-primary-label {{
                color: rgb({rgb_css(text_rgb)});
                font-size: {self.key_font_size}px;
                font-weight: 500;
            }}

            #vboard-main #grid button label.key-secondary-label {{
                color: rgb({rgb_css(text_rgb)});
                opacity: 0.72;
                font-size: {self.secondary_key_font_size}px;
                font-weight: 500;
            }}

            #vboard-main #grid button.media-mode-active label.key-primary-label {{
                opacity: 0.55;
            }}

            #vboard-main #grid button.media-mode-active label.key-secondary-label {{
                color: {accent};
                opacity: 1.0;
                font-weight: 600;
            }}

            #vboard-main #grid button {{
                min-width: 0px;
                min-height: 0px;
                border: 1px solid transparent;
                border-radius: {key_radius_enhanced}px;
                background-color: {rgba(key_rgb, 1.0)};
                background-image: none;
                padding: {key_padding}px;
                margin: {key_margin_enhanced}px;
                {gnome_specific};
            }}

            #vboard-main button {{
                background-color: transparent;
                color: rgb({rgb_css(text_rgb)});
            }}

            #vboard-main #grid button:hover {{
                border: 1px solid {accent};
                background-color: {rgba(hover_rgb, 1.0)};
            }}

            #vboard-main #grid button:active,
            #vboard-main #grid button:active:hover {{
                border: 1px solid rgb({rgb_css(text_rgb)});
                background-color: {rgba(pressed_rgb, 1.0)};
            }}

            #vboard-main #grid button.active-modifier {{
                border: 1px solid {accent};
                background-color: {rgba(pressed_rgb, 1.0)};
                {gnome_specific};
            }}

            #vboard-main #grid button.locked-modifier {{
                border: 1px solid {accent};
                background-color: {rgba(pressed_rgb, 1.0)};
                {gnome_specific};
            }}

            #vboard-main headerbar button.active-header-toggle {{
                border: 1px solid {accent};
                background-color: {rgba(key_rgb, 0.9)};
            }}

            #vboard-main #grid button.active-command-modifier {{
                border: 1px solid {rgba(command_modifier_rgb, 1.0)};
                color: white;
                background-color: {rgba(command_modifier_rgb, 1.0)};
                background-image: none;
                {gnome_specific};
            }}

            #vboard-main #grid button.active-command-modifier label {{
                color: white;
            }}

            #vboard-main #esc-button {{
                min-width: {esc_min_w}px;
                min-height: {header_btn_min_h}px;
                padding: {header_btn_pad_v}px {header_btn_pad_h}px;
                border: 1px solid transparent;
                border-radius: {btn_radius_enhanced}px;
                color: rgb({rgb_css(text_rgb)});
                background-color: {rgba(key_rgb, 1.0)};
                background-image: none;
            }}

            #vboard-main #esc-button:hover {{
                border: 1px solid {accent};
                background-color: {rgba(hover_rgb, 1.0)};
            }}

            #vboard-main tooltip {{
                color: white;
                padding: 5px;
            }}

            #vboard-main #combobox button.combo {{
                min-width: 0px;
                min-height: {header_btn_min_h}px;
                color: rgb({rgb_css(text_rgb)});
                padding: {combo_padding}px;
                border: 1px solid transparent;
                border-radius: {btn_radius_enhanced}px;
                background-color: transparent;
                background-image: none;
            }}

            #vboard-main #suggestion-bar {{
                background-color: transparent;
            }}

            #vboard-main #suggestion-button {{
                border: 1px solid transparent;
                border-radius: {btn_radius_enhanced}px;
                background-color: {rgba(suggestion_rgb, 1.0)};
                background-image: none;
                min-width: 0px;
                min-height: 0px;
                padding: {sugg_pad_v}px {sugg_pad_h}px;
            }}

            #vboard-main #suggestion-button label,
            #vboard-main #suggestion-button:disabled label {{
                color: rgb({rgb_css(text_rgb)});
                font-size: {self.suggestion_font_size}px;
            }}

            #vboard-main #suggestion-button.has-suggestion {{
                border: 1px solid rgb({rgb_css(text_rgb)});
            }}

            #vboard-main #suggestion-button.has-suggestion:hover {{
                border: 1px solid {accent};
                background-color: {rgba(hover_rgb, 1.0)};
            }}
            """
        else:
            css = f"""
            #vboard-main {{
                background-color: rgba({self.bg_color}, {self.opacity});
            }}

            #vboard-main headerbar {{
                background-color: rgba({self.bg_color}, {self.opacity});
                border: 0px;
                box-shadow: none;
                min-height: 0px;
                padding: {header_pad_v}px {header_pad_h}px;
            }}

            #vboard-main headerbar button {{
                min-width: {header_btn_min_w}px;
                min-height: {header_btn_min_h}px;
                padding: {header_btn_pad_v}px {header_btn_pad_h}px;
                border: 0px;
                margin: 0px;
                {gnome_specific}
            }}

            #vboard-main headerbar .titlebutton {{
                min-width: {titlebtn_min_w}px;
                min-height: {titlebtn_min_h}px;
            }}

            #vboard-main headerbar button label,
            #vboard-main headerbar .title {{
                color: {self.text_color};
                font-size: {self.header_font_size}px;
            }}

            #vboard-main #headbar-button,
            #vboard-main #combobox button.combo {{
                background-image: none;
            }}

            #vboard-main #grid button label {{
                color: {self.text_color};
                font-size: {self.key_font_size}px;
            }}

            #vboard-main #grid button label.key-primary-label {{
                color: {self.text_color};
                font-size: {self.key_font_size}px;
            }}

            #vboard-main #grid button label.key-secondary-label {{
                color: {self.text_color};
                opacity: 0.72;
                font-size: {self.secondary_key_font_size}px;
            }}

            #vboard-main #grid button.media-mode-active label.key-primary-label {{
                opacity: 0.55;
            }}

            #vboard-main #grid button.media-mode-active label.key-secondary-label {{
                color: #00CACB;
                opacity: 1.0;
                font-weight: bold;
            }}

            #vboard-main #grid button {{
                min-width: 0px;
                min-height: 0px;
                border: 1px solid {self.text_color};
                background-image: none;
                padding: {key_padding}px;
                margin: {key_margin}px;
            }}

            #vboard-main button {{
                background-color: transparent;
                color: {self.text_color};
            }}

            #vboard-main #grid button:hover {{
                border: 1px solid #00CACB;
            }}

            #vboard-main #grid button.pressed,
            #vboard-main #grid button.pressed:hover {{
                border: 1px solid {self.text_color};
            }}

            #vboard-main #grid button.active-modifier {{
                border: 1px solid #00CACB;
                {gnome_specific}
            }}

            #vboard-main #grid button.locked-modifier {{
                border: 1px solid #00CACB;
                background-color: rgba({self.bg_color}, 0.5);
                {gnome_specific}
            }}

            #vboard-main headerbar button.active-header-toggle {{
                border: 1px solid #00CACB;
            }}

            #vboard-main #grid button.active-command-modifier {{
                border: 1px solid rgb{command_modifier_rgb};
                color: white;
                background-color: {rgba(command_modifier_rgb, 1.0)};
                background-image: none;
                {gnome_specific}
            }}

            #vboard-main #grid button.active-command-modifier label {{
                color: white;
            }}

            #vboard-main #esc-button {{
                min-width: {esc_min_w}px;
                min-height: {header_btn_min_h}px;
                padding: {header_btn_pad_v}px {header_btn_pad_h}px;
                border: 1px solid {self.text_color};
                background-image: none;
            }}

            #vboard-main #esc-button:hover {{
                border: 1px solid #00CACB;
            }}

            #vboard-main tooltip {{
                color: white;
                padding: 5px;
            }}

            #vboard-main #combobox button.combo {{
                min-width: 0px;
                min-height: {header_btn_min_h}px;
                color: {self.text_color};
                padding: {combo_padding}px;
            }}

            #vboard-main #suggestion-bar {{
                background-color: transparent;
            }}

            #vboard-main #suggestion-button {{
                border: 1px solid transparent;
                background-image: none;
                min-width: 0px;
                min-height: 0px;
                padding: {sugg_pad_v}px {sugg_pad_h}px;
            }}

            #vboard-main #suggestion-button label,
            #vboard-main #suggestion-button:disabled label {{
                color: {self.text_color};
                font-size: {self.suggestion_font_size}px;
            }}

            #vboard-main #suggestion-button.has-suggestion {{
                border: 1px solid {self.text_color};
            }}

            #vboard-main #suggestion-button.has-suggestion:hover {{
                border: 1px solid #00CACB;
            }}
            """

        try:
            self.css_provider.load_from_data(css.encode("utf-8"))
        except GLib.GError as exc:
            print(f"CSS Error: {exc.message}")
            return

        screen = self.get_screen()
        if screen is not None and not self._css_provider_registered:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                self.css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_USER,
            )
            self._css_provider_registered = True

    def create_row(self, grid, row_index, keys):
        col = 0

        for key_event in keys:
            if key_event in FUNCTION_ROW_KEYS:
                button = ScalableKeyButton(key_event=key_event)
                vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                vbox.set_halign(Gtk.Align.CENTER)
                vbox.set_valign(Gtk.Align.CENTER)

                primary_label = Gtk.Label()
                primary_label.get_style_context().add_class("key-primary-label")
                secondary_label = Gtk.Label()
                secondary_label.get_style_context().add_class("key-secondary-label")

                vbox.pack_start(primary_label, True, True, 0)
                vbox.pack_start(secondary_label, False, False, 0)
                button.add(vbox)
                button.primary_label = primary_label
                button.secondary_label = secondary_label
            else:
                button = ScalableKeyButton(key_event=key_event)
                button.set_label(self.get_button_label(key_event))

            button.set_hexpand(True)
            button.set_vexpand(True)
            button.add_events(
                Gdk.EventMask.BUTTON_PRESS_MASK
                | Gdk.EventMask.BUTTON_RELEASE_MASK
                | Gdk.EventMask.POINTER_MOTION_MASK
            )
            button.connect("button-press-event", self.on_key_button_press_event, key_event)
            button.connect("motion-notify-event", self.on_key_button_motion_event, key_event)
            button.connect("button-release-event", self.on_key_button_release_event, key_event)
            self.key_buttons[key_event] = button
            if key_event in self.modifiers:
                self.modifier_buttons[key_event] = button

            width = KEY_WIDTHS.get(key_event, 2)

            grid.attach(button, col, row_index, width, 1)
            col += width

        self.update_key_labels()

    def get_button_label(self, key_event):
        if key_event == "CapsLock":
            return "Caps"

        if key_event == "Fn":
            return "Fn"

        if key_event in MODIFIER_KEYS:
            return key_event[:-2]

        key_labels = self.get_active_key_labels()
        shifted_map = self.get_active_shifted_map()
        shift_active = self.modifiers["Shift_L"] or self.modifiers["Shift_R"]
        key_label = key_labels.get(key_event, key_event)

        if len(key_label) == 1 and key_label.isalpha():
            uppercase_active = shift_active != self.caps_lock_active
            return key_label.upper() if uppercase_active else key_label.lower()

        if shift_active and key_event in shifted_map:
            return shifted_map[key_event]

        return key_label

    def update_key_labels(self):
        send_f_keys = bool(getattr(self, "fn_locked", True))
        for key_event, button in self.key_buttons.items():
            if key_event in FUNCTION_ROW_KEYS:
                if key_event == "Fn":
                    sec_label = "LOCK" if getattr(self, "fn_locked", True) else "MEDIA"
                    if isinstance(button, ScalableKeyButton):
                        button.set_dual_labels("Fn", sec_label)
                    else:
                        button.set_label("Fn")

                    style_context = button.get_style_context()
                    style_context.remove_class("active-modifier")
                    style_context.remove_class("active-command-modifier")
                    style_context.remove_class("locked-modifier")
                    if getattr(self, "fn_locked", True):
                        style_context.add_class("locked-modifier")
                else:
                    sec_info = FUNCTION_KEY_SECONDARY_ACTIONS.get(key_event)
                    sec_label = sec_info["label"] if sec_info else ""
                    if isinstance(button, ScalableKeyButton):
                        button.set_dual_labels(key_event, sec_label)
                    else:
                        button.set_label(key_event)

                    style_context = button.get_style_context()
                    if not send_f_keys and sec_info:
                        style_context.add_class("media-mode-active")
                    else:
                        style_context.remove_class("media-mode-active")
            else:
                button.set_label(self.get_button_label(key_event))

    def update_modifier(self, key_event, value):
        self.modifiers[key_event] = value
        button = self.modifier_buttons.get(key_event)
        if button is None:
            return
        style_context = button.get_style_context()
        modifier_class = (
            "active-command-modifier"
            if key_event.startswith(("Shift", "Ctrl", "Alt"))
            else "active-modifier"
        )
        style_context.remove_class("active-modifier")
        style_context.remove_class("active-command-modifier")
        if value:
            style_context.add_class(modifier_class)

    def set_caps_lock_active(self, active, update_system=True):
        active = bool(active)
        if update_system and active != self.caps_lock_active:
            empty_modifiers = {modifier: False for modifier in MODIFIER_KEYS}
            if self.gesture_controller is not None:
                self.gesture_controller.note_non_gesture_key()
            self.backend.emit_key("CapsLock", empty_modifiers)

        if active == self.caps_lock_active:
            return

        self.caps_lock_active = active
        button = self.key_buttons.get("CapsLock")
        if button is not None:
            style_context = button.get_style_context()
            style_context.remove_class("active-modifier")
            style_context.remove_class("active-command-modifier")
            if active:
                style_context.add_class("active-command-modifier")
        self.update_key_labels()

    def toggle_caps_lock(self):
        self.set_caps_lock_active(not self.caps_lock_active)
        self.current_word = ""
        self.update_suggestions()

    def on_key_button_press_event(self, widget, event, key_event):
        if event.type in (Gdk.EventType._2BUTTON_PRESS, Gdk.EventType._3BUTTON_PRESS):
            return True

        self.stop_key_repeat()
        self.clear_suggestion_override(update=False)

        if event.button == 3:
            if key_event not in self.modifiers:
                self.emit_shifted_key(key_event)
            return True

        if event.button != 1:
            return False

        if key_event == "CapsLock":
            self.toggle_caps_lock()
            self.reset_modifiers()
            return False

        if key_event == "Fn":
            self.fn_locked = not getattr(self, "fn_locked", True)
            self.save_settings()
            self.update_key_labels()
            return False

        if key_event in self.modifiers:
            self.update_modifier(key_event, not self.modifiers[key_event])

            if self.modifiers["Shift_L"] and self.modifiers["Shift_R"]:
                self.update_modifier("Shift_L", False)
                self.update_modifier("Shift_R", False)

            self.update_key_labels()
            return False

        if key_event in FUNCTION_ROW_KEYS:
            send_f_keys = bool(getattr(self, "fn_locked", True))
            if not send_f_keys and key_event in FUNCTION_KEY_SECONDARY_ACTIONS:
                target_key = FUNCTION_KEY_SECONDARY_ACTIONS[key_event]["action"]
            else:
                target_key = key_event
            self.emit_key(target_key)
            self.delay_source = GLib.timeout_add(400, self.start_repeat, target_key)
            return False

        if self.gesture_controller is not None and self.gesture_controller.handle_key_press(
            widget,
            event,
            key_event,
        ):
            return False

        self.emit_key(key_event)
        self.delay_source = GLib.timeout_add(400, self.start_repeat, key_event)
        return False

    def on_key_button_motion_event(self, widget, event, key_event):
        if self.gesture_controller is not None:
            self.gesture_controller.handle_key_motion(widget, event)
        return False

    def on_key_button_release_event(self, widget, event, key_event):
        if event.button != 1:
            return False

        if self.gesture_controller is not None and self.gesture_controller.handle_key_release(
            widget,
            event,
            key_event,
        ):
            return False

        self.stop_key_repeat()
        return False

    def stop_key_repeat(self):
        if hasattr(self, "delay_source"):
            GLib.source_remove(self.delay_source)
            del self.delay_source
        if hasattr(self, "repeat_source"):
            GLib.source_remove(self.repeat_source)
            del self.repeat_source

    def start_repeat(self, key_event):
        self.repeat_source = GLib.timeout_add(100, self.repeat_key, key_event)
        return False

    def repeat_key(self, key_event):
        self.emit_key(key_event)
        return True

    def emit_shifted_key(self, key_event):
        modifiers = dict(self.modifiers)
        modifiers["Shift_L"] = True
        self.emit_key(key_event, modifiers)

    def emit_key(self, key_event, modifiers=None):
        active_modifiers = self.modifiers if modifiers is None else modifiers
        if self.gesture_controller is not None:
            self.gesture_controller.note_non_gesture_key()
        self.track_current_word(key_event, active_modifiers)
        self.backend.emit_key(key_event, active_modifiers)
        self.reset_modifiers()

    def emit_text(self, text):
        for char in text:
            key_event, modifiers = self.character_to_key_event(char)
            if key_event is None:
                continue
            self.backend.emit_key(key_event, modifiers)

    def reset_modifiers(self):
        for mod_key, active in self.modifiers.items():
            if active:
                self.update_modifier(mod_key, False)
        self.update_key_labels()

    def clear_suggestion_override(self, update=False):
        has_gesture_commit = (
            self.gesture_controller is not None and self.gesture_controller.has_committed_text()
        )
        if self.suggestion_override is None and not has_gesture_commit:
            return

        self.suggestion_override = None
        if self.gesture_controller is not None:
            self.gesture_controller.clear_committed_text()
        if update:
            self.update_suggestions()

    def track_current_word(self, key_event, modifiers=None):
        active_modifiers = self.modifiers if modifiers is None else modifiers
        self.clear_suggestion_override(update=False)

        if not self.text_prediction_enabled:
            self.current_word = ""
            return

        if self.has_active_command_modifier(active_modifiers):
            self.current_word = ""
            self.update_suggestions()
            return

        if key_event == "Backspace":
            self.current_word = self.current_word[:-1]
            self.update_suggestions()
            return

        if (
            key_event in {"Space", "Tab", "Enter", "Esc", "CapsLock", "←", "→", "↑", "↓"}
            or key_event in FUNCTION_ROW_KEYS
            or key_event
            in {
                "Mute",
                "VolumeDown",
                "VolumeUp",
                "MicMute",
                "BrightnessDown",
                "BrightnessUp",
                "PreviousSong",
                "PlayPause",
                "NextSong",
            }
        ):
            self.current_word = ""
            self.update_suggestions()
            return

        typed_char = self.key_event_to_character(key_event, active_modifiers)
        if typed_char and all(char.isalpha() or char in {"'", "-"} for char in typed_char):
            self.current_word += typed_char
        else:
            self.current_word = ""

        self.update_suggestions()

    def has_active_command_modifier(self, modifiers=None):
        active_modifiers = self.modifiers if modifiers is None else modifiers
        return any(active_modifiers[modifier] for modifier in COMMAND_MODIFIER_KEYS)

    def key_event_to_character(self, key_event, modifiers=None):
        active_modifiers = self.modifiers if modifiers is None else modifiers
        shift_active = active_modifiers["Shift_L"] or active_modifiers["Shift_R"]
        key_labels = self.get_active_key_labels()
        shifted_map = self.get_active_shifted_map()
        key_label = key_labels.get(key_event, key_event)

        if len(key_label) == 1 and key_label.isalpha():
            uppercase_active = shift_active != self.caps_lock_active
            return key_label.upper() if uppercase_active else key_label.lower()

        if shift_active and key_event in shifted_map:
            return shifted_map[key_event]

        if len(key_label) == 1:
            return key_label

        return None

    def update_suggestions(self):
        if not self.text_prediction_enabled:
            suggestions = []
        elif self.suggestion_override is not None:
            suggestions = self.suggestion_override
        else:
            suggestions = self.suggestion_engine.get_suggestions(
                self.current_word,
                SUGGESTION_LIMIT,
            )

        for index, button in enumerate(self.suggestion_buttons):
            style_context = button.get_style_context()
            if index < len(suggestions):
                label = suggestions[index]
                if self.suggestion_override is None:
                    label = self.apply_suggestion_case(label)
                button.set_label(label)
                button.set_sensitive(True)
                style_context.add_class("has-suggestion")
            else:
                button.set_label(" ")
                button.set_sensitive(False)
                style_context.remove_class("has-suggestion")
            button.show()

        self.suggestion_revealer.set_reveal_child(self.text_prediction_enabled)

    def apply_suggestion_case(self, suggestion):
        if self.current_word.isupper():
            return suggestion.upper()
        if self.current_word[:1].isupper() and self.current_word[1:].islower():
            return suggestion.capitalize()
        return suggestion

    def on_suggestion_clicked(self, widget):
        suggestion = widget.get_label().strip()
        if not suggestion:
            return

        if (
            self.gesture_controller is not None
            and self.suggestion_override is not None
            and self.gesture_controller.has_committed_text()
        ):
            self.gesture_controller.replace_committed_word(suggestion)
            return

        if not self.current_word:
            return

        completion = suggestion[len(self.current_word):]
        if not completion:
            return

        for modifier in MODIFIER_KEYS:
            if self.modifiers[modifier]:
                self.update_modifier(modifier, False)

        for char in completion:
            key_event, modifiers = self.character_to_key_event(char)
            if key_event is None:
                continue
            self.backend.emit_key(key_event, modifiers)

        self.current_word = suggestion
        self.update_suggestions()

    def character_to_key_event(self, char):
        modifiers = {modifier: False for modifier in MODIFIER_KEYS}

        if char == " ":
            return "Space", modifiers

        key_event_with_shift = self.layout_character_lookup.get(char)
        if key_event_with_shift is not None:
            key_event, needs_shift = key_event_with_shift
            if self.caps_lock_active and char.isalpha():
                needs_shift = not needs_shift
            if needs_shift:
                modifiers["Shift_L"] = True
            return key_event, modifiers

        return None, modifiers

    def read_settings(self):
        try:
            os.makedirs(self.CONFIG_DIR, exist_ok=True)
        except PermissionError:
            print("Warning: No permission to create the config directory. Proceeding without it.")

        try:
            if os.path.exists(self.CONFIG_FILE):
                self.config.read(self.CONFIG_FILE)
                self.bg_color = self.config.get(
                    "DEFAULT", "bg_color", fallback=self.bg_color
                ).replace(" ", "")
                self.opacity = self.config.get(
                    "DEFAULT", "opacity", fallback=self.opacity
                )
                self.text_color = self.config.get("DEFAULT", "text_color", fallback="white")
                self.style_variant = self.config.get(
                    "DEFAULT", "style_variant", fallback="classic"
                )
                self.gesture_enabled = self.config.getboolean(
                    "DEFAULT", "gesture_enabled", fallback=True
                )
                self.gesture_visual_feedback_enabled = self.config.getboolean(
                    "DEFAULT",
                    "gesture_visual_feedback_enabled",
                    fallback=True,
                )
                self.text_prediction_enabled = self.config.getboolean(
                    "DEFAULT",
                    "text_prediction_enabled",
                    fallback=True,
                )
                self.start_minimized = self.config.getboolean(
                    "DEFAULT",
                    "start_minimized",
                    fallback=False,
                )
                self.keyboard_layout = self.normalize_keyboard_layout(
                    self.config.get(
                        "DEFAULT",
                        "keyboard_layout",
                        fallback=DEFAULT_KEYBOARD_LAYOUT,
                    )
                )
                self.show_function_row = self.config.getboolean(
                    "DEFAULT",
                    "show_function_row",
                    fallback=True,
                )
                self.fn_locked = self.config.getboolean(
                    "DEFAULT",
                    "fn_locked",
                    fallback=True,
                )
                width_raw = self.config.get("DEFAULT", "width", fallback="0")
                height_raw = self.config.get("DEFAULT", "height", fallback="0")
                self.width, self.height = self.validate_window_size(
                    width_raw, height_raw
                )
                pos_x_str = self.config.get("DEFAULT", "pos_x", fallback="0")
                pos_y_str = self.config.get("DEFAULT", "pos_y", fallback="0")
                try:
                    self.pos_x = int(pos_x_str)
                    self.pos_y = int(pos_y_str)
                    self.config_pos_x = self.pos_x
                    self.config_pos_y = self.pos_y
                except ValueError:
                    self.pos_x = self.config_pos_x = 0
                    self.pos_y = self.config_pos_y = 0

        except (configparser.Error, ValueError) as exc:
            print(f"Warning: Could not read config file ({exc}). Using default values.")
            self.width, self.height = self.validate_window_size(0, 0)

    def save_settings(self):
        self.cancel_scheduled_save_settings()
        if self.get_visible():
            current_w, current_h = self.get_size()
            if current_w > 0 and current_h > 0:
                self.width, self.height = self.validate_window_size(
                    current_w, current_h
                )
        self.width, self.height = self.validate_window_size(
            self.width, self.height
        )
        self.config["DEFAULT"] = {
            "bg_color": self.bg_color,
            "opacity": self.opacity,
            "text_color": self.text_color,
            "style_variant": self.style_variant,
            "text_prediction_enabled": str(self.text_prediction_enabled),
            "start_minimized": str(self.start_minimized),
            "gesture_enabled": str(self.gesture_enabled),
            "gesture_visual_feedback_enabled": str(
                self.gesture_visual_feedback_enabled
            ),
            "show_function_row": str(self.show_function_row),
            "fn_locked": str(self.fn_locked),
            "keyboard_layout": self.keyboard_layout,
            "width": str(self.width),
            "height": str(self.height),
            "pos_x": str(self.pos_x),
            "pos_y": str(self.pos_y),
        }

        try:
            with open(self.CONFIG_FILE, "w") as configfile:
                self.config.write(configfile)
        except (configparser.Error, IOError) as exc:
            print(f"Warning: Could not write to config file ({exc}). Changes will not be saved.")

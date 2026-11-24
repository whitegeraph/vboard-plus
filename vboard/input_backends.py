import atexit
import sys
import time

from .constants import MAX_KEY_HOLD_SECONDS, MODIFIER_KEYS, TAP_ONLY_ACTION_KEYS

try:
    import uinput
except ImportError:
    uinput = None

try:
    import evdev
except ImportError:
    evdev = None


KEY_NAME_MAP = {
    "Esc": ("KEY_ESC",),
    "1": ("KEY_1",),
    "2": ("KEY_2",),
    "3": ("KEY_3",),
    "4": ("KEY_4",),
    "5": ("KEY_5",),
    "6": ("KEY_6",),
    "7": ("KEY_7",),
    "8": ("KEY_8",),
    "9": ("KEY_9",),
    "0": ("KEY_0",),
    "-": ("KEY_MINUS",),
    "=": ("KEY_EQUAL",),
    "Backspace": ("KEY_BACKSPACE",),
    "Tab": ("KEY_TAB",),
    "Q": ("KEY_Q",),
    "W": ("KEY_W",),
    "E": ("KEY_E",),
    "R": ("KEY_R",),
    "T": ("KEY_T",),
    "Y": ("KEY_Y",),
    "U": ("KEY_U",),
    "I": ("KEY_I",),
    "O": ("KEY_O",),
    "P": ("KEY_P",),
    "[": ("KEY_LEFTBRACE",),
    "]": ("KEY_RIGHTBRACE",),
    "Enter": ("KEY_ENTER",),
    "Ctrl_L": ("KEY_LEFTCTRL",),
    "Ctrl_R": ("KEY_RIGHTCTRL",),
    "A": ("KEY_A",),
    "S": ("KEY_S",),
    "D": ("KEY_D",),
    "F": ("KEY_F",),
    "G": ("KEY_G",),
    "H": ("KEY_H",),
    "J": ("KEY_J",),
    "K": ("KEY_K",),
    "L": ("KEY_L",),
    ";": ("KEY_SEMICOLON",),
    "'": ("KEY_APOSTROPHE",),
    "`": ("KEY_GRAVE",),
    "Shift_L": ("KEY_LEFTSHIFT",),
    "Shift_R": ("KEY_RIGHTSHIFT",),
    "\\": ("KEY_BACKSLASH",),
    "Z": ("KEY_Z",),
    "X": ("KEY_X",),
    "C": ("KEY_C",),
    "V": ("KEY_V",),
    "B": ("KEY_B",),
    "N": ("KEY_N",),
    "M": ("KEY_M",),
    ",": ("KEY_COMMA",),
    ".": ("KEY_DOT",),
    "/": ("KEY_SLASH",),
    "Alt_L": ("KEY_LEFTALT",),
    "Alt_R": ("KEY_RIGHTALT",),
    "Space": ("KEY_SPACE",),
    "CapsLock": ("KEY_CAPSLOCK",),
    "→": ("KEY_RIGHT",),
    "←": ("KEY_LEFT",),
    "↓": ("KEY_DOWN",),
    "↑": ("KEY_UP",),
    "Super_L": ("KEY_LEFTMETA",),
    "Super_R": ("KEY_RIGHTMETA",),
    "F1": ("KEY_F1",),
    "F2": ("KEY_F2",),
    "F3": ("KEY_F3",),
    "F4": ("KEY_F4",),
    "F5": ("KEY_F5",),
    "F6": ("KEY_F6",),
    "F7": ("KEY_F7",),
    "F8": ("KEY_F8",),
    "F9": ("KEY_F9",),
    "F10": ("KEY_F10",),
    "F11": ("KEY_F11",),
    "F12": ("KEY_F12",),
    "Mute": ("KEY_MUTE",),
    "VolumeDown": ("KEY_VOLUMEDOWN",),
    "VolumeUp": ("KEY_VOLUMEUP",),
    "MicMute": ("KEY_MICMUTE",),
    "BrightnessDown": ("KEY_BRIGHTNESSDOWN",),
    "BrightnessUp": ("KEY_BRIGHTNESSUP",),
    "PreviousSong": ("KEY_PREVIOUSSONG",),
    "PlayPause": ("KEY_PLAYPAUSE",),
    "NextSong": ("KEY_NEXTSONG",),
    "PrtSc": ("KEY_SYSRQ", "KEY_PRINT"),
    "Delete": ("KEY_DELETE",),
    "Insert": ("KEY_INSERT",),
    "Home": ("KEY_HOME",),
    "End": ("KEY_END",),
}

OPTIONAL_KEY_NAME_MAP = {
    "<": ("KEY_LESS", "KEY_102ND"),
}


class InputBackend:
    name = "unknown"

    def emit_key(self, key_label, modifiers):
        raise NotImplementedError

    def release_all_keys(self):
        pass

    def check_stuck_keys(self, max_hold_seconds=MAX_KEY_HOLD_SECONDS):
        pass

    def destroy(self):
        pass


class NullInputBackend(InputBackend):
    name = "disabled"

    def __init__(self, reason=None):
        self.reason = reason
        if reason:
            print(f"Warning: {reason}")

    def emit_key(self, key_label, modifiers):
        return

    def release_all_keys(self):
        return

    def check_stuck_keys(self, max_hold_seconds=MAX_KEY_HOLD_SECONDS):
        return

    def destroy(self):
        return


class _BaseUInputBackend(InputBackend):
    def _install_excepthook(self):
        old_hook = sys.excepthook

        def _hook(exc_type, exc_value, exc_traceback):
            try:
                self.release_all_keys()
            except Exception:
                pass
            if old_hook:
                old_hook(exc_type, exc_value, exc_traceback)

        sys.excepthook = _hook

    def _emit_raw(self, key_event, value, syn=True):
        raise NotImplementedError

    def _press_key(self, key_event, syn=True):
        self._emit_raw(key_event, 1, syn=syn)
        self.pressed_keys[key_event] = time.monotonic()

    def _release_key(self, key_event, syn=True):
        try:
            self._emit_raw(key_event, 0, syn=syn)
        finally:
            self.pressed_keys.pop(key_event, None)

    def release_all_keys(self):
        for key_event in list(self.pressed_keys.keys()):
            try:
                self._emit_raw(key_event, 0, syn=True)
            except Exception:
                pass
            finally:
                self.pressed_keys.pop(key_event, None)

    def check_stuck_keys(self, max_hold_seconds=MAX_KEY_HOLD_SECONDS):
        now = time.monotonic()
        stuck = [
            k for k, t in list(self.pressed_keys.items())
            if now - t >= max_hold_seconds
        ]
        for key_event in stuck:
            try:
                self._emit_raw(key_event, 0, syn=True)
            except Exception:
                pass
            finally:
                self.pressed_keys.pop(key_event, None)

    def emit_key(self, key_label, modifiers):
        key_event = self.key_map.get(key_label)
        if key_event is None:
            return

        applied_mods = []
        try:
            for mod_key in self.modifier_order:
                if modifiers.get(mod_key, False):
                    mod_event = self.key_map[mod_key]
                    self._press_key(mod_event, syn=False)
                    applied_mods.append(mod_event)

            self._press_key(key_event, syn=True)
            if key_label in TAP_ONLY_ACTION_KEYS:
                time.sleep(0.015)
            self._release_key(key_event, syn=True)
        finally:
            for mod_event in reversed(applied_mods):
                try:
                    self._release_key(mod_event, syn=True)
                except Exception:
                    pass


class UInputBackend(_BaseUInputBackend):
    name = "uinput"

    def __init__(self):
        if uinput is None:
            raise RuntimeError("python-uinput is not installed")

        self.key_map = {
            label: self._uinput_key(*names, required=True)
            for label, names in KEY_NAME_MAP.items()
        }
        for label, names in OPTIONAL_KEY_NAME_MAP.items():
            key = self._uinput_key(*names, required=False)
            if key is not None:
                self.key_map[label] = key

        self.modifier_order = [key for key in MODIFIER_KEYS if key in self.key_map]
        extra_keys = [
            k
            for k in (
                self._uinput_key("KEY_SYSRQ", required=False),
                self._uinput_key("KEY_PRINT", required=False),
            )
            if k is not None
        ]
        device_keys = list(dict.fromkeys(list(self.key_map.values()) + extra_keys))
        self.device = uinput.Device(device_keys)
        self.pressed_keys = {}
        atexit.register(self.destroy)
        self._install_excepthook()

    @staticmethod
    def _uinput_key(*names, required=True):
        for name in names:
            key = getattr(uinput, name, None)
            if key is not None:
                return key
        if required:
            raise RuntimeError(
                "python-uinput is missing required key constant(s): "
                + ", ".join(names)
            )
        return None

    def _emit_raw(self, key_event, value, syn=True):
        if self.device is None:
            return
        self.device.emit(key_event, value, syn=syn)

    def destroy(self):
        self.release_all_keys()
        device = getattr(self, "device", None)
        if device is not None:
            self.device = None
            try:
                device.destroy()
            except Exception:
                pass


class EvdevUInputBackend(_BaseUInputBackend):
    name = "evdev-uinput"

    def __init__(self):
        if evdev is None:
            raise RuntimeError("python-evdev is not installed")

        ecodes = evdev.ecodes
        self._ev_key = ecodes.EV_KEY
        self.key_map = {
            label: self._evdev_key(ecodes, *names, required=True)
            for label, names in KEY_NAME_MAP.items()
        }
        for label, names in OPTIONAL_KEY_NAME_MAP.items():
            key = self._evdev_key(ecodes, *names, required=False)
            if key is not None:
                self.key_map[label] = key

        self.modifier_order = [key for key in MODIFIER_KEYS if key in self.key_map]
        extra_keys = [
            k
            for k in (
                self._evdev_key(ecodes, "KEY_SYSRQ", required=False),
                self._evdev_key(ecodes, "KEY_PRINT", required=False),
            )
            if k is not None
        ]
        device_keys = list(dict.fromkeys(list(self.key_map.values()) + extra_keys))
        self.device = evdev.UInput(
            {self._ev_key: device_keys},
            name="vboard-plus",
        )
        self.pressed_keys = {}
        atexit.register(self.destroy)
        self._install_excepthook()

    @staticmethod
    def _evdev_key(ecodes, *names, required=True):
        for name in names:
            key = getattr(ecodes, name, None)
            if key is not None:
                return key
        if required:
            raise RuntimeError(
                "python-evdev is missing required key constant(s): "
                + ", ".join(names)
            )
        return None

    def _emit_raw(self, key_event, value, syn=True):
        if self.device is None:
            return
        self.device.write(self._ev_key, key_event, value)
        if syn:
            self.device.syn()

    def destroy(self):
        self.release_all_keys()
        device = getattr(self, "device", None)
        if device is not None:
            self.device = None
            try:
                device.close()
            except Exception:
                pass


def create_uinput_backend():
    errors = []
    if uinput is not None:
        try:
            return UInputBackend()
        except Exception as exc:
            errors.append(f"python-uinput: {exc}")

    if evdev is not None:
        try:
            return EvdevUInputBackend()
        except Exception as exc:
            errors.append(f"python-evdev: {exc}")

    if errors:
        raise RuntimeError("; ".join(errors))
    raise RuntimeError("Neither python-uinput nor python-evdev is installed")

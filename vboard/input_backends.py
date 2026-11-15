import atexit
import sys
import time

from .constants import MAX_KEY_HOLD_SECONDS, MODIFIER_KEYS, TAP_ONLY_ACTION_KEYS

try:
    import uinput
except ImportError:
    uinput = None


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


class UInputBackend(InputBackend):
    name = "uinput"

    def __init__(self):
        if uinput is None:
            raise RuntimeError("python-uinput is not installed")

        less_key = self._uinput_key("KEY_LESS", "KEY_102ND", required=False)
        self.key_map = {
            "Esc": uinput.KEY_ESC,
            "1": uinput.KEY_1,
            "2": uinput.KEY_2,
            "3": uinput.KEY_3,
            "4": uinput.KEY_4,
            "5": uinput.KEY_5,
            "6": uinput.KEY_6,
            "7": uinput.KEY_7,
            "8": uinput.KEY_8,
            "9": uinput.KEY_9,
            "0": uinput.KEY_0,
            "-": uinput.KEY_MINUS,
            "=": uinput.KEY_EQUAL,
            "Backspace": uinput.KEY_BACKSPACE,
            "Tab": uinput.KEY_TAB,
            "Q": uinput.KEY_Q,
            "W": uinput.KEY_W,
            "E": uinput.KEY_E,
            "R": uinput.KEY_R,
            "T": uinput.KEY_T,
            "Y": uinput.KEY_Y,
            "U": uinput.KEY_U,
            "I": uinput.KEY_I,
            "O": uinput.KEY_O,
            "P": uinput.KEY_P,
            "[": uinput.KEY_LEFTBRACE,
            "]": uinput.KEY_RIGHTBRACE,
            "Enter": uinput.KEY_ENTER,
            "Ctrl_L": uinput.KEY_LEFTCTRL,
            "Ctrl_R": uinput.KEY_RIGHTCTRL,
            "A": uinput.KEY_A,
            "S": uinput.KEY_S,
            "D": uinput.KEY_D,
            "F": uinput.KEY_F,
            "G": uinput.KEY_G,
            "H": uinput.KEY_H,
            "J": uinput.KEY_J,
            "K": uinput.KEY_K,
            "L": uinput.KEY_L,
            ";": uinput.KEY_SEMICOLON,
            "'": uinput.KEY_APOSTROPHE,
            "`": uinput.KEY_GRAVE,
            "Shift_L": uinput.KEY_LEFTSHIFT,
            "Shift_R": uinput.KEY_RIGHTSHIFT,
            "\\": uinput.KEY_BACKSLASH,
            "Z": uinput.KEY_Z,
            "X": uinput.KEY_X,
            "C": uinput.KEY_C,
            "V": uinput.KEY_V,
            "B": uinput.KEY_B,
            "N": uinput.KEY_N,
            "M": uinput.KEY_M,
            ",": uinput.KEY_COMMA,
            ".": uinput.KEY_DOT,
            "/": uinput.KEY_SLASH,
            "Alt_L": uinput.KEY_LEFTALT,
            "Alt_R": uinput.KEY_RIGHTALT,
            "Space": uinput.KEY_SPACE,
            "CapsLock": uinput.KEY_CAPSLOCK,
            "→": uinput.KEY_RIGHT,
            "←": uinput.KEY_LEFT,
            "↓": uinput.KEY_DOWN,
            "↑": uinput.KEY_UP,
            "Super_L": uinput.KEY_LEFTMETA,
            "Super_R": uinput.KEY_RIGHTMETA,
            "F1": uinput.KEY_F1,
            "F2": uinput.KEY_F2,
            "F3": uinput.KEY_F3,
            "F4": uinput.KEY_F4,
            "F5": uinput.KEY_F5,
            "F6": uinput.KEY_F6,
            "F7": uinput.KEY_F7,
            "F8": uinput.KEY_F8,
            "F9": uinput.KEY_F9,
            "F10": uinput.KEY_F10,
            "F11": uinput.KEY_F11,
            "F12": uinput.KEY_F12,
            "Mute": uinput.KEY_MUTE,
            "VolumeDown": uinput.KEY_VOLUMEDOWN,
            "VolumeUp": uinput.KEY_VOLUMEUP,
            "MicMute": uinput.KEY_MICMUTE,
            "KbdBacklight": uinput.KEY_KBDILLUMTOGGLE,
            "BrightnessDown": uinput.KEY_BRIGHTNESSDOWN,
            "BrightnessUp": uinput.KEY_BRIGHTNESSUP,
            "SwitchDisplay": uinput.KEY_SWITCHVIDEOMODE,
            "PreviousSong": uinput.KEY_PREVIOUSSONG,
            "PlayPause": uinput.KEY_PLAYPAUSE,
            "NextSong": uinput.KEY_NEXTSONG,
            "PrtSc": self._uinput_key("KEY_SYSRQ", "KEY_PRINT"),
            "Delete": uinput.KEY_DELETE,
            "Insert": uinput.KEY_INSERT,
            "Home": uinput.KEY_HOME,
            "End": uinput.KEY_END,
        }
        if less_key is not None:
            self.key_map["<"] = less_key
        self.modifier_order = [key for key in MODIFIER_KEYS if key in self.key_map]
        device_keys = list(dict.fromkeys(list(self.key_map.values()) + [uinput.KEY_SYSRQ, uinput.KEY_PRINT]))
        self.device = uinput.Device(device_keys)
        self.pressed_keys = {}
        atexit.register(self.destroy)
        self._install_excepthook()

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

    def _press_key(self, key_event, syn=True):
        self.device.emit(key_event, 1, syn=syn)
        self.pressed_keys[key_event] = time.monotonic()

    def _release_key(self, key_event, syn=True):
        try:
            self.device.emit(key_event, 0, syn=syn)
        finally:
            self.pressed_keys.pop(key_event, None)

    def release_all_keys(self):
        for key_event in list(self.pressed_keys.keys()):
            try:
                self.device.emit(key_event, 0, syn=True)
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
                self.device.emit(key_event, 0, syn=True)
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

    def destroy(self):
        self.release_all_keys()
        device = getattr(self, "device", None)
        if device is not None:
            self.device = None
            try:
                device.destroy()
            except Exception:
                pass

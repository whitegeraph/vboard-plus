APP_DISPLAY_NAME = "Vboard"
APP_ID = "io.github.archisman-panigrahi.vboard"
VERSION = "2.7.0"

MODIFIER_KEYS = (
    "Shift_L",
    "Shift_R",
    "Ctrl_L",
    "Ctrl_R",
    "Alt_L",
    "Alt_R",
    "Super_L",
    "Super_R",
)

FUNCTION_ROW_KEYS = (
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
    "F8",
    "F9",
    "F10",
    "F11",
    "F12",
    "Fn",
)

FUNCTION_KEY_SECONDARY_ACTIONS = {
    "F1": {"action": "Mute", "label": "Mute", "icon": "audio-volume-muted-symbolic"},
    "F2": {"action": "VolumeDown", "label": "Vol-", "icon": "audio-volume-low-symbolic"},
    "F3": {"action": "VolumeUp", "label": "Vol+", "icon": "audio-volume-high-symbolic"},
    "F4": {"action": "PreviousSong", "label": "Prev", "icon": "media-skip-backward-symbolic"},
    "F5": {"action": "PlayPause", "label": "Play", "icon": "media-playback-start-symbolic"},
    "F6": {"action": "NextSong", "label": "Next", "icon": "media-skip-forward-symbolic"},
    "F7": {"action": "BrightnessDown", "label": "Bri-", "icon": "display-brightness-low-symbolic"},
    "F8": {"action": "BrightnessUp", "label": "Bri+", "icon": "display-brightness-high-symbolic"},
    "F9": {"action": "MicMute", "label": "Mic×", "icon": "microphone-sensitivity-muted-symbolic"},
    "F10": {"action": "PrtSc", "label": "PrtSc", "icon": "applets-screenshooter-symbolic"},
    "F11": {"action": "Home", "label": "Home"},
    "F12": {"action": "End", "label": "End"},
}

DEFAULT_KEYBOARD_LAYOUT = "en"

COMMAND_MODIFIER_KEYS = (
    "Ctrl_L",
    "Ctrl_R",
    "Alt_L",
    "Alt_R",
    "Super_L",
    "Super_R",
)

ONBOARD_BACKGROUND_PRESET = "__onboard__"
ENHANCED_BACKGROUND_PRESET = "__enhanced__"

COLOR_PRESETS = [
    ("Black", "0,0,0"),
    ("Red", "255,0,0"),
    ("Pink", "255,105,183"),
    ("White", "255,255,255"),
    ("Green", "0,255,0"),
    ("Blue", "0,0,110"),
    ("Gray", "128,128,128"),
    ("Dark Gray", "64,64,64"),
    ("Slate", "51,65,85"),
    ("Orange", "255,165,0"),
    ("Yellow", "255,255,0"),
    ("Purple", "128,0,128"),
    ("Cyan", "0,255,255"),
    ("Teal", "0,128,128"),
    ("Brown", "139,69,19"),
    ("Gold", "255,215,0"),
    ("Silver", "192,192,192"),
    ("Turquoise", "64,224,208"),
    ("Magenta", "255,0,255"),
    ("Olive", "128,128,0"),
    ("Maroon", "128,0,0"),
    ("Indigo", "75,0,130"),
    ("Beige", "245,245,220"),
    ("Lavender", "230,230,250"),
]

COLOR_CHOICES = [
    ("Onboard Droid Theme", ONBOARD_BACKGROUND_PRESET),
    *[
        (f"Enhanced {label}", (ENHANCED_BACKGROUND_PRESET, color))
        for label, color in COLOR_PRESETS
    ],
    *COLOR_PRESETS,
]

LIGHT_BACKGROUND_COLORS = {
    "255,255,255",
    "0,255,0",
    "255,255,0",
    "245,245,220",
    "230,230,250",
    "255,215,0",
}

KEY_WIDTHS = {
    "Space": 12,
    "CapsLock": 3,
    "Shift_R": 2,
    "Shift_L": 2,
    "Backspace": 5,
    "`": 1,
    "\\": 4,
    "Enter": 5,
    "<": 2,
    "Fn": 4,
    "F1": 2,
    "F2": 2,
    "F3": 2,
    "F4": 2,
    "F5": 2,
    "F6": 2,
    "F7": 2,
    "F8": 2,
    "F9": 2,
    "F10": 2,
    "F11": 2,
    "F12": 2,
    "PrtSc": 2,
    "Delete": 2,
    "Insert": 2,
    "Home": 2,
    "End": 2,
}

NAV_KEYS = (
    "PrtSc",
    "Delete",
    "Insert",
    "Home",
    "End",
)

TAP_ONLY_ACTION_KEYS = (
    "PrtSc",
    "Insert",
    "Home",
    "End",
    "Esc",
    "CapsLock",
    "Fn",
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
    "F8",
    "F9",
    "F10",
    "F11",
    "F12",
    "Mute",
    "VolumeDown",
    "VolumeUp",
    "MicMute",
    "BrightnessDown",
    "BrightnessUp",
    "PreviousSong",
    "PlayPause",
    "NextSong",
)

PRTSC_DEBOUNCE_SECONDS = 0.5
PRTSC_LOCKOUT_SECONDS = 1.5
OVERLAY_KEY_RELEASE_DELAY_MS = 120
OVERLAY_GRAB_KEYS = ("PrtSc",)
MAX_KEY_HOLD_SECONDS = 1.0

SUPPORTED_WORD_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'-")
SUGGESTION_LIMIT = 5

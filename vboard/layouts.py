import json
import os

from .constants import DEFAULT_KEYBOARD_LAYOUT


SYSTEM_LAYOUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layouts")
USER_LAYOUT_DIR = os.path.expanduser("~/.config/vboard-plus/layouts")
REQUIRED_LAYOUT_FIELDS = ("id", "label", "rows")


def get_layout_directories(user_layout_dir=USER_LAYOUT_DIR):
    return (SYSTEM_LAYOUT_DIR, user_layout_dir)


def load_keyboard_layouts(user_layout_dir=USER_LAYOUT_DIR):
    layouts = {}
    for layout_dir in get_layout_directories(user_layout_dir):
        if not os.path.isdir(layout_dir):
            continue

        for filename in sorted(os.listdir(layout_dir)):
            if not filename.endswith(".json"):
                continue

            path = os.path.join(layout_dir, filename)
            try:
                layout = load_keyboard_layout(path)
            except (OSError, ValueError) as exc:
                print(f"Warning: Could not load keyboard layout {path} ({exc}).")
                continue

            layouts[layout["id"]] = layout

    if not layouts:
        searched_dirs = ", ".join(get_layout_directories(user_layout_dir))
        raise RuntimeError(f"No keyboard layouts found. Checked: {searched_dirs}")

    return layouts


def load_keyboard_layout(path):
    with open(path, "r", encoding="utf-8") as layout_file:
        layout = json.load(layout_file)

    validate_keyboard_layout(layout, path)
    return {
        "id": layout["id"],
        "label": layout["label"],
        "order": layout.get("order"),
        "rows": layout["rows"],
        "labels": layout.get("labels", {}),
        "shifted": layout.get("shifted", {}),
    }


def validate_keyboard_layout(layout, path):
    if not isinstance(layout, dict):
        raise ValueError("layout must be a JSON object")

    for field in REQUIRED_LAYOUT_FIELDS:
        if field not in layout:
            raise ValueError(f"missing required field: {field}")

    if not isinstance(layout["id"], str) or not layout["id"]:
        raise ValueError("id must be a non-empty string")
    if not isinstance(layout["label"], str) or not layout["label"]:
        raise ValueError("label must be a non-empty string")
    if not isinstance(layout["rows"], list) or not layout["rows"]:
        raise ValueError("rows must be a non-empty list")
    if "order" in layout and not isinstance(layout["order"], int):
        raise ValueError("order must be an integer")

    for row in layout["rows"]:
        if not isinstance(row, list) or not row:
            raise ValueError("each row must be a non-empty list")
        for key in row:
            if not isinstance(key, str) or not key:
                raise ValueError("each key must be a non-empty string")

    for field in ("labels", "shifted"):
        if field not in layout:
            continue
        if not isinstance(layout[field], dict):
            raise ValueError(f"{field} must be an object")
        for key, value in layout[field].items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(f"{field} keys and values must be strings")


def get_layout_choices(layouts):
    choices = []
    for layout_id, layout in layouts.items():
        choices.append((layout_id, layout["label"], layout.get("order")))
    sorted_choices = sorted(choices, key=get_layout_choice_sort_key)
    return tuple((layout_id, label) for layout_id, label, _order in sorted_choices)


def get_layout_choice_sort_key(choice):
    layout_id, label, order = choice
    if isinstance(order, int):
        return (0, order, label.lower(), layout_id)
    if layout_id == DEFAULT_KEYBOARD_LAYOUT:
        return (1, 0, "", "")
    return (1, 1, label.lower(), layout_id)


def get_default_layout_key(layouts):
    if DEFAULT_KEYBOARD_LAYOUT in layouts:
        return DEFAULT_KEYBOARD_LAYOUT
    return next(iter(layouts))


SYSTEM_LAYOUT_VARIANT_ALIASES = {
    ("ca", "fr"): "fr",
    ("ca", "multix"): "fr",
    ("ch", "fr"): "fr",
    ("ch", "fr_mac"): "fr",
    ("dz", "ar"): "ar",
    ("iq", "ku"): "en",
    ("ma", "french"): "fr",
    ("us", "rus"): "ru",
}

SYSTEM_LAYOUT_ALIASES = {
    # English
    "us": "en",
    "gb": "en",
    "uk": "en",
    "en": "en",
    "eng": "en",
    "au": "en",
    "ca": "en",
    "ie": "en",
    "in": "en",
    "nz": "en",
    "za": "en",
    # Arabic
    "ar": "ar",
    "ara": "ar",
    "eg": "ar",
    "iq": "ar",
    "ma": "ar",
    "sy": "ar",
    "sa": "ar",
    "ae": "ar",
    "jo": "ar",
    "kw": "ar",
    "lb": "ar",
    "ly": "ar",
    "om": "ar",
    "qa": "ar",
    "ye": "ar",
    "bh": "ar",
    "tn": "ar",
    "sd": "ar",
    "ps": "ar",
    # Swedish
    "se": "sv",
    "sv": "sv",
    "swe": "sv",
    # German
    "de": "de",
    "deu": "de",
    "ger": "de",
    "at": "de",
    "ch": "de",
    # French
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "be": "fr",
    # Russian
    "ru": "ru",
    "rus": "ru",
}


def resolve_system_layout_id(source_type, source_id, available_layouts):
    """Map a system input source (XKB or IBus) to an available Vboard layout ID."""
    if not available_layouts:
        return None

    norm_type = (source_type or "").strip().lower()
    norm_id = (source_id or "").strip().lower()
    if not norm_id:
        return None

    xkb_layout = ""
    xkb_variant = ""
    ibus_lang = ""

    if norm_type == "ibus":
        if norm_id.startswith("xkb:"):
            parts = norm_id.split(":")
            xkb_layout = parts[1] if len(parts) > 1 else ""
            xkb_variant = parts[2] if len(parts) > 2 else ""
            ibus_lang = parts[3] if len(parts) > 3 else ""
        else:
            parts = norm_id.split(":")
            for part in parts:
                if part in available_layouts:
                    return part
                mapped = SYSTEM_LAYOUT_ALIASES.get(part)
                if mapped and mapped in available_layouts:
                    return mapped
            return None
    else:
        if "+" in norm_id:
            xkb_layout, xkb_variant = norm_id.split("+", 1)
        else:
            xkb_layout = norm_id

    if (xkb_layout, xkb_variant) in SYSTEM_LAYOUT_VARIANT_ALIASES:
        candidate = SYSTEM_LAYOUT_VARIANT_ALIASES[(xkb_layout, xkb_variant)]
        if candidate in available_layouts:
            return candidate

    if xkb_layout in available_layouts:
        return xkb_layout

    for token in (xkb_layout, ibus_lang):
        if not token:
            continue
        candidate = SYSTEM_LAYOUT_ALIASES.get(token)
        if candidate and candidate in available_layouts:
            return candidate

    return None


def resolve_gnome_input_source(
    mru_sources, sources, current_index, available_layouts
):
    """Resolve the active GNOME org.gnome.desktop.input-sources entry to a layout ID."""
    active_source = None
    sources_list = list(sources) if sources else []
    sources_set = {tuple(item) for item in sources_list if len(item) >= 2}

    for item in mru_sources or ():
        if len(item) < 2:
            continue
        item_tuple = (item[0], item[1])
        if not sources_set or item_tuple in sources_set:
            active_source = item_tuple
            break

    if active_source is None and sources_list:
        idx = current_index if isinstance(current_index, int) else 0
        if not (0 <= idx < len(sources_list)):
            idx = 0
        if len(sources_list[idx]) >= 2:
            active_source = (sources_list[idx][0], sources_list[idx][1])

    if active_source is None:
        return None

    return resolve_system_layout_id(
        active_source[0], active_source[1], available_layouts
    )


def resolve_kde_layout(layouts_list, current_index, available_layouts):
    """Resolve the active KDE org.kde.KeyboardLayouts entry to a layout ID."""
    entries = list(layouts_list) if layouts_list else []
    if not entries:
        return None

    idx = current_index if isinstance(current_index, int) else 0
    if not (0 <= idx < len(entries)):
        idx = 0

    entry = entries[idx]
    if not entry:
        return None

    layout = str(entry[0]).strip() if len(entry) >= 1 and entry[0] is not None else ""
    variant = str(entry[1]).strip() if len(entry) >= 2 and entry[1] is not None else ""
    if not layout:
        return None

    source_id = f"{layout}+{variant}" if variant else layout
    return resolve_system_layout_id("xkb", source_id, available_layouts)


def resolve_keymap_layout(keymap, available_layouts, keyval_name_fn):
    """Best-effort fallback detecting layout from Gdk.Keymap group 0 entries."""
    if keymap is None or not available_layouts:
        return None

    def first_key_name(keycode):
        try:
            ok, keys, keyvals = keymap.get_entries_for_keycode(keycode)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return None
        if not ok:
            return None
        for key, keyval in zip(keys, keyvals):
            if getattr(key, "group", 0) == 0 and getattr(key, "level", 0) == 0:
                return keyval_name_fn(keyval)
        return None

    q_name = first_key_name(24)
    y_name = first_key_name(29)
    semi_name = first_key_name(47)

    candidate = None
    if q_name:
        if q_name.startswith("Arabic_"):
            candidate = "ar"
        elif q_name.startswith("Cyrillic_"):
            candidate = "ru"
        elif q_name in ("a", "A"):
            candidate = "fr"
        elif semi_name in ("odiaeresis", "Odiaeresis"):
            candidate = "sv"
        elif y_name in ("z", "Z"):
            candidate = "de"
        elif q_name in ("q", "Q") and y_name in ("y", "Y"):
            candidate = "en"

    if candidate and candidate in available_layouts:
        return candidate
    return None

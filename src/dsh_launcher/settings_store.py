"""Launcher-local preferences (~/.dsh/launcher.json)."""

from __future__ import annotations

import json
from pathlib import Path

from dsh_launcher.paths import dsh_home

_DEFAULTS = {
    "open_with_chrome": True,
    "use_china_mirror": True,
    "language": "zh",
    "theme": "dark",
    "auto_start": True,
    "check_plugins_on_start": True,
}


def settings_path() -> Path:
    return dsh_home() / "launcher.json"


def load_settings() -> dict:
    path = settings_path()
    data = dict(_DEFAULTS)
    if not path.is_file():
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update({k: raw[k] for k in _DEFAULTS if k in raw})
    except (OSError, json.JSONDecodeError):
        pass
    return data


def save_settings(updates: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_settings()
    data.update(updates)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_open_with_chrome() -> bool:
    return bool(load_settings().get("open_with_chrome", True))


def set_open_with_chrome(enabled: bool) -> None:
    save_settings({"open_with_chrome": bool(enabled)})


def get_use_china_mirror() -> bool:
    return bool(load_settings().get("use_china_mirror", True))


def set_use_china_mirror(enabled: bool) -> None:
    save_settings({"use_china_mirror": bool(enabled)})


def get_language() -> str:
    lang = str(load_settings().get("language", "zh")).lower()
    return "en" if lang.startswith("en") else "zh"


def set_language(lang: str) -> None:
    save_settings({"language": "en" if str(lang).lower().startswith("en") else "zh"})


def get_theme() -> str:
    theme = str(load_settings().get("theme", "dark")).lower()
    return "light" if theme == "light" else "dark"


def set_theme(theme: str) -> None:
    save_settings({"theme": "light" if str(theme).lower() == "light" else "dark"})


def get_auto_start() -> bool:
    return bool(load_settings().get("auto_start", True))


def set_auto_start(enabled: bool) -> None:
    save_settings({"auto_start": bool(enabled)})


def get_check_plugins_on_start() -> bool:
    return bool(load_settings().get("check_plugins_on_start", True))


def set_check_plugins_on_start(enabled: bool) -> None:
    save_settings({"check_plugins_on_start": bool(enabled)})

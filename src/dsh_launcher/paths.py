from __future__ import annotations

import sys
from pathlib import Path


APP_USER_MODEL_ID = "DeepSeek.Harness.Launcher"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3080
DEFAULT_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/"


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base.joinpath(*parts)
    return project_root().joinpath(*parts)


def icon_path() -> Path:
    bundled = resource_path("assets", "dsh.ico")
    if bundled.exists():
        return bundled
    fallback = dsh_home() / "dsh.ico"
    if fallback.exists():
        return fallback
    return bundled


def dsh_home() -> Path:
    return Path.home() / ".dsh"


def chrome_profile_dir() -> Path:
    """Persistent Chrome user-data-dir for the launcher (cookies / logins survive)."""
    return dsh_home() / "chrome-profile"


def web_profile_dir() -> Path:
    return dsh_home() / "profiles" / "web"


def web_patch_path() -> Path:
    return web_profile_dir() / "cordis.patch.yml"


def harness_cwd() -> Path:
    """Directory used as cwd for ``dsh web``.

    Must not be the user home: a ``package.json`` there can pin Corepack/pnpm
    to an old version. Prefer the web profile when it already has a manifest;
    otherwise a small isolated folder under ``~/.dsh``.
    """
    web = web_profile_dir()
    if (web / "package.json").is_file():
        return web
    isolated = dsh_home() / "launcher-cwd"
    isolated.mkdir(parents=True, exist_ok=True)
    sentinel = isolated / "package.json"
    if not sentinel.is_file():
        sentinel.write_text('{"private": true}\n', encoding="utf-8")
    return isolated

"""Open the DSH web UI in a dedicated, persistent Chrome profile."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from dsh_launcher.paths import chrome_profile_dir

# Detach Chrome from the launcher process tree on Windows.
_DETACHED = 0x00000008
_NEW_PROCESS_GROUP = 0x00000200
_BREAKAWAY = 0x01000000


def find_chrome() -> Path | None:
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
        ]
        for path in candidates:
            if path.is_file():
                return path
        which = shutil.which("chrome") or shutil.which("google-chrome")
        return Path(which) if which else None

    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        which = shutil.which(name)
        if which:
            return Path(which)
    return None


def chrome_launch_args(chrome: Path, url: str, *, profile: Path | None = None) -> list[str]:
    """Same user-data-dir every time; no --new-window so Chrome reuses the window."""
    data_dir = profile or chrome_profile_dir()
    return [
        str(chrome),
        f"--user-data-dir={data_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=ChromeWhatsNewUI",
        url,
    ]


def open_url(url: str, *, use_chrome: bool) -> tuple[bool, str]:
    """Open URL. Dedicated Chrome profile if use_chrome; else the system default browser."""
    if not use_chrome:
        webbrowser.open(url)
        return True, "已用系统默认浏览器打开"

    chrome = find_chrome()
    if chrome is None:
        webbrowser.open(url)
        return False, "未找到 Chrome，已用系统默认浏览器打开（可关闭「用 Chrome 打开」开关）"

    flags = 0
    if sys.platform == "win32":
        flags = _DETACHED | _NEW_PROCESS_GROUP
        try:
            flags |= _BREAKAWAY
        except Exception:
            pass

    profile = chrome_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    cmd = chrome_launch_args(chrome, url, profile=profile)
    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
            "close_fds": sys.platform != "win32",
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = flags
            kwargs["startupinfo"] = subprocess.STARTUPINFO()
            kwargs["startupinfo"].dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"].wShowWindow = 1  # SW_SHOWNORMAL
        subprocess.Popen(cmd, **kwargs)
    except OSError as exc:
        webbrowser.open(url)
        return False, f"启动 Chrome 失败（{exc}），已用默认浏览器打开"

    return True, f"已用固定 Chrome 配置打开（登录会保留）: {chrome.name}"


def open_in_chrome(url: str) -> tuple[bool, str]:
    return open_url(url, use_chrome=True)

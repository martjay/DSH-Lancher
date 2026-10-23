from __future__ import annotations

from pathlib import Path

from dsh_launcher.browser import chrome_launch_args
from dsh_launcher.paths import chrome_profile_dir


def test_chrome_profile_is_under_dsh_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("dsh_launcher.paths.dsh_home", lambda: tmp_path)
    assert chrome_profile_dir() == tmp_path / "chrome-profile"


def test_chrome_launch_reuses_profile_without_new_window(tmp_path) -> None:
    chrome = tmp_path / "chrome.exe"
    profile = tmp_path / "chrome-profile"
    url = "http://127.0.0.1:28467/?token=abc"
    cmd = chrome_launch_args(chrome, url, profile=profile)
    assert cmd[0] == str(chrome)
    assert f"--user-data-dir={profile}" in cmd
    assert "--profile-directory=Default" in cmd
    assert "--new-window" not in cmd
    assert "--guest" not in cmd
    assert "--incognito" not in cmd
    assert cmd[-1] == url

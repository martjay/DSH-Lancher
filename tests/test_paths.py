from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from dsh_launcher.paths import harness_cwd


def test_harness_cwd_prefers_web_profile() -> None:
    home = Path(tempfile.mkdtemp())
    web = home / "profiles" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text('{"name":"dsh-profile-web","private":true}\n', encoding="utf-8")
    with patch("dsh_launcher.paths.dsh_home", lambda: home):
        assert harness_cwd() == web


def test_harness_cwd_isolated_when_no_profile() -> None:
    home = Path(tempfile.mkdtemp())
    with patch("dsh_launcher.paths.dsh_home", lambda: home):
        cwd = harness_cwd()
        assert cwd == home / "launcher-cwd"
        assert (cwd / "package.json").is_file()

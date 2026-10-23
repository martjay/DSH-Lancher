from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from dsh_launcher.dsh_cli import find_working_dsh, is_desktop_shim, list_dsh_candidates


def test_desktop_shim_paths() -> None:
    assert is_desktop_shim(r"C:\Users\tianj\AppData\Local\deepseek-harness\bin\dsh.cmd")
    assert is_desktop_shim(r"C:\Users\tianj\AppData\Roaming\io.github.hairyf.deepseek-harness-desktop\dsh")
    assert not is_desktop_shim(r"C:\nvm4w\nodejs\dsh.cmd")


def test_list_candidates_skips_protected_path() -> None:
    import os

    protected = r"C:\WINDOWS\system32\config"
    with patch.dict(os.environ, {"PATH": protected, "NVM_SYMLINK": ""}, clear=False):
        with patch("dsh_launcher.dsh_cli.refresh_path"):
            found = list_dsh_candidates()
    assert all("system32\\config" not in str(p).lower().replace("/", "\\") for p in found)


def test_find_working_skips_shim() -> None:
    root = Path(tempfile.mkdtemp())
    shim_dir = root / "deepseek-harness" / "bin"
    real_dir = root / "nvm4w" / "nodejs"
    shim_dir.mkdir(parents=True)
    real_dir.mkdir(parents=True)
    (shim_dir / "dsh.cmd").write_text("@echo off\n", encoding="utf-8")
    (real_dir / "dsh.cmd").write_text("@echo off\n", encoding="utf-8")

    def fake_probe(path, *, timeout=8):
        return (True, "0.1.1-rc.2") if "nvm4w" in str(path).replace("\\", "/") else (False, "CLI not found")

    with (
        patch("dsh_launcher.dsh_cli._bindirs", lambda: [shim_dir, real_dir]),
        patch("dsh_launcher.dsh_cli.probe_dsh", fake_probe),
    ):
        found = find_working_dsh()
        assert found
        assert "nvm4w" in found.replace("\\", "/")
        assert any(p.name == "dsh.cmd" for p in list_dsh_candidates())


def test_bindirs_include_nvm_version_folders(tmp_path: Path) -> None:
    import os

    old = tmp_path / "v24.14.0"
    new = tmp_path / "v26.5.1"
    old.mkdir()
    new.mkdir()
    (old / "node.exe").write_bytes(b"")
    (new / "node.exe").write_bytes(b"")
    (old / "dsh.cmd").write_text("@echo 0.1.1\n", encoding="utf-8")
    (new / "dsh.cmd").write_text("@echo 0.1.5\n", encoding="utf-8")

    def fake_probe(path, *, timeout=8):
        text = str(path)
        if "v26.5.1" in text:
            return True, "0.1.5-rc.3"
        if "v24.14.0" in text:
            return True, "0.1.1-rc.2"
        return False, ""

    with (
        patch.dict(os.environ, {"NVM_HOME": str(tmp_path), "NVM_SYMLINK": "", "PATH": str(tmp_path)}, clear=False),
        patch("dsh_launcher.dsh_cli.refresh_path"),
        patch("dsh_launcher.dsh_cli.probe_dsh", fake_probe),
    ):
        names = [p.parent.name for p in list_dsh_candidates() if p.name.startswith("dsh")]
        assert names[0] == "v26.5.1"
        found = find_working_dsh()
        assert found
        assert "v26.5.1" in found.replace("\\", "/")

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from dsh_launcher.node_bootstrap import ensure_npm, resolve_npm


def test_resolve_npm_prefers_nvm() -> None:
    root = Path(tempfile.mkdtemp())
    nvm = root / "nvm4w" / "nodejs" / "npm.cmd"
    nvm.parent.mkdir(parents=True)
    nvm.write_text("@echo off\n", encoding="utf-8")
    pf = root / "Program Files" / "nodejs" / "npm.cmd"
    pf.parent.mkdir(parents=True)
    pf.write_text("@echo off\n", encoding="utf-8")
    with (
        patch("dsh_launcher.node_bootstrap.refresh_path"),
        patch("dsh_launcher.node_bootstrap._nvm_npm", lambda: nvm),
        patch("dsh_launcher.node_bootstrap.shutil.which", return_value=str(pf)),
    ):
        assert Path(resolve_npm() or "") == nvm


def test_ensure_npm_does_not_install_when_nvm_present() -> None:
    nvm = Path(tempfile.mkdtemp()) / "npm.cmd"
    nvm.write_text("@echo off\n", encoding="utf-8")
    with (
        patch("dsh_launcher.node_bootstrap.refresh_path"),
        patch("dsh_launcher.node_bootstrap._nvm_npm", lambda: nvm),
        patch("dsh_launcher.node_bootstrap._install_node_winget") as winget,
        patch("dsh_launcher.node_bootstrap._install_node_msiexec") as msi,
    ):
        ok, detail = ensure_npm()
        assert ok
        assert str(nvm) in detail
        winget.assert_not_called()
        msi.assert_not_called()

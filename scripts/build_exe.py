"""Build the windowed onefile exe. Invoked by build-exe.bat so cmd.exe ^-breaks cannot happen."""

from __future__ import annotations

import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "assets" / "dsh.ico"
ENTRY = ROOT / "src" / "dsh_launcher" / "__main__.py"


def main() -> int:
    if not ICON.is_file():
        print(f"[error] missing {ICON}", file=sys.stderr)
        return 1
    if not ENTRY.is_file():
        print(f"[error] missing {ENTRY}", file=sys.stderr)
        return 1

    sep = ";" if sys.platform == "win32" else ":"
    PyInstaller.__main__.run(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "DeepSeek Harness",
            "--icon",
            str(ICON),
            "--add-data",
            f"{ICON}{sep}assets",
            "--paths",
            str(ROOT / "src"),
            "--hidden-import",
            "dsh_launcher.mirrors",
            "--hidden-import",
            "dsh_launcher.node_bootstrap",
            "--hidden-import",
            "dsh_launcher.settings_store",
            "--hidden-import",
            "dsh_launcher.browser",
            "--hidden-import",
            "dsh_launcher.watch",
            "--hidden-import",
            "dsh_launcher.dsh_cli",
            "--hidden-import",
            "dsh_launcher.plugins",
            "--hidden-import",
            "dsh_launcher.plugins_ui",
            "--hidden-import",
            "dsh_launcher.update_check",
            "--hidden-import",
            "dsh_launcher.ui",
            "--hidden-import",
            "dsh_launcher.app",
            "--hidden-import",
            "psutil",
            "--hidden-import",
            "pystray",
            "--hidden-import",
            "PIL",
            "--collect-all",
            "pystray",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(ROOT / "build"),
            "--specpath",
            str(ROOT / "build"),
            str(ENTRY),
        ]
    )
    exe = ROOT / "dist" / "DeepSeek Harness.exe"
    print(f"[build] exe: {exe}")
    return 0 if exe.is_file() else 1


if __name__ == "__main__":
    raise SystemExit(main())

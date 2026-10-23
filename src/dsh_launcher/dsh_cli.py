"""Locate a real DSH CLI, skipping Desktop shims that only print CLI-not-found."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dsh_launcher.node_bootstrap import refresh_path

_STUB_MARKERS = (
    "cli not found",
    "please run deepseek harness desktop",
)
_SHIM_DIR_MARKERS = (
    "deepseek-harness\\bin",
    "deepseek-harness/bin",
    "io.github.hairyf.deepseek-harness-desktop",
)


def _creationflags() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def wrap_cmd(executable: str, *args: str) -> list[str]:
    if sys.platform == "win32" and executable.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/d", "/s", "/c", executable, *args]
    return [executable, *args]


def is_desktop_shim(path: str | Path) -> bool:
    text = str(path).lower().replace("/", "\\")
    return any(marker in text for marker in _SHIM_DIR_MARKERS)


def _run(cmd: list[str], *, timeout: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_creationflags(),
            shell=False,
        )
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        return 124, "命令超时"
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def _dsh_names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("dsh.cmd", "dsh.exe", "dsh.bat", "dsh")
    return ("dsh",)


_SKIP_DIR_MARKERS = (
    r"\windows\system32\config",
    r"/windows/system32/config",
    r"\windows\syswow64\config",
    r"/windows/syswow64/config",
)


def _is_protected_dir(path: str | Path) -> bool:
    text = str(path).lower().replace("/", "\\")
    return any(marker in text for marker in _SKIP_DIR_MARKERS)


def _path_key(raw: str | Path) -> str:
    """Normalize without touching the filesystem (avoids WinError 5 on protected dirs)."""
    return os.path.normcase(os.path.abspath(os.path.expandvars(str(raw))))


def _nvm_home() -> Path | None:
    for raw in (
        os.environ.get("NVM_HOME"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "nvm",
    ):
        if not raw:
            continue
        path = Path(str(raw).strip().strip('"'))
        try:
            if path.is_dir():
                return path
        except OSError:
            continue
    return None


def _version_sort_key(name: str) -> tuple:
    bits: list[int] = []
    for part in name.lstrip("vV").split("."):
        try:
            bits.append(int(part))
        except ValueError:
            bits.append(-1)
    return tuple(bits)


def _nvm_version_dirs() -> list[Path]:
    """nvm-windows keeps a separate global npm prefix per Node version."""
    home = _nvm_home()
    if home is None:
        return []
    found: list[Path] = []
    try:
        children = list(home.iterdir())
    except OSError:
        return []
    for path in children:
        try:
            if not path.is_dir():
                continue
            if not (path / "node.exe").is_file() and not (path / "node").is_file():
                continue
        except OSError:
            continue
        found.append(path)
    found.sort(key=lambda p: _version_sort_key(p.name), reverse=True)
    return found


def _bindirs() -> list[Path]:
    refresh_path()
    dirs: list[Path] = []
    seen: set[str] = set()

    def add(raw: str | Path | None) -> None:
        if not raw:
            return
        path = Path(str(raw).strip().strip('"'))
        if not str(path) or _is_protected_dir(path):
            return
        key = _path_key(path)
        if key in seen:
            return
        seen.add(key)
        dirs.append(path)

    add(os.environ.get("NVM_SYMLINK"))
    add(Path(r"C:\nvm4w\nodejs"))
    npm_home = os.environ.get("APPDATA")
    if npm_home:
        add(Path(npm_home) / "npm")
    for chunk in os.environ.get("PATH", "").split(os.pathsep):
        add(chunk.strip())
    for version_dir in _nvm_version_dirs():
        add(version_dir)
    return dirs


def list_dsh_candidates() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for directory in _bindirs():
        if _is_protected_dir(directory):
            continue
        for name in _dsh_names():
            path = directory / name
            try:
                ok = path.is_file()
            except OSError:
                continue
            if not ok:
                continue
            try:
                key = _path_key(path)
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return found


def probe_dsh(path: str | Path, *, timeout: float = 8) -> tuple[bool, str]:
    """Return (ok, output). ok means --version ran and is not a Desktop stub."""
    code, out = _run(wrap_cmd(str(path), "--version"), timeout=timeout)
    low = out.lower()
    if any(marker in low for marker in _STUB_MARKERS):
        return False, out
    if code != 0:
        return False, out
    return True, out


def find_working_dsh(*, timeout: float = 8) -> str | None:
    """First DSH on PATH (nvm first) whose ``--version`` actually works."""
    try:
        candidates = list_dsh_candidates()
    except OSError:
        candidates = []
    for path in candidates:
        if is_desktop_shim(path):
            continue
        try:
            ok, _out = probe_dsh(path, timeout=timeout)
        except OSError:
            continue
        if ok:
            bindir = str(path.parent)
            parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
            parts = [bindir, *[p for p in parts if os.path.normcase(p) != os.path.normcase(bindir)]]
            os.environ["PATH"] = os.pathsep.join(parts)
            return str(path)
    return None


def resolve_dsh_argv(*args: str) -> list[str]:
    found = find_working_dsh()
    if not found:
        raise FileNotFoundError("找不到可用的 DSH CLI。请先安装 @deepseek-ai/dsh（不要用 Desktop 空壳）。")
    return wrap_cmd(found, *args)

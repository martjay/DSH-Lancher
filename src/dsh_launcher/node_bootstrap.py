"""Ensure Node.js / npm exist so @deepseek-ai/dsh can be installed."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _creationflags() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


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


def _which(name: str) -> str | None:
    try:
        return shutil.which(name)
    except OSError:
        return None


def refresh_path() -> None:
    """Merge Machine+User PATH into this process (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import winreg
    except ImportError:
        return
    parts: list[str] = []
    for hive, sub in (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, "Environment"),
    ):
        try:
            with winreg.OpenKey(hive, sub) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
                if value:
                    parts.extend(str(value).split(";"))
        except OSError:
            continue
    # Keep existing first so current session tools stay preferred, then registry.
    merged: list[str] = []
    for chunk in [*os.environ.get("PATH", "").split(";"), *parts]:
        c = chunk.strip()
        if c and c not in merged:
            merged.append(c)
    os.environ["PATH"] = ";".join(merged)


def _candidate_npm_paths() -> list[Path]:
    home = Path.home()
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    pf86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    nvm_symlink = os.environ.get("NVM_SYMLINK")
    return [
        Path(nvm_symlink) / "npm.cmd" if nvm_symlink else Path(r"C:\nvm4w\nodejs") / "npm.cmd",
        Path(r"C:\nvm4w\nodejs") / "npm.cmd",
        home / "scoop" / "apps" / "nodejs-lts" / "current" / "npm.cmd",
        home / "scoop" / "apps" / "nodejs" / "current" / "npm.cmd",
        local / "Programs" / "node" / "npm.cmd",
        pf / "nodejs" / "npm.cmd",
        pf86 / "nodejs" / "npm.cmd",
    ]


def _is_official_nodejs(path: str) -> bool:
    text = path.lower().replace("/", "\\")
    return "\\program files\\nodejs" in text or "\\program files (x86)\\nodejs" in text


def _nvm_npm() -> Path | None:
    seen: list[Path] = []
    symlink = os.environ.get("NVM_SYMLINK")
    if symlink:
        seen.append(Path(symlink) / "npm.cmd")
    seen.append(Path(r"C:\nvm4w\nodejs") / "npm.cmd")
    for path in seen:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def _prefer_npm(path: str) -> None:
    bindir = str(Path(path).parent)
    current = os.environ.get("PATH", "")
    parts = [p for p in current.split(os.pathsep) if p]
    if bindir in parts:
        parts = [bindir, *[p for p in parts if p != bindir]]
    else:
        parts = [bindir, *parts]
    os.environ["PATH"] = os.pathsep.join(parts)


def resolve_npm() -> str | None:
    refresh_path()
    nvm = _nvm_npm()
    if nvm:
        _prefer_npm(str(nvm))
        return str(nvm)
    found = _which("npm") or _which("npm.cmd")
    if found and not _is_official_nodejs(found):
        return found
    for path in _candidate_npm_paths():
        try:
            if path.is_file():
                _prefer_npm(str(path))
                return str(path)
        except OSError:
            continue
    if found:
        return found
    return None


def has_npm() -> bool:
    return resolve_npm() is not None


def _install_node_winget() -> tuple[bool, str]:
    winget = _which("winget")
    if not winget:
        return False, "未找到 winget"
    code, out = _run(
        [
            winget,
            "install",
            "-e",
            "--id",
            "OpenJS.NodeJS.LTS",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        ],
        timeout=900,
    )
    # winget often returns 0 even when already installed; -1978335189 = already installed
    if code not in (0, -1978335189, 3010) and "successfully installed" not in out.lower():
        # Some winget builds use unsigned exit codes
        if code != 0 and "No newer package versions are available" not in out:
            return False, out or f"winget 安装 Node.js 失败 ({code})"
    refresh_path()
    return True, out or "winget 已处理 Node.js LTS"


def _install_node_msiexec(*, use_mirror: bool) -> tuple[bool, str]:
    """Download Node.js LTS MSI and silent-install (Windows)."""
    import json
    import tempfile
    import urllib.request

    from dsh_launcher.mirrors import node_index_url, node_msi_url

    index = node_index_url(mirror=use_mirror)
    try:
        req = urllib.request.Request(index, headers={"User-Agent": "dsh-launcher"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return False, f"获取 Node.js 版本列表失败：{exc}"

    lts = next((r for r in releases if r.get("lts")), None)
    if not lts:
        return False, "未找到 Node.js LTS 版本"
    ver = lts["version"]  # e.g. v24.20.0
    msi_url = node_msi_url(ver, mirror=use_mirror)
    dest = Path(tempfile.gettempdir()) / f"node-{ver}-x64.msi"
    try:
        req = urllib.request.Request(msi_url, headers={"User-Agent": "dsh-launcher"})
        with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
    except Exception as exc:
        return False, f"下载 Node.js 安装包失败：{exc}"

    code, out = _run(
        ["msiexec", "/i", str(dest), "/qn", "/norestart"],
        timeout=900,
    )
    refresh_path()
    if code not in (0, 3010):
        return False, out or f"msiexec 安装失败 ({code})"
    src = "npmmirror" if use_mirror else "nodejs.org"
    return True, f"已静默安装 Node.js {ver}（来源 {src}）"


def ensure_npm(*, log=None, use_mirror: bool = True) -> tuple[bool, str]:
    """
    Make sure npm is available. If missing on Windows, install Node.js LTS.
    When use_mirror, skip winget and download MSI from npmmirror.
    """
    existing = resolve_npm()
    if existing:
        return True, f"已找到 npm：{existing}"

    notes: list[str] = []
    nvm = _nvm_npm()
    if nvm:
        _prefer_npm(str(nvm))
        msg = f"使用已有 nvm Node（{nvm}），跳过官方 Node.js 安装。"
        if log:
            log(msg)
        return True, msg

    if sys.platform != "win32":
        return False, "未找到 npm。请先安装 Node.js LTS：https://nodejs.org"

    notes.append("未找到 npm，开始自动安装 Node.js LTS（含 npm）…")
    if log:
        log(notes[-1])

    if use_mirror:
        notes.append("镜像加速已开启：从 npmmirror 下载 Node.js MSI")
        if log:
            log(notes[-1])
        ok2, detail2 = _install_node_msiexec(use_mirror=True)
        notes.append(detail2)
        if log:
            log(detail2.splitlines()[-1] if detail2 else "")
    else:
        notes.append("镜像加速已关闭：将走官方源 / winget，国内网络通常需要系统代理。")
        if log:
            log(notes[-1])
        ok, detail = _install_node_winget()
        notes.append(detail)
        if log:
            log("winget：" + (detail.splitlines()[-1] if detail else ("成功" if ok else "失败")))
        if ok and resolve_npm():
            return True, "\n".join(notes)
        notes.append("winget 不可用或未生效，改用官方 MSI 静默安装…")
        if log:
            log(notes[-1])
        ok2, detail2 = _install_node_msiexec(use_mirror=False)
        notes.append(detail2)
        if log:
            log(detail2.splitlines()[-1] if detail2 else "")

    npm = resolve_npm()
    if npm:
        notes.append(f"Node.js / npm 已就绪：{npm}")
        return True, "\n".join(notes)
    return False, "\n".join(notes) + "\n自动安装 Node.js 失败。请手动安装 https://nodejs.org （勾选加入 PATH）后重试。"

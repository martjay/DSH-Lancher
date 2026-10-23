"""Check / upgrade the globally installed @deepseek-ai/dsh package."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from dsh_launcher.dsh_cli import find_working_dsh, probe_dsh
from dsh_launcher.node_bootstrap import ensure_npm, has_npm, resolve_npm

PACKAGE = "@deepseek-ai/dsh"
_VERSION_RE = re.compile(r"^\s*v?(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?\s*$")


@dataclass(frozen=True)
class UpdateInfo:
    local: str | None
    latest: str | None
    available: bool
    error: str | None = None
    missing: bool = False  # dsh not installed on this machine
    need_node: bool = False  # npm / node missing


def _run(cmd: list[str], *, timeout: float = 90) -> tuple[int, str]:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
            shell=False,
        )
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        return 124, "命令超时"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out


def _creationflags() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _split_stream(buf: str) -> tuple[list[str], str]:
    """Turn npm \\r progress + newlines into whole lines; keep leftover."""
    lines: list[str] = []
    buf = buf.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" not in buf:
        return lines, buf
    *parts, rest = buf.split("\n")
    for part in parts:
        text = part.strip()
        if text:
            lines.append(text)
    return lines, rest


def _wrap_win_cmd(cmd: list[str]) -> list[str]:
    if sys.platform == "win32" and cmd and str(cmd[0]).lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/d", "/s", "/c", *cmd]
    return cmd


def _run_stream(
    cmd: list[str],
    *,
    timeout: float,
    log: Callable[[str], None] | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run a command and forward stdout/stderr as they arrive (not after exit)."""
    env = os.environ.copy()
    env["FORCE_COLOR"] = "0"
    env["NO_COLOR"] = "1"
    env["npm_config_progress"] = "false"
    env["npm_config_loglevel"] = "notice"
    env["npm_config_fund"] = "false"
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.Popen(
            _wrap_win_cmd(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            bufsize=0,
            env=env,
            creationflags=_creationflags(),
            shell=False,
        )
    except FileNotFoundError as exc:
        return 127, str(exc)

    collected: list[str] = []
    raw_q: queue.Queue[bytes | None] = queue.Queue()

    def reader() -> None:
        try:
            stdout = proc.stdout
            if not stdout:
                return
            while True:
                chunk = stdout.read(512)
                if not chunk:
                    break
                raw_q.put(chunk)
        finally:
            raw_q.put(None)

    threading.Thread(target=reader, name="dsh-cmd-reader", daemon=True).start()
    deadline = time.time() + timeout
    last_out = time.time()
    buf = ""

    def emit(text: str) -> None:
        collected.append(text)
        if log:
            log(text)

    while True:
        if time.time() > deadline:
            proc.kill()
            emit("命令超时，已中止。")
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
            return 124, "\n".join(collected)
        try:
            chunk = raw_q.get(timeout=0.5)
        except queue.Empty:
            if proc.poll() is not None:
                try:
                    leftover = raw_q.get(timeout=0.2)
                except queue.Empty:
                    break
                if leftover is None:
                    break
                chunk = leftover
            else:
                if log and time.time() - last_out >= 4:
                    log("仍在下载/安装，请稍候（npm 这一步可能要一两分钟）…")
                    last_out = time.time()
                continue
        if chunk is None:
            break
        buf += chunk.decode("utf-8", errors="replace")
        lines, buf = _split_stream(buf)
        for line in lines:
            last_out = time.time()
            emit(line)
    rest = buf.strip()
    if rest:
        emit(rest)
    code = proc.wait()
    return code, "\n".join(collected)


def is_dsh_installed() -> bool:
    """True only when a real CLI answers ``dsh --version``.

    Desktop leftover ``dsh.cmd`` shims must not count — they print
    CLI-not-found and used to leave the launcher stuck on Starting….
    """
    return find_working_dsh() is not None


def normalize_version(raw: str | None) -> str | None:
    if not raw:
        return None
    line = raw.strip().splitlines()[0].strip()
    # dsh --version may print just "0.1.1-rc.2"
    m = _VERSION_RE.match(line)
    if m:
        main, pre = m.group(1), m.group(2)
        return f"{main}-{pre}" if pre else main
    # fallback: first token that looks like a version
    for token in re.findall(r"v?\d+(?:\.\d+)+(?:-[0-9A-Za-z.-]+)?", line):
        m = _VERSION_RE.match(token)
        if m:
            main, pre = m.group(1), m.group(2)
            return f"{main}-{pre}" if pre else main
    return line or None


def _parse(v: str) -> tuple[tuple[int, ...], int, tuple]:
    """Sort key: release > prerelease; higher numbers win."""
    m = _VERSION_RE.match(v.strip())
    if not m:
        return ((0,), 0, (v,))
    nums = tuple(int(x) for x in m.group(1).split("."))
    pre = m.group(2)
    if not pre:
        return (nums, 1, ())
    bits: list = []
    for part in pre.split("."):
        if part.isdigit():
            bits.append((0, int(part)))
        else:
            bits.append((1, part))
    return (nums, 0, tuple(bits))


def is_newer(latest: str, local: str) -> bool:
    return _parse(latest) > _parse(local)


def read_local_version(*, timeout: float = 20) -> tuple[str | None, str | None]:
    dsh = find_working_dsh(timeout=min(timeout, 8))
    if not dsh:
        return None, "未找到可用的 dsh 命令（Desktop 空壳不算）"
    ok, out = probe_dsh(dsh, timeout=timeout)
    if not ok:
        return None, out or "dsh --version 失败"
    ver = normalize_version(out)
    if not ver or not _VERSION_RE.match(ver):
        return None, f"无法解析本地版本：{out!r}"
    return ver, None


def read_latest_version(*, use_mirror: bool = True) -> tuple[str | None, str | None]:
    npm = resolve_npm()
    if not npm:
        return None, "未找到 npm 命令"
    from dsh_launcher.mirrors import npm_registry_args

    extra = npm_registry_args(mirror=use_mirror)
    code, out = _run([npm, "view", PACKAGE, "version", *extra], timeout=60)
    if code != 0:
        return None, out or f"npm view 失败 ({code})"
    ver = normalize_version(out)
    if not ver:
        return None, f"无法解析远程版本：{out!r}"
    return ver, None


def check_update(*, use_mirror: bool = True) -> UpdateInfo:
    try:
        if not has_npm():
            return UpdateInfo(
                None,
                None,
                False,
                "未安装 Node.js / npm。一键安装会先自动安装 Node.js LTS，再安装 DSH。",
                missing=True,
                need_node=True,
            )
        local, err_l = read_local_version()
        if err_l and not local:
            latest, _err_r = read_latest_version(use_mirror=use_mirror)
            tip = "未检测到 DSH。可一键安装（npm 全局包 @deepseek-ai/dsh）。"
            return UpdateInfo(None, latest, False, tip, missing=True, need_node=False)
        latest, err_r = read_latest_version(use_mirror=use_mirror)
        if err_r and not latest:
            return UpdateInfo(local, None, False, err_r)
        assert local and latest
        return UpdateInfo(local, latest, is_newer(latest, local), None)
    except OSError as exc:
        winerr = getattr(exc, "winerror", None)
        if winerr == 5 or "拒绝访问" in str(exc) or "access is denied" in str(exc).lower():
            return UpdateInfo(
                None,
                None,
                False,
                "扫描 PATH 时碰到无权限的系统目录，已跳过。请再点「检查更新」。",
            )
        return UpdateInfo(None, None, False, str(exc))


def install_or_upgrade_latest(
    *,
    log: Callable[[str], None] | None = None,
    use_mirror: bool = True,
) -> tuple[bool, str]:
    from dsh_launcher.mirrors import NPM_REGISTRY, npm_registry_args

    ok_npm, npm_detail = ensure_npm(log=log, use_mirror=use_mirror)
    if not ok_npm:
        return False, npm_detail
    npm = resolve_npm()
    if not npm:
        return False, npm_detail + "\n仍未找到 npm。"
    extra = npm_registry_args(mirror=use_mirror)
    if log:
        log(f"使用 npm：{npm}")
        if use_mirror:
            log(f"镜像加速：{NPM_REGISTRY}")
        else:
            log("镜像加速已关闭：使用官方 registry。国内网络请打开系统代理后再安装。")
        log(f"执行：npm install -g {PACKAGE}@latest" + (" --registry npmmirror" if use_mirror else ""))
        log("开始下载依赖，下面会持续刷 npm 输出。")
    code, out = _run_stream(
        [
            npm,
            "install",
            "-g",
            f"{PACKAGE}@latest",
            *extra,
            "--progress",
            "false",
            "--loglevel",
            "notice",
        ],
        timeout=300,
        log=log,
    )
    if code != 0:
        return False, (npm_detail + "\n" + (out or f"安装失败 ({code})")).strip()
    from dsh_launcher.node_bootstrap import refresh_path

    refresh_path()
    return True, (
        (npm_detail + "\n" if "未找到 npm" in npm_detail or "自动安装" in npm_detail else "") + (out or "安装完成")
    ).strip()
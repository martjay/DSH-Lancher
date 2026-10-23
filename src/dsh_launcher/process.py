from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import psutil

from dsh_launcher.dsh_cli import resolve_dsh_argv
from dsh_launcher.paths import DEFAULT_HOST, DEFAULT_PORT, harness_cwd, web_profile_dir

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

LogFn = Callable[[str], None]

_CRASH_MARKERS = (
    "cordis-plugin-loader",
    "at async entry.update",
    "err_module_not_found",
    "cannot find package",
    "uncaught exception",
    "unhandledrejection",
)
_LOCK_TIMEOUT_MARK = "timed out waiting for the writer lock"
_LOCK_PID_RE = re.compile(r"^(\d+)\n?$")

_AUTH_URL_RE = re.compile(
    r"https?://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?/[^\s]*[?&]token=[A-Za-z0-9_\-]+",
    re.IGNORECASE,
)


def parse_auth_url(line: str) -> str | None:
    """Pick the dsh-web URL that includes the session token, if present."""
    match = _AUTH_URL_RE.search(line.strip())
    if not match:
        return None
    return match.group(0).rstrip(").,]\"'")


def port_pid(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> int | None:
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if not conn.laddr:
                continue
            if int(conn.laddr.port) != port:
                continue
            ip = str(conn.laddr.ip)
            if ip not in {host, "0.0.0.0", "::", "::1", "127.0.0.1"}:
                continue
            if conn.status == psutil.CONN_LISTEN and conn.pid:
                return int(conn.pid)
    except (psutil.AccessDenied, psutil.Error):
        pass
    return None


def is_listening(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port(up: bool, timeout: float = 20.0, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_listening(host, port) is up:
            return True
        time.sleep(0.2)
    return is_listening(host, port) is up


def kill_pid_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for proc in [*children, parent]:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs([*children, parent], timeout=4)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def kill_listeners(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> list[int]:
    seen: set[int] = set()
    for _ in range(8):
        pid = port_pid(host, port)
        if not pid or pid in seen:
            if not is_listening(host, port):
                break
        if pid:
            seen.add(pid)
            kill_pid_tree(pid)
        time.sleep(0.25)
    return sorted(seen)


def _lock_holder_pid(lock_path: Path) -> int | None:
    try:
        text = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _LOCK_PID_RE.fullmatch(text)
    if not match:
        return None
    pid = int(match.group(1))
    return pid if pid > 0 else None


def clear_stale_profile_locks(profile: Path | None = None) -> list[Path]:
    """Remove profile writer locks whose recorded process is gone.

    DSH serializes ``package.json`` writes with a sibling ``.lock``. A crash
    can leave that file behind; a later start then waits 2s and dies with
    ``atomic-write: timed out waiting for the writer lock``.
    """
    root = profile if profile is not None else web_profile_dir()
    removed: list[Path] = []
    for path in [root / "package.json.lock", *sorted(root.glob("package.json.lock.takeover-*"))]:
        if not path.is_file():
            continue
        pid = _lock_holder_pid(path)
        if pid is not None and psutil.pid_exists(pid):
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path)
    return removed


def resolve_dsh_command(*, no_open: bool = True) -> list[str]:
    extra = ["--no-open"] if no_open else []
    try:
        return resolve_dsh_argv("web", *extra)
    except FileNotFoundError:
        npx = shutil.which("npx.cmd") or shutil.which("npx")
        if npx:
            if npx.lower().endswith((".cmd", ".bat")):
                return ["cmd.exe", "/d", "/s", "/c", npx, "--yes", "@deepseek-ai/dsh", "web", *extra]
            return [npx, "--yes", "@deepseek-ai/dsh", "web", *extra]
        raise FileNotFoundError("找不到可用的 DSH CLI / npx，请先安装 @deepseek-ai/dsh") from None


class HarnessProcess:
    def __init__(self, log: LogFn, get_port: Callable[[], int]) -> None:
        self._log = log
        self._get_port = get_port
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self.stopping = False
        self.fail_hint: str | None = None
        self.web_url: str | None = None

    @property
    def port(self) -> int:
        return int(self._get_port())

    @property
    def pid(self) -> int | None:
        proc = self._proc
        return proc.pid if proc and proc.poll() is None else None

    def alive(self) -> bool:
        proc = self._proc
        return bool(proc and proc.poll() is None)

    def start(self) -> None:
        with self._lock:
            if self.alive():
                return
            self.stopping = False
            self.fail_hint = None
            self.web_url = None
            cmd = resolve_dsh_command()
            cwd = harness_cwd()
            self._log("启动命令: " + " ".join(cmd))
            self._log(f"工作目录: {cwd}")
            for stale in clear_stale_profile_locks():
                self._log(f"已清除过期写锁: {stale}")
            flags = 0
            if sys.platform == "win32":
                flags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            env = os.environ.copy()
            env["DSH_TELEMETRY_DISABLED"] = "1"
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=flags,
                env=env,
            )
            self._reader = threading.Thread(target=self._pump, daemon=True)
            self._reader.start()

    def _pump(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            text = line.rstrip("\r\n")
            if not text:
                continue
            low = text.lower()
            if "cli not found" in low or "please run deepseek harness desktop" in low:
                self.fail_hint = "未找到 Harness CLI，请先安装 DSH"
            elif _LOCK_TIMEOUT_MARK in low:
                self.fail_hint = (
                    "插件加载时抢写配置超时（package.json.lock）。清过期锁解决不了："
                    "多半是 dsh-plugin-zero-token 等插件在启动瞬间 settings.update，"
                    "DSH 写锁只等 2 秒。请更新/重装该插件后再启动。"
                )
            elif any(marker in low for marker in _CRASH_MARKERS):
                self.fail_hint = "插件层加载失败，进程已退出。升级 DSH 后部分旧插件可能不兼容。"
            auth = parse_auth_url(text)
            if auth:
                self.web_url = auth
            self._log(text)

    def stop(self, port: int | None = None) -> None:
        listen = int(port) if port is not None else self.port
        self.stopping = True
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc and proc.poll() is None:
            self._log(f"停止进程树 pid={proc.pid}")
            kill_pid_tree(proc.pid)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        killed = kill_listeners(port=listen)
        if killed:
            self._log(f"已释放端口 {listen}，结束 pid=" + ",".join(str(p) for p in killed))
        wait_port(False, timeout=8, port=listen)
        self.web_url = None

    def wait_ready(self, timeout: float, port: int, *, token_wait: float = 12.0) -> str:
        """Poll until the port is up, the child exits, or time runs out.

        Returns ``ready`` | ``exited`` | ``timeout``.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if is_listening(port=port):
                token_until = time.time() + token_wait
                while time.time() < token_until:
                    if self.web_url:
                        return "ready"
                    if not self.alive():
                        return "exited"
                    time.sleep(0.1)
                return "ready"
            if not self.alive():
                return "exited"
            time.sleep(0.15)
        if is_listening(port=port):
            return "ready"
        if not self.alive():
            return "exited"
        return "timeout"

    def restart(self) -> None:
        self._log("手动重启 Harness…")
        self.stop()
        time.sleep(0.4)
        self.start()

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from dsh_launcher.process import HarnessProcess, clear_stale_profile_locks, parse_auth_url


class _FakeProc:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def poll(self):
        return None if self._alive else 1


def test_wait_ready_exits_fast() -> None:
    hp = HarnessProcess(lambda _l: None, lambda: 9)
    hp._proc = _FakeProc(False)  # type: ignore[assignment]
    with patch("dsh_launcher.process.is_listening", return_value=False):
        assert hp.wait_ready(timeout=5, port=9) == "exited"


def test_wait_ready_ready() -> None:
    hp = HarnessProcess(lambda _l: None, lambda: 9)
    hp._proc = _FakeProc(True)  # type: ignore[assignment]
    with patch("dsh_launcher.process.is_listening", return_value=True):
        assert hp.wait_ready(timeout=5, port=9, token_wait=0) == "ready"


def test_clear_stale_profile_locks_drops_dead_pid() -> None:
    root = Path(tempfile.mkdtemp())
    lock = root / "package.json.lock"
    lock.write_text("1\n", encoding="utf-8")
    with patch("dsh_launcher.process.psutil.pid_exists", return_value=False):
        removed = clear_stale_profile_locks(root)
    assert removed == [lock]
    assert not lock.exists()


def test_clear_stale_profile_locks_keeps_live_pid() -> None:
    root = Path(tempfile.mkdtemp())
    lock = root / "package.json.lock"
    lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    with patch("dsh_launcher.process.psutil.pid_exists", return_value=True):
        removed = clear_stale_profile_locks(root)
    assert removed == []
    assert lock.exists()


def test_parse_auth_url() -> None:
    assert parse_auth_url("http://127.0.0.1:28467/") is None
    url = parse_auth_url(
        "http://127.0.0.1:28467/?token=mpivmMo3YBhVnT-DnyLVySCJwS5i4QS_74-siOHIFhA"
    )
    assert url and "token=" in url
    assert parse_auth_url("noise http://127.0.0.1:3080/?token=abc-def extra") == "http://127.0.0.1:3080/?token=abc-def"

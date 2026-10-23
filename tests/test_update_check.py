"""Unit tests for DSH version compare / normalize / install stream."""

from __future__ import annotations

import sys
from unittest.mock import patch

from dsh_launcher.update_check import (
    _run_stream,
    _split_stream,
    is_dsh_installed,
    is_newer,
    normalize_version,
    read_local_version,
)


def test_normalize_plain() -> None:
    assert normalize_version("0.1.1-rc.2") == "0.1.1-rc.2"
    assert normalize_version("v0.1.1\n") == "0.1.1"


def test_is_newer_prerelease() -> None:
    assert is_newer("0.1.1-rc.3", "0.1.1-rc.2")
    assert not is_newer("0.1.1-rc.2", "0.1.1-rc.2")
    assert is_newer("0.1.1", "0.1.1-rc.9")
    assert is_newer("0.1.2-rc.1", "0.1.1")


def test_stub_cli_is_not_installed() -> None:
    with patch("dsh_launcher.update_check.find_working_dsh", return_value=None):
        assert is_dsh_installed() is False
        ver, err = read_local_version(timeout=1)
        assert ver is None
        assert err


def test_split_stream_cr_and_newline() -> None:
    lines, rest = _split_stream("a\rb\npartial")
    assert lines == ["a", "b"]
    assert rest == "partial"


def test_run_stream_forwards_lines() -> None:
    seen: list[str] = []
    code, out = _run_stream(
        [sys.executable, "-c", "import sys; print('hello', flush=True); print('world', flush=True)"],
        timeout=15,
        log=seen.append,
    )
    assert code == 0
    assert "hello" in out
    assert "world" in out
    assert any("hello" in line for line in seen)

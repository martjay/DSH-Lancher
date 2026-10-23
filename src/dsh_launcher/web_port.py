from __future__ import annotations

import re
from pathlib import Path

from dsh_launcher.paths import DEFAULT_PORT
from dsh_launcher.search_patch import ensure_patch_file, write_patch

_DEFAULT_PORT_EXPR = f"!!js ctx.webStartup.port ?? {DEFAULT_PORT}"


def _webserver_span(text: str) -> tuple[int, int] | None:
    start = re.search(r"(?m)^- id:\s*webserver\s*$", text)
    if not start:
        return None
    rest = text[start.end() :]
    nxt = re.search(r"(?m)^- id:", rest)
    end = start.end() + (nxt.start() if nxt else len(rest))
    return start.start(), end


def read_configured_port(text: str) -> int:
    span = _webserver_span(text)
    block = text[span[0] : span[1]] if span else text
    literal = re.search(r"(?m)^\s+port:\s*(\d+)\s*$", block)
    if literal:
        return int(literal.group(1))
    fallback = re.search(r"webStartup\.port\s*\?\?\s*(\d+)", block)
    if fallback:
        return int(fallback.group(1))
    return DEFAULT_PORT


def is_default_port_expr(text: str) -> bool:
    span = _webserver_span(text)
    block = text[span[0] : span[1]] if span else text
    return bool(
        re.search(
            rf"(?m)^\s+port:\s*!!js ctx\.webStartup\.port \?\? {DEFAULT_PORT}\s*$",
            block,
        )
    )


def apply_web_port(text: str, port: int | None) -> str:
    """Set webserver port. None restores the official !!js fallback."""
    span = _webserver_span(text)
    if span is None:
        raise ValueError("cordis.patch.yml 里没有 webserver 段")
    block = text[span[0] : span[1]]
    if port is None:
        repl = f"    port: {_DEFAULT_PORT_EXPR}"
    else:
        n = int(port)
        if n < 1 or n > 65535:
            raise ValueError("端口必须在 1–65535")
        repl = f"    port: {n}"
    if re.search(r"(?m)^\s+port:\s*.+$", block):
        new_block = re.sub(r"(?m)^\s+port:\s*.+$", repl, block, count=1)
    else:
        new_block = block.rstrip() + "\n" + repl + "\n"
    return text[: span[0]] + new_block + text[span[1] :]


def set_web_port(port: int | None, path: Path | None = None) -> bool:
    target = ensure_patch_file(path)
    before = target.read_text(encoding="utf-8")
    after = apply_web_port(before, port)
    if after == before:
        return False
    write_patch(after, target)
    return True


def current_web_port(path: Path | None = None) -> int:
    return read_configured_port(ensure_patch_file(path).read_text(encoding="utf-8"))

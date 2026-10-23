from __future__ import annotations

import re
from pathlib import Path

from dsh_launcher.paths import web_patch_path

SEARCH_BLOCK = """# DSH-Launcher: disable built-in DeepSeek web search (use free-search plugin)
- id: web-search-deepseek
  disabled: true
- id: tool-web
  config:
    search: false
"""

_HEADER = """# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).
"""

_WEBSERVER = """- id: webserver
  name: '@deepseek-ai/dsh-host-webserver'
  config:
    host: !!js ctx.webStartup.host ?? '127.0.0.1'
    port: !!js ctx.webStartup.port ?? 3080
"""

_SKIP_IDS = {"web-search-deepseek", "tool-web"}
_COMMENT_NEEDLES = (
    "Disable built-in DeepSeek web search",
    "DSH-Launcher: disable built-in DeepSeek web search",
)


def _is_top_level_id(line: str) -> str | None:
    if not line.startswith("- id:"):
        return None
    return line[len("- id:") :].strip().split()[0] if line[len("- id:") :].strip() else ""


def strip_builtin_search_entries(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped.startswith("#") and any(n in raw for n in _COMMENT_NEEDLES):
            i += 1
            continue
        ident = _is_top_level_id(raw)
        if ident in _SKIP_IDS:
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.startswith("- id:") or (nxt.startswith("- ") and not nxt.startswith(" ")):
                    break
                if nxt.startswith("- id:"):
                    break
                i += 1
            continue
        out.append(raw)
        i += 1
    cleaned = "\n".join(out).rstrip() + "\n"
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def builtin_search_disabled(text: str) -> bool:
    if re.search(r"(?m)^- id:\s*web-search-deepseek\s*$", text) and re.search(
        r"(?m)^\s+disabled:\s*true\s*$", text
    ):
        if re.search(r"(?m)^- id:\s*tool-web\s*$", text) and re.search(
            r"(?m)^\s+search:\s*false\s*$", text
        ):
            return True
    return False


def apply_disable_builtin_search(text: str) -> str:
    body = strip_builtin_search_entries(text).rstrip() + "\n\n" + SEARCH_BLOCK
    return body.rstrip() + "\n"


def apply_enable_builtin_search(text: str) -> str:
    return strip_builtin_search_entries(text)


def ensure_patch_file(path: Path | None = None) -> Path:
    target = path or web_patch_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or not target.read_text(encoding="utf-8").strip():
        target.write_text(_HEADER + _WEBSERVER, encoding="utf-8")
    return target


def read_patch(path: Path | None = None) -> str:
    target = ensure_patch_file(path)
    return target.read_text(encoding="utf-8")


def write_patch(text: str, path: Path | None = None) -> Path:
    target = path or web_patch_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return target


def set_disable_builtin_search(enabled: bool, path: Path | None = None) -> bool:
    """When enabled=True, write the disable-builtin-search patch.

    Returns whether the file actually changed.
    """
    target = ensure_patch_file(path)
    before = target.read_text(encoding="utf-8")
    after = apply_disable_builtin_search(before) if enabled else apply_enable_builtin_search(before)
    if after == before:
        return False
    write_patch(after, target)
    return True


def is_disable_builtin_search_on(path: Path | None = None) -> bool:
    return builtin_search_disabled(read_patch(path))

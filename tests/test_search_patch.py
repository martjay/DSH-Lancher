from __future__ import annotations

from pathlib import Path

from dsh_launcher.search_patch import (
    SEARCH_BLOCK,
    apply_disable_builtin_search,
    apply_enable_builtin_search,
    builtin_search_disabled,
    set_disable_builtin_search,
)
from dsh_launcher.web_port import apply_web_port, is_default_port_expr, read_configured_port

SAMPLE = """# header
- id: webserver
  name: '@deepseek-ai/dsh-host-webserver'
  config:
    host: !!js ctx.webStartup.host ?? '127.0.0.1'
    port: !!js ctx.webStartup.port ?? 28467
"""


def test_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "cordis.patch.yml"
    p.write_text(SAMPLE, encoding="utf-8")
    assert not builtin_search_disabled(p.read_text(encoding="utf-8"))
    assert set_disable_builtin_search(True, p) is True
    text = p.read_text(encoding="utf-8")
    assert "!!js ctx.webStartup.host" in text
    assert builtin_search_disabled(text)
    assert SEARCH_BLOCK.splitlines()[0] in text
    assert set_disable_builtin_search(True, p) is False
    assert set_disable_builtin_search(False, p) is True
    restored = p.read_text(encoding="utf-8")
    assert not builtin_search_disabled(restored)
    assert "web-search-deepseek" not in restored
    assert "tool-web" not in restored
    assert "!!js ctx.webStartup.port" in restored


def test_strips_legacy_comment_block() -> None:
    legacy = SAMPLE + """
# Disable built-in DeepSeek web search; use local searxng MCP instead
- id: web-search-deepseek
  disabled: true
- id: tool-web
  config:
    search: false
"""
    off = apply_enable_builtin_search(legacy)
    assert "web-search-deepseek" not in off
    on = apply_disable_builtin_search(off)
    assert builtin_search_disabled(on)


def test_port_roundtrip() -> None:
    assert read_configured_port(SAMPLE) == 28467
    assert not is_default_port_expr(SAMPLE)
    custom = apply_web_port(SAMPLE, 30080)
    assert read_configured_port(custom) == 30080
    assert "port: 30080" in custom
    assert "!!js ctx.webStartup.host" in custom
    back = apply_web_port(custom, None)
    assert is_default_port_expr(back)
    assert read_configured_port(back) == 3080
    assert "?? 3080" in back
    with_search = apply_disable_builtin_search(custom)
    again = apply_web_port(with_search, 19000)
    assert builtin_search_disabled(again)
    assert read_configured_port(again) == 19000


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_roundtrip(Path(d))
    test_strips_legacy_comment_block()
    test_port_roundtrip()
    print("ok: search_patch")

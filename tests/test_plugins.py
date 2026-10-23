from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from dsh_launcher.plugins import (
    PluginInfo,
    _scan_text,
    add_plugin_with_exemption,
    is_enabled,
    is_hot_overlay,
    list_user_plugins,
    parse_allow_version_hints,
    plugin_matches_filter,
    preserve_hot_overlays,
    set_enabled,
    spec_declared_version,
    spec_is_exact_pin,
    spec_source,
    update_flags,
)


def test_spec_source() -> None:
    assert spec_source("file:D:/x.tgz") == "file"
    assert spec_source("git+https://github.com/a/b.git") == "git"
    assert spec_source("github:foo/bar") == "git"
    assert spec_source("^0.18.0") == "npm"


def test_update_flags_pinned_newer_is_update() -> None:
    assert update_flags("file", "1.11.2", "1.66.5") == (True, False, False)
    assert update_flags("npm", "1.11.2", "1.66.5") == (True, False, False)
    assert update_flags("file", "1.66.5", "1.66.5") == (False, True, False)
    assert update_flags("npm", "1.66.5", "1.66.5") == (False, False, False)
    assert update_flags("npm", "2.5.7", "2.1.0") == (False, False, True)


def test_preserve_hot_overlays_restores_downgrade() -> None:
    home = Path(tempfile.mkdtemp())
    pkg = home / "node_modules" / "dsh-our-free-model"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"name":"dsh-our-free-model","version":"2.5.7"}\n', encoding="utf-8")
    (pkg / "keep.txt").write_text("hot", encoding="utf-8")
    (home / "package.json").write_text(
        json.dumps({"dependencies": {"dsh-our-free-model": "2.1.0"}}),
        encoding="utf-8",
    )

    def smash() -> tuple[int, str]:
        (pkg / "package.json").write_text('{"name":"dsh-our-free-model","version":"2.1.0"}\n', encoding="utf-8")
        (pkg / "keep.txt").write_text("npm", encoding="utf-8")
        return 0, "ok"

    with patch("dsh_launcher.plugins.web_profile_dir", lambda: home):
        code, _out = preserve_hot_overlays(smash)
    assert code == 0
    assert json.loads((pkg / "package.json").read_text(encoding="utf-8"))["version"] == "2.5.7"
    assert (pkg / "keep.txt").read_text(encoding="utf-8") == "hot"


def test_hot_overlay_exact_pin() -> None:
    assert spec_is_exact_pin("2.1.0")
    assert not spec_is_exact_pin("^2.1.0")
    assert spec_declared_version("^0.9.11") == "0.9.11"
    assert is_hot_overlay("2.5.7", "2.1.0")
    assert not is_hot_overlay("2.1.0", "2.1.0")
    assert not is_hot_overlay("0.9.13", "^0.9.11")
    assert is_hot_overlay("2.5.7", "^2.1.0", "2.1.0")


def test_scan_import_not_comment() -> None:
    bad = 'import { settingsNamespace } from "@deepseek-ai/dsh-settings";\n'
    ok = "// the runtime helper this used to call (settingsNamespace) is gone\n"
    assert _scan_text(bad) == "incompat_settings"
    assert _scan_text(ok) is None
    assert _scan_text("ctx.subagents.registerContinuableSetup(() => {})") == "incompat_subagents"


def test_disable_enable(tmp_path: Path | None = None) -> None:
    import tempfile

    home = Path(tempfile.mkdtemp())
    (home / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"dsh-at-file": "^1.0.0"},
                "dsh": {"profile": {"bundles": ["dsh-at-file"], "disabledBundles": []}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    with patch("dsh_launcher.plugins.web_profile_dir", lambda: home):
        rows = list_user_plugins()
        assert rows[0].name == "dsh-at-file"
        assert rows[0].enabled is True
        set_enabled("dsh-at-file", False)
        assert is_enabled("dsh-at-file") is False
        data = json.loads((home / "package.json").read_text(encoding="utf-8"))
        assert "dsh-at-file" in data["dsh"]["profile"]["disabledBundles"]
        assert "dsh-at-file" not in data["dsh"]["profile"]["bundles"]
        set_enabled("dsh-at-file", True)
        assert is_enabled("dsh-at-file") is True


def test_plugin_matches_filter() -> None:
    row = PluginInfo(
        name="demo",
        spec="^1.0.0",
        installed="1.0.0",
        latest="1.1.0",
        source="npm",
        enabled=True,
        incompatible=False,
        reason_key=None,
        update_available=True,
    )
    assert plugin_matches_filter(row, "all")
    assert plugin_matches_filter(row, "updates")
    assert not plugin_matches_filter(row, "bad")
    assert not plugin_matches_filter(row, "off")
    off = PluginInfo(**{**row.__dict__, "enabled": False, "update_available": False})
    assert plugin_matches_filter(off, "off")
    hot = PluginInfo(**{**row.__dict__, "update_available": False, "ahead_of_registry": True})
    assert not plugin_matches_filter(hot, "updates")
    bad = PluginInfo(**{**row.__dict__, "incompatible": True, "update_available": False})
    assert plugin_matches_filter(bad, "bad")
    pinned = PluginInfo(
        **{**row.__dict__, "source": "file", "update_available": False, "switch_to_npm": True}
    )
    assert plugin_matches_filter(pinned, "updates")


def test_parse_allow_version_hints() -> None:
    raw = """dsh: plugin command failed
dsh: dsh-better-sidebar@0.24.1 is not compatible with DSH 0.1.7-rc.2
dsh: nothing was installed
dsh: to accept the risk, run: dsh plugin --profile web allow-version dsh-better-sidebar@0.24.1 --dsh-version 0.1.7-rc.2 --accept-risk
"""
    assert parse_allow_version_hints(raw) == [("dsh-better-sidebar@0.24.1", "0.1.7-rc.2")]
    assert parse_allow_version_hints("ok") == []


def test_add_plugin_with_exemption_retries(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake(*args, log=None, timeout=180):
        calls.append(args)
        if args[0] == "add" and len(calls) == 1:
            return 1, "allow-version foo@2 --dsh-version 0.1.7-rc.2 --accept-risk"
        return 0, "ok"

    monkeypatch.setattr("dsh_launcher.plugins.run_dsh_plugin", fake)
    code, _out = add_plugin_with_exemption("foo@2")
    assert code == 0
    assert calls[0] == ("add", "foo@2")
    assert calls[1] == (
        "allow-version",
        "foo@2",
        "--dsh-version",
        "0.1.7-rc.2",
        "--accept-risk",
    )
    assert calls[2] == ("add", "foo@2")

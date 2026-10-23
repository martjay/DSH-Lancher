"""Read / mutate the web profile plugins, scan for known DSH API breaks."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from dsh_launcher.dsh_cli import find_working_dsh, wrap_cmd
from dsh_launcher.i18n import t
from dsh_launcher.mirrors import npm_registry_args
from dsh_launcher.node_bootstrap import resolve_npm
from dsh_launcher.paths import web_profile_dir
from dsh_launcher.update_check import _run, _run_stream, is_newer, normalize_version

CORE_BUNDLES = frozenset(
    {
        "@deepseek-ai/dsh-base",
        "@deepseek-ai/dsh-web-app",
    }
)

_SPEC_VER_RE = re.compile(r"(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?)")
_EXACT_PIN_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?$")

_INCOMPAT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"import\s*\{[^}]*\bsettingsNamespace\b"), "incompat_settings"),
    (re.compile(r"import\s*\{[^}]*\binstallSettingsSection\b"), "incompat_settings"),
    (re.compile(r"registerContinuableSetup\s*\("), "incompat_subagents"),
)


def _scan_text(text: str) -> str | None:
    for pattern, key in _INCOMPAT_RULES:
        if pattern.search(text):
            return key
    return None


@dataclass
class PluginInfo:
    name: str
    spec: str
    installed: str | None
    latest: str | None
    source: str
    enabled: bool
    incompatible: bool
    reason_key: str | None
    update_available: bool
    switch_to_npm: bool = False
    ahead_of_registry: bool = False


def profile_manifest_path() -> Path:
    return web_profile_dir() / "package.json"


def load_manifest() -> dict:
    path = profile_manifest_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_manifest(data: dict) -> None:
    path = profile_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def spec_source(spec: str) -> str:
    s = str(spec)
    if s.startswith("file:") or s.startswith("link:"):
        return "file"
    if s.startswith("github:") or "git+" in s or s.startswith("git:"):
        return "git"
    return "npm"


def _pkg_dir(name: str) -> Path:
    return web_profile_dir() / "node_modules" / Path(*name.split("/"))


def installed_version(name: str) -> str | None:
    path = _pkg_dir(name) / "package.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ver = raw.get("version") if isinstance(raw, dict) else None
    return str(ver) if ver else None


def scan_incompat(name: str) -> str | None:
    root = _pkg_dir(name)
    if not root.is_dir():
        return None
    candidates = [
        root / "lib" / "index.js",
        root / "dist" / "index.js",
        root / "index.js",
    ]
    for path in candidates:
        try:
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")[:400_000]
        except OSError:
            continue
        hit = _scan_text(text)
        if hit:
            return hit
    return None


def _profile_lists(data: dict) -> tuple[list[str], list[str]]:
    profile = ((data.get("dsh") or {}).get("profile") or {}) if isinstance(data.get("dsh"), dict) else {}
    bundles = [str(x) for x in (profile.get("bundles") or []) if x]
    disabled = [str(x) for x in (profile.get("disabledBundles") or []) if x]
    return bundles, disabled


def is_enabled(name: str, data: dict | None = None) -> bool:
    data = data if data is not None else load_manifest()
    bundles, disabled = _profile_lists(data)
    if name in disabled:
        return False
    if name in CORE_BUNDLES:
        return True
    return name in bundles


def list_user_plugins() -> list[PluginInfo]:
    data = load_manifest()
    deps = data.get("dependencies") if isinstance(data.get("dependencies"), dict) else {}
    bundles, _disabled = _profile_lists(data)
    names: list[str] = []
    for name in [*deps.keys(), *bundles]:
        if name in CORE_BUNDLES or name in names:
            continue
        names.append(str(name))
    rows: list[PluginInfo] = []
    for name in names:
        spec = str(deps.get(name) or "")
        inst = installed_version(name)
        reason = scan_incompat(name)
        src = spec_source(spec) if spec else "npm"
        rows.append(
            PluginInfo(
                name=name,
                spec=spec,
                installed=inst,
                latest=None,
                source=src,
                enabled=is_enabled(name, data),
                incompatible=bool(reason),
                reason_key=reason,
                update_available=False,
                switch_to_npm=False,
            )
        )
    return rows


def fetch_latest(name: str, *, use_mirror: bool) -> str | None:
    npm = resolve_npm()
    if not npm:
        return None
    extra = npm_registry_args(mirror=use_mirror)
    code, out = _run([npm, "view", name, "version", *extra], timeout=25)
    if code != 0:
        return None
    return normalize_version(out)


def spec_declared_version(spec: str) -> str | None:
    s = str(spec).strip()
    if not s or spec_source(s) != "npm":
        return None
    match = _SPEC_VER_RE.search(s)
    return match.group(1) if match else None


def spec_is_exact_pin(spec: str) -> bool:
    return bool(_EXACT_PIN_RE.fullmatch(str(spec).strip()))


def is_hot_overlay(installed: str | None, spec: str, latest: str | None = None) -> bool:
    """True when on-disk files are newer than npm / the exact profile pin (in-app hot update)."""
    if not installed:
        return False
    if latest and is_newer(installed, latest):
        return True
    declared = spec_declared_version(spec)
    return bool(spec_is_exact_pin(spec) and declared and is_newer(installed, declared))


def update_flags(source: str, installed: str | None, latest: str | None) -> tuple[bool, bool, bool]:
    """Return ``(update_available, switch_to_npm, ahead_of_registry)``."""
    ahead = bool(latest and installed and is_newer(installed, latest))
    newer = bool(latest and installed and is_newer(latest, installed))
    if latest and not installed and source != "npm":
        newer = True
    if ahead:
        newer = False
    switch = source != "npm" and not newer and not ahead
    return newer, switch, ahead


def enrich_updates(rows: list[PluginInfo], *, use_mirror: bool) -> list[PluginInfo]:
    found: dict[str, str | None] = {}
    if rows:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = {pool.submit(fetch_latest, row.name, use_mirror=use_mirror): row.name for row in rows}
            for fut in as_completed(futs):
                name = futs[fut]
                try:
                    found[name] = fut.result()
                except Exception:
                    found[name] = None
    out: list[PluginInfo] = []
    for row in rows:
        latest = found.get(row.name)
        update, switch, ahead = update_flags(row.source, row.installed, latest)
        if not ahead:
            ahead = is_hot_overlay(row.installed, row.spec, latest)
        out.append(
            PluginInfo(
                name=row.name,
                spec=row.spec,
                installed=row.installed,
                latest=latest,
                source=row.source,
                enabled=row.enabled,
                incompatible=row.incompatible,
                reason_key=row.reason_key,
                update_available=update,
                switch_to_npm=switch,
                ahead_of_registry=ahead,
            )
        )
    return out


def enabled_incompatible() -> list[PluginInfo]:
    return [row for row in list_user_plugins() if row.enabled and row.incompatible]


def set_enabled(name: str, enabled: bool) -> None:
    data = load_manifest()
    profile = data.setdefault("dsh", {}).setdefault("profile", {})
    bundles = [str(x) for x in (profile.get("bundles") or []) if x]
    disabled = [str(x) for x in (profile.get("disabledBundles") or []) if x]
    if enabled:
        disabled = [x for x in disabled if x != name]
        if name not in bundles and name not in CORE_BUNDLES:
            bundles.append(name)
    else:
        bundles = [x for x in bundles if x != name]
        if name not in disabled:
            disabled.append(name)
    profile["bundles"] = bundles
    profile["disabledBundles"] = disabled
    save_manifest(data)


def plugin_matches_filter(row: PluginInfo, filt: str) -> bool:
    if filt in {"", "all"}:
        return True
    if filt == "updates":
        return bool(row.update_available or row.switch_to_npm)
    if filt == "bad":
        return bool(row.incompatible)
    if filt == "off":
        return not row.enabled
    return True


_ALLOW_VERSION_RE = re.compile(
    r"allow-version\s+(\S+)\s+--dsh-version\s+(\S+)",
    re.IGNORECASE,
)


def parse_allow_version_hints(output: str) -> list[tuple[str, str]]:
    """Extract ``(package@version, dsh-version)`` pairs from a failed ``dsh plugin add``."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for pkg, runtime in _ALLOW_VERSION_RE.findall(output or ""):
        key = (pkg.strip(), runtime.strip().rstrip("."))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def spec_package_name(spec: str) -> str:
    s = str(spec).strip()
    if s.startswith("@"):
        rest = s[1:]
        pkg, _sep, _ver = rest.partition("@")
        return "@" + pkg
    return s.split("@", 1)[0]


def collect_hot_overlays(*, exclude: set[str] | None = None) -> dict[str, str]:
    skip = exclude or set()
    data = load_manifest()
    deps = data.get("dependencies") if isinstance(data.get("dependencies"), dict) else {}
    found: dict[str, str] = {}
    for name, spec in deps.items():
        if str(name) in CORE_BUNDLES or str(name) in skip:
            continue
        inst = installed_version(str(name))
        if inst and is_hot_overlay(inst, str(spec)):
            found[str(name)] = inst
    return found


def preserve_hot_overlays(
    fn: Callable[[], tuple[int, str]],
    *,
    exclude: set[str] | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """Keep in-app hot-updated plugin trees if pnpm reinstalls the npm pin."""
    overlays = collect_hot_overlays(exclude=exclude)
    if not overlays:
        return fn()
    backups: dict[str, Path] = {}
    root = Path(tempfile.mkdtemp(prefix="dsh-overlay-"))
    try:
        for name, version in overlays.items():
            src = _pkg_dir(name)
            if not src.is_dir():
                continue
            dest = root / name.replace("/", "__")
            shutil.copytree(src, dest, dirs_exist_ok=True)
            backups[name] = dest
            if log:
                log(t("plugins_hot_guard", name=name, ver=version))
        result = fn()
        for name, version in overlays.items():
            bak = backups.get(name)
            if bak is None or not bak.is_dir():
                continue
            current = installed_version(name)
            if current == version or (current and is_newer(current, version)):
                continue
            dest = _pkg_dir(name)
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(bak, dest)
            except OSError as exc:
                if log:
                    log(t("plugins_hot_restore_fail", name=name, err=str(exc)))
                continue
            if log:
                log(t("plugins_hot_restored", name=name, old=current or "—", ver=version))
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run_dsh_plugin(
    *args: str,
    log: Callable[[str], None] | None = None,
    timeout: float = 180,
) -> tuple[int, str]:
    dsh = find_working_dsh()
    if not dsh:
        return 127, "未找到可用的 dsh"

    def go() -> tuple[int, str]:
        return _run_stream(wrap_cmd(dsh, "plugin", "--profile", "web", *args), timeout=timeout, log=log)

    action = args[0] if args else ""
    if action not in {"add", "remove"}:
        return go()
    exclude: set[str] = set()
    if len(args) > 1:
        exclude.add(spec_package_name(args[1]) if action == "add" else str(args[1]))
    return preserve_hot_overlays(go, exclude=exclude, log=log)


def add_plugin_with_exemption(
    spec: str,
    log: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """Install/update a plugin; grant DSH version exemptions if the CLI asks for them."""
    code, out = run_dsh_plugin("add", spec, log=log)
    if code == 0:
        return code, out
    hints = parse_allow_version_hints(out)
    if not hints:
        return code, out
    if log:
        log(t("plugins_exempt_retry"))
    for pkg, runtime in hints:
        ac, aout = run_dsh_plugin(
            "allow-version",
            pkg,
            "--dsh-version",
            runtime,
            "--accept-risk",
            log=log,
        )
        if ac != 0:
            return ac, aout or out
    return run_dsh_plugin("add", spec, log=log)


def switch_plugin_to_npm(
    name: str,
    log: Callable[[str], None] | None = None,
    version: str | None = None,
) -> tuple[int, str]:
    """Drop a file:/git: pin and install the official npm package (optionally a version)."""
    code, out = run_dsh_plugin("remove", name, log=log)
    if code != 0:
        return code, out
    spec = f"{name}@{version}" if version and version != "latest" else name
    return add_plugin_with_exemption(spec, log=log)


def install_plugin_update(
    name: str,
    version: str,
    *,
    unpin: bool,
    log: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """Install ``name@version`` from npm; uninstall a file/git pin first when needed."""
    if unpin:
        return switch_plugin_to_npm(name, log=log, version=version)
    return add_plugin_with_exemption(f"{name}@{version}", log=log)

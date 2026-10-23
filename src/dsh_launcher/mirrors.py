"""China-region download mirrors (npmmirror)."""

from __future__ import annotations

NPM_REGISTRY = "https://registry.npmmirror.com"
NODE_INDEX_MIRROR = "https://cdn.npmmirror.com/binaries/node/index.json"
NODE_INDEX_OFFICIAL = "https://nodejs.org/dist/index.json"


def node_msi_url(version: str, *, mirror: bool) -> str:
    # version like v24.20.0
    name = f"node-{version}-x64.msi"
    if mirror:
        return f"https://cdn.npmmirror.com/binaries/node/{version}/{name}"
    return f"https://nodejs.org/dist/{version}/{name}"


def node_index_url(*, mirror: bool) -> str:
    return NODE_INDEX_MIRROR if mirror else NODE_INDEX_OFFICIAL


def npm_registry_args(*, mirror: bool) -> list[str]:
    if mirror:
        return ["--registry", NPM_REGISTRY]
    return []

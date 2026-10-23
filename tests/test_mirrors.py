"""Tests for China-region mirror helpers."""

from __future__ import annotations

from dsh_launcher.mirrors import NPM_REGISTRY, node_index_url, node_msi_url, npm_registry_args


def test_registry_args_on() -> None:
    assert npm_registry_args(mirror=True) == ["--registry", NPM_REGISTRY]


def test_registry_args_off() -> None:
    assert npm_registry_args(mirror=False) == []


def test_node_urls() -> None:
    assert "npmmirror" in node_index_url(mirror=True)
    assert "nodejs.org" in node_index_url(mirror=False)
    msi = node_msi_url("v24.20.0", mirror=True)
    assert msi.endswith("node-v24.20.0-x64.msi")
    assert "npmmirror" in msi

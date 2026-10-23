from __future__ import annotations

from dsh_launcher.watch import watch_disconnect


def test_crash_does_not_autostart() -> None:
    d = watch_disconnect(
        listening=False,
        child=False,
        status="running",
        fail_hint="插件层加载失败",
        lost_at=None,
        now=100.0,
        orphan_restarts=0,
    )
    assert d.status == "failed"
    assert d.log == "crashed"
    assert d.autostart is False


def test_marketplace_wait_then_revive() -> None:
    waiting = watch_disconnect(
        listening=False,
        child=False,
        status="running",
        fail_hint=None,
        lost_at=None,
        now=10.0,
        orphan_restarts=0,
    )
    assert waiting.status == "wait_restart"
    assert waiting.lost_at == 10.0
    still = watch_disconnect(
        listening=False,
        child=False,
        status="wait_restart",
        fail_hint=None,
        lost_at=10.0,
        now=14.0,
        orphan_restarts=0,
    )
    assert still.autostart is False
    revived = watch_disconnect(
        listening=True,
        child=False,
        status="wait_restart",
        fail_hint=None,
        lost_at=10.0,
        now=15.0,
        orphan_restarts=0,
    )
    assert revived.status == "running"
    assert revived.log == "revived"


def test_orphan_autostart_once_then_give_up() -> None:
    first = watch_disconnect(
        listening=False,
        child=False,
        status="wait_restart",
        fail_hint=None,
        lost_at=0.0,
        now=9.0,
        orphan_restarts=0,
    )
    assert first.autostart is True
    second = watch_disconnect(
        listening=False,
        child=False,
        status="wait_restart",
        fail_hint=None,
        lost_at=0.0,
        now=9.0,
        orphan_restarts=1,
    )
    assert second.autostart is False
    assert second.status == "failed"
    assert second.log == "gave_up"


def test_healthy_child_clears_lost() -> None:
    d = watch_disconnect(
        listening=True,
        child=True,
        status="running",
        fail_hint="stale",
        lost_at=1.0,
        now=2.0,
        orphan_restarts=3,
    )
    assert d.status == "running"
    assert d.lost_at is None
    assert d.clear_fail_hint is True

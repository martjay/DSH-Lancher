"""Decide what the launcher should do when the child / port state changes."""

from __future__ import annotations

from dataclasses import dataclass


WAIT_RESTART_SEC = 8.0
MAX_ORPHAN_RESTARTS = 1


@dataclass(frozen=True)
class WatchDecision:
    status: str | None = None
    log: str | None = None
    lost_at: float | None = None
    autostart: bool = False
    clear_fail_hint: bool = False


def watch_disconnect(
    *,
    listening: bool,
    child: bool,
    status: str,
    fail_hint: str | None,
    lost_at: float | None,
    now: float,
    orphan_restarts: int,
    wait_sec: float = WAIT_RESTART_SEC,
    max_restarts: int = MAX_ORPHAN_RESTARTS,
) -> WatchDecision:
    """Status machine for a running (or wait-restart) instance that may drop.

    Marketplace restart: port blips, then a *new* process listens — we wait.
    Plugin/CLI crash: logs set fail_hint, port stays down — do not loop-start.
    """
    if child:
        if listening:
            return WatchDecision(status="running", lost_at=None, clear_fail_hint=True)
        return WatchDecision(lost_at=None)
    if listening:
        log = None
        if status not in {"running", "starting", "restarting"}:
            log = "revived"
        return WatchDecision(status="running", log=log, lost_at=None)
    if status not in {"running", "wait_restart"}:
        return WatchDecision(lost_at=lost_at)
    if fail_hint:
        return WatchDecision(status="failed", log="crashed", lost_at=None)
    if lost_at is None:
        return WatchDecision(status="wait_restart", log="waiting", lost_at=now)
    if now - lost_at < wait_sec:
        return WatchDecision(lost_at=lost_at)
    if orphan_restarts >= max_restarts:
        return WatchDecision(status="failed", log="gave_up", lost_at=None)
    return WatchDecision(status="starting", log="autostart", lost_at=None, autostart=True)

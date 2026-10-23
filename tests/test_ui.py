from __future__ import annotations

from dsh_launcher.ui import overlay_position, tcl_int


def test_overlay_centers_on_parent() -> None:
    x, y = overlay_position(100, 50, 800, 600, 400, 300, 1920, 1080)
    assert (x, y) == (300, 200)


def test_overlay_clamps_to_screen() -> None:
    x, y = overlay_position(0, 0, 200, 100, 800, 600, 800, 600)
    assert x == 0
    assert y == 0


def test_tcl_int_accepts_string_and_empty() -> None:
    assert tcl_int("120") == 120
    assert tcl_int("120.0") == 120
    assert tcl_int("") == 0
    assert tcl_int(None) == 0
    assert tcl_int(88) == 88


def test_overlay_centers_on_parent() -> None:
    x, y = overlay_position(100, 50, 800, 600, 400, 300, 1920, 1080)
    assert (x, y) == (300, 200)


def test_overlay_clamps_to_screen() -> None:
    x, y = overlay_position(0, 0, 200, 100, 800, 600, 800, 600)
    assert x == 0
    assert y == 0

"""Cool graphite + Apple cyan — compact tool UI.

Direction brief:
- Category: desktop process launcher / control panel
- Density: compact (IDE-like)
- Tone: calm graphite, precise, console-adjacent
- Accent: one cyan; neutrals do the rest
- Material: hairline borders, almost no shadow
- Radius: 8px controls, 12px cards
- Reference: macOS Settings rows + a dark terminal log
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from tkinter.font import Font

FONTS = ("Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", "sans-serif")
MONO = ("Cascadia Mono", "Consolas", "Courier New")


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface_2: str
    surface_3: str
    hairline: str
    label: str
    secondary: str
    muted: str
    accent: str
    accent_hover: str
    accent_press: str
    accent_soft: str
    accent_on: str
    fill: str
    fill_hover: str
    fill_press: str
    green: str
    green_hover: str
    green_press: str
    orange: str
    red: str
    log_bg: str
    log_fg: str
    knob: str


DARK = Palette(
    bg="#0E1014",
    surface="#181B22",
    surface_2="#22262F",
    surface_3="#2C313C",
    hairline="#2E3340",
    label="#F4F5F7",
    secondary="#9AA0AC",
    muted="#6F7685",
    accent="#64D2FF",
    accent_hover="#8ADEFF",
    accent_press="#3BB8E8",
    accent_soft="#16303A",
    accent_on="#0A1218",
    fill="#22262F",
    fill_hover="#2C313C",
    fill_press="#1A1E26",
    green="#30D158",
    green_hover="#4AE06A",
    green_press="#24B84C",
    orange="#FF9F0A",
    red="#FF453A",
    log_bg="#0A0C10",
    log_fg="#C9CED8",
    knob="#FFFFFF",
)

LIGHT = Palette(
    bg="#F2F3F5",
    surface="#FFFFFF",
    surface_2="#EEF0F3",
    surface_3="#E2E5EA",
    hairline="#D8DCE3",
    label="#1C1E22",
    secondary="#5C6370",
    muted="#8A909C",
    accent="#0A84FF",
    accent_hover="#409CFF",
    accent_press="#0066D6",
    accent_soft="#E5F1FF",
    accent_on="#F5FAFF",
    fill="#EEF0F3",
    fill_hover="#E4E7ED",
    fill_press="#D8DCE3",
    green="#248A3D",
    green_hover="#1F7A36",
    green_press="#196C2E",
    orange="#C93400",
    red="#D70015",
    log_bg="#1C1E22",
    log_fg="#D7DBE2",
    knob="#FFFFFF",
)

P = DARK

# Back-compat names used across the app
BG = SURFACE = SURFACE_2 = SURFACE_3 = HAIRLINE = LABEL = SECONDARY = MUTED = ""
ACCENT = ACCENT_HOVER = ACCENT_PRESS = ACCENT_SOFT = FILL = FILL_HOVER = FILL_PRESS = ""
GREEN = GREEN_HOVER = GREEN_PRESS = ORANGE = RED = LOG_BG = LOG_FG = ""


def apply_palette(name: str) -> str:
    global P, BG, SURFACE, SURFACE_2, SURFACE_3, HAIRLINE, LABEL, SECONDARY, MUTED
    global ACCENT, ACCENT_HOVER, ACCENT_PRESS, ACCENT_SOFT, FILL, FILL_HOVER, FILL_PRESS
    global GREEN, GREEN_HOVER, GREEN_PRESS, ORANGE, RED, LOG_BG, LOG_FG
    global _scroll_style_ready
    resolved = "light" if name == "light" else "dark"
    P = LIGHT if resolved == "light" else DARK
    BG, SURFACE, SURFACE_2, SURFACE_3 = P.bg, P.surface, P.surface_2, P.surface_3
    HAIRLINE, LABEL, SECONDARY, MUTED = P.hairline, P.label, P.secondary, P.muted
    ACCENT, ACCENT_HOVER, ACCENT_PRESS, ACCENT_SOFT = P.accent, P.accent_hover, P.accent_press, P.accent_soft
    FILL, FILL_HOVER, FILL_PRESS = P.fill, P.fill_hover, P.fill_press
    GREEN, GREEN_HOVER, GREEN_PRESS = P.green, P.green_hover, P.green_press
    ORANGE, RED, LOG_BG, LOG_FG = P.orange, P.red, P.log_bg, P.log_fg
    _scroll_style_ready = False
    return resolved


apply_palette("dark")


def tcl_int(value, default: int = 0) -> int:
    """Python 3.12 Tk may return Tcl_Obj from cget(); int() cannot coerce that."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def font(size: int, *, bold: bool = False) -> tuple:
    return (FONTS[0], size, "bold" if bold else "normal")


def mono(size: int = 12) -> tuple:
    return (MONO[0], size)


def rounded_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    r: float,
    **kw,
) -> list[int]:
    """Quarter-circle corners. Cheap: 4 arcs + 2 bars, no smooth-polygon."""
    fill = kw.get("fill", "")
    outline = kw.get("outline", fill)
    tags = kw.get("tags", "")
    extra = {"tags": tags} if tags else {}
    if x2 <= x1 or y2 <= y1:
        return []
    r = max(0.0, min(float(r), (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    ids: list[int] = []
    if r < 1.5:
        ids.append(canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=0, **extra))
        return ids
    ids.append(canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="pieslice", fill=fill, outline=fill, **extra))
    ids.append(canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="pieslice", fill=fill, outline=fill, **extra))
    ids.append(canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style="pieslice", fill=fill, outline=fill, **extra))
    ids.append(canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style="pieslice", fill=fill, outline=fill, **extra))
    ids.append(canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="", width=0, **extra))
    ids.append(canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="", width=0, **extra))
    return ids


_font_cache: dict[tuple, object] = {}


def _measure(text: str, size: int = 12, *, bold: bool = True) -> int:
    key = (text, size, bold)
    cached = _font_cache.get(key)
    if isinstance(cached, int):
        return cached
    try:
        w = Font(font=font(size, bold=bold)).measure(text)
    except tk.TclError:
        w = len(text) * 12
    _font_cache[key] = w
    return w


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command,
        *,
        kind: str = "fill",
        height: int = 28,
        radius: int = 7,
        padx: int = 10,
        canvas_bg: str | None = None,
    ) -> None:
        w = max(72, _measure(text) + padx * 2)
        super().__init__(
            master,
            width=w,
            height=height,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            bg=canvas_bg or P.surface,
        )
        self._canvas_bg = canvas_bg or P.surface
        self._text = text
        self._command = command
        self._kind = kind
        self._radius = radius
        self._padx = padx
        self._height = height
        self._state = "idle"
        self._enabled = True
        self._last_size = (0, 0)
        self.bind("<Enter>", lambda *_: self._set("hover"))
        self.bind("<Leave>", lambda *_: self._set("idle"))
        self.bind("<ButtonPress-1>", lambda *_: self._set("press"))
        self.bind("<ButtonRelease-1>", self._release)
        self._redraw()

    def set_text(self, text: str) -> None:
        self._text = text
        self.configure(width=max(72, _measure(text) + self._padx * 2))
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.configure(cursor="hand2" if self._enabled else "arrow")
        if not self._enabled:
            self._state = "idle"
        self._redraw()

    def _palette(self) -> tuple[str, str]:
        if not self._enabled:
            return P.surface_2, P.muted
        if self._kind == "green":
            return {
                "idle": (P.green, "#05210C" if P is DARK else "#F3FFF6"),
                "hover": (P.green_hover, "#05210C" if P is DARK else "#F3FFF6"),
                "press": (P.green_press, "#05210C" if P is DARK else "#FFFFFF"),
            }[self._state]
        if self._kind == "accent":
            return {
                "idle": (P.accent, P.accent_on),
                "hover": (P.accent_hover, P.accent_on),
                "press": (P.accent_press, P.accent_on),
            }[self._state]
        if self._kind == "soft":
            return {
                "idle": (P.accent_soft, P.accent_hover if P is DARK else P.accent),
                "hover": ("#1E4450" if P is DARK else "#D6E8FF", P.accent_hover if P is DARK else P.accent),
                "press": ("#102830" if P is DARK else "#C5DCFF", P.accent),
            }[self._state]
        return {
            "idle": (P.fill, P.label),
            "hover": (P.fill_hover, P.label),
            "press": (P.fill_press, P.label),
        }[self._state]

    def _set(self, state: str) -> None:
        if not self._enabled:
            return
        self._state = state
        self._redraw()

    def _release(self, event) -> None:
        if not self._enabled:
            return
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._set("hover" if inside else "idle")
        if inside and self._command:
            self._command()

    def _redraw(self, *_args) -> None:
        w = max(tcl_int(self.cget("width"), 72), 72)
        h = self._height
        size = (w, h)
        if size == self._last_size and self.find_all():
            # still need to repaint colors on hover
            pass
        self._last_size = size
        self.delete("all")
        bg, fg = self._palette()
        rounded_rect(self, 0.5, 0.5, w - 0.5, h - 0.5, self._radius, fill=bg)
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=font(12, bold=True))


class Toggle(tk.Canvas):
    W, H, TRACK_H = 40, 22, 20

    def __init__(self, master: tk.Misc, variable: tk.BooleanVar, command=None, *, canvas_bg: str | None = None) -> None:
        super().__init__(
            master,
            width=self.W,
            height=self.H,
            highlightthickness=0,
            bd=0,
            bg=canvas_bg or P.surface,
            cursor="hand2",
        )
        self._canvas_bg = canvas_bg or P.surface
        self._var = variable
        self._command = command
        self._knob = 12.0 if not variable.get() else float(self.W - 12)
        self.bind("<Button-1>", self._flip)
        self._redraw()

    def _flip(self, *_args) -> None:
        self._var.set(not bool(self._var.get()))
        self._knob = float(self.W - 12) if self._var.get() else 12.0
        self._redraw()
        if self._command:
            self._command()

    def _redraw(self, *_args) -> None:
        self.delete("all")
        on = bool(self._var.get())
        track = P.accent if on else P.surface_3
        y0 = (self.H - self.TRACK_H) / 2
        rounded_rect(self, 1, y0, self.W - 1, y0 + self.TRACK_H, self.TRACK_H / 2, fill=track)
        cy = self.H / 2
        kr = 7
        self.create_oval(self._knob - kr, cy - kr, self._knob + kr, cy + kr, fill=P.knob, outline="")


def overlay_position(
    px: int, py: int, pw: int, ph: int, width: int, height: int, sw: int, sh: int
) -> tuple[int, int]:
    """Center a child window on its parent, then clamp to the screen."""
    x = int(px + (pw - width) / 2)
    y = int(py + (ph - height) / 2)
    x = min(max(0, x), max(0, sw - width))
    y = min(max(0, y), max(0, sh - height))
    return x, y


def place_over_parent(
    win: tk.Toplevel, parent: tk.Misc, *, width: int, height: int, hide_first: bool = True
) -> None:
    """Show a Toplevel centered on the launcher — not at screen (0, 0)."""
    if hide_first:
        try:
            win.withdraw()
        except tk.TclError:
            pass
    parent.update_idletasks()
    win.update_idletasks()
    x, y = overlay_position(
        parent.winfo_rootx(),
        parent.winfo_rooty(),
        max(parent.winfo_width(), 1),
        max(parent.winfo_height(), 1),
        width,
        height,
        win.winfo_screenwidth(),
        win.winfo_screenheight(),
    )
    win.geometry(f"{width}x{height}+{x}+{y}")
    win.deiconify()
    win.lift()
    try:
        win.focus_force()
    except tk.TclError:
        pass


def bind_wrap(label: tk.Label, pad: int = 4) -> None:
    last = {"w": 0}

    def _sync(_event=None) -> None:
        width = label.winfo_width()
        if width < 32 or abs(width - last["w"]) < 8:
            return
        last["w"] = width
        wrap = max(120, width - pad)
        if tcl_int(label.cget("wraplength")) != wrap:
            label.configure(wraplength=wrap)

    label.bind("<Configure>", _sync, add="+")


class Card(tk.Frame):
    """Flat surface + 1px hairline. Canvas round-rect shells were re-entering Configure and freezing the window."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        radius: int = 10,
        fill: str | None = None,
        canvas_bg: str | None = None,
        expand: bool = False,
        pady: tuple[int, int] = (0, 8),
        pack: bool = True,
        padding: int | None = None,
    ) -> None:
        super().__init__(master, bg=canvas_bg or P.bg, highlightthickness=0)
        fill = fill or P.surface
        self.body = tk.Frame(
            self,
            bg=fill,
            highlightthickness=1,
            highlightbackground=P.hairline,
            highlightcolor=P.hairline,
        )
        pad = 10 if padding is None else padding
        self.body.pack(fill="both", expand=True, padx=0, pady=0)
        self._pad = pad
        self._inner = tk.Frame(self.body, bg=fill)
        self._inner.pack(fill="both", expand=True, padx=pad, pady=pad)
        self.body = self._inner
        if pack:
            if expand:
                self.pack(fill="both", expand=True, pady=pady)
            else:
                self.pack(fill="x", expand=False, pady=pady)


_SCROLL_STYLE = "Dark.Vertical.TScrollbar"
_scroll_style_ready = False


def ensure_dark_scrollbar_style(widget: tk.Misc) -> None:
    global _scroll_style_ready
    style = ttk.Style(widget.winfo_toplevel())
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        _SCROLL_STYLE,
        background=P.surface_2,
        troughcolor=P.bg,
        bordercolor=P.bg,
        lightcolor=P.surface,
        darkcolor=P.surface,
        arrowcolor=P.muted,
        relief="flat",
        borderwidth=0,
        arrowsize=12,
        width=12,
    )
    style.map(
        _SCROLL_STYLE,
        background=[("active", P.hairline), ("pressed", P.surface_3)],
        arrowcolor=[("active", P.label), ("pressed", P.label)],
    )
    _scroll_style_ready = True


def dark_vscroll(master: tk.Misc, command) -> ttk.Scrollbar:
    ensure_dark_scrollbar_style(master)
    return ttk.Scrollbar(master, orient="vertical", command=command, style=_SCROLL_STYLE)


class ScrollColumn(tk.Frame):
    """Natural-height left rail; scrolls instead of crushing children."""

    def __init__(self, master: tk.Misc, *, bg: str | None = None) -> None:
        color = bg or P.bg
        super().__init__(master, bg=color, highlightthickness=0)
        self._canvas = tk.Canvas(
            self,
            bg=color,
            highlightthickness=0,
            bd=0,
            highlightbackground=color,
            highlightcolor=color,
        )
        self._bar = dark_vscroll(self, self._canvas.yview)
        self.inner = tk.Frame(self._canvas, bg=color)
        self._win = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._canvas.configure(yscrollcommand=self._bar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._on_inner)
        self._canvas.bind("<Configure>", self._on_canvas)
        self.bind("<Enter>", self._bind_wheel)
        self.bind("<Leave>", self._unbind_wheel)

    def _on_inner(self, _event=None) -> None:
        bbox = self._canvas.bbox("all")
        if bbox:
            self._canvas.configure(scrollregion=bbox)
        self.show_scrollbar_if_needed()

    def _on_canvas(self, event) -> None:
        if tcl_int(self._canvas.itemcget(self._win, "width")) != event.width:
            self._canvas.itemconfigure(self._win, width=max(event.width, 1))

    def show_scrollbar_if_needed(self) -> None:
        need = self.inner.winfo_reqheight() > self._canvas.winfo_height() + 8
        mapped = bool(self._bar.winfo_ismapped())
        if need == mapped:
            return
        if need:
            self._bar.pack(side="right", fill="y")
        else:
            self._bar.pack_forget()

    def _bind_wheel(self, _event=None) -> None:
        self._canvas.bind_all("<MouseWheel>", self._wheel)

    def _unbind_wheel(self, _event=None) -> None:
        self._canvas.unbind_all("<MouseWheel>")

    def _wheel(self, event) -> None:
        self._canvas.yview_scroll(int(-event.delta / 120), "units")


class HelpIcon(tk.Canvas):
    """28px circular help control."""

    def __init__(self, master: tk.Misc, command, *, canvas_bg: str | None = None, size: int = 28) -> None:
        super().__init__(
            master,
            width=size,
            height=size,
            highlightthickness=0,
            bd=0,
            bg=canvas_bg or P.surface,
            cursor="hand2",
        )
        self._command = command
        self._size = size
        self._canvas_bg = canvas_bg or P.surface
        self.bind("<Button-1>", lambda *_: command() if command else None)
        self.bind("<Enter>", lambda *_: self._draw(hover=True))
        self.bind("<Leave>", lambda *_: self._draw(hover=False))
        self._draw(hover=False)

    def _draw(self, *, hover: bool) -> None:
        self.delete("all")
        s = self._size
        fill = P.fill_hover if hover else P.fill
        self.create_oval(1, 1, s - 2, s - 2, fill=fill, outline="")
        self.create_text(
            s / 2,
            s / 2 - 0.5,
            text="?",
            fill=P.label if hover else P.secondary,
            font=font(12, bold=True),
        )

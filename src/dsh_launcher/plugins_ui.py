"""Plugin manager: per-row actions, centered on the launcher."""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox

from dsh_launcher import ui as gui
from dsh_launcher.i18n import t
from dsh_launcher.plugins import (
    PluginInfo,
    add_plugin_with_exemption,
    enrich_updates,
    install_plugin_update,
    list_user_plugins,
    plugin_matches_filter,
    run_dsh_plugin,
    set_enabled,
    switch_plugin_to_npm,
)
from dsh_launcher.ui import RoundedButton, Toggle, dark_vscroll, font, place_over_parent

_WIN_W = 720
_WIN_H = 580


class PluginManager:
    def __init__(
        self,
        app,
        *,
        use_mirror: bool,
        log: Callable[[str], None],
        on_busy=None,
        block_start: bool = False,
    ) -> None:
        self._app = app
        self._use_mirror = use_mirror
        self._log = log
        self._on_busy = on_busy
        self._block_start = block_start
        self._rows: list[PluginInfo] = []
        self._filter = "all"
        self._busy = False
        self._action_btns: list[RoundedButton] = []
        win = tk.Toplevel(app.root)
        self.win = win
        win.withdraw()
        win.title(t("plugins_title"))
        win.configure(bg=gui.P.bg)
        win.minsize(640, 420)
        win.transient(app.root)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.bind("<Escape>", lambda *_: win.destroy())

        pad = tk.Frame(win, bg=gui.P.bg)
        pad.pack(fill="both", expand=True, padx=16, pady=16)

        head = tk.Frame(pad, bg=gui.P.bg)
        head.pack(fill="x")
        titles = tk.Frame(head, bg=gui.P.bg)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(titles, text=t("plugins_title"), bg=gui.P.bg, fg=gui.P.label, font=font(14, bold=True)).pack(
            anchor="w"
        )
        self.hint = tk.Label(
            titles,
            text=t("plugins_hint"),
            bg=gui.P.bg,
            fg=gui.P.muted,
            font=font(11),
            wraplength=480,
            justify="left",
            anchor="w",
        )
        self.hint.pack(anchor="w", fill="x", pady=(4, 0))
        self.btn_refresh = RoundedButton(head, t("plugins_refresh"), self.refresh, padx=10)
        self.btn_refresh.pack(side="right", anchor="n")
        self.btn_update_all = RoundedButton(
            head, t("plugins_update_all"), self._update_all, kind="accent", padx=10
        )

        chips = tk.Frame(pad, bg=gui.P.bg)
        chips.pack(fill="x", pady=(12, 0))
        self._filter_btns: dict[str, RoundedButton] = {}
        for key, label in (
            ("all", t("plugins_filter_all")),
            ("updates", t("plugins_filter_updates")),
            ("bad", t("plugins_filter_bad")),
            ("off", t("plugins_filter_off")),
        ):
            btn = RoundedButton(chips, label, lambda k=key: self._set_filter(k), padx=8)
            btn.pack(side="left", padx=(0, 8))
            self._filter_btns[key] = btn

        install = tk.Frame(pad, bg=gui.P.surface, highlightthickness=1, highlightbackground=gui.P.hairline)
        install.pack(fill="x", pady=(12, 0))
        inner = tk.Frame(install, bg=gui.P.surface)
        inner.pack(fill="x", padx=10, pady=8)
        tk.Label(inner, text=t("plugins_install"), bg=gui.P.surface, fg=gui.P.label, font=font(12, bold=True)).pack(
            side="left"
        )
        shell = tk.Frame(inner, bg=gui.P.surface_2, highlightthickness=1, highlightbackground=gui.P.hairline)
        shell.pack(side="left", fill="x", expand=True, padx=(12, 8))
        self._install_var = tk.StringVar()
        self.install_entry = tk.Entry(
            shell,
            textvariable=self._install_var,
            bg=gui.P.surface_2,
            fg=gui.P.label,
            insertbackground=gui.P.label,
            relief="flat",
            highlightthickness=0,
            bd=0,
            font=font(12),
        )
        self.install_entry.pack(fill="x", padx=8, pady=6)
        self._install_hint = True
        self._install_var.set(t("plugins_install_ph"))
        self.install_entry.configure(fg=gui.P.muted)
        self.install_entry.bind("<FocusIn>", self._install_focus_in)
        self.install_entry.bind("<FocusOut>", self._install_focus_out)
        self.install_entry.bind("<Return>", lambda *_: self._install())
        self.btn_install = RoundedButton(inner, t("plugins_install_go"), self._install, kind="accent", padx=10)
        self.btn_install.pack(side="right")

        list_host = tk.Frame(pad, bg=gui.P.surface, highlightthickness=1, highlightbackground=gui.P.hairline)
        list_host.pack(fill="both", expand=True, pady=(12, 0))
        self._canvas = tk.Canvas(list_host, bg=gui.P.surface, highlightthickness=0, bd=0)
        scroll = dark_vscroll(list_host, self._canvas.yview)
        self._inner = tk.Frame(self._canvas, bg=gui.P.surface)
        self._win_id = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._canvas.configure(yscrollcommand=scroll.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._inner.bind("<Configure>", lambda *_: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfigure(self._win_id, width=e.width))
        self._canvas.bind("<Enter>", lambda *_: self._canvas.bind_all("<MouseWheel>", self._wheel))
        self._canvas.bind("<Leave>", lambda *_: self._canvas.unbind_all("<MouseWheel>"))

        foot = tk.Frame(pad, bg=gui.P.bg)
        foot.pack(fill="x", pady=(12, 0))
        self.btn_close = RoundedButton(foot, t("plugins_close"), win.destroy, padx=12)
        self.btn_close.pack(side="right")
        self.btn_start = RoundedButton(foot, t("plugins_start_anyway"), self._start_anyway, kind="soft", padx=12)
        self._sync_block_start()

        self._paint_filters()
        self.recenter()
        self.refresh()

    def recenter(self) -> None:
        mapped = False
        try:
            mapped = bool(self.win.winfo_ismapped())
        except tk.TclError:
            pass
        place_over_parent(self.win, self._app.root, width=_WIN_W, height=_WIN_H, hide_first=not mapped)

    def set_block_start(self, block_start: bool) -> None:
        self._block_start = block_start
        self._sync_block_start()

    def _sync_block_start(self) -> None:
        if self._block_start:
            if not self.btn_start.winfo_ismapped():
                self.btn_start.pack(side="right", padx=(0, 8))
        else:
            self.btn_start.pack_forget()

    def _install_focus_in(self, *_args) -> None:
        if self._install_hint:
            self._install_hint = False
            self._install_var.set("")
            self.install_entry.configure(fg=gui.P.label)

    def _install_focus_out(self, *_args) -> None:
        if not (self._install_var.get() or "").strip():
            self._install_hint = True
            self._install_var.set(t("plugins_install_ph"))
            self.install_entry.configure(fg=gui.P.muted)

    def _wheel(self, event) -> None:
        self._canvas.yview_scroll(int(-event.delta / 120), "units")

    def _set_filter(self, filt: str) -> None:
        self._filter = filt
        self._paint_filters()
        self._render_rows()

    def _paint_filters(self) -> None:
        for key, btn in self._filter_btns.items():
            btn._kind = "accent" if key == self._filter else "fill"
            btn._redraw()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if self._on_busy:
            self._on_busy(busy)
        enabled = not busy
        for btn in (self.btn_refresh, self.btn_install, self.btn_update_all, *self._action_btns):
            try:
                btn.set_enabled(enabled)
            except tk.TclError:
                pass

    def refresh(self) -> None:
        if self._busy:
            return
        self.hint.configure(text=t("plugins_scanning"))
        self._set_busy(True)

        def go() -> None:
            rows = list_user_plugins()
            try:
                rows = enrich_updates(rows, use_mirror=self._use_mirror)
            except Exception:
                pass
            self._app.root.after(0, lambda: self._apply_rows(rows))

        threading.Thread(target=go, name="dsh-plugin-scan", daemon=True).start()

    def _apply_rows(self, rows: list[PluginInfo]) -> None:
        self._rows = rows
        bad = sum(1 for r in rows if r.incompatible and r.enabled)
        upd = sum(1 for r in rows if r.update_available or r.switch_to_npm)
        self.hint.configure(text=t("plugins_summary", n=len(rows), bad=bad, upd=upd))
        if upd:
            if not self.btn_update_all.winfo_ismapped():
                self.btn_update_all.pack(side="right", anchor="n", padx=(0, 8), before=self.btn_refresh)
        else:
            self.btn_update_all.pack_forget()
        self._set_busy(False)
        self._render_rows()

    def _visible(self) -> list[PluginInfo]:
        return [row for row in self._rows if plugin_matches_filter(row, self._filter)]

    def _render_rows(self) -> None:
        for child in self._inner.winfo_children():
            child.destroy()
        self._action_btns = []
        visible = self._visible()
        if not visible:
            tk.Label(
                self._inner,
                text=t("plugins_empty"),
                bg=gui.P.surface,
                fg=gui.P.muted,
                font=font(12),
                anchor="w",
                justify="left",
            ).pack(anchor="w", padx=16, pady=24)
            return
        for i, row in enumerate(visible):
            self._add_row(row, alt=bool(i % 2))

    def _add_row(self, row: PluginInfo, *, alt: bool) -> None:
        bg = gui.P.surface_2 if alt else gui.P.surface
        line = tk.Frame(self._inner, bg=bg)
        line.pack(fill="x")
        body = tk.Frame(line, bg=bg)
        body.pack(fill="x", padx=12, pady=10)
        body.grid_columnconfigure(0, weight=1)

        copy = tk.Frame(body, bg=bg)
        copy.grid(row=0, column=0, sticky="ew")
        top = tk.Frame(copy, bg=bg)
        top.pack(fill="x")
        tk.Label(top, text=row.name, bg=bg, fg=gui.P.label, font=font(12, bold=True), anchor="w").pack(
            side="left"
        )
        badge, badge_fg = _badge(row)
        tk.Label(top, text=badge, bg=bg, fg=badge_fg, font=font(11), anchor="w").pack(side="left", padx=(8, 0))

        ver = row.installed or "—"
        if row.ahead_of_registry:
            ver = f"{ver}  ·  npm {row.latest}" if row.latest else ver
        elif row.latest and row.installed and row.latest != row.installed:
            ver = t("plugins_ver_arrow", installed=row.installed, latest=row.latest)
        elif row.switch_to_npm and row.latest:
            ver = f"{ver}  ·  {t('plugins_official_ver', ver=row.latest)}"
        elif row.latest and row.latest != row.installed:
            ver = f"{ver}  ·  {row.latest}"
        note = ""
        if row.incompatible:
            note = t(row.reason_key or "incompat_settings")
        elif row.ahead_of_registry:
            note = t("plugins_hot_note", installed=row.installed or "—", latest=row.latest or "—")
        elif row.source != "npm":
            note = t("plugins_pinned")
        sub = ver if not note else f"{ver}  ·  {note}"
        tk.Label(copy, text=sub, bg=bg, fg=gui.P.muted, font=font(11), anchor="w").pack(anchor="w", pady=(4, 0))

        actions = tk.Frame(body, bg=bg)
        actions.grid(row=0, column=1, sticky="e", padx=(12, 0))
        enabled_var = tk.BooleanVar(value=row.enabled)
        toggle = Toggle(actions, enabled_var, command=lambda r=row, v=enabled_var: self._toggle(r, v), canvas_bg=bg)
        toggle.pack(side="left")
        if row.update_available and row.latest:
            upd = RoundedButton(actions, t("plugins_row_update"), lambda r=row: self._update_one(r), kind="accent", padx=8)
            upd.pack(side="left", padx=(8, 0))
            self._action_btns.append(upd)
        elif row.switch_to_npm:
            unp = RoundedButton(
                actions, t("plugins_row_unpin"), lambda r=row: self._unpin_one(r), kind="accent", padx=8
            )
            unp.pack(side="left", padx=(8, 0))
            self._action_btns.append(unp)
        rm = RoundedButton(actions, t("plugins_row_remove"), lambda r=row: self._remove_one(r), padx=8)
        rm.pack(side="left", padx=(8, 0))
        self._action_btns.append(rm)

    def _toggle(self, row: PluginInfo, var: tk.BooleanVar) -> None:
        if self._busy:
            return
        enabled = bool(var.get())
        set_enabled(row.name, enabled)
        row.enabled = enabled
        self._log(t("plugins_toggled", name=row.name, state=t("plugins_on") if enabled else t("plugins_off")))
        if enabled and row.incompatible:
            self._log(t("plugins_enabled_bad", name=row.name))
        self._log(t("plugins_restart_hint"))
        self._render_rows()

    def _run_jobs(self, jobs: list[tuple[str, Callable[[], None]]]) -> None:
        if self._busy or not jobs:
            return
        self._set_busy(True)

        def go() -> None:
            for label, fn in jobs:
                self._log(label)
                try:
                    fn()
                except Exception as exc:
                    self._log(str(exc))
            self._log(t("plugins_restart_hint"))
            self._app.root.after(0, lambda: (self._set_busy(False), self.refresh()))

        threading.Thread(target=go, name="dsh-plugin-apply", daemon=True).start()

    def _update_one(self, row: PluginInfo) -> None:
        if row.ahead_of_registry:
            messagebox.showinfo(
                t("plugins_title"),
                t("plugins_skip_downgrade", name=row.name, installed=row.installed or "—", latest=row.latest or "—"),
                parent=self.win,
            )
            return
        target = row.latest or "latest"
        if row.source != "npm":
            if not messagebox.askyesno(
                t("plugins_title"),
                t("plugins_confirm_update_pinned", name=row.name, ver=target),
                parent=self.win,
            ):
                return
        self._run_jobs(
            [
                (
                    t("plugins_updating", name=row.name, ver=target),
                    lambda n=row.name, v=target, u=row.source != "npm": _check(
                        install_plugin_update(n, v, unpin=u, log=self._log)
                    ),
                )
            ]
        )

    def _update_all(self) -> None:
        rows = [r for r in self._rows if r.update_available and r.latest]
        if not rows:
            self._log(t("plugins_none_npm"))
            return
        if any(r.source != "npm" for r in rows) and not messagebox.askyesno(
            t("plugins_title"),
            t("plugins_confirm_update_pinned_all"),
            parent=self.win,
        ):
            return
        jobs = []
        for row in rows:
            target = row.latest or "latest"
            jobs.append(
                (
                    t("plugins_updating", name=row.name, ver=target),
                    lambda n=row.name, v=target, u=row.source != "npm": _check(
                        install_plugin_update(n, v, unpin=u, log=self._log)
                    ),
                )
            )
        self._run_jobs(jobs)

    def _unpin_one(self, row: PluginInfo) -> None:
        if not messagebox.askyesno(
            t("plugins_title"),
            t("plugins_confirm_unpin", name=row.name),
            parent=self.win,
        ):
            return
        self._run_jobs(
            [
                (
                    t("plugins_unpinning", name=row.name),
                    lambda n=row.name, v=row.latest: _check(switch_plugin_to_npm(n, log=self._log, version=v)),
                )
            ]
        )

    def _remove_one(self, row: PluginInfo) -> None:
        if not messagebox.askyesno(
            t("plugins_title"),
            t("plugins_confirm_remove", name=row.name),
            parent=self.win,
        ):
            return
        self._run_jobs(
            [
                (
                    t("plugins_removing", name=row.name),
                    lambda n=row.name: _check(run_dsh_plugin("remove", n, log=self._log)),
                )
            ]
        )

    def _install(self) -> None:
        spec = "" if self._install_hint else (self._install_var.get() or "").strip()
        if not spec or spec == t("plugins_install_ph"):
            self._log(t("plugins_need_name"))
            return
        self._run_jobs(
            [
                (
                    t("plugins_installing", spec=spec),
                    lambda s=spec: _check(add_plugin_with_exemption(s, log=self._log)),
                )
            ]
        )
        self._install_hint = True
        self._install_var.set(t("plugins_install_ph"))
        self.install_entry.configure(fg=gui.P.muted)

    def _start_anyway(self) -> None:
        self.win.destroy()
        self._app._on_start(force=True)


def _badge(row: PluginInfo) -> tuple[str, str]:
    if row.incompatible and row.enabled:
        return t("plugins_bad"), gui.P.red
    if not row.enabled:
        return t("plugins_off"), gui.P.muted
    if row.ahead_of_registry:
        return t("plugins_hot"), gui.P.orange
    if row.update_available or row.switch_to_npm:
        return t("plugins_can_update"), gui.P.orange
    return t("plugins_on"), gui.P.green


def _check(result: tuple[int, str]) -> None:
    code, out = result
    if code != 0:
        raise RuntimeError(out or f"exit {code}")

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
import tkinter as tk

from PIL import Image
from pystray import Icon, Menu, MenuItem

from dsh_launcher import ui as gui
from dsh_launcher.browser import open_url
from dsh_launcher.i18n import language as i18n_language
from dsh_launcher.i18n import set_language as set_i18n_lang
from dsh_launcher.i18n import t
from dsh_launcher.paths import APP_USER_MODEL_ID, DEFAULT_HOST, DEFAULT_PORT, icon_path
from dsh_launcher.process import HarnessProcess, is_listening
from dsh_launcher.search_patch import is_disable_builtin_search_on, set_disable_builtin_search
from dsh_launcher.settings_store import (
    get_auto_start,
    get_check_plugins_on_start,
    get_language,
    get_open_with_chrome,
    get_theme,
    get_use_china_mirror,
    set_auto_start,
    set_check_plugins_on_start,
    set_language as persist_language,
    set_open_with_chrome,
    set_theme as persist_theme,
    set_use_china_mirror,
)
from dsh_launcher.ui import (
    Card,
    HelpIcon,
    RoundedButton,
    ScrollColumn,
    Toggle,
    bind_wrap,
    font,
    mono,
)
from dsh_launcher.update_check import UpdateInfo, check_update, install_or_upgrade_latest
from dsh_launcher.web_port import current_web_port, set_web_port
from dsh_launcher.watch import watch_disconnect


def _windows_app_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def _tray_image() -> Image.Image:
    ico = icon_path()
    img = Image.open(ico)
    if getattr(img, "n_frames", 1) > 1:
        best = img
        best_area = img.size[0] * img.size[1]
        for i in range(img.n_frames):
            img.seek(i)
            area = img.size[0] * img.size[1]
            if area > best_area:
                best = img.copy()
                best_area = area
        img = best
    return img.convert("RGBA")


class LauncherApp:
    def __init__(self) -> None:
        _windows_app_identity()
        self.root = tk.Tk()
        gui.apply_palette(get_theme())
        set_i18n_lang(get_language())
        self.root.title(t("app_title"))
        self.root.geometry("1100x760")
        self.root.minsize(1000, 640)
        self.root.configure(bg=gui.P.bg)
        ico = icon_path()
        if ico.exists():
            try:
                self.root.iconbitmap(default=str(ico))
                self.root.iconbitmap(str(ico))
            except Exception:
                pass
        self.logs: queue.Queue[str] = queue.Queue()
        self._port = current_web_port()
        self.harness = HarnessProcess(self._log, lambda: self._port)
        self._status = t("status_stopped")
        self._status_kind = "stopped"
        self._action_mode = ""
        self._last_update: UpdateInfo | None = None
        self._busy = False
        self._child_lost_at: float | None = None
        self._orphan_restarts = 0
        self._tray_hinted = False
        self._quitting = False
        self._tray: Icon | None = None
        self._search_var = tk.BooleanVar(value=is_disable_builtin_search_on())
        self._chrome_var = tk.BooleanVar(value=get_open_with_chrome())
        self._mirror_var = tk.BooleanVar(value=get_use_china_mirror())
        self._auto_start_var = tk.BooleanVar(value=get_auto_start())
        self._check_plugins_var = tk.BooleanVar(value=get_check_plugins_on_start())
        self._plugin_mgr = None
        self._port_var = tk.StringVar(value=str(self._port))
        self._local_ver: str | None = None
        self._latest_ver: str | None = None
        self._update_available = False
        self._update_busy = False
        self._last_open_url: str | None = None
        self._build()
        self._setup_tray()
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.root.after(80, self._drain_logs)
        self.root.after(400, self._tick)
        self.root.after(200, self._boot)
        self.root.after(1200, lambda: self._check_update(silent=True))

    def _url(self) -> str:
        return self.harness.web_url or f"http://{DEFAULT_HOST}:{self._port}/"

    def _url_label(self) -> str:
        raw = self._url()
        if "token=" in raw:
            return t("url_authed", url=f"http://{DEFAULT_HOST}:{self._port}/")
        return raw

    def _build(self) -> None:
        root_pad = tk.Frame(self.root, bg=gui.P.bg)
        root_pad.pack(fill="both", expand=True, padx=12, pady=12)
        self._shell = root_pad

        top = Card(root_pad, pady=(0, 8), padding=8)
        top_inner = tk.Frame(top.body, bg=gui.P.surface)
        top_inner.pack(fill="x")

        right = tk.Frame(top_inner, bg=gui.P.surface)
        right.pack(side="right", padx=(12, 0))

        actions = tk.Frame(right, bg=gui.P.surface)
        actions.pack(anchor="e")
        HelpIcon(actions, self._show_about, size=28).pack(side="right", padx=(8, 0))
        self.btn_open = RoundedButton(actions, t("btn_open"), self._on_open, kind="green", padx=10)
        self.btn_open.pack(side="right", padx=(8, 0))
        self._action_host = tk.Frame(actions, bg=gui.P.surface)
        self._action_host.pack(side="right")
        self.btn_upgrade = RoundedButton(
            self._action_host, t("btn_upgrade"), self._on_upgrade, kind="accent", padx=10
        )
        self.btn_install = RoundedButton(
            self._action_host, t("btn_install"), self._on_install, kind="accent", padx=10
        )
        self.btn_check = RoundedButton(
            self._action_host,
            t("btn_check"),
            lambda: self._check_update(silent=False),
            padx=10,
        )
        self.btn_check.pack(side="right")

        ops = tk.Frame(right, bg=gui.P.surface)
        ops.pack(anchor="e", pady=(6, 0))
        self.btn_start = RoundedButton(ops, t("btn_start"), self._on_start, kind="accent", padx=10)
        self.btn_stop = RoundedButton(ops, t("btn_stop"), self._on_stop, padx=10)
        self.btn_restart = RoundedButton(ops, t("btn_restart"), self._on_restart, kind="soft", padx=10)
        self.btn_start.pack(side="left")
        self.btn_stop.pack(side="left", padx=(6, 0))
        self.btn_restart.pack(side="left", padx=(6, 0))
        self.btn_plugins = RoundedButton(ops, t("btn_plugins"), self._open_plugins, kind="accent", padx=10)
        self.btn_plugins.pack(side="left", padx=(6, 0))

        left = tk.Frame(top_inner, bg=gui.P.surface)
        left.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(left, bg=gui.P.surface)
        row1.pack(anchor="w", fill="x")
        self._status_dot = tk.Canvas(row1, width=10, height=10, bg=gui.P.surface, highlightthickness=0)
        self._status_dot.pack(side="left", pady=4)
        self._dot_id = self._status_dot.create_oval(1, 1, 9, 9, fill=gui.P.secondary, outline="")
        self.status_lbl = tk.Label(
            row1,
            text=f"{t('status')}  {t('status_stopped')}",
            bg=gui.P.surface,
            fg=gui.P.secondary,
            font=font(13, bold=True),
        )
        self.status_lbl.pack(side="left", padx=(8, 8))
        tk.Label(row1, text="·", bg=gui.P.surface, fg=gui.P.hairline, font=font(13)).pack(side="left", padx=(0, 8))
        self.update_lbl = tk.Label(
            row1,
            text=t("checking_version"),
            bg=gui.P.surface,
            fg=gui.P.muted,
            font=font(12),
            anchor="w",
        )
        self.update_lbl.pack(side="left", fill="x", expand=True)

        row2 = tk.Frame(left, bg=gui.P.surface)
        row2.pack(anchor="w", fill="x", pady=(2, 0))
        self.url_lbl = tk.Label(row2, text=self._url_label(), bg=gui.P.surface, fg=gui.P.muted, font=font(11), anchor="w")
        self.url_lbl.pack(side="left")

        self.update_tip = tk.Label(
            left,
            text="",
            bg=gui.P.surface,
            fg=gui.P.muted,
            font=font(11),
            justify="left",
            anchor="w",
        )
        self._tip_host = left

        split = tk.Frame(root_pad, bg=gui.P.bg)
        split.pack(fill="both", expand=True)
        split.grid_columnconfigure(0, weight=0, minsize=300)
        split.grid_columnconfigure(1, weight=1, minsize=360)
        split.grid_rowconfigure(0, weight=1)

        left_shell = tk.Frame(split, bg=gui.P.bg)
        left_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self._left_scroll = ScrollColumn(left_shell)
        self._left_scroll.pack(fill="both", expand=True)
        col_left = self._left_scroll.inner

        col_right = tk.Frame(split, bg=gui.P.bg)
        col_right.grid(row=0, column=1, sticky="nsew")

        tk.Label(col_left, text=t("settings"), bg=gui.P.bg, fg=gui.P.muted, font=font(11, bold=True)).pack(
            anchor="w", padx=2, pady=(0, 4)
        )
        settings = Card(col_left, pady=(0, 0), padding=10)

        port_block = tk.Frame(settings.body, bg=gui.P.surface)
        port_block.pack(fill="x")
        tk.Label(port_block, text=t("web_port"), bg=gui.P.surface, fg=gui.P.label, font=font(12, bold=True)).pack(
            anchor="w"
        )

        port_row = tk.Frame(port_block, bg=gui.P.surface)
        port_row.pack(fill="x", pady=(6, 0))
        port_shell = tk.Frame(
            port_row,
            bg=gui.P.surface_2,
            highlightthickness=1,
            highlightbackground=gui.P.hairline,
            highlightcolor=gui.P.accent,
        )
        port_shell.pack(side="left")
        self.port_entry = tk.Entry(
            port_shell,
            textvariable=self._port_var,
            width=8,
            bg=gui.P.surface_2,
            fg=gui.P.label,
            insertbackground=gui.P.label,
            relief="flat",
            highlightthickness=0,
            bd=0,
            font=font(12),
        )
        self.port_entry.pack(side="left", padx=(8, 8), pady=4)
        self.port_entry.bind(
            "<FocusIn>",
            lambda *_: port_shell.configure(highlightbackground=gui.P.accent),
        )
        self.port_entry.bind(
            "<FocusOut>",
            lambda *_: port_shell.configure(highlightbackground=gui.P.hairline),
        )
        RoundedButton(port_row, t("btn_restore"), self._on_restore_port, padx=10).pack(side="right")
        RoundedButton(port_row, t("btn_apply"), self._on_apply_port, kind="accent", padx=10).pack(
            side="right", padx=(0, 6)
        )

        port_hint = tk.Label(
            port_block,
            text=t("port_hint", port=DEFAULT_PORT),
            bg=gui.P.surface,
            fg=gui.P.muted,
            font=font(11),
            justify="left",
            anchor="w",
        )
        port_hint.pack(anchor="w", fill="x", pady=(4, 0))
        bind_wrap(port_hint)

        self._add_toggle_row(
            settings.body,
            title=t("chrome"),
            subtitle=t("chrome_sub"),
            variable=self._chrome_var,
            command=self._on_toggle_chrome,
            attr="chrome_toggle",
        )
        self.mirror_sub = self._add_toggle_row(
            settings.body,
            title=t("mirror"),
            subtitle="",
            variable=self._mirror_var,
            command=self._on_toggle_mirror,
            attr="mirror_toggle",
            sub_attr="mirror_sub",
        )
        self._refresh_mirror_hint()
        self._add_toggle_row(
            settings.body,
            title=t("search"),
            subtitle=t("search_sub"),
            variable=self._search_var,
            command=self._on_toggle_search,
            attr="search_toggle",
        )
        self._add_toggle_row(
            settings.body,
            title=t("auto_start"),
            subtitle=t("auto_start_sub"),
            variable=self._auto_start_var,
            command=self._on_toggle_auto_start,
            attr="auto_start_toggle",
        )
        self._add_toggle_row(
            settings.body,
            title=t("check_plugins"),
            subtitle=t("check_plugins_sub"),
            variable=self._check_plugins_var,
            command=self._on_toggle_check_plugins,
            attr="check_plugins_toggle",
        )

        appear_block = tk.Frame(settings.body, bg=gui.P.surface)
        appear_block.pack(fill="x", pady=(8, 8))
        tk.Frame(appear_block, bg=gui.P.hairline, height=1).pack(fill="x")
        tk.Label(
            appear_block, text=t("appearance"), bg=gui.P.surface, fg=gui.P.label, font=font(12, bold=True)
        ).pack(anchor="w", pady=(8, 0))
        chips = tk.Frame(appear_block, bg=gui.P.surface)
        chips.pack(anchor="w", pady=(6, 0))
        self.btn_theme_dark = RoundedButton(
            chips, t("theme_dark"), lambda: self._on_theme("dark"), kind="accent" if get_theme() == "dark" else "fill", padx=8
        )
        self.btn_theme_light = RoundedButton(
            chips, t("theme_light"), lambda: self._on_theme("light"), kind="accent" if get_theme() == "light" else "fill", padx=8
        )
        self.btn_lang_zh = RoundedButton(
            chips, t("lang_zh"), lambda: self._on_language("zh"), kind="accent" if i18n_language() == "zh" else "fill", padx=8
        )
        self.btn_lang_en = RoundedButton(
            chips, t("lang_en"), lambda: self._on_language("en"), kind="accent" if i18n_language() == "en" else "fill", padx=8
        )
        self.btn_theme_dark.pack(side="left")
        self.btn_theme_light.pack(side="left", padx=(6, 0))
        self.btn_lang_zh.pack(side="left", padx=(12, 0))
        self.btn_lang_en.pack(side="left", padx=(6, 0))
        self.root.after(80, self._left_scroll.show_scrollbar_if_needed)

        log_head = tk.Frame(col_right, bg=gui.P.bg)
        log_head.pack(fill="x", pady=(0, 4))
        tk.Label(log_head, text=t("logs"), bg=gui.P.bg, fg=gui.P.muted, font=font(11, bold=True)).pack(
            side="left", padx=2
        )
        self.btn_log_clear = RoundedButton(log_head, t("logs_clear"), self._clear_logs, padx=8)
        self.btn_log_clear.pack(side="right")
        log_card = Card(col_right, expand=True, pady=(0, 0), padding=6)
        log_frame = tk.Frame(log_card.body, bg=gui.P.log_bg)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_frame,
            wrap="char",
            bg=gui.P.log_bg,
            fg=gui.P.log_fg,
            insertbackground=gui.P.label,
            relief="flat",
            font=mono(11),
            padx=8,
            pady=8,
            state="disabled",
            highlightthickness=0,
            borderwidth=0,
            spacing1=2,
            spacing3=2,
        )
        self._log_scroll = tk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log.yview,
            width=14,
            bg=gui.P.surface_2,
            troughcolor=gui.P.log_bg,
            activebackground=gui.P.hairline,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.log.configure(yscrollcommand=self._log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        self._log_scroll.pack(side="right", fill="y")
        log_frame.bind("<Enter>", self._log_pointer_in)
        self.log.bind("<MouseWheel>", self._on_log_wheel)
        self.log.bind("<Button-4>", self._on_log_wheel)
        self.log.bind("<Button-5>", self._on_log_wheel)

    def _add_toggle_row(
        self,
        parent: tk.Misc,
        *,
        title: str,
        subtitle: str,
        variable: tk.BooleanVar,
        command,
        attr: str,
        sub_attr: str | None = None,
    ) -> tk.Label:
        sep = tk.Frame(parent, bg=gui.P.hairline, height=1)
        sep.pack(fill="x", pady=(5, 0))
        row = tk.Frame(parent, bg=gui.P.surface)
        row.pack(fill="x", pady=(5, 0))
        slot = tk.Frame(row, bg=gui.P.surface)
        slot.pack(side="right", padx=(8, 0), anchor="center")
        toggle = Toggle(slot, variable, command=command)
        setattr(self, attr, toggle)
        toggle.pack()
        copy = tk.Frame(row, bg=gui.P.surface)
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(copy, text=title, bg=gui.P.surface, fg=gui.P.label, font=font(12, bold=True)).pack(anchor="w")
        sub = tk.Label(
            copy,
            text=subtitle,
            bg=gui.P.surface,
            fg=gui.P.muted,
            font=font(11),
            justify="left",
            anchor="w",
        )
        sub.pack(anchor="w", fill="x", pady=(2, 0))
        bind_wrap(sub)
        if sub_attr:
            setattr(self, sub_attr, sub)
        return sub

    def _ui(self, fn) -> None:
        self.root.after(0, fn)

    def _setup_tray(self) -> None:
        menu = Menu(
            MenuItem(t("tray_show"), lambda *_: self._ui(self._show_window), default=True),
            MenuItem(t("tray_open"), lambda *_: self._ui(self._on_open)),
            Menu.SEPARATOR,
            MenuItem(t("tray_start"), lambda *_: self._ui(self._on_start)),
            MenuItem(t("tray_stop"), lambda *_: self._ui(self._on_stop)),
            MenuItem(t("tray_restart"), lambda *_: self._ui(self._on_restart)),
            Menu.SEPARATOR,
            MenuItem(t("tray_quit"), lambda *_: self._ui(self._quit)),
        )
        self._tray = Icon("DeepSeek Harness", _tray_image(), "DeepSeek Harness", menu)
        threading.Thread(target=self._tray.run, name="dsh-tray", daemon=True).start()

    def _hide_to_tray(self) -> None:
        self.root.withdraw()
        if not self._tray_hinted and self._tray is not None:
            self._tray_hinted = True
            try:
                self._tray.notify("已缩小到托盘，Harness 继续运行。右键「退出」才会关掉。", "DeepSeek Harness")
            except Exception:
                pass
            self._log("窗口已缩小到托盘，Harness 继续运行。")

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _refresh_url(self) -> None:
        self.url_lbl.configure(text=self._url_label())
        if self._tray is not None:
            self._tray.title = f"DeepSeek Harness · {self._port}"

    def _log(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logs.put(f"[{stamp}] {line}")

    def _clear_logs(self) -> None:
        while True:
            try:
                self.logs.get_nowait()
            except queue.Empty:
                break
        try:
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.configure(state="disabled")
        except tk.TclError:
            pass

    def _on_log_wheel(self, event) -> str:
        if getattr(event, "num", None) == 4:
            steps = -1
        elif getattr(event, "num", None) == 5:
            steps = 1
        else:
            steps = int(-event.delta / 120)
        if steps:
            self.log.yview_scroll(steps, "units")
        return "break"

    def _log_pointer_in(self, *_args) -> None:
        try:
            self._left_scroll._unbind_wheel()
        except Exception:
            pass

    def _drain_logs(self) -> None:
        try:
            while True:
                line = self.logs.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                if float(self.log.index("end")) > 4000:
                    self.log.delete("1.0", "200.0")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._drain_logs)

    def _set_status(self, text: str, color: str | None = None) -> None:
        kind_map = {
            t("status_stopped"): "stopped",
            t("status_starting"): "starting",
            t("status_running"): "running",
            t("status_stopping"): "stopping",
            t("status_restarting"): "restarting",
            t("status_timeout"): "timeout",
            t("status_failed"): "failed",
            t("status_error"): "error",
            t("status_missing"): "missing",
            t("status_installing"): "installing",
            t("status_wait_restart"): "wait_restart",
        }
        self._status_kind = kind_map.get(text, self._status_kind)
        self._set_status_kind(self._status_kind, color=color, label=text)

    def _set_status_kind(self, kind: str, *, color: str | None = None, label: str | None = None) -> None:
        self._status_kind = kind
        colors = {
            "stopped": gui.P.secondary,
            "starting": gui.P.accent,
            "running": gui.P.green,
            "stopping": gui.P.secondary,
            "restarting": gui.P.accent,
            "timeout": gui.P.red,
            "failed": gui.P.red,
            "error": gui.P.red,
            "missing": gui.P.orange,
            "installing": gui.P.accent,
            "wait_restart": gui.P.accent,
        }
        paint = color or colors.get(kind, gui.P.secondary)
        key = {
            "stopped": "status_stopped",
            "starting": "status_starting",
            "running": "status_running",
            "stopping": "status_stopping",
            "restarting": "status_restarting",
            "timeout": "status_timeout",
            "failed": "status_failed",
            "error": "status_error",
            "missing": "status_missing",
            "installing": "status_installing",
            "wait_restart": "status_wait_restart",
        }.get(kind, "status_stopped")
        text = label or t(key)
        self._status = text
        try:
            self.status_lbl.configure(text=f"{t('status')}  {text}", fg=paint)
            self._status_dot.itemconfigure(self._dot_id, fill=paint)
        except tk.TclError:
            pass

    def _boot(self) -> None:
        def go() -> None:
            from dsh_launcher.dsh_cli import find_working_dsh

            found = find_working_dsh()
            listening = is_listening(port=self._port)
            if self._quitting:
                return

            def apply() -> None:
                if not found:
                    self._log("未检测到可用的 DSH CLI，已跳过自动启动。可在顶栏一键安装。")
                    self._set_status_kind("missing")
                    return
                self._log(f"检测到 DSH CLI：{found}")
                if listening:
                    self._log(f"检测到 {self._port} 已在监听，接管已有实例（不重复启动）。")
                    self._set_status_kind("running")
                    return
                if not bool(self._auto_start_var.get()):
                    self._log("已关闭自动启动，等待手动点「启动」。")
                    self._set_status_kind("stopped")
                    return
                if self._plugins_block_start():
                    self._set_status_kind("stopped")
                    return
                self._log("自动启动 DeepSeek Harness…")
                self._on_start()

            self._ui(apply)

        threading.Thread(target=go, name="dsh-boot", daemon=True).start()

    def _open_plugins(self, *, block_start: bool = False) -> None:
        mgr = getattr(self, "_plugin_mgr", None)
        if mgr is not None:
            try:
                if mgr.win.winfo_exists():
                    mgr.set_block_start(block_start)
                    mgr.recenter()
                    mgr.win.lift()
                    mgr.win.focus_force()
                    mgr.refresh()
                    return
            except tk.TclError:
                pass
        from dsh_launcher.plugins_ui import PluginManager

        self._plugin_mgr = PluginManager(
            self,
            use_mirror=bool(self._mirror_var.get()),
            log=self._log,
            block_start=block_start,
        )

    def _plugins_block_start(self) -> bool:
        if not bool(self._check_plugins_var.get()):
            return False
        from dsh_launcher.plugins import enabled_incompatible

        bad = enabled_incompatible()
        if not bad:
            return False
        names = "、".join(row.name for row in bad)
        self._log(f"发现不兼容插件：{names}。已打开插件管理，未启动。")
        self._open_plugins(block_start=True)
        return True

    def _on_toggle_check_plugins(self) -> None:
        enabled = bool(self._check_plugins_var.get())
        try:
            set_check_plugins_on_start(enabled)
        except Exception as exc:
            self._log(f"保存插件检查开关失败: {exc}")
            self._check_plugins_var.set(not enabled)
            return
        if enabled:
            self._log("已开启：启动前检查插件兼容性")
        else:
            self._log("已关闭启动前插件检查")

    def _show_about(self) -> None:
        if getattr(self, "_about_win", None) is not None:
            try:
                if self._about_win.winfo_exists():
                    self._about_win.lift()
                    self._about_win.focus_force()
                    return
            except tk.TclError:
                pass
        win = tk.Toplevel(self.root)
        self._about_win = win
        win.withdraw()
        win.title(t("about_title"))
        win.configure(bg=gui.P.surface)
        win.resizable(False, False)
        win.transient(self.root)
        body = tk.Frame(win, bg=gui.P.surface, padx=28, pady=24)
        body.pack()
        tk.Label(body, text=t("about_name"), bg=gui.P.surface, fg=gui.P.label, font=font(14, bold=True)).pack(
            anchor="w"
        )
        tk.Label(body, text=t("about_author"), bg=gui.P.surface, fg=gui.P.secondary, font=font(12)).pack(
            anchor="w", pady=(12, 0)
        )
        RoundedButton(body, t("about_ok"), win.destroy, kind="accent", height=36, padx=20).pack(
            anchor="e", pady=(20, 0)
        )
        win.update_idletasks()
        gui.place_over_parent(
            win, self.root, width=max(win.winfo_reqwidth(), 280), height=max(win.winfo_reqheight(), 140)
        )
        win.grab_set()

    def _set_upgrade_visible(self, show: bool) -> None:
        self._set_action_mode("upgrade" if show else "")

    def _set_action_mode(self, mode: str) -> None:
        """mode: '' | 'upgrade' | 'install'.

        Install mode must not also pack 「检查更新」 — that canvas was being
        crushed to a 1px sliver beside the install button.
        """
        self._action_mode = mode
        self.btn_upgrade.pack_forget()
        self.btn_install.pack_forget()
        self.btn_check.pack_forget()
        if mode == "upgrade":
            self.btn_upgrade.pack(side="right", padx=(8, 0))
            self.btn_check.pack(side="right")
        elif mode == "install":
            self.btn_install.pack(side="right")
        else:
            self.btn_check.pack(side="right")

    def _set_install_tip(self, text: str | None) -> None:
        if text:
            self.update_tip.configure(text=text)
            if not self.update_tip.winfo_ismapped():
                self.update_tip.pack(anchor="w", fill="x", pady=(6, 0))
        else:
            self.update_tip.configure(text="")
            self.update_tip.pack_forget()

    def _apply_update_info(self, info: UpdateInfo, *, silent: bool) -> None:
        self._last_update = info
        self._local_ver = info.local
        self._latest_ver = info.latest
        self._update_available = bool(info.available)
        if info.missing:
            mirror = t("tip_mirror_on") if bool(self._mirror_var.get()) else t("tip_mirror_off")
            if info.need_node:
                self.update_lbl.configure(
                    text=t("missing_node"),
                    fg=gui.P.orange,
                    font=font(13, bold=True),
                )
                self._set_install_tip(t("tip_need_node") + mirror)
                self._set_action_mode("install")
            else:
                latest = t("latest_suffix", ver=info.latest) if info.latest else ""
                self.update_lbl.configure(
                    text=t("missing_dsh") + latest,
                    fg=gui.P.orange,
                    font=font(13, bold=True),
                )
                self._set_install_tip(t("tip_need_dsh") + mirror)
                self._set_action_mode("install")
            if not silent:
                self._log(info.error or "未检测到 DSH")
            return
        self._set_install_tip(None)
        if info.error:
            shown = info.error.replace("\n", " ")
            if len(shown) > 80:
                shown = shown[:77] + "…"
            self.update_lbl.configure(text=f"版本检查失败：{shown}", fg=gui.P.orange, font=font(11, bold=True))
            self._set_action_mode("")
            self._log(f"版本检查失败：{info.error}")
            return
        local = info.local or "?"
        latest = info.latest or "?"
        if info.available:
            self.update_lbl.configure(
                text=f"发现新版本 {latest}（当前 {local}）",
                fg=gui.P.orange,
                font=font(12, bold=True),
            )
            self._set_action_mode("upgrade")
            self._log(f"发现 DSH 新版本：{latest}（当前 {local}）")
        else:
            self.update_lbl.configure(
                text=f"已是最新  {local}",
                fg=gui.P.secondary,
                font=font(11),
            )
            self._set_action_mode("")
            if not silent:
                self._log(f"DSH 已是最新版本：{local}")
        if self._status_kind in {"missing", "installing"}:
            self._set_status_kind("stopped")

    def _check_update(self, *, silent: bool = False) -> None:
        if self._update_busy or self._quitting:
            return
        if not silent:
            self.update_lbl.configure(text="正在检查更新…", fg=gui.P.muted, font=font(11))

        def run() -> None:
            self._update_busy = True
            try:
                info = check_update(use_mirror=bool(self._mirror_var.get()))
            except Exception as exc:
                info = UpdateInfo(None, None, False, str(exc))
            finally:
                self._update_busy = False
            if self._quitting:
                return
            self._ui(lambda: self._apply_update_info(info, silent=silent))

        threading.Thread(target=run, name="dsh-update-check", daemon=True).start()

    def _run_npm_install(self, *, label: str) -> None:
        if self._update_busy or self._busy or self._quitting:
            return
        self.update_lbl.configure(text=f"正在{label} DSH…", fg=gui.P.accent, font=font(11, bold=True))
        self._set_status_kind("installing")
        self._log(f"开始{label}：若缺 npm 会先自动安装 Node.js，再 npm install -g @deepseek-ai/dsh@latest")

        def go() -> None:
            self._update_busy = True
            was_running = is_listening(port=self._port) or self.harness.alive()
            try:
                if was_running:
                    self._log(f"{label}前先停止 Harness…")
                    self.harness.stop(port=self._port)
                    self._ui(lambda: self._set_status_kind("stopped"))
                    self._ui(lambda: self._set_status_kind("installing"))

                last_ui = [0.0]

                def progress(line: str) -> None:
                    text = line.strip()
                    if not text:
                        return
                    self._log(text)
                    now = time.time()
                    if now - last_ui[0] < 0.25:
                        return
                    last_ui[0] = now
                    shown = (text[:48] + "…") if len(text) > 48 else text
                    self._ui(
                        lambda s=shown: self.update_lbl.configure(
                            text=s,
                            fg=gui.P.accent,
                            font=font(11, bold=True),
                        )
                    )

                ok, detail = install_or_upgrade_latest(
                    log=progress,
                    use_mirror=bool(self._mirror_var.get()),
                )
                if not ok:
                    if detail:
                        for line in detail.splitlines()[-8:]:
                            if line.strip():
                                self._log(line)
                    self._ui(
                        lambda: self.update_lbl.configure(
                            text=f"{label}失败，详见日志",
                            fg=gui.P.red,
                            font=font(11, bold=True),
                        )
                    )
                    self._ui(lambda: self._set_status_kind("missing"))
                    self._log(f"{label}失败。")
                    return
                self._log(f"{label}完成，正在复查版本…")
                info = check_update(use_mirror=bool(self._mirror_var.get()))
                self._ui(lambda: self._apply_update_info(info, silent=False))
                if was_running and not self._quitting and info.local:
                    self._log(f"{label}后重新启动 Harness…")
                    self._ui(self._on_start)
                elif info.local and not self._quitting:
                    self._log(f"{label}完成，可点击「启动」。")
            except Exception as exc:
                self._log(f"{label}出错：{exc}")
                self._ui(
                    lambda: self.update_lbl.configure(
                        text=f"{label}出错：{exc}",
                        fg=gui.P.red,
                        font=font(11, bold=True),
                    )
                )
                self._ui(lambda: self._set_status_kind("missing"))
            finally:
                self._update_busy = False

        threading.Thread(target=go, name="dsh-npm-install", daemon=True).start()

    def _on_upgrade(self) -> None:
        self._run_npm_install(label="升级")

    def _on_install(self) -> None:
        self._run_npm_install(label="安装")

    def _work(self, fn) -> None:
        if self._busy or self._quitting:
            return

        def run() -> None:
            self._busy = True
            try:
                fn()
            except Exception as exc:
                self._log(f"错误: {exc}")
                self._ui(lambda: self._set_status_kind("error"))
            finally:
                self._busy = False

        threading.Thread(target=run, daemon=True).start()

    def _on_start(self, force: bool = False) -> None:
        if not force and self._plugins_block_start():
            if self._status_kind == "starting":
                self._set_status_kind("stopped")
            return
        self._set_status_kind("starting")

        def go() -> None:
            if is_listening(port=self._port) and not self.harness.alive():
                self._log("端口已占用，视为已在运行。")
                self._log(t("open_need_token"))
                self._ui(lambda: (self._set_status_kind("running"), self._refresh_url()))
                return
            try:
                self.harness.start()
            except FileNotFoundError as exc:
                self._log(str(exc))
                self._ui(lambda: self._set_status_kind("failed"))
                return
            result = self.harness.wait_ready(timeout=45, port=self._port)
            if result == "ready":
                self._log(f"已就绪 {self._url_label()}")
                self._ui(lambda: self._after_ready())
                return
            if result == "exited":
                time.sleep(0.2)
                hint = self.harness.fail_hint or "进程已退出，端口未就绪。"
                self._log(f"启动失败：{hint}")
                self._ui(lambda: self._set_status_kind("failed"))
                return
            self._log(f"启动超时：尚未监听 {self._port}。")
            self._ui(lambda: self._set_status_kind("timeout"))

        self._work(go)

    def _on_stop(self) -> None:
        self._set_status_kind("stopping")

        def go() -> None:
            self.harness.stop(port=self._port)
            self.harness.web_url = None
            self._last_open_url = None
            self._child_lost_at = None
            self._orphan_restarts = 0
            self._ui(lambda: (self._set_status_kind("stopped"), self._refresh_url()))

        self._work(go)

    def _on_restart(self, *, old_port: int | None = None) -> None:
        if self._plugins_block_start():
            if self._status_kind == "restarting":
                self._set_status_kind("stopped")
            return
        self._set_status_kind("restarting")
        stop_port = old_port if old_port is not None else self._port

        def go() -> None:
            self.harness.stop(port=stop_port)
            time.sleep(0.4)
            try:
                self.harness.start()
            except FileNotFoundError as exc:
                self._log(str(exc))
                self._ui(lambda: self._set_status_kind("failed"))
                return
            result = self.harness.wait_ready(timeout=45, port=self._port)
            if result == "ready":
                self._log(f"重启完成 {self._url_label()}")
                self._ui(lambda: self._after_ready())
            elif result == "exited":
                hint = self.harness.fail_hint or "进程已退出。"
                self._log(f"重启失败：{hint}")
                self._ui(lambda: self._set_status_kind("failed"))
            else:
                self._log("重启后端口仍未就绪。")
                self._ui(lambda: self._set_status_kind("timeout"))

        self._work(go)

    def _after_ready(self) -> None:
        self._set_status_kind("running")
        self._refresh_url()
        # Never open the bare port. DSH 0.1.2+ needs ?token=; _tick opens
        # once harness.web_url is captured.
        self._maybe_auto_open(allow_bare=False)

    def _maybe_auto_open(self, *, allow_bare: bool = False) -> None:
        url = self._url()
        if "token=" not in url and not allow_bare:
            return
        if self._last_open_url == url:
            return
        self._last_open_url = url
        self._on_open()

    def _on_open(self) -> None:
        url = self._url()
        if "token=" not in url:
            self._log(t("open_need_token"))
        use_chrome = bool(self._chrome_var.get())
        _ok, msg = open_url(url, use_chrome=use_chrome)
        self._last_open_url = url
        self._log(msg)

    def _on_toggle_chrome(self) -> None:
        enabled = bool(self._chrome_var.get())
        try:
            set_open_with_chrome(enabled)
        except Exception as exc:
            self._log(f"保存 Chrome 开关失败: {exc}")
            self._chrome_var.set(not enabled)
            return
        if enabled:
            self._log("已开启：用固定 Chrome 配置打开网页（登录会保留）")
        else:
            self._log("已关闭：用系统默认浏览器打开网页")

    def _refresh_mirror_hint(self) -> None:
        if bool(self._mirror_var.get()):
            self.mirror_sub.configure(text=t("mirror_on"), fg=gui.P.muted)
        else:
            self.mirror_sub.configure(text=t("mirror_off"), fg=gui.P.orange)

    def _on_toggle_mirror(self) -> None:
        enabled = bool(self._mirror_var.get())
        try:
            set_use_china_mirror(enabled)
        except Exception as exc:
            self._log(f"保存镜像开关失败: {exc}")
            self._mirror_var.set(not enabled)
            return
        self._refresh_mirror_hint()
        if enabled:
            self._log("已开启国内镜像加速：registry.npmmirror.com / cdn.npmmirror.com")
        else:
            self._log("已关闭镜像加速。安装 npm / DSH 请先打开系统代理。")

    def _parse_port_entry(self) -> int:
        raw = self._port_var.get().strip()
        if not raw.isdigit():
            raise ValueError("端口必须是数字")
        n = int(raw)
        if n < 1 or n > 65535:
            raise ValueError("端口必须在 1–65535")
        return n

    def _apply_port(self, port: int | None, *, restart: bool) -> None:
        old = self._port
        try:
            changed = set_web_port(port)
        except Exception as exc:
            self._log(f"写入端口失败: {exc}")
            self._port_var.set(str(self._port))
            return
        self._port = current_web_port()
        self._port_var.set(str(self._port))
        self._refresh_url()
        if port is None:
            self._log(f"已恢复默认端口表达式（回退 {DEFAULT_PORT}）")
        else:
            self._log(f"已写入 webserver.port = {self._port}")
        if not changed and old == self._port:
            self._log("端口未变化。")
            return
        if restart and (is_listening(port=old) or self.harness.alive()):
            self._log("端口已改，正在重启使补丁生效…")
            self._on_restart(old_port=old)

    def _on_apply_port(self) -> None:
        try:
            n = self._parse_port_entry()
        except ValueError as exc:
            self._log(str(exc))
            self._port_var.set(str(self._port))
            return
        self._apply_port(n, restart=True)

    def _on_restore_port(self) -> None:
        self._apply_port(None, restart=True)

    def _on_toggle_auto_start(self) -> None:
        enabled = bool(self._auto_start_var.get())
        try:
            set_auto_start(enabled)
        except Exception as exc:
            self._log(f"保存自动启动开关失败: {exc}")
            self._auto_start_var.set(not enabled)
            return
        if enabled:
            self._log("已开启：打开启动器时自动启动 Harness")
        else:
            self._log("已关闭自动启动：打开启动器只显示面板")

    def _on_toggle_search(self) -> None:
        enabled = bool(self._search_var.get())
        try:
            changed = set_disable_builtin_search(enabled)
        except Exception as exc:
            self._log(f"写入搜索补丁失败: {exc}")
            self._search_var.set(not enabled)
            return
        if enabled:
            self._log("已关闭 DSH 自带搜索：写入 web-search-deepseek disabled + tool-web.search=false")
        else:
            self._log("已恢复 DSH 自带搜索：移除对应 patch 条目")
        if not changed:
            self._log("配置文件已是目标状态，无需改写。")
            return
        if is_listening(port=self._port) or self.harness.alive():
            self._log("配置已改，正在重启使补丁生效…")
            self._on_restart()

    def _tick(self) -> None:
        if self._quitting:
            return
        if self._busy or self._update_busy or self.harness.stopping:
            self.root.after(700, self._tick)
            return
        if self._status_kind == "installing":
            self.root.after(700, self._tick)
            return
        listening = is_listening(port=self._port, timeout=0.05)
        child = self.harness.alive()
        decision = watch_disconnect(
            listening=listening,
            child=child,
            status=self._status_kind,
            fail_hint=self.harness.fail_hint,
            lost_at=self._child_lost_at,
            now=time.time(),
            orphan_restarts=self._orphan_restarts,
        )
        if listening or child:
            self._orphan_restarts = 0
        if decision.clear_fail_hint:
            self.harness.fail_hint = None
        self._child_lost_at = decision.lost_at
        if decision.log == "revived":
            self._log("Harness 已在后台复活（插件市场重启），启动器继续待命。")
        elif decision.log == "waiting":
            self._log("端口暂时关闭，等待插件市场重启（启动器不会退出）…")
        elif decision.log == "crashed":
            self._log("Harness 异常退出，已停止自动重启。")
            if self.harness.fail_hint:
                self._log(self.harness.fail_hint)
        elif decision.log == "autostart":
            self._log("等待超时，由启动器重新拉起。")
        elif decision.log == "gave_up":
            self._log("多次未能恢复监听，已停止自动重启。请查看日志后手动启动。")
        if decision.status:
            self._set_status_kind(decision.status)
        if decision.autostart:
            self._orphan_restarts += 1
            self._on_start()
        try:
            if self._status_kind == "running":
                self._refresh_url()
                self._maybe_auto_open(allow_bare=False)
        except tk.TclError:
            pass
        self.root.after(700, self._tick)

    def _on_theme(self, name: str) -> None:
        persist_theme(name)
        gui.apply_palette(name)
        self._rebuild_ui()

    def _on_language(self, lang: str) -> None:
        persist_language(lang)
        set_i18n_lang(lang)
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        log_dump = ""
        try:
            self.log.configure(state="normal")
            log_dump = self.log.get("1.0", "end-1c")
            self.log.configure(state="disabled")
        except tk.TclError:
            pass
        status_kind = getattr(self, "_status_kind", "stopped")
        last = self._last_update
        self._shell.destroy()
        self.root.configure(bg=gui.P.bg)
        self.root.title(t("app_title"))
        self._build()
        self._set_status_kind(status_kind)
        if last is not None:
            self._apply_update_info(last, silent=True)
        if log_dump:
            self.log.configure(state="normal")
            self.log.insert("end", log_dump)
            self.log.see("end")
            self.log.configure(state="disabled")

    def _quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.harness.stopping = True
        try:
            self.harness.stop(port=self._port)
        except Exception:
            pass
        tray = self._tray
        self._tray = None
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    LauncherApp().run()

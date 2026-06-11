#!/usr/bin/env python3
"""
303Modbus13 RTU Control — GUI for Ideaflex 303Modbus13 relay module.
MIT License — see LICENSE.
"""

from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk

logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk

from i18n import get_i18n
from modbus_device import (
    Modbus303Device,
    OperationCancelledError,
    RELAY_COUNT,
    INPUT_COUNT,
    SerialSettings,
    list_serial_ports,
    scan_for_device,
)

COLORS = {
    "bg": "#0f172a",
    "panel": "#1e293b",
    "panel_light": "#334155",
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "success": "#22c55e",
    "danger": "#ef4444",
    "warning": "#f59e0b",
    "text": "#f1f5f9",
    "text_muted": "#94a3b8",
    "relay_on": "#4ade80",
    "relay_off": "#475569",
    "input_active": "#fbbf24",
    "field_bg": "#e2e8f0",
    "field_text": "#0f172a",
}


class StatusLed(tk.Canvas):
    def __init__(self, master, size: int = 18, **kwargs):
        super().__init__(master, width=size, height=size, highlightthickness=0, **kwargs)
        self.size = size
        self._oid = self.create_oval(2, 2, size - 2, size - 2, fill=COLORS["relay_off"], outline="#64748b")
        self.configure(bg=COLORS["panel"])

    def set_state(self, active: bool, active_color: str = COLORS["relay_on"]) -> None:
        self.itemconfig(self._oid, fill=active_color if active else COLORS["relay_off"])


class RelayChannel(tk.Frame):
    def __init__(self, master, channel: int, on_toggle, **kwargs):
        super().__init__(master, bg=COLORS["panel"], padx=6, pady=4, **kwargs)
        self.channel = channel
        self.on_toggle = on_toggle

        tk.Label(
            self, text=f"CH{channel + 1}", font=("Segoe UI", 10, "bold"),
            fg=COLORS["text"], bg=COLORS["panel"], width=4,
        ).grid(row=0, column=0, padx=(0, 4))

        self.led = StatusLed(self, size=22)
        self.led.grid(row=0, column=1, padx=4)

        btn_frame = tk.Frame(self, bg=COLORS["panel"])
        btn_frame.grid(row=0, column=2, padx=(8, 0))

        self.btn_on = tk.Button(
            btn_frame, text="ON", width=4, font=("Segoe UI", 8, "bold"),
            bg=COLORS["success"], fg="white", activebackground="#16a34a",
            relief=tk.FLAT, cursor="hand2",
            command=lambda: self.on_toggle(channel, True),
        )
        self.btn_on.pack(side=tk.LEFT, padx=1)

        self.btn_off = tk.Button(
            btn_frame, text="OFF", width=4, font=("Segoe UI", 8, "bold"),
            bg=COLORS["danger"], fg="white", activebackground="#dc2626",
            relief=tk.FLAT, cursor="hand2",
            command=lambda: self.on_toggle(channel, False),
        )
        self.btn_off.pack(side=tk.LEFT, padx=1)

    def update_state(self, active: bool) -> None:
        self.led.set_state(active)


class InputChannel(tk.Frame):
    def __init__(self, master, channel: int, **kwargs):
        super().__init__(master, bg=COLORS["panel"], padx=4, pady=2, **kwargs)
        tk.Label(
            self, text=f"IN{channel + 1}", font=("Segoe UI", 9),
            fg=COLORS["text_muted"], bg=COLORS["panel"], width=4,
        ).pack(side=tk.LEFT)
        self.led = StatusLed(self, size=16)
        self.led.pack(side=tk.LEFT, padx=4)

    def update_state(self, active: bool) -> None:
        self.led.set_state(active, active_color=COLORS["input_active"])


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.i18n = get_i18n()
        self._lf_panels: list[tuple[tk.LabelFrame, str, dict]] = []
        self._conn_ui_state = "disconnected"
        self._conn_details = ""

        self.title(self.t("app.window_title"))
        self.geometry("960x720")
        self.minsize(860, 640)
        self.configure(bg=COLORS["bg"])

        self.device = Modbus303Device()
        self._modbus_lock = threading.Lock()
        self._user_op_active = False
        self._async_generation = 0
        self._cancel_requested = False
        self._pending_operation = ""

        self._build_styles()
        self._build_header()
        self._build_status_bar()
        self._build_notebook()
        self._refresh_ports()
        self._set_connection_status("disconnected")

    def t(self, key: str, **kwargs) -> str:
        return self.i18n.t(key, **kwargs)

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=COLORS["panel_light"],
            foreground=COLORS["text"],
            padding=[14, 8],
            font=("Segoe UI", 10),
        )
        style.map("TNotebook.Tab", background=[("selected", COLORS["accent"])])

        combo_style = "Field.TCombobox"
        style.configure(
            combo_style,
            fieldbackground=COLORS["field_bg"],
            background=COLORS["field_bg"],
            foreground=COLORS["field_text"],
            arrowcolor=COLORS["field_text"],
            bordercolor=COLORS["panel_light"],
        )
        style.map(
            combo_style,
            fieldbackground=[("readonly", COLORS["field_bg"]), ("disabled", COLORS["field_bg"])],
            foreground=[("readonly", COLORS["field_text"]), ("disabled", COLORS["text_muted"])],
            background=[("readonly", COLORS["field_bg"]), ("disabled", COLORS["field_bg"])],
            arrowcolor=[("readonly", COLORS["field_text"]), ("disabled", COLORS["text_muted"])],
        )
        self._combo_style = combo_style
        self.option_add("*TCombobox*Listbox.background", COLORS["field_bg"])
        self.option_add("*TCombobox*Listbox.foreground", COLORS["field_text"])

    def _style_combobox(self, combo: ttk.Combobox) -> None:
        def apply() -> None:
            try:
                for child in combo.winfo_children():
                    if child.winfo_class() in ("Entry", "TEntry"):
                        child.configure(
                            foreground=COLORS["field_text"],
                            background=COLORS["field_bg"],
                            readonlybackground=COLORS["field_bg"],
                            disabledforeground=COLORS["text_muted"],
                        )
            except tk.TclError:
                pass

        combo.bind("<Map>", lambda _e: apply(), add="+")
        combo.after_idle(apply)

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=COLORS["panel"], height=64)
        header.pack(fill=tk.X, padx=0, pady=0)
        header.pack_propagate(False)

        tk.Label(
            header, text="303Modbus13", font=("Segoe UI", 18, "bold"),
            fg=COLORS["accent"], bg=COLORS["panel"],
        ).pack(side=tk.LEFT, padx=20, pady=12)

        self.header_subtitle = tk.Label(
            header, text=self.t("header.subtitle"), font=("Segoe UI", 11),
            fg=COLORS["text_muted"], bg=COLORS["panel"],
        )
        self.header_subtitle.pack(side=tk.LEFT, pady=14)

        lang_frame = tk.Frame(header, bg=COLORS["panel"])
        lang_frame.pack(side=tk.RIGHT, padx=(0, 12), pady=14)
        self.lang_label = tk.Label(
            lang_frame, text=self.t("lang.label"), font=("Segoe UI", 9),
            fg=COLORS["text_muted"], bg=COLORS["panel"],
        )
        self.lang_label.pack(side=tk.LEFT, padx=(0, 6))
        self.lang_var = tk.StringVar()
        self.lang_combo = ttk.Combobox(
            lang_frame, textvariable=self.lang_var, width=12, state="readonly",
            values=[self.t("lang.pl"), self.t("lang.en")], style=self._combo_style,
        )
        self.lang_combo.pack(side=tk.LEFT)
        self._style_combobox(self.lang_combo)
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_language_changed)
        self._sync_lang_combo()

        status_frame = tk.Frame(header, bg=COLORS["panel"])
        status_frame.pack(side=tk.RIGHT, padx=20)

        self.conn_led = StatusLed(status_frame, size=22)
        self.conn_led.pack(side=tk.LEFT, padx=(0, 8))
        status_text = tk.Frame(status_frame, bg=COLORS["panel"])
        status_text.pack(side=tk.LEFT)
        self.conn_label = tk.Label(
            status_text, text=self.t("conn.disconnected"), font=("Segoe UI", 12, "bold"),
            fg=COLORS["danger"], bg=COLORS["panel"],
        )
        self.conn_label.pack(anchor="e")
        self.conn_detail_label = tk.Label(
            status_text, text=self.t("conn.detail_none"), font=("Segoe UI", 9),
            fg=COLORS["text_muted"], bg=COLORS["panel"],
        )
        self.conn_detail_label.pack(anchor="e")

    def _lang_display_to_code(self, display: str) -> str:
        for code in self.i18n.SUPPORTED:
            for catalog in self.i18n._catalog.values():
                if display == catalog.get(f"lang.{code}"):
                    return code
        return self.i18n.lang

    def _sync_lang_combo(self) -> None:
        self.lang_var.set(self.t("lang.en") if self.i18n.lang == "en" else self.t("lang.pl"))

    def _on_language_changed(self, _event=None) -> None:
        code = self._lang_display_to_code(self.lang_var.get())
        if code == self.i18n.lang:
            return
        self.i18n.set_language(code)
        self._apply_language()

    def _apply_language(self) -> None:
        self.lang_combo.configure(values=[self.t("lang.pl"), self.t("lang.en")])
        self._sync_lang_combo()
        self.lang_label.configure(text=self.t("lang.label"))
        self.header_subtitle.configure(text=self.t("header.subtitle"))
        self.notebook.tab(self.tab_connection, text=self.t("tab.connection"))
        self.notebook.tab(self.tab_control, text=self.t("tab.control"))
        self.notebook.tab(self.tab_advanced, text=self.t("tab.advanced"))
        self.notebook.tab(self.tab_about, text=self.t("tab.about"))

        for box, key, fmt in self._lf_panels:
            box.configure(text=f"  {self.t(key, **fmt)}  ")

        self.hint_label.configure(text=self.t("hint.factory_addr"))
        self.addr_help_label.configure(text=self.t("addr.help"))
        for lbl, key in self._conn_labels:
            lbl.configure(text=self.t(key))
        self.save_addr_btn.configure(text=self.t("btn.save_address"))
        for lbl, key in self._info_labels:
            lbl.configure(text=f"• {self.t(key)}")

        self.control_lock_label.configure(text=self.t("control.lock_banner"))
        self.both_on_btn.configure(text=self.t("btn.both_on"))
        self.both_off_btn.configure(text=self.t("btn.both_off"))
        self.refresh_btn.configure(text=self.t("btn.refresh"))
        self.read_inputs_btn.configure(text=self.t("btn.read_inputs"))
        self.advanced_help_label.configure(text=self.t("advanced.help"))
        for lbl, key in self._adv_labels:
            lbl.configure(text=self.t(key))
        self.execute_btn.configure(text=self.t("btn.execute"))
        self.result_label.configure(text=self.t("label.result"))
        self.about_label.configure(text=self.t("about.body"))
        for lbl, key in self._about_steps:
            lbl.configure(text=self.t(key))

        if not self.device.is_connected:
            th_text = self.t("th.not_connected")
        elif self.th_status_label.cget("fg") == COLORS["success"]:
            th_text = self.t("th.active")
        else:
            th_text = self.t("th.not_connected")
        self.th_status_label.configure(text=th_text)

        self._set_connection_status(self._conn_ui_state, self._conn_details)

    def _build_status_bar(self) -> None:
        self.status_bar = tk.Frame(self, bg=COLORS["panel_light"], height=28)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_bar.pack_propagate(False)
        self.status_bar_label = tk.Label(
            self.status_bar, text="", font=("Segoe UI", 9),
            fg=COLORS["text_muted"], bg=COLORS["panel_light"], anchor="w",
        )
        self.status_bar_label.pack(fill=tk.X, padx=12, pady=4)

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self.tab_connection = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.tab_control = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.tab_advanced = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.tab_about = tk.Frame(self.notebook, bg=COLORS["bg"])

        self.notebook.add(self.tab_connection, text=self.t("tab.connection"))
        self.notebook.add(self.tab_control, text=self.t("tab.control"))
        self.notebook.add(self.tab_advanced, text=self.t("tab.advanced"))
        self.notebook.add(self.tab_about, text=self.t("tab.about"))

        self._build_connection_tab()
        self._build_control_tab()
        self._build_advanced_tab()
        self._build_about_tab()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _panel(self, parent, title_key: str, **fmt) -> tk.Frame:
        outer = tk.Frame(parent, bg=COLORS["bg"])
        outer.pack(fill=tk.X, padx=8, pady=6)
        box = tk.LabelFrame(
            outer, text=f"  {self.t(title_key, **fmt)}  ", font=("Segoe UI", 10, "bold"),
            fg=COLORS["text"], bg=COLORS["panel"], labelanchor="nw",
            padx=12, pady=10,
        )
        box.pack(fill=tk.X)
        self._lf_panels.append((box, title_key, fmt))
        return box

    def _build_connection_tab(self) -> None:
        serial_panel = self._panel(self.tab_connection, "panel.serial")
        grid = tk.Frame(serial_panel, bg=COLORS["panel"])
        grid.pack(fill=tk.X)

        self._conn_labels: list[tuple[tk.Label, str]] = []
        for i, key in enumerate(["label.com_port", "label.baud", "label.slave"]):
            lbl = tk.Label(grid, text=self.t(key), font=("Segoe UI", 10), fg=COLORS["text_muted"], bg=COLORS["panel"])
            lbl.grid(row=i, column=0, sticky="w", pady=4, padx=(0, 12))
            self._conn_labels.append((lbl, key))

        port_row = tk.Frame(grid, bg=COLORS["panel"])
        port_row.grid(row=0, column=1, sticky="w", pady=4)
        self.port_var = tk.StringVar(value="COM4")
        self.port_combo = ttk.Combobox(
            port_row, textvariable=self.port_var, width=12, state="readonly", style=self._combo_style,
        )
        self.port_combo.pack(side=tk.LEFT)
        self._style_combobox(self.port_combo)
        tk.Button(
            port_row, text="↻", font=("Segoe UI", 9), width=3,
            bg=COLORS["panel_light"], fg=COLORS["text"], relief=tk.FLAT,
            command=self._refresh_ports,
        ).pack(side=tk.LEFT, padx=4)

        self.baud_var = tk.StringVar(value="9600")
        self.baud_combo = ttk.Combobox(
            grid, textvariable=self.baud_var, width=12, state="readonly",
            values=["4800", "9600", "19200"], style=self._combo_style,
        )
        self.baud_combo.grid(row=1, column=1, sticky="w", pady=4)
        self._style_combobox(self.baud_combo)

        self.slave_var = tk.StringVar(value="FF")
        tk.Entry(
            grid, textvariable=self.slave_var, width=8, font=("Consolas", 11),
            bg=COLORS["panel_light"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT,
        ).grid(row=2, column=1, sticky="w", pady=4)

        btn_row = tk.Frame(serial_panel, bg=COLORS["panel"])
        btn_row.pack(fill=tk.X, pady=(12, 0))

        self.connect_btn = tk.Button(
            btn_row, text=self.t("btn.connect"), font=("Segoe UI", 11, "bold"),
            bg=COLORS["accent"], fg="white", activebackground=COLORS["accent_hover"],
            relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
            command=self._toggle_connection,
        )
        self.connect_btn.pack(side=tk.LEFT)

        self.scan_btn = tk.Button(
            btn_row, text=self.t("btn.scan"), font=("Segoe UI", 10),
            bg=COLORS["panel_light"], fg=COLORS["text"], relief=tk.FLAT,
            padx=14, pady=8, cursor="hand2", command=self._scan_for_module,
        )
        self.scan_btn.pack(side=tk.LEFT, padx=(10, 0))

        self.hint_label = tk.Label(
            serial_panel, text=self.t("hint.factory_addr"),
            font=("Segoe UI", 9), fg=COLORS["warning"], bg=COLORS["panel"], wraplength=700, justify=tk.LEFT,
        )
        self.hint_label.pack(anchor="w", pady=(10, 0))

        self.conn_banner = tk.Frame(serial_panel, bg="#7f1d1d", pady=10, padx=12)
        self.conn_banner.pack(fill=tk.X, pady=(14, 0))
        self.conn_banner_led = StatusLed(self.conn_banner, size=20)
        self.conn_banner_led.pack(side=tk.LEFT, padx=(0, 10))
        self.conn_banner_text = tk.Frame(self.conn_banner, bg=self.conn_banner["bg"])
        self.conn_banner_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.conn_banner_title = tk.Label(
            self.conn_banner_text, text=self.t("conn.banner_title_disconnected"),
            font=("Segoe UI", 13, "bold"), fg="white", bg=self.conn_banner["bg"], anchor="w",
        )
        self.conn_banner_title.pack(fill=tk.X)
        self.conn_banner_sub = tk.Label(
            self.conn_banner_text, text=self.t("conn.banner_sub_disconnected"),
            font=("Segoe UI", 10), fg="#fecaca", bg=self.conn_banner["bg"], anchor="w",
        )
        self.conn_banner_sub.pack(fill=tk.X)

        addr_panel = self._panel(self.tab_connection, "panel.address")
        self.addr_help_label = tk.Label(
            addr_panel, text=self.t("addr.help"),
            font=("Segoe UI", 9), fg=COLORS["text_muted"], bg=COLORS["panel"], wraplength=700, justify=tk.LEFT,
        )
        self.addr_help_label.pack(anchor="w", pady=(0, 8))

        addr_row = tk.Frame(addr_panel, bg=COLORS["panel"])
        addr_row.pack(anchor="w")
        self.new_addr_lbl = tk.Label(addr_row, text=self.t("label.new_address"), font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["panel"])
        self.new_addr_lbl.pack(side=tk.LEFT)
        self._conn_labels.append((self.new_addr_lbl, "label.new_address"))
        self.new_addr_var = tk.StringVar(value="01")
        tk.Entry(
            addr_row, textvariable=self.new_addr_var, width=6, font=("Consolas", 11),
            bg=COLORS["panel_light"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=8)
        self.save_addr_btn = tk.Button(
            addr_row, text=self.t("btn.save_address"), font=("Segoe UI", 10),
            bg=COLORS["warning"], fg="#1e293b", activebackground="#d97706",
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2",
            command=self._set_device_address,
        )
        self.save_addr_btn.pack(side=tk.LEFT)

        info_panel = self._panel(self.tab_connection, "panel.comm_params")
        self._info_labels: list[tuple[tk.Label, str]] = []
        for key in ["info.proto", "info.format", "info.factory", "info.sensor"]:
            lbl = tk.Label(info_panel, text=f"• {self.t(key)}", font=("Segoe UI", 9), fg=COLORS["text_muted"], bg=COLORS["panel"], anchor="w")
            lbl.pack(anchor="w", pady=1)
            self._info_labels.append((lbl, key))

    def _build_control_tab(self) -> None:
        self.control_lock_banner = tk.Frame(self.tab_control, bg="#78350f", pady=8, padx=12)
        self.control_lock_banner.pack(fill=tk.X, padx=8, pady=(8, 0))
        self.control_lock_label = tk.Label(
            self.control_lock_banner, text=self.t("control.lock_banner"),
            font=("Segoe UI", 10, "bold"), fg="#fef3c7", bg="#78350f",
        )
        self.control_lock_label.pack(anchor="w")

        top = tk.Frame(self.tab_control, bg=COLORS["bg"])
        top.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(top, bg=COLORS["bg"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        relay_panel = self._panel(left, "panel.relays", last=RELAY_COUNT - 1)
        relay_grid = tk.Frame(relay_panel, bg=COLORS["panel"])
        relay_grid.pack(fill=tk.X)
        self.relay_channels: list[RelayChannel] = []
        for i in range(RELAY_COUNT):
            ch = RelayChannel(relay_grid, i, self._relay_toggle)
            ch.grid(row=0, column=i, sticky="w", padx=12, pady=6)
            self.relay_channels.append(ch)

        bulk_row = tk.Frame(relay_panel, bg=COLORS["panel"])
        bulk_row.pack(fill=tk.X, pady=(12, 0))
        self._control_buttons: list[tk.Button] = []
        self.both_on_btn = tk.Button(
            bulk_row, text=self.t("btn.both_on"), font=("Segoe UI", 9, "bold"),
            bg=COLORS["success"], fg="white", relief=tk.FLAT, padx=12, pady=6, cursor="hand2",
            command=lambda: self._set_all_relays(True),
        )
        self.both_on_btn.pack(side=tk.LEFT, padx=4)
        self._control_buttons.append(self.both_on_btn)
        self.both_off_btn = tk.Button(
            bulk_row, text=self.t("btn.both_off"), font=("Segoe UI", 9, "bold"),
            bg=COLORS["danger"], fg="white", relief=tk.FLAT, padx=12, pady=6, cursor="hand2",
            command=lambda: self._set_all_relays(False),
        )
        self.both_off_btn.pack(side=tk.LEFT, padx=4)
        self._control_buttons.append(self.both_off_btn)
        self.refresh_btn = tk.Button(
            bulk_row, text=self.t("btn.refresh"), font=("Segoe UI", 9, "bold"),
            bg=COLORS["accent"], fg="white", relief=tk.FLAT, padx=12, pady=6, cursor="hand2",
            command=self._refresh_status,
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=4)
        self._control_buttons.append(self.refresh_btn)

        input_panel = self._panel(left, "panel.inputs", count=INPUT_COUNT)
        input_grid = tk.Frame(input_panel, bg=COLORS["panel"])
        input_grid.pack(fill=tk.X)
        self.input_channels: list[InputChannel] = []
        for i in range(INPUT_COUNT):
            ch = InputChannel(input_grid, i)
            ch.grid(row=0, column=i, sticky="w", padx=12, pady=4)
            self.input_channels.append(ch)
        self.read_inputs_btn = tk.Button(
            input_panel, text=self.t("btn.read_inputs"), font=("Segoe UI", 9),
            bg=COLORS["accent"], fg="white", relief=tk.FLAT, padx=10, pady=4,
            cursor="hand2", command=self._read_inputs_only,
        )
        self.read_inputs_btn.pack(anchor="w", pady=(8, 0))
        self._control_buttons.append(self.read_inputs_btn)

        right = tk.Frame(top, bg=COLORS["bg"])
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=(6, 0))

        th_panel = self._panel(right, "panel.th_sensor")
        self.th_temp_label = tk.Label(th_panel, text="— °C", font=("Segoe UI", 22, "bold"), fg=COLORS["accent"], bg=COLORS["panel"])
        self.th_temp_label.pack(pady=(4, 0))
        self.th_hum_label = tk.Label(th_panel, text="— %", font=("Segoe UI", 16), fg=COLORS["text_muted"], bg=COLORS["panel"])
        self.th_hum_label.pack()
        self.th_status_label = tk.Label(
            th_panel, text=self.t("th.not_connected"), font=("Segoe UI", 8),
            fg=COLORS["text_muted"], bg=COLORS["panel"],
        )
        self.th_status_label.pack(pady=(4, 0))

        log_panel = self._panel(self.tab_control, "panel.comm_log")
        self.log_text = scrolledtext.ScrolledText(
            log_panel, height=8, font=("Consolas", 9),
            bg="#0c1222", fg="#a5f3fc", insertbackground=COLORS["text"],
            relief=tk.FLAT, state=tk.DISABLED,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _build_advanced_tab(self) -> None:
        panel = self._panel(self.tab_advanced, "panel.modbus_console")
        self.advanced_help_label = tk.Label(
            panel, text=self.t("advanced.help"),
            font=("Segoe UI", 9), fg=COLORS["text_muted"], bg=COLORS["panel"], wraplength=800, justify=tk.LEFT,
        )
        self.advanced_help_label.pack(anchor="w", pady=(0, 10))

        form = tk.Frame(panel, bg=COLORS["panel"])
        form.pack(fill=tk.X)

        self._functions = [
            ("Read Coils (0x01)", "read_coils"),
            ("Read Discrete Inputs (0x02)", "read_discrete_inputs"),
            ("Read Holding Registers (0x03)", "read_holding_registers"),
            ("Read Input Registers (0x04)", "read_input_registers"),
            ("Write Single Coil (0x05)", "write_coil"),
            ("Write Single Register (0x06)", "write_register"),
            ("Write Multiple Coils (0x0F)", "write_coils"),
            ("Write Multiple Registers (0x10)", "write_registers"),
        ]
        self._func_map = {label: key for label, key in self._functions}
        self.func_display_var = tk.StringVar(value=self._functions[0][0])
        self._adv_labels: list[tuple[tk.Label, str]] = []
        lbl = tk.Label(form, text=self.t("label.function"), font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["panel"])
        lbl.grid(row=0, column=0, sticky="w", pady=4)
        self._adv_labels.append((lbl, "label.function"))
        func_combo = ttk.Combobox(
            form, textvariable=self.func_display_var, width=36, state="readonly",
            values=[f[0] for f in self._functions], style=self._combo_style,
        )
        func_combo.grid(row=0, column=1, sticky="w", pady=4, padx=8)
        self._style_combobox(func_combo)
        func_combo.bind("<<ComboboxSelected>>", self._on_advanced_function_changed)

        self.adv_address_var = tk.StringVar(value="0")
        self.adv_count_var = tk.StringVar(value="8")
        self.adv_values_var = tk.StringVar(value="")
        self.adv_slave_var = tk.StringVar(value="")

        for row, (key, var) in enumerate([
            ("label.address", self.adv_address_var),
            ("label.count", self.adv_count_var),
            ("label.values", self.adv_values_var),
            ("label.slave_optional", self.adv_slave_var),
        ], start=1):
            lbl = tk.Label(form, text=self.t(key), font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["panel"])
            lbl.grid(row=row, column=0, sticky="w", pady=4)
            self._adv_labels.append((lbl, key))
            tk.Entry(
                form, textvariable=var, width=40, font=("Consolas", 10),
                bg=COLORS["panel_light"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT,
            ).grid(row=row, column=1, sticky="w", pady=4, padx=8)

        self.execute_btn = tk.Button(
            panel, text=self.t("btn.execute"), font=("Segoe UI", 11, "bold"),
            bg=COLORS["accent"], fg="white", relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
            command=self._execute_advanced,
        )
        self.execute_btn.pack(anchor="w", pady=(12, 0))

        self.adv_result_var = tk.StringVar(value="")
        self.result_label = tk.Label(panel, text=self.t("label.result"), font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["panel"])
        self.result_label.pack(anchor="w", pady=(12, 4))
        tk.Entry(
            panel, textvariable=self.adv_result_var, font=("Consolas", 10),
            bg=COLORS["panel_light"], fg=COLORS["success"], state="readonly", relief=tk.FLAT,
        ).pack(fill=tk.X)

    def _build_about_tab(self) -> None:
        panel = self._panel(self.tab_about, "panel.about")
        self.about_label = tk.Label(
            panel, text=self.t("about.body"), font=("Segoe UI", 10), fg=COLORS["text"],
            bg=COLORS["panel"], justify=tk.LEFT, anchor="nw",
        )
        self.about_label.pack(anchor="w")

        doc_panel = self._panel(self.tab_about, "panel.quick_start")
        self._about_steps: list[tuple[tk.Label, str]] = []
        for key in ["about.step1", "about.step2", "about.step3", "about.step4", "about.step5", "about.step6"]:
            lbl = tk.Label(doc_panel, text=self.t(key), font=("Segoe UI", 10), fg=COLORS["text_muted"], bg=COLORS["panel"], anchor="w")
            lbl.pack(anchor="w", pady=2)
            self._about_steps.append((lbl, key))

    def _log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _refresh_ports(self) -> None:
        ports = list_serial_ports()
        self.port_combo["values"] = ports
        if ports and self.port_var.get() not in ports:
            preferred = "COM4" if "COM4" in ports else ports[0]
            self.port_var.set(preferred)

    def _set_connection_status(self, state: str, details: str = "") -> None:
        self._conn_ui_state = state
        self._conn_details = details

        if state == "connected":
            bg = "#14532d"
            sub_fg = "#bbf7d0"
            title = self.t("conn.banner_title_connected")
            header_text = self.t("conn.connected")
            header_fg = COLORS["success"]
            detail = details or self.t("conn.detail_active")
            bar = self.t("conn.bar_connected", detail=detail)
            win_suffix = self.t("app.window_connected")
            led_on = True
            self.connect_btn.configure(
                text=self.t("btn.disconnect"), bg=COLORS["danger"], activebackground="#dc2626",
                state=tk.NORMAL, command=self._toggle_connection,
            )
            self.scan_btn.configure(text=self.t("btn.scan"), state=tk.NORMAL, command=self._scan_for_module)
            self.control_lock_banner.pack_forget()
        elif state == "connecting":
            bg = "#713f12"
            sub_fg = "#fef08a"
            title = self.t("conn.banner_title_connecting")
            header_text = self.t("conn.connecting")
            header_fg = COLORS["warning"]
            detail = details or self.t("conn.detail_connecting")
            bar = self.t("conn.bar_connecting", detail=detail)
            win_suffix = self.t("app.window_connecting")
            led_on = True
            self.connect_btn.configure(
                text=self.t("btn.cancel"), bg=COLORS["danger"], activebackground="#dc2626",
                state=tk.NORMAL, command=self._cancel_pending_operation,
            )
            self.scan_btn.configure(text=self.t("btn.cancel"), state=tk.NORMAL, command=self._cancel_pending_operation)
            self.control_lock_banner.pack(fill=tk.X, padx=8, pady=(8, 0))
        else:
            bg = "#7f1d1d"
            sub_fg = "#fecaca"
            title = self.t("conn.banner_title_disconnected")
            header_text = self.t("conn.disconnected")
            header_fg = COLORS["danger"]
            detail = details or self.t("conn.detail_none")
            bar = self.t("conn.bar_disconnected")
            win_suffix = ""
            led_on = False
            self.connect_btn.configure(
                text=self.t("btn.connect"), bg=COLORS["accent"], activebackground=COLORS["accent_hover"],
                state=tk.NORMAL, command=self._toggle_connection,
            )
            self.scan_btn.configure(text=self.t("btn.scan"), state=tk.NORMAL, command=self._scan_for_module)
            self.control_lock_banner.pack(fill=tk.X, padx=8, pady=(8, 0))

        self.conn_banner.configure(bg=bg)
        self.conn_banner_text.configure(bg=bg)
        self.conn_banner_title.configure(text=title, bg=bg)
        self.conn_banner_sub.configure(text=detail if state != "disconnected" else self.t("conn.banner_sub_disconnected"), fg=sub_fg, bg=bg)
        self.conn_banner_led.configure(bg=bg)
        self.conn_banner_led.set_state(led_on, active_color=COLORS["success"] if state == "connected" else COLORS["warning"])
        self.conn_led.set_state(led_on, active_color=COLORS["success"] if state == "connected" else COLORS["warning"])
        self.conn_label.configure(text=header_text, fg=header_fg)
        self.conn_detail_label.configure(text=detail)
        self.status_bar_label.configure(
            text=bar,
            fg=COLORS["success"] if state == "connected" else (COLORS["warning"] if state == "connecting" else COLORS["text_muted"]),
        )
        self.title(self.t("app.window_title") + win_suffix)
        self._update_controls_enabled(state == "connected")

    def _update_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for ch in self.relay_channels:
            ch.btn_on.configure(state=state)
            ch.btn_off.configure(state=state)
        for btn in getattr(self, "_control_buttons", []):
            btn.configure(state=state)
        if hasattr(self, "execute_btn"):
            self.execute_btn.configure(state=state)

    def _should_cancel(self) -> bool:
        return self._cancel_requested

    def _cancel_pending_operation(self) -> None:
        if not self._user_op_active:
            return
        self._cancel_requested = True
        self._async_generation += 1
        self._user_op_active = False
        try:
            self.device.disconnect()
        except Exception:
            pass
        self._set_connection_status("disconnected", self.t("detail.cancelled"))
        self._log(self.t("log.cancelled", op=self._pending_operation or "..."))

    def _run_async(self, fn, on_ok=None, on_err=None, operation_name: str = "", warn_if_busy: bool = False) -> None:
        if self._user_op_active:
            if warn_if_busy:
                messagebox.showwarning(self.t("msg.busy_title"), self.t("msg.busy"))
            return
        self._user_op_active = True
        self._cancel_requested = False
        self._pending_operation = operation_name
        self._async_generation += 1
        generation = self._async_generation

        def worker():
            try:
                with self._modbus_lock:
                    if generation != self._async_generation or self._cancel_requested:
                        self.after(0, lambda: self._release_user_op(generation))
                        return
                    result = fn()
                if generation != self._async_generation or self._cancel_requested:
                    self.after(0, lambda: self._release_user_op(generation))
                    return
                self.after(0, lambda r=result: self._async_done(generation, None, r, on_ok, on_err))
            except OperationCancelledError:
                if generation == self._async_generation:
                    self.after(0, lambda: self._on_operation_cancelled(generation))
                else:
                    self.after(0, lambda: self._release_user_op(generation))
            except Exception as exc:
                if generation != self._async_generation or self._cancel_requested:
                    self.after(0, lambda: self._release_user_op(generation))
                    return
                self.after(0, lambda e=exc: self._async_done(generation, e, None, on_ok, on_err))

        threading.Thread(target=worker, daemon=True).start()

    def _release_user_op(self, generation: int) -> None:
        if generation == self._async_generation:
            self._user_op_active = False

    def _on_operation_cancelled(self, generation: int) -> None:
        if generation != self._async_generation:
            return
        self._user_op_active = False
        self._set_connection_status("disconnected", self.t("detail.cancelled"))

    def _async_done(self, generation: int, error, result, on_ok, on_err) -> None:
        if generation != self._async_generation:
            return
        self._user_op_active = False
        if error:
            if on_err:
                on_err(error)
            else:
                self._log(self.t("log.error", msg=error))
        elif on_ok:
            on_ok(result)

    def _toggle_connection(self) -> None:
        if self._user_op_active:
            self._cancel_pending_operation()
            return
        if self.device.is_connected:
            self.device.disconnect()
            self._set_connection_status("disconnected")
            self._log(self.t("log.disconnected"))
            return

        try:
            slave_id = int(self.slave_var.get().strip(), 16)
            if not (0 <= slave_id <= 255):
                raise ValueError
        except ValueError:
            messagebox.showerror(self.t("msg.error"), self.t("msg.error_slave"))
            return

        port = self.port_var.get()
        baud = int(self.baud_var.get())
        settings = SerialSettings(port=port, baudrate=baud)
        connecting_details = f"{port} @ {baud} baud, slave 0x{slave_id:02X}"
        self._set_connection_status("connecting", connecting_details)
        self._log(self.t("log.connecting", detail=connecting_details))

        def connect():
            self.device.settings = settings
            self.device.connect(slave_id=slave_id, should_cancel=self._should_cancel)

        def on_ok(_):
            ok_details = f"{port} @ {baud} baud, slave 0x{slave_id:02X}"
            self._set_connection_status("connected", ok_details)
            self._log(self.t("log.connected", detail=ok_details))
            self._apply_relay_states(self.device.relay_cache)
            self._read_inputs_only()

        def on_err(exc):
            self._set_connection_status("disconnected", self.t("detail.conn_failed"))
            self._log(self.t("log.conn_failed", msg=exc))
            messagebox.showerror(self.t("msg.conn_error_title"), self.t("msg.conn_error_hint", err=exc))

        self._run_async(connect, on_ok=on_ok, on_err=on_err, operation_name=self.t("op.connect"))

    def _scan_for_module(self) -> None:
        if self._user_op_active:
            self._cancel_pending_operation()
            return
        if self.device.is_connected:
            messagebox.showinfo(self.t("msg.scan_title"), self.t("msg.scan_disconnect"))
            return

        self._set_connection_status("connecting", self.t("detail.scanning"))
        self._log(self.t("log.scan_start"))

        def scan():
            return scan_for_device(should_cancel=self._should_cancel)

        def on_ok(result):
            if result is None:
                self._set_connection_status("disconnected", self.t("detail.not_found"))
                self._log(self.t("log.scan_not_found"))
                messagebox.showwarning(self.t("msg.not_found_title"), self.t("msg.not_found"))
                return
            self.port_var.set(result.port)
            self.baud_var.set(str(result.baudrate))
            self.slave_var.set(f"{result.slave_id:02X}")
            detail = f"{result.port} @ {result.baudrate}, slave 0x{result.slave_id:02X}"
            self._set_connection_status("disconnected", self.t("detail.found", detail=detail))
            self._log(self.t("log.scan_found", detail=detail))
            messagebox.showinfo(
                self.t("msg.found_title"),
                self.t("msg.found", port=result.port, baud=result.baudrate, slave=result.slave_id),
            )

        def on_err(exc):
            self._set_connection_status("disconnected", self.t("detail.scan_error"))
            self._log(self.t("log.scan_error", msg=exc))

        self._run_async(scan, on_ok=on_ok, on_err=on_err, operation_name=self.t("op.scan"))

    def _set_device_address(self) -> None:
        if not self.device.is_connected:
            messagebox.showwarning(self.t("msg.no_connection_title"), self.t("msg.no_connection"))
            return
        try:
            new_addr = int(self.new_addr_var.get(), 16)
        except ValueError:
            messagebox.showerror(self.t("msg.error"), self.t("msg.error_addr_hex"))
            return

        if not messagebox.askyesno(self.t("msg.confirm_title"), self.t("msg.confirm_addr", addr=new_addr)):
            return

        def action():
            self.device.set_device_address(new_addr)
            return new_addr

        def on_ok(addr):
            self.slave_var.set(f"{addr:02X}")
            self.device.disconnect()
            self._set_connection_status("disconnected", self.t("detail.addr_changed", addr=addr))
            self._log(self.t("log.addr_changed", addr=addr))
            messagebox.showinfo(self.t("msg.success_title"), self.t("msg.success_addr", addr=addr))

        def on_err(exc):
            self._log(self.t("log.error", msg=exc))
            messagebox.showerror(self.t("msg.error"), str(exc))

        self._run_async(
            action, on_ok=on_ok, on_err=on_err, operation_name=self.t("op.set_address"), warn_if_busy=True,
        )

    def _relay_toggle(self, channel: int, state: bool) -> None:
        if not self.device.is_connected:
            messagebox.showwarning(self.t("msg.no_connection_title"), self.t("msg.no_connection"))
            return

        def action():
            return self.device.write_coil_and_read_inputs(channel, state)

        def on_ok(inputs):
            self._apply_relay_states(self.device.relay_cache)
            self._apply_input_states(inputs)
            st = self.t("state.on") if state else self.t("state.off")
            self._log(self.t("log.relay", ch=channel + 1, state=st))
            active = [i + 1 for i, s in enumerate(inputs) if s]
            if active:
                self._log(self.t("log.inputs_after", inputs=inputs, active=active))
            else:
                self._log(self.t("log.inputs_after_none", inputs=inputs))

        self._run_async(action, on_ok=on_ok, operation_name=f"CH{channel + 1}")

    def _set_all_relays(self, state: bool) -> None:
        if not self.device.is_connected:
            messagebox.showwarning(self.t("msg.no_connection_title"), self.t("msg.no_connection"))
            return

        def action():
            return self.device.set_all_relays_and_read_inputs(state)

        def on_ok(inputs):
            self._apply_relay_states(self.device.relay_cache)
            self._apply_input_states(inputs)
            st = self.t("state.on") if state else self.t("state.off")
            self._log(self.t("log.all_relays", state=st, inputs=inputs))

        def on_err(exc):
            self._log(self.t("log.both_error", msg=exc))

        self._run_async(action, on_ok=on_ok, on_err=on_err, operation_name=self.t("op.all_relays"))

    def _apply_relay_states(self, states: list[bool]) -> None:
        for i, state in enumerate(states):
            if i < len(self.relay_channels):
                self.relay_channels[i].update_state(state)

    def _apply_input_states(self, inputs: list[bool]) -> None:
        for i, state in enumerate(inputs):
            if i < len(self.input_channels):
                self.input_channels[i].update_state(state)

    def _read_inputs_only(self) -> None:
        if not self.device.is_connected:
            messagebox.showwarning(self.t("msg.no_connection_title"), self.t("msg.no_connection"))
            return

        def action():
            return self.device.read_discrete_inputs()

        def on_ok(inputs):
            self._apply_input_states(inputs)
            active = [i + 1 for i, s in enumerate(inputs) if s]
            if active:
                self._log(self.t("log.inputs_ok_active", inputs=inputs, active=active))
            else:
                self._log(self.t("log.inputs_ok_none", inputs=inputs))

        def on_err(exc):
            self._log(self.t("log.inputs_error", msg=exc))

        self._run_async(action, on_ok=on_ok, on_err=on_err, operation_name=self.t("op.read_inputs"))

    def _fetch_status(self):
        coils = self.device.read_coils_safe()
        inputs = self.device.read_discrete_inputs_safe()
        th = self.device.read_th_sensor()
        return coils, inputs, th, self.device.relay_cache

    def _apply_status(self, data) -> None:
        coils, inputs, th, cache = data
        self._apply_relay_states(coils if coils is not None else cache)
        if inputs is not None:
            self._apply_input_states(inputs)
        elif coils is None:
            self._log(self.t("log.inputs_unavailable"))
        if th:
            self.th_temp_label.configure(text=f"{th.temperature_c:.1f} °C")
            self.th_hum_label.configure(text=f"{th.humidity_pct:.1f} %")
            self.th_status_label.configure(text=self.t("th.active"), fg=COLORS["success"])
        else:
            self.th_temp_label.configure(text="— °C")
            self.th_hum_label.configure(text="— %")
            self.th_status_label.configure(text=self.t("th.not_connected"), fg=COLORS["text_muted"])
        if coils is None:
            self._log(self.t("log.state_unavailable"))

    def _refresh_status(self) -> None:
        if not self.device.is_connected:
            return
        self._run_async(self._fetch_status, on_ok=self._apply_status, operation_name=self.t("op.refresh"))

    def _on_advanced_function_changed(self, _event=None) -> None:
        func_key = self._func_map.get(self.func_display_var.get(), "read_coils")
        presets = {
            "read_coils": ("8", ""),
            "read_discrete_inputs": ("8", ""),
            "read_holding_registers": ("1", ""),
            "read_input_registers": ("1", ""),
            "write_coil": ("1", "1"),
            "write_register": ("1", "1"),
            "write_coils": ("8", "1,1,1,1,1,1,1,1"),
            "write_registers": ("1", "1"),
        }
        count, vals = presets.get(func_key, ("8", ""))
        self.adv_count_var.set(count)
        self.adv_values_var.set(vals)

    def _execute_advanced(self) -> None:
        if not self.device.is_connected:
            messagebox.showwarning(self.t("msg.no_connection_title"), self.t("msg.no_connection"))
            return
        func_key = self._func_map.get(self.func_display_var.get(), "read_coils")

        try:
            address = int(self.adv_address_var.get())
            count = int(self.adv_count_var.get())
            if count < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror(self.t("msg.error"), self.t("msg.error_addr_int"))
            return

        raw_vals = self.adv_values_var.get().strip()
        values: list[int] = []
        if raw_vals:
            try:
                values = [int(x.strip()) for x in raw_vals.split(",")]
            except ValueError:
                messagebox.showerror(self.t("msg.error"), self.t("msg.error_values"))
                return

        write_funcs = {"write_coil", "write_register", "write_coils", "write_registers"}
        if func_key in write_funcs and not values:
            messagebox.showerror(self.t("msg.error"), self.t("msg.error_write_values"))
            return

        slave_raw = self.adv_slave_var.get().strip()
        try:
            slave_id = int(slave_raw, 16) if slave_raw else None
            if slave_id is not None and not (0 <= slave_id <= 255):
                raise ValueError
        except ValueError:
            messagebox.showerror(self.t("msg.error"), self.t("msg.error_slave_optional"))
            return

        sid_log = f"0x{slave_id:02X}" if slave_id is not None else f"0x{self.device.slave_id:02X}"
        self._log(self.t("log.console_req", func=func_key, addr=address, count=count, slave=sid_log, values=values))

        def action():
            return self.device.execute_raw(func_key, address, count, values, slave_id)

        def on_ok(response):
            result = Modbus303Device.format_raw_response(func_key, response, count)
            self.adv_result_var.set(result)
            self._log(self.t("log.console_ok", result=result))

        def on_err(exc):
            self.adv_result_var.set(self.t("result.error", msg=exc))
            self._log(self.t("log.console_err", msg=exc))

        self._run_async(
            action, on_ok=on_ok, on_err=on_err, operation_name=self.t("op.console"), warn_if_busy=True,
        )

    def _on_close(self) -> None:
        self.device.disconnect()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
303Modbus13 RTU Control — graficzna aplikacja sterująca modułem przekaźnikowym.
Ideaflex sp. z o.o.
"""

from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk

logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk

from modbus_device import (
    Modbus303Device,
    OperationCancelledError,
    RELAY_COUNT,
    INPUT_COUNT,
    SerialSettings,
    list_serial_ports,
    scan_for_device,
)

# ---------------------------------------------------------------------------
# Paleta kolorów
# ---------------------------------------------------------------------------
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
}


class StatusLed(tk.Canvas):
    """Okrągła lampka statusu."""

    def __init__(self, master, size: int = 18, **kwargs):
        super().__init__(master, width=size, height=size, highlightthickness=0, **kwargs)
        self.size = size
        self._oid = self.create_oval(2, 2, size - 2, size - 2, fill=COLORS["relay_off"], outline="#64748b")
        self.configure(bg=COLORS["panel"])

    def set_state(self, active: bool, active_color: str = COLORS["relay_on"]) -> None:
        self.itemconfig(self._oid, fill=active_color if active else COLORS["relay_off"])


class RelayChannel(tk.Frame):
    """Pojedynczy kanał przekaźnika z lampką i przyciskami ON/OFF."""

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
    """Wskaźnik wejścia opto."""

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
        self.title("303Modbus13 — Modbus RTU Control")
        self.geometry("960x720")
        self.minsize(860, 640)
        self.configure(bg=COLORS["bg"])

        self.device = Modbus303Device()
        self._poll_job: str | None = None
        self._poll_interval_ms = 1000
        self._busy = False
        self._async_generation = 0
        self._cancel_requested = False
        self._pending_operation = ""
        self._conn_details = ""

        self._build_styles()
        self._build_header()
        self._build_status_bar()
        self._build_notebook()
        self._refresh_ports()
        self._set_connection_status("disconnected")

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
        style.configure("TCombobox", fieldbackground=COLORS["panel_light"], foreground=COLORS["text"])

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=COLORS["panel"], height=64)
        header.pack(fill=tk.X, padx=0, pady=0)
        header.pack_propagate(False)

        tk.Label(
            header,
            text="303Modbus13",
            font=("Segoe UI", 18, "bold"),
            fg=COLORS["accent"],
            bg=COLORS["panel"],
        ).pack(side=tk.LEFT, padx=20, pady=12)

        tk.Label(
            header,
            text=f"Moduł przekaźnikowy 2× — sterowanie Modbus RTU",
            font=("Segoe UI", 11),
            fg=COLORS["text_muted"],
            bg=COLORS["panel"],
        ).pack(side=tk.LEFT, pady=14)

        status_frame = tk.Frame(header, bg=COLORS["panel"])
        status_frame.pack(side=tk.RIGHT, padx=20)

        self.conn_led = StatusLed(status_frame, size=22)
        self.conn_led.pack(side=tk.LEFT, padx=(0, 8))
        status_text = tk.Frame(status_frame, bg=COLORS["panel"])
        status_text.pack(side=tk.LEFT)
        self.conn_label = tk.Label(
            status_text, text="ROZŁĄCZONY", font=("Segoe UI", 12, "bold"),
            fg=COLORS["danger"], bg=COLORS["panel"],
        )
        self.conn_label.pack(anchor="e")
        self.conn_detail_label = tk.Label(
            status_text, text="brak połączenia z modułem", font=("Segoe UI", 9),
            fg=COLORS["text_muted"], bg=COLORS["panel"],
        )
        self.conn_detail_label.pack(anchor="e")

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

        self.notebook.add(self.tab_connection, text="  Połączenie  ")
        self.notebook.add(self.tab_control, text="  Sterowanie  ")
        self.notebook.add(self.tab_advanced, text="  Zaawansowane  ")
        self.notebook.add(self.tab_about, text="  O programie  ")

        self._build_connection_tab()
        self._build_control_tab()
        self._build_advanced_tab()
        self._build_about_tab()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _panel(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=COLORS["bg"])
        outer.pack(fill=tk.X, padx=8, pady=6)
        box = tk.LabelFrame(
            outer, text=f"  {title}  ", font=("Segoe UI", 10, "bold"),
            fg=COLORS["text"], bg=COLORS["panel"], labelanchor="nw",
            padx=12, pady=10,
        )
        box.pack(fill=tk.X)
        return box

    def _build_connection_tab(self) -> None:
        serial_panel = self._panel(self.tab_connection, "Port szeregowy (Modbus RTU)")

        grid = tk.Frame(serial_panel, bg=COLORS["panel"])
        grid.pack(fill=tk.X)

        labels = ["Port COM:", "Prędkość:", "Slave ID (hex):"]
        for i, text in enumerate(labels):
            tk.Label(grid, text=text, font=("Segoe UI", 10), fg=COLORS["text_muted"], bg=COLORS["panel"]).grid(
                row=i, column=0, sticky="w", pady=4, padx=(0, 12),
            )

        port_row = tk.Frame(grid, bg=COLORS["panel"])
        port_row.grid(row=0, column=1, sticky="w", pady=4)
        self.port_var = tk.StringVar(value="COM4")
        self.port_combo = ttk.Combobox(port_row, textvariable=self.port_var, width=12, state="readonly")
        self.port_combo.pack(side=tk.LEFT)
        tk.Button(
            port_row, text="↻", font=("Segoe UI", 9), width=3,
            bg=COLORS["panel_light"], fg=COLORS["text"], relief=tk.FLAT,
            command=self._refresh_ports,
        ).pack(side=tk.LEFT, padx=4)

        self.baud_var = tk.StringVar(value="9600")
        baud_combo = ttk.Combobox(
            grid, textvariable=self.baud_var, width=12, state="readonly",
            values=["4800", "9600", "19200"],
        )
        baud_combo.grid(row=1, column=1, sticky="w", pady=4)

        self.slave_var = tk.StringVar(value="FF")
        slave_entry = tk.Entry(
            grid, textvariable=self.slave_var, width=8, font=("Consolas", 11),
            bg=COLORS["panel_light"], fg=COLORS["text"], insertbackground=COLORS["text"],
            relief=tk.FLAT,
        )
        slave_entry.grid(row=2, column=1, sticky="w", pady=4)

        btn_row = tk.Frame(serial_panel, bg=COLORS["panel"])
        btn_row.pack(fill=tk.X, pady=(12, 0))

        self.connect_btn = tk.Button(
            btn_row, text="Połącz", font=("Segoe UI", 11, "bold"),
            bg=COLORS["accent"], fg="white", activebackground=COLORS["accent_hover"],
            relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
            command=self._toggle_connection,
        )
        self.connect_btn.pack(side=tk.LEFT)

        self.scan_btn = tk.Button(
            btn_row, text="Szukaj modułu", font=("Segoe UI", 10),
            bg=COLORS["panel_light"], fg=COLORS["text"], relief=tk.FLAT,
            padx=14, pady=8, cursor="hand2", command=self._scan_for_module,
        )
        self.scan_btn.pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(
            serial_panel,
            text="Wskazówka: adres fabryczny to FF (255). Po ustawieniu nowego adresu połącz się z tym adresem (np. 01).",
            font=("Segoe UI", 9), fg=COLORS["warning"], bg=COLORS["panel"], wraplength=700, justify=tk.LEFT,
        ).pack(anchor="w", pady=(10, 0))

        self.conn_banner = tk.Frame(serial_panel, bg="#7f1d1d", pady=10, padx=12)
        self.conn_banner.pack(fill=tk.X, pady=(14, 0))
        self.conn_banner_led = StatusLed(self.conn_banner, size=20)
        self.conn_banner_led.pack(side=tk.LEFT, padx=(0, 10))
        self.conn_banner_text = tk.Frame(self.conn_banner, bg=self.conn_banner["bg"])
        self.conn_banner_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.conn_banner_title = tk.Label(
            self.conn_banner_text, text="STATUS: ROZŁĄCZONY",
            font=("Segoe UI", 13, "bold"), fg="white", bg=self.conn_banner["bg"], anchor="w",
        )
        self.conn_banner_title.pack(fill=tk.X)
        self.conn_banner_sub = tk.Label(
            self.conn_banner_text, text="Kliknij „Połącz”, aby nawiązać komunikację z modułem.",
            font=("Segoe UI", 10), fg="#fecaca", bg=self.conn_banner["bg"], anchor="w",
        )
        self.conn_banner_sub.pack(fill=tk.X)

        addr_panel = self._panel(self.tab_connection, "Zmiana adresu Modbus (broadcast)")
        tk.Label(
            addr_panel,
            text="Zapis do rejestru 0 z slave=0 (broadcast). Po zmianie rozłącz i połącz z nowym adresem.",
            font=("Segoe UI", 9), fg=COLORS["text_muted"], bg=COLORS["panel"], wraplength=700, justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 8))

        addr_row = tk.Frame(addr_panel, bg=COLORS["panel"])
        addr_row.pack(anchor="w")
        tk.Label(addr_row, text="Nowy adres (hex):", font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["panel"]).pack(side=tk.LEFT)
        self.new_addr_var = tk.StringVar(value="01")
        tk.Entry(
            addr_row, textvariable=self.new_addr_var, width=6, font=("Consolas", 11),
            bg=COLORS["panel_light"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=8)
        tk.Button(
            addr_row, text="Zapisz nowy adres", font=("Segoe UI", 10),
            bg=COLORS["warning"], fg="#1e293b", activebackground="#d97706",
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2",
            command=self._set_device_address,
        ).pack(side=tk.LEFT)

        info_panel = self._panel(self.tab_connection, "Parametry komunikacji")
        for line in [
            "Protokół: Modbus RTU",
            "Format: 9600 baud, 8N1 (8 bitów, brak parzystości, 1 bit stopu)",
            "Adres fabryczny nowego modułu: 0xFF (255). Po konfiguracji może być np. 0x01",
            "Opcjonalny sensor T/H: Slave ID 0x02 (jeśli zamontowany)",
        ]:
            tk.Label(info_panel, text=f"• {line}", font=("Segoe UI", 9), fg=COLORS["text_muted"], bg=COLORS["panel"], anchor="w").pack(anchor="w", pady=1)

    def _build_control_tab(self) -> None:
        self.control_lock_banner = tk.Frame(self.tab_control, bg="#78350f", pady=8, padx=12)
        self.control_lock_banner.pack(fill=tk.X, padx=8, pady=(8, 0))
        tk.Label(
            self.control_lock_banner,
            text="⚠  STEROWANIE ZABLOKOWANE — najpierw połącz się z modułem (zakładka Połączenie)",
            font=("Segoe UI", 10, "bold"), fg="#fef3c7", bg="#78350f",
        ).pack(anchor="w")

        top = tk.Frame(self.tab_control, bg=COLORS["bg"])
        top.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(top, bg=COLORS["bg"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        relay_panel = self._panel(left, f"Przekaźniki (Coils 0–{RELAY_COUNT - 1})")
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
        for text, cmd, color in [
            ("Oba ON", lambda: self._set_all_relays(True), COLORS["success"]),
            ("Oba OFF", lambda: self._set_all_relays(False), COLORS["danger"]),
            ("Odśwież stan", self._refresh_status, COLORS["accent"]),
        ]:
            btn = tk.Button(
                bulk_row, text=text, font=("Segoe UI", 9, "bold"),
                bg=color, fg="white", relief=tk.FLAT, padx=12, pady=6, cursor="hand2",
                command=cmd,
            )
            btn.pack(side=tk.LEFT, padx=4)
            self._control_buttons.append(btn)

        input_panel = self._panel(left, f"Wejścia opto IN1–IN{INPUT_COUNT} (FC 0x02)")
        input_grid = tk.Frame(input_panel, bg=COLORS["panel"])
        input_grid.pack(fill=tk.X)
        self.input_channels: list[InputChannel] = []
        for i in range(INPUT_COUNT):
            ch = InputChannel(input_grid, i)
            ch.grid(row=0, column=i, sticky="w", padx=12, pady=4)
            self.input_channels.append(ch)
        self.read_inputs_btn = tk.Button(
            input_panel, text="Odczytaj wejścia", font=("Segoe UI", 9),
            bg=COLORS["accent"], fg="white", relief=tk.FLAT, padx=10, pady=4,
            cursor="hand2", command=self._read_inputs_only,
        )
        self.read_inputs_btn.pack(anchor="w", pady=(8, 0))
        self._control_buttons.append(self.read_inputs_btn)

        right = tk.Frame(top, bg=COLORS["bg"])
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=(6, 0))

        th_panel = self._panel(right, "Sensor T/H (opcjonalny)")
        self.th_temp_label = tk.Label(th_panel, text="— °C", font=("Segoe UI", 22, "bold"), fg=COLORS["accent"], bg=COLORS["panel"])
        self.th_temp_label.pack(pady=(4, 0))
        self.th_hum_label = tk.Label(th_panel, text="— %", font=("Segoe UI", 16), fg=COLORS["text_muted"], bg=COLORS["panel"])
        self.th_hum_label.pack()
        self.th_status_label = tk.Label(
            th_panel, text="Sensor niepodłączony", font=("Segoe UI", 8),
            fg=COLORS["text_muted"], bg=COLORS["panel"],
        )
        self.th_status_label.pack(pady=(4, 0))

        poll_panel = self._panel(right, "Auto-odświeżanie")
        self.auto_poll_var = tk.BooleanVar(value=False)
        self.auto_poll_check = tk.Checkbutton(
            poll_panel, text="Odświeżaj co 1 s", variable=self.auto_poll_var,
            font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["panel"],
            selectcolor=COLORS["panel_light"], activebackground=COLORS["panel"],
            command=self._toggle_auto_poll,
        )
        self.auto_poll_check.pack(anchor="w")

        log_panel = self._panel(self.tab_control, "Log komunikacji")
        self.log_text = scrolledtext.ScrolledText(
            log_panel, height=8, font=("Consolas", 9),
            bg="#0c1222", fg="#a5f3fc", insertbackground=COLORS["text"],
            relief=tk.FLAT, state=tk.DISABLED,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _build_advanced_tab(self) -> None:
        panel = self._panel(self.tab_advanced, "Konsola Modbus — dowolna komenda")
        tk.Label(
            panel,
            text=(
                "Wybierz funkcję Modbus, podaj adres, liczbę elementów i wartości (rozdzielone przecinkami). "
                "Odczyt coils/wejść: count=8. Zapis wielu cewek (0x0F): wartości 1,1,1,1,1,1,1,1 lub jedna wartość 1/0."
            ),
            font=("Segoe UI", 9), fg=COLORS["text_muted"], bg=COLORS["panel"], wraplength=800, justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 10))

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
        tk.Label(form, text="Funkcja:", font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["panel"]).grid(row=0, column=0, sticky="w", pady=4)
        func_combo = ttk.Combobox(
            form, textvariable=self.func_display_var, width=36, state="readonly",
            values=[f[0] for f in self._functions],
        )
        func_combo.grid(row=0, column=1, sticky="w", pady=4, padx=8)
        func_combo.bind("<<ComboboxSelected>>", self._on_advanced_function_changed)

        self.adv_address_var = tk.StringVar(value="0")
        self.adv_count_var = tk.StringVar(value="8")
        self.adv_values_var = tk.StringVar(value="")
        self.adv_slave_var = tk.StringVar(value="")

        for row, (label, var) in enumerate([
            ("Adres:", self.adv_address_var),
            ("Liczba:", self.adv_count_var),
            ("Wartości:", self.adv_values_var),
            ("Slave (hex, puste=aktualny):", self.adv_slave_var),
        ], start=1):
            tk.Label(form, text=label, font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["panel"]).grid(row=row, column=0, sticky="w", pady=4)
            tk.Entry(
                form, textvariable=var, width=40, font=("Consolas", 10),
                bg=COLORS["panel_light"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT,
            ).grid(row=row, column=1, sticky="w", pady=4, padx=8)

        self.execute_btn = tk.Button(
            panel, text="Wykonaj", font=("Segoe UI", 11, "bold"),
            bg=COLORS["accent"], fg="white", relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
            command=self._execute_advanced,
        )
        self.execute_btn.pack(anchor="w", pady=(12, 0))

        self.adv_result_var = tk.StringVar(value="")
        tk.Label(panel, text="Wynik:", font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w", pady=(12, 4))
        tk.Entry(
            panel, textvariable=self.adv_result_var, font=("Consolas", 10),
            bg=COLORS["panel_light"], fg=COLORS["success"], state="readonly", relief=tk.FLAT,
        ).pack(fill=tk.X)

    def _build_about_tab(self) -> None:
        panel = self._panel(self.tab_about, "O aplikacji")
        about_text = """
303Modbus13 RTU Control v1.0

Aplikacja do sterowania i diagnostyki modułu przekaźnikowego
Ideaflex 303Modbus13 przez interfejs szeregowy Modbus RTU.

Funkcje:
  • Sterowanie 2 przekaźnikami (coils 0–1)
  • Odczyt 2 wejść opto (discrete inputs 0–1)
  • Odczyt opcjonalnego sensora temperatury i wilgotności
  • Zmiana adresu Modbus slave
  • Konsola zaawansowana — wszystkie funkcje Modbus FC 01–06, 0F, 10

Dokumentacja rejestrów: docs/REGISTERS.md

© Ideaflex sp. z o.o.
        """.strip()
        tk.Label(
            panel, text=about_text, font=("Segoe UI", 10), fg=COLORS["text"],
            bg=COLORS["panel"], justify=tk.LEFT, anchor="nw",
        ).pack(anchor="w")

        doc_panel = self._panel(self.tab_about, "Szybki start")
        steps = [
            "1. Podłącz moduł do portu COM (np. przez konwerter USB-RS485).",
            "2. Wybierz port COM i kliknij „Połącz”.",
            "3. Na zakładce Sterowanie włączaj/wyłączaj przekaźniki.",
            "4. Włącz auto-odświeżanie, aby na bieżąco widzieć stany.",
            "5. Pełna mapa rejestrów Modbus — w pliku docs/REGISTERS.md.",
        ]
        for step in steps:
            tk.Label(doc_panel, text=step, font=("Segoe UI", 10), fg=COLORS["text_muted"], bg=COLORS["panel"], anchor="w").pack(anchor="w", pady=2)

    # ------------------------------------------------------------------
    # Logika
    # ------------------------------------------------------------------
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
        """state: disconnected | connecting | connected"""
        self._conn_details = details

        if state == "connected":
            bg = "#14532d"
            sub_fg = "#bbf7d0"
            title = "STATUS: POŁĄCZONY"
            header_text = "POŁĄCZONY"
            header_fg = COLORS["success"]
            detail = details or "komunikacja Modbus aktywna"
            bar = f"● POŁĄCZONY — {detail}"
            win_suffix = " [POŁĄCZONY]"
            led_on = True
            self.connect_btn.configure(
                text="Rozłącz", bg=COLORS["danger"], activebackground="#dc2626",
                state=tk.NORMAL, command=self._toggle_connection,
            )
            self.scan_btn.configure(text="Szukaj modułu", state=tk.NORMAL, command=self._scan_for_module)
            self.control_lock_banner.pack_forget()
        elif state == "connecting":
            bg = "#713f12"
            sub_fg = "#fef08a"
            title = "STATUS: ŁĄCZENIE..."
            header_text = "ŁĄCZENIE..."
            header_fg = COLORS["warning"]
            detail = details or "nawiązywanie komunikacji Modbus RTU"
            bar = f"◌ ŁĄCZENIE — {detail}  |  kliknij ANULUJ aby przerwać"
            win_suffix = " [łączenie...]"
            led_on = True
            self.connect_btn.configure(
                text="Anuluj", bg=COLORS["danger"], activebackground="#dc2626",
                state=tk.NORMAL, command=self._cancel_pending_operation,
            )
            self.scan_btn.configure(
                text="Anuluj", state=tk.NORMAL, command=self._cancel_pending_operation,
            )
            self.control_lock_banner.pack(fill=tk.X, padx=8, pady=(8, 0))
        else:
            bg = "#7f1d1d"
            sub_fg = "#fecaca"
            title = "STATUS: ROZŁĄCZONY"
            header_text = "ROZŁĄCZONY"
            header_fg = COLORS["danger"]
            detail = details or "brak połączenia z modułem"
            bar = "○ ROZŁĄCZONY — wybierz port COM i kliknij „Połącz”"
            win_suffix = ""
            led_on = False
            self.connect_btn.configure(
                text="Połącz", bg=COLORS["accent"], activebackground=COLORS["accent_hover"],
                state=tk.NORMAL, command=self._toggle_connection,
            )
            self.scan_btn.configure(text="Szukaj modułu", state=tk.NORMAL, command=self._scan_for_module)
            self.control_lock_banner.pack(fill=tk.X, padx=8, pady=(8, 0))

        self.conn_banner.configure(bg=bg)
        self.conn_banner_text.configure(bg=bg)
        self.conn_banner_title.configure(text=title, bg=bg)
        self.conn_banner_sub.configure(text=detail, fg=sub_fg, bg=bg)
        self.conn_banner_led.configure(bg=bg)
        self.conn_banner_led.set_state(led_on, active_color=COLORS["success"] if state == "connected" else COLORS["warning"])

        self.conn_led.set_state(led_on, active_color=COLORS["success"] if state == "connected" else COLORS["warning"])
        self.conn_label.configure(text=header_text, fg=header_fg)
        self.conn_detail_label.configure(text=detail)
        self.status_bar_label.configure(
            text=bar,
            fg=COLORS["success"] if state == "connected" else (COLORS["warning"] if state == "connecting" else COLORS["text_muted"]),
        )
        self.title(f"303Modbus13 — Modbus RTU Control{win_suffix}")

        self._update_controls_enabled(state == "connected")

    def _update_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for ch in self.relay_channels:
            ch.btn_on.configure(state=state)
            ch.btn_off.configure(state=state)
        for btn in getattr(self, "_control_buttons", []):
            btn.configure(state=state)
        if hasattr(self, "auto_poll_check"):
            self.auto_poll_check.configure(state=state)
        if hasattr(self, "execute_btn"):
            self.execute_btn.configure(state=state)

    def _should_cancel(self) -> bool:
        return self._cancel_requested

    def _cancel_pending_operation(self) -> None:
        if not self._busy:
            return
        self._cancel_requested = True
        self._async_generation += 1
        self._busy = False
        try:
            self.device.disconnect()
        except Exception:
            pass
        self._set_connection_status("disconnected", "anulowano przez użytkownika")
        self._log(f"Anulowano: {self._pending_operation or 'operacja'}.")

    def _run_async(self, fn, on_ok=None, on_err=None, operation_name: str = "") -> None:
        if self._busy:
            return
        self._busy = True
        self._cancel_requested = False
        self._pending_operation = operation_name
        self._async_generation += 1
        generation = self._async_generation

        def worker():
            try:
                result = fn()
                if generation != self._async_generation or self._cancel_requested:
                    return
                self.after(0, lambda r=result: self._async_done(generation, None, r, on_ok, on_err))
            except OperationCancelledError:
                if generation == self._async_generation:
                    self.after(0, lambda: self._on_operation_cancelled(generation))
            except Exception as exc:
                if generation != self._async_generation or self._cancel_requested:
                    return
                self.after(0, lambda e=exc: self._async_done(generation, e, None, on_ok, on_err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_operation_cancelled(self, generation: int) -> None:
        if generation != self._async_generation:
            return
        self._busy = False
        self._set_connection_status("disconnected", "anulowano przez użytkownika")

    def _async_done(self, generation: int, error, result, on_ok, on_err) -> None:
        if generation != self._async_generation:
            return
        self._busy = False
        if error:
            if on_err:
                on_err(error)
            else:
                self._log(f"BŁĄD: {error}")
        elif on_ok:
            on_ok(result)

    def _toggle_connection(self) -> None:
        if self._busy:
            self._cancel_pending_operation()
            return
        if self.device.is_connected:
            self._stop_auto_poll()
            self.auto_poll_var.set(False)
            self.device.disconnect()
            self._set_connection_status("disconnected")
            self._log("Rozłączono.")
            return

        try:
            slave_id = int(self.slave_var.get().strip(), 16)
            if not (0 <= slave_id <= 255):
                raise ValueError
        except ValueError:
            messagebox.showerror("Błąd", "Slave ID musi być liczbą hex 00–FF (np. FF lub 01).")
            return

        port = self.port_var.get()
        baud = int(self.baud_var.get())
        settings = SerialSettings(port=port, baudrate=baud)
        connecting_details = f"{port} @ {baud} baud, slave 0x{slave_id:02X}"
        self._set_connection_status("connecting", connecting_details)
        self._log(f"Łączenie: {connecting_details}...")

        def connect():
            self.device.settings = settings
            self.device.connect(slave_id=slave_id, should_cancel=self._should_cancel)

        def on_ok(_):
            ok_details = f"{port} @ {baud} baud, slave 0x{slave_id:02X}"
            self._set_connection_status("connected", ok_details)
            self._log(f"Połączono: {ok_details}")
            self._apply_relay_states(self.device.relay_cache)
            self._read_inputs_only()

        def on_err(exc):
            self._set_connection_status("disconnected", "połączenie nieudane")
            self._log(f"BŁĄD połączenia: {exc}")
            hint = (
                f"{exc}\n\n"
                "Spróbuj:\n"
                "• Slave ID = FF (adres fabryczny 255)\n"
                "• Przycisk „Szukaj modułu”\n"
                "• Inny port COM w Menedżerze urządzeń\n"
                "• Zamknij inne programy używające portu szeregowego"
            )
            messagebox.showerror("Błąd połączenia", hint)

        self._run_async(connect, on_ok=on_ok, on_err=on_err, operation_name="łączenie")

    def _scan_for_module(self) -> None:
        if self._busy:
            self._cancel_pending_operation()
            return
        if self.device.is_connected:
            messagebox.showinfo("Skan", "Najpierw rozłącz, aby przeskanować porty.")
            return

        self._set_connection_status("connecting", "skanowanie portów COM i adresów slave...")
        self._log("Skanowanie: szukam modułu na portach COM...")

        def scan():
            return scan_for_device(should_cancel=self._should_cancel)

        def on_ok(result):
            if result is None:
                self._set_connection_status("disconnected", "moduł nie znaleziony")
                self._log("Skan zakończony — moduł nie odpowiedział.")
                messagebox.showwarning(
                    "Nie znaleziono",
                    "Moduł nie odpowiedział na żadnym porcie COM.\n\n"
                    "Sprawdź:\n"
                    "• Kabel USB-RS485 i zasilanie modułu\n"
                    "• Czy port COM się nie zmienił (Menedżer urządzeń)\n"
                    "• Okablowanie A/B na RS-485",
                )
                return
            self.port_var.set(result.port)
            self.baud_var.set(str(result.baudrate))
            self.slave_var.set(f"{result.slave_id:02X}")
            detail = f"znaleziono: {result.port} @ {result.baudrate}, slave 0x{result.slave_id:02X}"
            self._set_connection_status("disconnected", detail)
            self._log(f"Znaleziono moduł: {detail}")
            messagebox.showinfo(
                "Znaleziono moduł",
                f"Port: {result.port}\nBaud: {result.baudrate}\nSlave ID: 0x{result.slave_id:02X}\n\n"
                "Parametry ustawione — kliknij „Połącz”.",
            )

        def on_err(exc):
            self._set_connection_status("disconnected", "błąd skanowania")
            self._log(f"Błąd skanu: {exc}")

        self._run_async(scan, on_ok=on_ok, on_err=on_err, operation_name="skanowanie")

    def _set_device_address(self) -> None:
        if not self.device.is_connected:
            messagebox.showwarning("Brak połączenia", "Najpierw połącz z modułem.")
            return
        try:
            new_addr = int(self.new_addr_var.get(), 16)
        except ValueError:
            messagebox.showerror("Błąd", "Adres musi być liczbą hex.")
            return

        if not messagebox.askyesno("Potwierdzenie", f"Ustawić nowy adres Modbus na 0x{new_addr:02X}?"):
            return

        def action():
            self.device.set_device_address(new_addr)
            return new_addr

        def on_ok(addr):
            self.slave_var.set(f"{addr:02X}")
            self.device.disconnect()
            self._set_connection_status("disconnected", f"adres zmieniony na 0x{addr:02X} — połącz ponownie")
            self._log(f"Zmieniono adres na 0x{addr:02X}. Połącz ponownie z nowym adresem.")
            messagebox.showinfo("Sukces", f"Adres ustawiony na 0x{addr:02X}. Połącz ponownie.")

        self._run_async(action, on_ok=on_ok)

    def _relay_toggle(self, channel: int, state: bool) -> None:
        if not self.device.is_connected:
            messagebox.showwarning("Brak połączenia", "Najpierw połącz z modułem.")
            return

        def action():
            return self.device.write_coil_and_read_inputs(channel, state)

        def on_ok(inputs):
            self._apply_relay_states(self.device.relay_cache)
            self._apply_input_states(inputs)
            self._log(f"CH{channel + 1} -> {'ON' if state else 'OFF'}")
            active = [i + 1 for i, s in enumerate(inputs) if s]
            if active:
                self._log(f"  wejścia po zapisie: {inputs} (aktywne IN{active})")
            else:
                self._log(f"  wejścia po zapisie: {inputs}")

        self._run_async(action, on_ok=on_ok, operation_name=f"CH{channel + 1}")

    def _set_all_relays(self, state: bool) -> None:
        if not self.device.is_connected:
            messagebox.showwarning("Brak połączenia", "Najpierw połącz z modułem.")
            return

        def action():
            return self.device.set_all_relays_and_read_inputs(state)

        def on_ok(inputs):
            self._apply_relay_states(self.device.relay_cache)
            self._apply_input_states(inputs)
            self._log(f"Wszystkie przekaźniki -> {'ON' if state else 'OFF'}, wejścia: {inputs}")

        def on_err(exc):
            self._log(f"Błąd Oba ON/OFF: {exc}")

        self._run_async(action, on_ok=on_ok, on_err=on_err, operation_name="wszystkie przekaźniki")

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
            messagebox.showwarning("Brak połączenia", "Najpierw połącz z modułem.")
            return

        def action():
            return self.device.read_discrete_inputs()

        def on_ok(inputs):
            self._apply_input_states(inputs)
            active = [i + 1 for i, s in enumerate(inputs) if s]
            if active:
                self._log(f"Odczyt wejść OK (FC 0x02): {inputs} — aktywne: IN{active}")
            else:
                self._log(
                    f"Odczyt wejść OK (FC 0x02): {inputs} — brak sygnału na wejściach "
                    f"(sprawdź okablowanie +20V na zaciski IN/COM modułu)"
                )

        def on_err(exc):
            self._log(f"Błąd odczytu wejść: {exc}")

        self._run_async(action, on_ok=on_ok, on_err=on_err, operation_name="odczyt wejść")

    def _refresh_status(self) -> None:
        if not self.device.is_connected:
            return

        def action():
            coils = self.device.read_coils_safe()
            inputs = self.device.read_discrete_inputs_safe()
            th = self.device.read_th_sensor()
            return coils, inputs, th, self.device.relay_cache

        def on_ok(data):
            coils, inputs, th, cache = data
            self._apply_relay_states(coils if coils is not None else cache)
            if inputs is not None:
                self._apply_input_states(inputs)
            elif coils is None:
                self._log("Odczyt wejść niedostępny — użyj „Odczytaj wejścia”.")
            if th:
                self.th_temp_label.configure(text=f"{th.temperature_c:.1f} °C")
                self.th_hum_label.configure(text=f"{th.humidity_pct:.1f} %")
                self.th_status_label.configure(text="Sensor aktywny", fg=COLORS["success"])
            else:
                self.th_temp_label.configure(text="— °C")
                self.th_hum_label.configure(text="— %")
                self.th_status_label.configure(text="Sensor niepodłączony", fg=COLORS["text_muted"])
            if coils is None:
                self._log("Odczyt stanu niedostępny — wyświetlam ostatni znany (zapis działa).")

        self._run_async(action, on_ok=on_ok, operation_name="odświeżanie")

    def _toggle_auto_poll(self) -> None:
        if self.auto_poll_var.get():
            self._start_auto_poll()
        else:
            self._stop_auto_poll()

    def _start_auto_poll(self) -> None:
        self._stop_auto_poll()
        self._poll_tick()

    def _stop_auto_poll(self) -> None:
        if self._poll_job:
            self.after_cancel(self._poll_job)
            self._poll_job = None

    def _poll_tick(self) -> None:
        if self.auto_poll_var.get() and self.device.is_connected:
            self._refresh_status()
        if self.auto_poll_var.get():
            self._poll_job = self.after(self._poll_interval_ms, self._poll_tick)

    def _on_advanced_function_changed(self, _event=None) -> None:
        """Ustawia sensowne domyślne count/wartości pod wybraną funkcję Modbus."""
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
            messagebox.showwarning("Brak połączenia", "Najpierw połącz z modułem.")
            return
        if self._busy:
            messagebox.showwarning(
                "Operacja w toku",
                "Poczekaj na zakończenie bieżącej operacji lub kliknij „Anuluj”.",
            )
            return

        func_key = self._func_map.get(self.func_display_var.get(), "read_coils")

        try:
            address = int(self.adv_address_var.get())
            count = int(self.adv_count_var.get())
            if count < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Błąd", "Adres i liczba muszą być dodatnimi liczbami całkowitymi.")
            return

        raw_vals = self.adv_values_var.get().strip()
        values: list[int] = []
        if raw_vals:
            try:
                values = [int(x.strip()) for x in raw_vals.split(",")]
            except ValueError:
                messagebox.showerror("Błąd", "Wartości muszą być liczbami rozdzielonymi przecinkami.")
                return

        write_funcs = {"write_coil", "write_register", "write_coils", "write_registers"}
        if func_key in write_funcs and not values:
            messagebox.showerror(
                "Błąd",
                "Przy zapisie podaj wartości w polu „Wartości” (np. 1 dla ON, 0 dla OFF).",
            )
            return

        slave_raw = self.adv_slave_var.get().strip()
        try:
            slave_id = int(slave_raw, 16) if slave_raw else None
            if slave_id is not None and not (0 <= slave_id <= 255):
                raise ValueError
        except ValueError:
            messagebox.showerror("Błąd", "Slave ID musi być liczbą hex 00–FF lub puste.")
            return

        sid_log = f"0x{slave_id:02X}" if slave_id is not None else f"0x{self.device.slave_id:02X}"
        self._log(f"Konsola => {func_key}, addr={address}, count={count}, slave={sid_log}, values={values}")

        def action():
            return self.device.execute_raw(func_key, address, count, values, slave_id)

        def on_ok(response):
            result = Modbus303Device.format_raw_response(func_key, response, count)
            self.adv_result_var.set(result)
            self._log(f"Konsola <= {result}")

        def on_err(exc):
            self.adv_result_var.set(f"Błąd: {exc}")
            self._log(f"Konsola BŁĄD: {exc}")

        self._run_async(action, on_ok=on_ok, on_err=on_err, operation_name="konsola Modbus")

    def _on_close(self) -> None:
        self._stop_auto_poll()
        self.device.disconnect()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

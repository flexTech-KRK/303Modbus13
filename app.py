#!/usr/bin/env python3
"""
303Modbus13 RTU Control — graficzna aplikacja sterująca modułem przekaźnikowym.
Ideaflex sp. z o.o.
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk

from modbus_device import Modbus303Device, SerialSettings, list_serial_ports

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

        self._build_styles()
        self._build_header()
        self._build_notebook()
        self._refresh_ports()

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
            text="Moduł przekaźnikowy 8× — sterowanie Modbus RTU",
            font=("Segoe UI", 11),
            fg=COLORS["text_muted"],
            bg=COLORS["panel"],
        ).pack(side=tk.LEFT, pady=14)

        status_frame = tk.Frame(header, bg=COLORS["panel"])
        status_frame.pack(side=tk.RIGHT, padx=20)

        self.conn_led = StatusLed(status_frame, size=14)
        self.conn_led.pack(side=tk.LEFT, padx=(0, 6))
        self.conn_label = tk.Label(
            status_frame, text="Rozłączony", font=("Segoe UI", 10),
            fg=COLORS["text_muted"], bg=COLORS["panel"],
        )
        self.conn_label.pack(side=tk.LEFT)

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

        self.slave_var = tk.StringVar(value="01")
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
            "Domyślny Slave ID modułu przekaźników: 0x01",
            "Opcjonalny sensor T/H: Slave ID 0x02 (jeśli zamontowany)",
        ]:
            tk.Label(info_panel, text=f"• {line}", font=("Segoe UI", 9), fg=COLORS["text_muted"], bg=COLORS["panel"], anchor="w").pack(anchor="w", pady=1)

    def _build_control_tab(self) -> None:
        top = tk.Frame(self.tab_control, bg=COLORS["bg"])
        top.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(top, bg=COLORS["bg"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        relay_panel = self._panel(left, "Przekaźniki (Coils 0–7)")
        relay_grid = tk.Frame(relay_panel, bg=COLORS["panel"])
        relay_grid.pack(fill=tk.X)

        self.relay_channels: list[RelayChannel] = []
        for i in range(8):
            ch = RelayChannel(relay_grid, i, self._relay_toggle)
            ch.grid(row=i // 2, column=i % 2, sticky="w", padx=8, pady=3)
            self.relay_channels.append(ch)

        bulk_row = tk.Frame(relay_panel, bg=COLORS["panel"])
        bulk_row.pack(fill=tk.X, pady=(12, 0))
        for text, cmd, color in [
            ("Wszystkie ON", lambda: self._set_all_relays(True), COLORS["success"]),
            ("Wszystkie OFF", lambda: self._set_all_relays(False), COLORS["danger"]),
            ("Odśwież stan", self._refresh_status, COLORS["accent"]),
        ]:
            tk.Button(
                bulk_row, text=text, font=("Segoe UI", 9, "bold"),
                bg=color, fg="white", relief=tk.FLAT, padx=12, pady=6, cursor="hand2",
                command=cmd,
            ).pack(side=tk.LEFT, padx=4)

        input_panel = self._panel(left, "Wejścia opto (Discrete Inputs 0–7)")
        input_grid = tk.Frame(input_panel, bg=COLORS["panel"])
        input_grid.pack(fill=tk.X)
        self.input_channels: list[InputChannel] = []
        for i in range(8):
            ch = InputChannel(input_grid, i)
            ch.grid(row=i // 4, column=i % 4, sticky="w", padx=6, pady=2)
            self.input_channels.append(ch)

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
        tk.Checkbutton(
            poll_panel, text="Odświeżaj co 1 s", variable=self.auto_poll_var,
            font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["panel"],
            selectcolor=COLORS["panel_light"], activebackground=COLORS["panel"],
            command=self._toggle_auto_poll,
        ).pack(anchor="w")

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
            text="Wybierz funkcję Modbus, podaj adres, liczbę elementów i ewentualne wartości (rozdzielone przecinkami).",
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

        tk.Button(
            panel, text="Wykonaj", font=("Segoe UI", 11, "bold"),
            bg=COLORS["accent"], fg="white", relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
            command=self._execute_advanced,
        ).pack(anchor="w", pady=(12, 0))

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
  • Sterowanie 8 przekaźnikami (coils 0–7)
  • Odczyt 8 wejść opto (discrete inputs 0–7)
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

    def _set_connected_ui(self, connected: bool) -> None:
        if connected:
            self.conn_led.set_state(True)
            self.conn_label.configure(text="Połączony", fg=COLORS["success"])
            self.connect_btn.configure(text="Rozłącz", bg=COLORS["danger"], activebackground="#dc2626")
        else:
            self.conn_led.set_state(False)
            self.conn_label.configure(text="Rozłączony", fg=COLORS["text_muted"])
            self.connect_btn.configure(text="Połącz", bg=COLORS["accent"], activebackground=COLORS["accent_hover"])

    def _run_async(self, fn, on_ok=None, on_err=None) -> None:
        if self._busy:
            return
        self._busy = True

        def worker():
            try:
                result = fn()
                self.after(0, lambda: self._async_done(None, result, on_ok, on_err))
            except Exception as exc:
                self.after(0, lambda: self._async_done(exc, None, on_ok, on_err))

        threading.Thread(target=worker, daemon=True).start()

    def _async_done(self, error, result, on_ok, on_err) -> None:
        self._busy = False
        if error:
            if on_err:
                on_err(error)
            else:
                self._log(f"BŁĄD: {error}")
        elif on_ok:
            on_ok(result)

    def _toggle_connection(self) -> None:
        if self.device.is_connected:
            self._stop_auto_poll()
            self.device.disconnect()
            self._set_connected_ui(False)
            self._log("Rozłączono.")
            return

        try:
            slave_id = int(self.slave_var.get(), 16)
        except ValueError:
            messagebox.showerror("Błąd", "Slave ID musi być liczbą hex (np. 01).")
            return

        port = self.port_var.get()
        baud = int(self.baud_var.get())
        settings = SerialSettings(port=port, baudrate=baud)

        def connect():
            self.device.settings = settings
            self.device.connect(slave_id=slave_id)

        def on_ok(_):
            self._set_connected_ui(True)
            self._log(f"Połączono: {port} @ {baud} baud, slave=0x{slave_id:02X}")
            self._refresh_status()

        def on_err(exc):
            messagebox.showerror("Błąd połączenia", str(exc))

        self._run_async(connect, on_ok=on_ok, on_err=on_err)

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
            self._set_connected_ui(False)
            self._log(f"Zmieniono adres na 0x{addr:02X}. Połącz ponownie z nowym adresem.")
            messagebox.showinfo("Sukces", f"Adres ustawiony na 0x{addr:02X}. Połącz ponownie.")

        self._run_async(action, on_ok=on_ok)

    def _relay_toggle(self, channel: int, state: bool) -> None:
        if not self.device.is_connected:
            messagebox.showwarning("Brak połączenia", "Najpierw połącz z modułem.")
            return

        def action():
            self.device.write_coil(channel, state)

        def on_ok(_):
            self.relay_channels[channel].update_state(state)
            self._log(f"CH{channel + 1} -> {'ON' if state else 'OFF'}")

        self._run_async(action, on_ok=on_ok)

    def _set_all_relays(self, state: bool) -> None:
        if not self.device.is_connected:
            messagebox.showwarning("Brak połączenia", "Najpierw połącz z modułem.")
            return

        def action():
            self.device.set_all_relays(state)

        def on_ok(_):
            for ch in self.relay_channels:
                ch.update_state(state)
            self._log(f"Wszystkie przekaźniki -> {'ON' if state else 'OFF'}")

        self._run_async(action, on_ok=on_ok)

    def _refresh_status(self) -> None:
        if not self.device.is_connected:
            return

        def action():
            coils = self.device.read_coils()
            inputs = self.device.read_discrete_inputs()
            th = self.device.read_th_sensor()
            return coils, inputs, th

        def on_ok(data):
            coils, inputs, th = data
            for i, state in enumerate(coils):
                self.relay_channels[i].update_state(state)
            for i, state in enumerate(inputs):
                self.input_channels[i].update_state(state)
            if th:
                self.th_temp_label.configure(text=f"{th.temperature_c:.1f} °C")
                self.th_hum_label.configure(text=f"{th.humidity_pct:.1f} %")
                self.th_status_label.configure(text="Sensor aktywny", fg=COLORS["success"])
            else:
                self.th_temp_label.configure(text="— °C")
                self.th_hum_label.configure(text="— %")
                self.th_status_label.configure(text="Sensor niepodłączony", fg=COLORS["text_muted"])

        self._run_async(action, on_ok=on_ok)

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

    def _execute_advanced(self) -> None:
        if not self.device.is_connected:
            messagebox.showwarning("Brak połączenia", "Najpierw połącz z modułem.")
            return

        func_key = self._func_map.get(self.func_display_var.get(), "read_coils")

        try:
            address = int(self.adv_address_var.get())
            count = int(self.adv_count_var.get())
        except ValueError:
            messagebox.showerror("Błąd", "Adres i liczba muszą być liczbami całkowitymi.")
            return

        raw_vals = self.adv_values_var.get().strip()
        values = []
        if raw_vals:
            try:
                values = [int(x.strip()) for x in raw_vals.split(",")]
            except ValueError:
                messagebox.showerror("Błąd", "Wartości muszą być liczbami rozdzielonymi przecinkami.")
                return

        slave_raw = self.adv_slave_var.get().strip()
        slave_id = int(slave_raw, 16) if slave_raw else None

        def action():
            return self.device.execute_raw(func_key, address, count, values, slave_id)

        def on_ok(response):
            if hasattr(response, "bits"):
                result = str(list(response.bits))
            elif hasattr(response, "registers"):
                result = str(list(response.registers))
            elif response is None or (hasattr(response, "isError") and response.isError()):
                result = f"Błąd: {response}"
            else:
                result = "OK"
            self.adv_result_var.set(result)
            self._log(f"Advanced [{func_key}] addr={address} -> {result}")

        self._run_async(action, on_ok=on_ok)

    def _on_close(self) -> None:
        self._stop_auto_poll()
        self.device.disconnect()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

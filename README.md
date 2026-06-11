# 303Modbus13 RTU Control

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Modbus RTU](https://img.shields.io/badge/Modbus-RTU-green.svg)](docs/REGISTERS.md)
[![GitHub](https://img.shields.io/badge/GitHub-flexTech--KRK%2F303Modbus13-blue.svg)](https://github.com/flexTech-KRK/303Modbus13)
[![License](https://img.shields.io/badge/License-Proprietary-orange.svg)]()

Desktop GUI application for controlling and diagnosing the **Ideaflex 303Modbus13** relay module over **Modbus RTU** (serial/COM).

**Git repository:** [github.com/flexTech-KRK/303Modbus13](https://github.com/flexTech-KRK/303Modbus13)

> Designed for customers and integrators — quick module bring-up without a TCP/IP gateway.

---

## Features

| Feature | Description |
|---------|-------------|
| **2 relays** | CH1–CH2 ON/OFF, bulk Both ON / Both OFF |
| **2 opto inputs** | Live status of IN1–IN2 (FC 0x02) |
| **T/H sensor** | Temperature and humidity readout (if installed) |
| **Manual refresh** | Full status read (relays, inputs, optional T/H sensor) on demand |
| **Address change** | Slave ID configuration via Modbus broadcast |
| **Modbus console** | Full access to FC 01–06, 0F, 10 |
| **Polish / English UI** | Language selector in the header; choice saved in `settings.json` |
| **Documentation** | [User guide](docs/USER_GUIDE.md) · [Register map](docs/REGISTERS.md) |

---

## Requirements

- Windows 10/11 (or Linux with a serial port)
- Python 3.10 or newer
- USB ↔ RS-485 converter (or built-in COM port)
- 303Modbus13 module on the RS-485 bus

---

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/flexTech-KRK/303Modbus13.git
cd 303Modbus13
```

Online sources: [README.md](https://github.com/flexTech-KRK/303Modbus13/blob/main/README.md) · [REGISTERS.md](https://github.com/flexTech-KRK/303Modbus13/blob/main/docs/REGISTERS.md)

### 2. Virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the application

```bash
python app.py
```

### 5. Connect to the module

1. Connect the module to a COM port (e.g. `COM4` via USB-RS485).
2. Select the COM port and click **Connect**.
3. Default Slave ID: `FF` (255, factory address).
4. Open the **Control** tab and test the relays.

**Full UI walkthrough with screenshots:** **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**

---

## Communication parameters

| Parameter | Value |
|-----------|-------|
| Protocol | Modbus RTU |
| Baud rate | 9600 |
| Format | 8N1 |
| Slave ID (relays) | `0xFF` (255) factory default, then e.g. `0x01` |
| Slave ID (T/H sensor) | `0x02` |
| **Timeout** | **3.0 s** (serial port / pymodbus) |
| **Retries** | **3** |
| Post-write coil delay | 0.35 s |

At 9600 baud with a USB-RS485 converter, **do not use a 0.5–1.0 s timeout** — the module responds correctly but needs more time. Details, frames, and troubleshooting: **[docs/REGISTERS.md](docs/REGISTERS.md)**.

### Opto inputs (IN / COM)

Inputs are **opto-isolated**. Both connections are required:

- **COM** → GND (0 V) of the signal source
- **INx** → signal voltage (+12…24 V DC relative to COM)

Input **COM** is **not** the same as the board power GND — it is a separate isolated circuit. Voltage on a relay contact alone, without wiring **INx** and **COM** on the module, will not produce `True` in Modbus (FC 0x02).

---

## Command-line example (pymodbus)

Control relay CH1:

```python
from pymodbus.client import ModbusSerialClient

client = ModbusSerialClient(
    port="COM4", baudrate=9600, parity="N", stopbits=1, bytesize=8,
    timeout=3.0, retries=3,
)
client.connect()

# Turn CH1 ON (new module: slave=255 / 0xFF)
client.write_coil(address=0, value=True, slave=255)

# Read opto inputs (count=8 in frame; result: IN1, IN2, …)
inputs = client.read_discrete_inputs(address=0, count=8, slave=255)
print(inputs.bits[:2])

client.close()
```

---

## Project structure

| Path | Description |
|------|-------------|
| `app.py` | Tkinter GUI — application entry point |
| `i18n.py` | UI translations (Polish / English) |
| `locales/pl.json`, `locales/en.json` | Translation strings |
| `modbus_device.py` | Modbus RTU communication layer |
| `requirements.txt` | Python dependencies |
| `README.md` | This file |
| `scripts/generate_pdfs.py` | Build PDF documentation |
| `docs/USER_GUIDE.md` | User guide with screenshots |
| `docs/REGISTERS.md` | Full Modbus register map |
| `docs/images/` | Application screenshots |
| `docs/*.pdf` | PDF exports (README, USER_GUIDE, REGISTERS) |

### Generate PDFs

```bash
pip install markdown xhtml2pdf
python scripts/generate_pdfs.py
```

Output: `docs/README.pdf`, `docs/USER_GUIDE.pdf`, and `docs/REGISTERS.pdf`.

---

## First-time module setup

A new module ships with Slave ID **`0xFF` (255)**. To set address `0x01`:

1. Connect with Slave ID `FF`.
2. On the **Connection** tab, enter new address `01` and click **Save new address**.
3. Disconnect and reconnect with Slave ID `01`.

Alternatively — via the advanced console:
```
Function: Write Multiple Registers (0x10)
Address: 0
Values: 1
Slave: 0
```

---

## Modbus TCP/RTU gateway

The module can also be used through a network gateway (e.g. USR-M0) with Modbus TCP. The register map is identical — only the transport layer changes (IP instead of COM).

TCP/RTU application version: local repo `ModBus_Relay_303Modbus13` (RTU/COM version: [303Modbus13 on GitHub](https://github.com/flexTech-KRK/303Modbus13)).

---

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| Cannot open COM port | Check Device Manager → COM ports; close other apps using the port |
| No response from device | Check RS-485 (A/B), Slave ID (`FF` or `01`), timeout **3 s** |
| Opto inputs always off | Wire **COM → GND** and **INx → +signal** (isolated circuit — see REGISTERS.md) |
| T/H sensor shows not connected | Sensor is optional — relay module works without it |
| Address change error | Use Slave=0 (broadcast) |

---

## License

© **Ideaflex sp. z o.o.** — software provided to customers with the 303Modbus13 module.

---

## Contact

If you have any problems or questions, contact **FlexTech_KRK** on [Allegro](https://allegro.pl) or email **[biuro@ideaflex.pl](mailto:biuro@ideaflex.pl)**.

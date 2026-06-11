#!/usr/bin/env python3
"""Test delay/flash relay registers (chinalctech-style map)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pymodbus.client import ModbusSerialClient

PORT = "COM4"
BAUD = 9600
SLAVE = 1

# Relay n (1-based) -> holding register start address (manufacturer map)
RELAY_REG = {1: 0x0003, 2: 0x0008, 3: 0x000D, 4: 0x0012}

MODE_FLASH_OFF = 0x0004  # ON then auto OFF after delay
MODE_FLASH_ON = 0x0002   # OFF then auto ON after delay


def main() -> None:
    client = ModbusSerialClient(
        port=PORT, baudrate=BAUD, parity="N", stopbits=1, bytesize=8,
        timeout=3.0, retries=2,
    )
    if not client.connect():
        print(f"Cannot open {PORT} — close other apps using the port.")
        raise SystemExit(1)

    def coils():
        rr = client.read_coils(address=0, count=8, slave=SLAVE)
        return list(rr.bits[:8]) if rr and not rr.isError() else None

    def inputs():
        rr = client.read_discrete_inputs(address=0, count=8, slave=SLAVE)
        return list(rr.bits[:8]) if rr and not rr.isError() else None

    def read_holding(addr: int, count: int = 5):
        rr = client.read_holding_registers(address=addr, count=count, slave=SLAVE)
        if rr and not rr.isError():
            return list(rr.registers)
        return None

    print(f"=== Baseline slave={SLAVE} ===")
    print("Coils:", coils())
    print("Inputs:", inputs())
    print()

    print("=== Known holding blocks ===")
    for name, addr in [("addr/device", 0), ("relay1 block", 3), ("relay2 block", 8), ("relay3 block", 13)]:
        vals = read_holding(addr, 5)
        print(f"  {name} @ {addr} (0x{addr:04X}): {vals}")

    print("\n=== Test: CH1 flash-OFF 3.0s (reg 3, mode=4, time=30) ===")
    print("Relay should turn ON, then auto OFF after ~3s. Watch IN1 if wired to NO1.")
    rr = client.write_registers(address=RELAY_REG[1], values=[MODE_FLASH_OFF, 30], slave=SLAVE)
    print("Write response:", "OK" if rr and not rr.isError() else rr)
    for i in range(8):
        time.sleep(0.5)
        c, inp = coils(), inputs()
        print(f"  t={i*0.5:.1f}s coils={c[:2]} inputs={inp[:2] if inp else None}")

    print("\n=== Read relay1 block after test ===")
    print(read_holding(3, 5))

    client.close()
    print("Done.")


if __name__ == "__main__":
    main()

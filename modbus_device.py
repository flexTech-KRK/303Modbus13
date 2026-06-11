"""
Modbus RTU driver for Ideaflex 303Modbus13 relay module.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Optional

import serial
from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusIOException
from pymodbus.pdu.register_message import WriteMultipleRegistersResponse
from serial import SerialException


def _patch_write_multiple_registers_decode() -> None:
    """Work around non-standard 0x10 responses from the module firmware."""

    def custom_decode(self, data: bytes) -> None:
        if len(data) >= 4:
            self.address, self.count = struct.unpack(">HH", data[:4])
        else:
            raise Exception("Odebrano zbyt mało bajtów w odpowiedzi WriteMultipleRegistersResponse!")

    WriteMultipleRegistersResponse.decode = custom_decode  # type: ignore[method-assign]


_patch_write_multiple_registers_decode()


@dataclass
class SerialSettings:
    port: str = "COM4"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout: float = 1.0


@dataclass
class THReading:
    temperature_c: float
    humidity_pct: float


class Modbus303Device:
    RELAY_SLAVE_ID = 1
    SENSOR_SLAVE_ID = 2
    RELAY_COUNT = 8
    INPUT_COUNT = 8

    def __init__(self, settings: Optional[SerialSettings] = None) -> None:
        self.settings = settings or SerialSettings()
        self.client: Optional[ModbusSerialClient] = None
        self.slave_id = self.RELAY_SLAVE_ID

    @property
    def is_connected(self) -> bool:
        return self.client is not None

    def connect(self, slave_id: int = 1) -> None:
        self.disconnect()
        self.slave_id = slave_id
        port = self.settings.port
        baud = self.settings.baudrate

        try:
            probe = serial.Serial(
                port=port,
                baudrate=baud,
                parity=self.settings.parity,
                stopbits=self.settings.stopbits,
                bytesize=self.settings.bytesize,
                timeout=self.settings.timeout,
            )
            probe.close()
        except SerialException as exc:
            raise ConnectionError(f"Nie można otworzyć portu {port}: {exc}") from exc

        self.client = ModbusSerialClient(
            port=port,
            baudrate=baud,
            parity=self.settings.parity,
            stopbits=self.settings.stopbits,
            bytesize=self.settings.bytesize,
            timeout=self.settings.timeout,
            retries=1,
        )
        if not self.client.connect():
            self.client = None
            raise ConnectionError(f"Nie można otworzyć połączenia Modbus RTU na {port}.")

        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                rr = self.client.read_coils(address=0, count=1, slave=self.slave_id)
                if rr is not None and not rr.isError():
                    return
                last_error = ModbusIOException(f"Brak odpowiedzi od urządzenia (slave ID={self.slave_id}).")
            except ModbusIOException as exc:
                last_error = exc
            time.sleep(0.15 * (attempt + 1))

        self.client.close()
        self.client = None
        raise last_error or ModbusIOException(f"Brak odpowiedzi od urządzenia (slave ID={self.slave_id}).")

    def disconnect(self) -> None:
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None

    def _require_client(self) -> ModbusSerialClient:
        if not self.client:
            raise ConnectionError("Brak aktywnego połączenia Modbus.")
        return self.client

    def read_coils(self, address: int = 0, count: int = RELAY_COUNT) -> list[bool]:
        client = self._require_client()
        rr = client.read_coils(address=address, count=count, slave=self.slave_id)
        if rr is None or rr.isError():
            raise ModbusIOException("Błąd odczytu cewek (coils).")
        return list(rr.bits[:count])

    def read_discrete_inputs(self, address: int = 0, count: int = INPUT_COUNT) -> list[bool]:
        client = self._require_client()
        rr = client.read_discrete_inputs(address=address, count=count, slave=self.slave_id)
        if rr is None or rr.isError():
            raise ModbusIOException("Błąd odczytu wejść opto.")
        return list(rr.bits[:count])

    def write_coil(self, address: int, value: bool) -> None:
        client = self._require_client()
        rr = client.write_coil(address=address, value=value, slave=self.slave_id)
        if rr is None or rr.isError():
            raise ModbusIOException(f"Błąd zapisu cewki {address}.")

    def write_coils(self, address: int, values: list[bool]) -> None:
        client = self._require_client()
        rr = client.write_coils(address=address, values=values, slave=self.slave_id)
        if rr is None or rr.isError():
            raise ModbusIOException("Błąd zapisu wielu cewek.")

    def set_all_relays(self, state: bool) -> None:
        self.write_coils(0, [state] * self.RELAY_COUNT)

    def read_holding_registers(self, address: int, count: int = 1) -> list[int]:
        client = self._require_client()
        rr = client.read_holding_registers(address=address, count=count, slave=self.slave_id)
        if rr is None or rr.isError():
            raise ModbusIOException("Błąd odczytu rejestrów holding.")
        return list(rr.registers)

    def read_input_registers(self, address: int, count: int = 1, slave_id: Optional[int] = None) -> list[int]:
        client = self._require_client()
        sid = self.slave_id if slave_id is None else slave_id
        rr = client.read_input_registers(address=address, count=count, slave=sid)
        if rr is None or rr.isError():
            raise ModbusIOException("Błąd odczytu rejestrów input.")
        return list(rr.registers)

    def write_register(self, address: int, value: int) -> None:
        client = self._require_client()
        rr = client.write_register(address=address, value=value, slave=self.slave_id)
        if rr is None or rr.isError():
            raise ModbusIOException(f"Błąd zapisu rejestru {address}.")

    def write_registers(self, address: int, values: list[int], slave_id: Optional[int] = None) -> None:
        client = self._require_client()
        sid = self.slave_id if slave_id is None else slave_id
        rr = client.write_registers(address=address, values=values, slave=sid)
        if rr is None or rr.isError():
            raise ModbusIOException("Błąd zapisu wielu rejestrów.")

    def set_device_address(self, new_address: int) -> None:
        if not (0x01 <= new_address <= 0xFF):
            raise ValueError("Adres slave musi być w zakresie 0x01–0xFF.")
        self.write_registers(address=0, values=[new_address], slave_id=0)
        self.slave_id = new_address

    def read_th_sensor(self) -> Optional[THReading]:
        try:
            temp_raw = self.read_input_registers(1, count=1, slave_id=self.SENSOR_SLAVE_ID)[0]
            hum_raw = self.read_input_registers(2, count=1, slave_id=self.SENSOR_SLAVE_ID)[0]
        except ModbusIOException:
            return None
        return THReading(temperature_c=temp_raw / 10.0, humidity_pct=hum_raw / 10.0)

    def execute_raw(
        self,
        function: str,
        address: int,
        count: int,
        values: list[int],
        slave_id: Optional[int] = None,
    ):
        sid = self.slave_id if slave_id is None else slave_id
        client = self._require_client()

        if function == "read_coils":
            return client.read_coils(address=address, count=count, slave=sid)
        if function == "read_discrete_inputs":
            return client.read_discrete_inputs(address=address, count=count, slave=sid)
        if function == "read_holding_registers":
            return client.read_holding_registers(address=address, count=count, slave=sid)
        if function == "read_input_registers":
            return client.read_input_registers(address=address, count=count, slave=sid)
        if function == "write_coil":
            return client.write_coil(address=address, value=bool(values[0]), slave=sid)
        if function == "write_register":
            return client.write_register(address=address, value=values[0], slave=sid)
        if function == "write_coils":
            return client.write_coils(address=address, values=[bool(v) for v in values], slave=sid)
        if function == "write_registers":
            return client.write_registers(address=address, values=values, slave=sid)
        raise ValueError(f"Nieznana funkcja Modbus: {function}")


def list_serial_ports() -> list[str]:
    import serial.tools.list_ports

    return [p.device for p in serial.tools.list_ports.comports()]

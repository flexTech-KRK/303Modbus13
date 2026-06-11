"""
Modbus RTU driver for Ideaflex 303Modbus13 relay module.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable, Optional

import serial
from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusIOException
from pymodbus.pdu.register_message import WriteMultipleRegistersResponse
from serial import SerialException


class OperationCancelledError(Exception):
    """Operacja przerwana przez użytkownika."""


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
    timeout: float = 3.0  # jak apka_4 (ModbusTcpClient timeout=3)


# Po zapisie cewki — krótka pauza przed odczytem (jak sekwencja w apka_4.py).
POST_WRITE_DELAY_S = 0.35
# apka_4.py: read_discrete_inputs(address=0, count=8, slave=1)
INPUT_READ_COUNT = 8
# apka_4.py: write_coils(address=0, values=[state]*8, slave=1) — ALL ON/OFF
COIL_WRITE_COUNT = 8


@dataclass
class THReading:
    temperature_c: float
    humidity_pct: float


class Modbus303Device:
    FACTORY_SLAVE_ID = 255   # 0xFF — adres fabryczny nowego modułu
    RELAY_SLAVE_ID = 255
    SENSOR_SLAVE_ID = 2
    RELAY_COUNT = 2
    INPUT_COUNT = 2

    def __init__(self, settings: Optional[SerialSettings] = None) -> None:
        self.settings = settings or SerialSettings()
        self.client: Optional[ModbusSerialClient] = None
        self.slave_id = self.RELAY_SLAVE_ID
        self._relay_cache: list[bool] = [False] * self.RELAY_COUNT

    @property
    def is_connected(self) -> bool:
        return self.client is not None

    def connect(
        self,
        slave_id: int = 1,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> None:
        def _check_cancel() -> None:
            if should_cancel and should_cancel():
                self.disconnect()
                raise OperationCancelledError("Łączenie anulowane.")

        self.disconnect()
        self.slave_id = slave_id
        port = self.settings.port
        baud = self.settings.baudrate

        _check_cancel()

        # Ten sam sposób co w działającym teście z command line (pymodbus bezpośrednio).
        self.client = ModbusSerialClient(
            port=port,
            baudrate=baud,
            parity=self.settings.parity,
            stopbits=self.settings.stopbits,
            bytesize=self.settings.bytesize,
            timeout=self.settings.timeout,
            retries=3,
        )
        try:
            if not self.client.connect():
                raise ConnectionError(f"Nie można otworzyć połączenia Modbus RTU na {port}.")
        except SerialException as exc:
            self.client = None
            raise ConnectionError(f"Nie można otworzyć portu {port}: {exc}") from exc

        last_error: Optional[Exception] = None
        for attempt in range(3):
            _check_cancel()
            if self._ping_module():
                return
            last_error = ModbusIOException(
                f"Brak odpowiedzi od urządzenia (slave ID={self.slave_id} / 0x{self.slave_id:02X})."
            )
            _check_cancel()
            time.sleep(0.2 * (attempt + 1))

        self.client.close()
        self.client = None
        raise last_error or ModbusIOException(
            f"Brak odpowiedzi od urządzenia (slave ID={self.slave_id} / 0x{self.slave_id:02X})."
        )

    def _ping_module(self) -> bool:
        """Sprawdza komunikację — jak apka_4: odczyt coils lub discrete inputs."""
        for method in ("coils", "inputs", "write"):
            try:
                if method == "coils":
                    rr = self.client.read_coils(address=0, count=8, slave=self.slave_id)
                elif method == "inputs":
                    rr = self.client.read_discrete_inputs(
                        address=0, count=INPUT_READ_COUNT, slave=self.slave_id
                    )
                else:
                    rr = self.client.write_coil(address=0, value=False, slave=self.slave_id)
                if rr is not None and not rr.isError():
                    return True
            except ModbusIOException:
                pass
        return False

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

    def read_coils(self, address: int = 0, count: int = 8) -> list[bool]:
        client = self._require_client()
        last_err: Optional[Exception] = None
        for _ in range(3):
            try:
                rr = client.read_coils(address=address, count=count, slave=self.slave_id)
                if rr is not None and not rr.isError():
                    return list(rr.bits[:count])
            except ModbusIOException as exc:
                last_err = exc
            time.sleep(0.15)
        raise last_err or ModbusIOException("Błąd odczytu cewek (coils).")

    def read_coils_safe(self, address: int = 0, count: int = RELAY_COUNT) -> Optional[list[bool]]:
        try:
            states = self.read_coils(address=address, count=count)
            for i, state in enumerate(states):
                if i < len(self._relay_cache):
                    self._relay_cache[i] = state
            return states
        except ModbusIOException:
            return None

    @property
    def relay_cache(self) -> list[bool]:
        return list(self._relay_cache)

    def read_discrete_inputs(self, address: int = 0, count: int = INPUT_READ_COUNT) -> list[bool]:
        """FC 0x02 — identycznie jak apka_4.py (count=8), zwraca IN1..IN{INPUT_COUNT}."""
        client = self._require_client()
        last_err: Optional[Exception] = None
        for _ in range(3):
            try:
                rr = client.read_discrete_inputs(address=address, count=count, slave=self.slave_id)
                if rr is not None and not rr.isError():
                    return list(rr.bits[: self.INPUT_COUNT])
            except ModbusIOException as exc:
                last_err = exc
            time.sleep(0.2)
        raise last_err or ModbusIOException("Błąd odczytu wejść opto (FC 0x02).")

    def read_discrete_inputs_safe(self, address: int = 0, count: int = INPUT_READ_COUNT) -> Optional[list[bool]]:
        try:
            return self.read_discrete_inputs(address=address, count=count)
        except ModbusIOException:
            return None

    def write_coil(self, address: int, value: bool) -> None:
        client = self._require_client()
        rr = client.write_coil(address=address, value=value, slave=self.slave_id)
        if rr is None or rr.isError():
            raise ModbusIOException(f"Błąd zapisu cewki {address}.")
        if address < len(self._relay_cache):
            self._relay_cache[address] = value
        time.sleep(POST_WRITE_DELAY_S)

    def write_coil_and_read_inputs(self, address: int, value: bool) -> list[bool]:
        """Jak apka_4.py: zapis cewki, potem odczyt wejść w tej samej sesji."""
        self.write_coil(address, value)
        return self.read_discrete_inputs()

    def write_coils(self, address: int, values: list[bool]) -> None:
        client = self._require_client()
        rr = client.write_coils(address=address, values=values, slave=self.slave_id)
        if rr is None or rr.isError():
            raise ModbusIOException("Błąd zapisu wielu cewek.")
        for i, state in enumerate(values):
            idx = address + i
            if idx < len(self._relay_cache):
                self._relay_cache[idx] = state
        time.sleep(POST_WRITE_DELAY_S)

    def set_all_relays(self, state: bool) -> None:
        """FC 0x0F — firmware wymaga 8 cewek w ramce (jak apka_4.py ALL ON/OFF)."""
        self.write_coils(0, [state] * COIL_WRITE_COUNT)

    def set_all_relays_and_read_inputs(self, state: bool) -> list[bool]:
        self.set_all_relays(state)
        return self.read_discrete_inputs()

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

    def write_registers(
        self,
        address: int,
        values: list[int],
        slave_id: Optional[int] = None,
        *,
        no_response_expected: Optional[bool] = None,
    ) -> None:
        client = self._require_client()
        sid = self.slave_id if slave_id is None else slave_id
        if no_response_expected is None:
            no_response_expected = sid == 0
        rr = client.write_registers(
            address=address,
            values=values,
            slave=sid,
            no_response_expected=no_response_expected,
        )
        if no_response_expected:
            time.sleep(POST_WRITE_DELAY_S)
            return
        if rr is None or rr.isError():
            raise ModbusIOException("Błąd zapisu wielu rejestrów.")

    def set_device_address(self, new_address: int) -> None:
        if not (0x01 <= new_address <= 0xFF):
            raise ValueError("Adres slave musi być w zakresie 0x01–0xFF.")
        self.write_registers(address=0, values=[new_address], slave_id=0, no_response_expected=True)
        self.slave_id = new_address

    def read_th_sensor(self) -> Optional[THReading]:
        try:
            temp_raw = self.read_input_registers(1, count=1, slave_id=self.SENSOR_SLAVE_ID)[0]
            hum_raw = self.read_input_registers(2, count=1, slave_id=self.SENSOR_SLAVE_ID)[0]
        except ModbusIOException:
            return None
        return THReading(temperature_c=temp_raw / 10.0, humidity_pct=hum_raw / 10.0)

    @staticmethod
    def _check_modbus_response(response) -> object:
        if response is None:
            raise ModbusIOException("Brak odpowiedzi od urządzenia.")
        if hasattr(response, "isError") and response.isError():
            raise ModbusIOException(f"Błąd Modbus: {response}")
        return response

    @staticmethod
    def _resolve_coil_write_values(count: int, values: list[int]) -> list[bool]:
        if not values:
            raise ValueError(
                "Podaj wartości 0/1 rozdzielone przecinkami (np. 1,1,1,1,1,1,1,1 dla Oba ON)."
            )
        bools = [bool(v) for v in values]
        if len(bools) == 1:
            bools = bools * count
        elif len(bools) < count:
            bools = bools + [bools[-1]] * (count - len(bools))
        else:
            bools = bools[:count]
        return bools

    @staticmethod
    def format_raw_response(function: str, response, count: int) -> str:
        if function in ("read_coils", "read_discrete_inputs") and hasattr(response, "bits"):
            return str(list(response.bits[:count]))
        if function == "write_coil" and hasattr(response, "bits"):
            val = response.bits[0] if response.bits else "?"
            return f"OK — cewka {response.address} = {'ON' if val else 'OFF'}"
        if function == "write_coils":
            addr = getattr(response, "address", "?")
            cnt = getattr(response, "count", "?")
            return f"OK — zapisano {cnt} cewek od adresu {addr}"
        if function in ("read_holding_registers", "read_input_registers") and hasattr(response, "registers"):
            return str(list(response.registers[:count]))
        if function in ("write_register", "write_registers"):
            addr = getattr(response, "address", "?")
            cnt = getattr(response, "count", getattr(response, "registers", []))
            if isinstance(cnt, list):
                cnt = len(cnt)
            return f"OK — rejestry od {addr}, count={cnt}"
        return "OK"

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
            return self._check_modbus_response(
                client.read_coils(address=address, count=count, slave=sid)
            )
        if function == "read_discrete_inputs":
            return self._check_modbus_response(
                client.read_discrete_inputs(address=address, count=count, slave=sid)
            )
        if function == "read_holding_registers":
            return self._check_modbus_response(
                client.read_holding_registers(address=address, count=count, slave=sid)
            )
        if function == "read_input_registers":
            return self._check_modbus_response(
                client.read_input_registers(address=address, count=count, slave=sid)
            )
        if function == "write_coil":
            if not values:
                raise ValueError("Wymagana jedna wartość 0 lub 1 przy zapisie cewki.")
            return self._check_modbus_response(
                client.write_coil(address=address, value=bool(values[0]), slave=sid)
            )
        if function == "write_register":
            if not values:
                raise ValueError("Wymagana jedna wartość przy zapisie rejestru.")
            return self._check_modbus_response(
                client.write_register(address=address, value=values[0], slave=sid)
            )
        if function == "write_coils":
            coil_count = max(count, COIL_WRITE_COUNT) if count <= self.RELAY_COUNT else count
            coil_values = self._resolve_coil_write_values(coil_count, values)
            return self._check_modbus_response(
                client.write_coils(address=address, values=coil_values, slave=sid)
            )
        if function == "write_registers":
            if not values:
                raise ValueError("Podaj wartości rejestrów rozdzielone przecinkami.")
            no_rsp = sid == 0
            rr = client.write_registers(
                address=address, values=values, slave=sid, no_response_expected=no_rsp,
            )
            if no_rsp:
                time.sleep(POST_WRITE_DELAY_S)
                return SimpleNamespace(address=address, count=len(values))
            return self._check_modbus_response(rr)
        raise ValueError(f"Nieznana funkcja Modbus: {function}")


RELAY_COUNT = Modbus303Device.RELAY_COUNT
INPUT_COUNT = Modbus303Device.INPUT_COUNT


@dataclass
class ScanResult:
    port: str
    baudrate: int
    slave_id: int


def scan_for_device(
    ports: Optional[list[str]] = None,
    baudrates: Optional[list[int]] = None,
    slave_ids: Optional[list[int]] = None,
    timeout: float = 0.4,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Optional[ScanResult]:
    """Szuka modułu na dostępnych portach COM."""
    import serial.tools.list_ports

    if ports is None:
        ports = [p.device for p in serial.tools.list_ports.comports()]
    if baudrates is None:
        baudrates = [9600, 4800, 19200]
    if slave_ids is None:
        # 255 (0xFF) = adres fabryczny wg dokumentacji producenta
        slave_ids = [255, 1, 0, 2, 3, 4, 5]

    for port in ports:
        if should_cancel and should_cancel():
            raise OperationCancelledError("Skanowanie anulowane.")
        try:
            probe = serial.Serial(port=port, baudrate=9600, timeout=0.3)
            probe.close()
        except SerialException:
            continue

        for baud in baudrates:
            if should_cancel and should_cancel():
                raise OperationCancelledError("Skanowanie anulowane.")
            client = ModbusSerialClient(
                port=port,
                baudrate=baud,
                parity="N",
                stopbits=1,
                bytesize=8,
                timeout=timeout,
                retries=1,
            )
            try:
                if not client.connect():
                    continue
                for slave in slave_ids:
                    if should_cancel and should_cancel():
                        raise OperationCancelledError("Skanowanie anulowane.")
                    try:
                        rr = client.read_coils(address=0, count=1, slave=slave)
                        if rr is not None and not rr.isError():
                            return ScanResult(port=port, baudrate=baud, slave_id=slave)
                    except ModbusIOException:
                        pass
                    time.sleep(0.05)
            finally:
                try:
                    client.close()
                except Exception:
                    pass
    return None


def list_serial_ports() -> list[str]:
    import serial.tools.list_ports

    return [p.device for p in serial.tools.list_ports.comports()]

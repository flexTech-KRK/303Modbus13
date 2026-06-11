# 303Modbus13 RTU Control

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Modbus RTU](https://img.shields.io/badge/Modbus-RTU-green.svg)](docs/REGISTERS.md)
[![License](https://img.shields.io/badge/License-Proprietary-orange.svg)]()

Graficzna aplikacja desktopowa do sterowania i diagnostyki modułu przekaźnikowego **Ideaflex 303Modbus13** przez interfejs szeregowy **Modbus RTU**.

> Aplikacja przeznaczona dla klientów i integratorów — umożliwia szybkie uruchomienie modułu bez mostka TCP/IP.

---

## Funkcje

| Funkcja | Opis |
|---------|------|
| **8 przekaźników** | Włączanie/wyłączanie CH1–CH8, zbiorczo ON/OFF |
| **8 wejść opto** | Podgląd stanu IN1–IN8 w czasie rzeczywistym |
| **Sensor T/H** | Odczyt temperatury i wilgotności (jeśli zamontowany) |
| **Auto-odświeżanie** | Cykliczny odczyt stanów co 1 s |
| **Zmiana adresu** | Konfiguracja Slave ID przez broadcast Modbus |
| **Konsola Modbus** | Pełny dostęp do funkcji FC 01–06, 0F, 10 |
| **Dokumentacja** | Kompletna mapa rejestrów w [`docs/REGISTERS.md`](docs/REGISTERS.md) |

---

## Wymagania

- Windows 10/11 (lub Linux z portem szeregowym)
- Python 3.10 lub nowszy
- Konwerter USB ↔ RS-485 (lub wbudowany port COM)
- Moduł 303Modbus13 podłączony do magistrali RS-485

---

## Szybki start

### 1. Klonowanie repozytorium

```bash
git clone <url-repozytorium>
cd 303Modbus13_RTU_Control
```

### 2. Środowisko wirtualne

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate
```

### 3. Instalacja zależności

```bash
pip install -r requirements.txt
```

### 4. Uruchomienie

```bash
python app.py
```

### 5. Połączenie z modułem

1. Podłącz moduł do portu COM (np. `COM4` przez konwerter USB-RS485).
2. W aplikacji wybierz port COM i kliknij **Połącz**.
3. Domyślny Slave ID: `01` (hex).
4. Przejdź do zakładki **Sterowanie** i testuj przekaźniki.

---

## Parametry komunikacji

| Parametr | Wartość |
|----------|---------|
| Protokół | Modbus RTU |
| Baud rate | 9600 |
| Format | 8N1 |
| Slave ID (przekaźniki) | `0x01` |
| Slave ID (sensor T/H) | `0x02` |

Szczegółowa mapa rejestrów: **[docs/REGISTERS.md](docs/REGISTERS.md)**

---

## Przykłady użycia z linii poleceń (pymodbus)

Sterowanie przekaźnikiem CH1 (wymaga pymodbus):

```python
from pymodbus.client import ModbusSerialClient

client = ModbusSerialClient(port="COM4", baudrate=9600, parity="N", stopbits=1, bytesize=8, timeout=1)
client.connect()

# Włącz CH1
client.write_coil(address=0, value=True, slave=1)

# Odczytaj wszystkie przekaźniki
coils = client.read_coils(address=0, count=8, slave=1)
print(coils.bits)

client.close()
```

---

## Struktura projektu

```
303Modbus13_RTU_Control/
├── app.py              # Aplikacja GUI (Tkinter) — punkt wejścia
├── modbus_device.py    # Warstwa komunikacji Modbus RTU
├── requirements.txt    # Zależności Python
├── README.md           # Ten plik
└── docs/
    └── REGISTERS.md    # Pełna dokumentacja rejestrów Modbus
```

---

## Pierwsza konfiguracja nowego modułu

Nowy moduł może mieć domyślny adres `0x00`. Aby ustawić adres `0x01`:

1. Połącz się z aplikacją (Slave ID = `00` lub `01` — sprawdź oba).
2. Na zakładce **Połączenie** wpisz nowy adres `01` i kliknij **Zapisz nowy adres**.
3. Rozłącz i połącz ponownie ze Slave ID = `01`.

Alternatywnie — przez konsolę zaawansowaną:
```
Funkcja: Write Multiple Registers (0x10)
Adres: 0
Wartości: 1
Slave: 0
```

---

## Mostek Modbus TCP/RTU

Moduł można również obsługiwać przez mostek sieciowy (np. USR-M0) z protokołem Modbus TCP. Mapa rejestrów jest identyczna — zmienia się tylko warstwa transportu (IP zamiast COM).

Wersja aplikacji z obsługą TCP/RTU: repozytorium `ModBus_Relay_303Modbus13`.

---

## Rozwiązywanie problemów

| Objaw | Rozwiązanie |
|-------|-------------|
| „Nie można otworzyć portu COM” | Sprawdź Menedżer urządzeń → Porty COM, zamknij inne programy używające portu |
| „Brak odpowiedzi od urządzenia” | Sprawdź okablowanie RS-485 (A/B), Slave ID, prędkość 9600 |
| Sensor T/H pokazuje „niepodłączony” | Sensor jest opcjonalny — moduł przekaźników działa bez niego |
| Błąd przy zmianie adresu | Upewnij się, że używasz Slave=0 (broadcast) |

---

## Licencja

© **Ideaflex sp. z o.o.** — oprogramowanie udostępniane klientom wraz z modułem 303Modbus13.

---

## Kontakt

W razie pytań technicznych skontaktuj się z działem wsparcia Ideaflex.

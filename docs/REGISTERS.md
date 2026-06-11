# Mapa rejestrów Modbus — moduł 303Modbus13

Dokumentacja protokołu Modbus RTU dla modułu przekaźnikowego **Ideaflex 303Modbus13**.

---

## Parametry komunikacji

| Parametr | Wartość domyślna |
|----------|------------------|
| Protokół | Modbus RTU |
| Prędkość | 9600 baud |
| Format | 8N1 (8 bitów danych, brak parzystości, 1 bit stopu) |
| Slave ID (przekaźniki) | `0x01` (konfigurowalny) |
| Slave ID (sensor T/H) | `0x02` (opcjonalny) |

> **Uwaga:** Moduł może być podłączony bezpośrednio przez RS-485 (port COM) lub przez mostek Modbus TCP/RTU (np. USR-M0). Mapa rejestrów jest identyczna w obu przypadkach.

---

## Slave ID = 1 — moduł przekaźników

### Cewki (Coils) — wyjścia przekaźnikowe

Sterowanie 8 kanałami przekaźnikowymi CH1–CH8.

| Adres | Nazwa | Opis | Funkcja odczytu | Funkcja zapisu |
|-------|-------|------|-----------------|----------------|
| 0 | CH1 | Przekaźnik kanał 1 | FC `0x01` Read Coils | FC `0x05` Write Single Coil |
| 1 | CH2 | Przekaźnik kanał 2 | FC `0x01` Read Coils | FC `0x05` Write Single Coil |
| 2 | CH3 | Przekaźnik kanał 3 | FC `0x01` Read Coils | FC `0x05` Write Single Coil |
| 3 | CH4 | Przekaźnik kanał 4 | FC `0x01` Read Coils | FC `0x05` Write Single Coil |
| 4 | CH5 | Przekaźnik kanał 5 | FC `0x01` Read Coils | FC `0x05` Write Single Coil |
| 5 | CH6 | Przekaźnik kanał 6 | FC `0x01` Read Coils | FC `0x05` Write Single Coil |
| 6 | CH7 | Przekaźnik kanał 7 | FC `0x01` Read Coils | FC `0x05` Write Single Coil |
| 7 | CH8 | Przekaźnik kanał 8 | FC `0x01` Read Coils | FC `0x05` Write Single Coil |

**Zapis wielu cewek jednocześnie:** FC `0x0F` Write Multiple Coils, adres startowy `0`, liczba `8`.

| Wartość | Znaczenie |
|---------|-----------|
| `0` / `False` | Przekaźnik wyłączony (OFF) |
| `1` / `True` | Przekaźnik włączony (ON) |

**Przykład — włączenie CH1:**
```
FC 0x05, Slave=1, Address=0, Value=0xFF00 (ON)
```

**Przykład — włączenie wszystkich 8 przekaźników:**
```
FC 0x0F, Slave=1, Address=0, Count=8, Values=[ON, ON, ON, ON, ON, ON, ON, ON]
```

---

### Wejścia dyskretne (Discrete Inputs) — wejścia opto

Odczyt stanu 8 wejść optycznych IN1–IN8. Tylko odczyt.

| Adres | Nazwa | Opis | Funkcja |
|-------|-------|------|---------|
| 0 | IN1 | Wejście opto 1 | FC `0x02` Read Discrete Inputs |
| 1 | IN2 | Wejście opto 2 | FC `0x02` Read Discrete Inputs |
| 2 | IN3 | Wejście opto 3 | FC `0x02` Read Discrete Inputs |
| 3 | IN4 | Wejście opto 4 | FC `0x02` Read Discrete Inputs |
| 4 | IN5 | Wejście opto 5 | FC `0x02` Read Discrete Inputs |
| 5 | IN6 | Wejście opto 6 | FC `0x02` Read Discrete Inputs |
| 6 | IN7 | Wejście opto 7 | FC `0x02` Read Discrete Inputs |
| 7 | IN8 | Wejście opto 8 | FC `0x02` Read Discrete Inputs |

**Przykład — odczyt wszystkich wejść:**
```
FC 0x02, Slave=1, Address=0, Count=8
```

| Wartość | Znaczenie |
|---------|-----------|
| `0` / `False` | Wejście nieaktywne |
| `1` / `True` | Wejście aktywne |

---

### Rejestry Holding — konfiguracja

| Adres | Nazwa | Opis | Funkcja odczytu | Funkcja zapisu |
|-------|-------|------|-----------------|----------------|
| 0 | DEVICE_ADDR | Adres Modbus slave modułu | FC `0x03` Read Holding Registers | FC `0x10` Write Multiple Registers |

#### Zmiana adresu Modbus slave

Aby zmienić adres urządzenia, zapisz nowy adres do rejestru holding `0` z **Slave ID = 0** (adres broadcast):

```
FC 0x10, Slave=0 (broadcast), Address=0, Count=1, Values=[nowy_adres]
```

| Parametr | Zakres |
|----------|--------|
| `nowy_adres` | `0x01` – `0xFF` |

Po zmianie adresu należy komunikować się z modułem używając nowego Slave ID.

> **Procedura fabryczna:** Nowy moduł może mieć domyślny adres `0x00`. Użyj powyższej komendy z wartością `1`, a następnie komunikuj się ze Slave ID = `0x01`.

---

## Slave ID = 2 — sensor temperatury i wilgotności (opcjonalny)

Moduł może być wyposażony w czujnik T/H. Jeśli sensor nie jest zamontowany, zapytania do Slave ID = 2 nie zwrócą odpowiedzi.

### Rejestry Input — pomiary

| Adres | Nazwa | Opis | Funkcja | Jednostka |
|-------|-------|------|---------|-----------|
| 1 | TEMPERATURE | Temperatura | FC `0x04` Read Input Registers | °C × 10 |
| 2 | HUMIDITY | Wilgotność względna | FC `0x04` Read Input Registers | % × 10 |

**Przeliczenie wartości:**

```
temperatura_°C = rejestr[1] / 10.0
wilgotność_%   = rejestr[2] / 10.0
```

**Przykład — odczyt temperatury i wilgotności:**
```
FC 0x04, Slave=2, Address=1, Count=1  → temperatura
FC 0x04, Slave=2, Address=2, Count=1  → wilgotność
```

**Przykład odpowiedzi:**
```
Rejestr TEMPERATURE = 235  →  23.5 °C
Rejestr HUMIDITY    = 582  →  58.2 %
```

---

## Podsumowanie funkcji Modbus

| Kod FC | Nazwa | Zastosowanie w 303Modbus13 |
|--------|-------|----------------------------|
| `0x01` | Read Coils | Odczyt stanu przekaźników CH1–CH8 |
| `0x02` | Read Discrete Inputs | Odczyt wejść opto IN1–IN8 |
| `0x03` | Read Holding Registers | Odczyt konfiguracji (adres urządzenia) |
| `0x04` | Read Input Registers | Odczyt T/H (Slave ID = 2) |
| `0x05` | Write Single Coil | Włączenie/wyłączenie pojedynczego przekaźnika |
| `0x06` | Write Single Register | Zapis pojedynczego rejestru holding |
| `0x0F` | Write Multiple Coils | Sterowanie wieloma przekaźnikami jednocześnie |
| `0x10` | Write Multiple Registers | Zmiana adresu Modbus (broadcast, Slave=0) |

---

## Schemat połączeń RS-485

```
  [PC / PLC]                    [303Modbus13]
      |                              |
   USB-RS485  ─── A/B (RS-485) ───  A/B
      |                              |
     COM                           Zasilanie
```

- Linia **A** → **A**, linia **B** → **B**
- Wspólna masa (GND) zalecana
- Maksymalna długość magistrali i terminacja zgodnie z dokumentacją modułu

---

## Rozwiązywanie problemów

| Problem | Możliwa przyczyna | Rozwiązanie |
|---------|-------------------|-------------|
| Brak odpowiedzi Modbus | Zły port COM lub prędkość | Sprawdź 9600 8N1, właściwy port COM |
| Brak odpowiedzi Modbus | Zły Slave ID | Spróbuj ID=1; przy nowym module ustaw adres przez broadcast (Slave=0) |
| Sensor T/H nie odpowiada | Sensor nie zamontowany | Normalne — moduł działa bez sensora |
| Błąd CRC / timeout | Problem z okablowaniem RS-485 | Sprawdź polaryzację A/B, połączenie GND |

---

*© Ideaflex sp. z o.o. — dokumentacja dla modułu 303Modbus13*

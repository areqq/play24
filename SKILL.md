---
name: play24
description: >
  Sprawdzanie i zarządzanie kontami Play (polski operator, prepaid/abonament) bez oficjalnej
  apki. Użyj, gdy użytkownik pyta o: saldo / stan konta Play, ile zostało GB / minut / SMS,
  ważność konta lub pakietu, listę swoich numerów Play, albo chce włączyć/wyłączyć pakiet.
  Dane pobierane są przez JSON-owe CLI (read-only) lub bibliotekę; aktywacja pakietów (płatna)
  przez interaktywny klient. Keywords: Play24, Play, prepaid, saldo, GB, minuty, pakiet, MSISDN.
---

# Skill: play24

Nieoficjalny dostęp do API self-care **Play24**. Pozwala odczytać status konta i (interaktywnie)
włączać pakiety. Implementacja: `play24_json.py` (JSON, read-only), `play24lib.py` (biblioteka),
`play24.py` (pełny CLI, w tym operacje płatne).

## Wymagania wstępne (jednorazowo, poza agentem)
Numer musi być najpierw **onboardowany** (rejestracja passkey przez kod SMS) — to wymaga
interakcji człowieka (kod z SMS), więc agent tego nie robi sam:
```bash
python3 play24.py register-start --msisdn 48XXXXXXXXX   # SMS
python3 play24.py register-otp   --code 1234            # passkey zapisany w ~/.play24/
```
Po tym agent loguje się **samym passkeyem** (bez SMS), na dowolnej sieci.

## Jak agent ma używać (read-only, JSON na stdout)
Zawsze parsuj JSON ze stdout; sprawdzaj `ok` i kod wyjścia (0=ok, 1=błąd).

```bash
python3 play24_json.py accounts                      # lista numerów (bez sieci)
python3 play24_json.py summary  --msisdn 48XXXXXXXXX # NAJWAŻNIEJSZE: skrót statusu
python3 play24_json.py packages --msisdn 48XXXXXXXXX # pakiety + daty odnowienia/wygaśnięcia
python3 play24_json.py counters --msisdn 48XXXXXXXXX # liczniki (dane/minuty/SMS)
python3 play24_json.py account  --msisdn 48XXXXXXXXX # dane klienta
```

### Kontrakt JSON
- sukces: `{"ok": true, "cmd": "...", "msisdn": "...", "data": {...}}`
- błąd:   `{"ok": false, "cmd": "...", "error": "...", "type": "Play24Error"}`

`summary.data` (najczęściej wystarcza): `balance_pln`, `balance_unit`, `account_expires`,
`account_expires_days`, `data_gb` (krajowe), `data_gb_roaming`, `minutes`, `counters[]`,
`packages[]` (każdy: `title`, `paid`, `price_pln`, `cyclic`, `activationDate`, `nextApplyDate`,
`expirationDate`). Pakiet cykliczny pilnuj po `nextApplyDate`, jednorazowy po `expirationDate`.

## Operacje płatne (włączanie pakietów)
**Wymaga potwierdzenia człowieka** (realny koszt + autoryzacja PIN/SCA). Nie rób autonomicznie:
```bash
python3 play24.py packages --all                 # katalog z id
python3 play24.py activate <id>                   # zapyta o potwierdzenie; szczegóły: ACTIVATION.md
```

## Użycie jako biblioteka (agent w Pythonie)
```python
from play24lib import Play24
s = Play24("48XXXXXXXXX").login().summary()
```

## Uwagi
- Konfiguracja/sekrety/passkey: `~/.play24/` (poza repo). Nigdy nie loguj tokenów/cookies.
- Każde wywołanie = pełne logowanie passkeyem (kilka żądań) — nie odpytuj w pętli zbyt często.
- Pełna dokumentacja API: `API.md`, `ACTIVATION.md`, `endpoints.txt`.

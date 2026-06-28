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
`play24.py` (pełny CLI), `play24_mcp.py` (serwer MCP — pełny protokół jako narzędzia).
Środowisko: `uv` (`uv sync`); komendy odpalaj przez `uv run …`.

## Wymagania wstępne (jednorazowo, poza agentem)
Numer musi być najpierw **onboardowany** (rejestracja passkey przez kod SMS) — to wymaga
interakcji człowieka (kod z SMS), więc agent tego nie robi sam:
```bash
uv run play24 register-start --msisdn 48XXXXXXXXX               # SMS
uv run play24 register-otp   --msisdn 48XXXXXXXXX --code 1234   # passkey zapisany w ~/.play24/
```
Po tym agent loguje się **samym passkeyem** (bez SMS), na dowolnej sieci.

## Jak agent ma używać (read-only, JSON na stdout)
Zawsze parsuj JSON ze stdout; sprawdzaj `ok` i kod wyjścia (0=ok, 1=błąd).

```bash
uv run play24-json accounts                      # lista numerów (bez sieci)
uv run play24-json summary  --msisdn 48XXXXXXXXX # NAJWAŻNIEJSZE: skrót statusu
uv run play24-json packages --msisdn 48XXXXXXXXX # pakiety + daty odnowienia/wygaśnięcia
uv run play24-json counters --msisdn 48XXXXXXXXX # liczniki (dane/minuty/SMS)
uv run play24-json account  --msisdn 48XXXXXXXXX # dane klienta
```

## Natywnie przez MCP (typowane narzędzia)
Dla klientów MCP: `uv run play24-mcp` (stdio). Narzędzia: `play24_accounts`, `play24_summary`,
`play24_balance`, `play24_counters`, `play24_packages`, `play24_account`, `play24_numbers`,
`play24_raw` oraz (operacje na koncie) `play24_register_start`/`play24_register_complete`,
`play24_switch`, `play24_activate`/`play24_deactivate`. Te same dane co JSON-CLI, bez parsowania stdout.

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
uv run play24 packages --all                 # katalog z id i ceną
uv run play24 activate <id>                   # zapyta o potwierdzenie; szczegóły: ACTIVATION.md
```
(W MCP: `play24_activate` — najpierw potwierdź cenę z użytkownikiem; step-up FIDO robi się sam.)

## Użycie jako biblioteka (agent w Pythonie)
```python
from play24lib import Play24
s = Play24("48XXXXXXXXX").login().summary()
```

## Uwagi
- Konfiguracja/sekrety/passkey: `~/.play24/` (poza repo). Nigdy nie loguj tokenów/cookies.
- Każde wywołanie = pełne logowanie passkeyem (kilka żądań) — nie odpytuj w pętli zbyt często.
- Pełna dokumentacja API: `API.md`, `ACTIVATION.md`, `endpoints.txt`.

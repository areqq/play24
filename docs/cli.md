# CLI — referencja komend

Pełny klient `play24` (cienka warstwa nad `play24lib`). Odpalaj przez `uv run play24 …`
(albo `python3 play24.py …`). Logowanie passkeyem dzieje się automatycznie przy każdej komendzie.

← [README](../README.md) · [Szybki start](../QUICKSTART.md) · [Uwierzytelnianie](auth.md) · [Wiele numerów](multi-number.md)

## Wybór numeru
Każda komenda przyjmuje `--msisdn`. Bez niego użyty zostanie numer **domyślny** (ustaw `use`)
lub jedyny zarejestrowany. Saldo dodatkowo: `--kind {VOICE,DATA,FIX,TV}` i `--type {PREPAID,POSTPAID,MIX}`
(domyślnie `VOICE`/`PREPAID`).

## Komendy
```
uv run play24 register-start --msisdn 48...   # onboarding krok 1: wyślij kod SMS
uv run play24 register-otp --msisdn 48... --code 1234   # krok 2: kod SMS → passkey
uv run play24 accounts           # lokalne konta (osobne profile); * = domyślny
uv run play24 use <msisdn>       # ustaw domyślny numer (potem --msisdn opcjonalny)
uv run play24 whoami             # lokalny stan (profile, domyślny numer, device_id)

uv run play24 summary            # skrót: saldo, ważność konta, GB (krajowe/roaming), minuty, pakiety
uv run play24 balance            # saldo główne (ms-balances/main)
uv run play24 balances-all       # wszystkie liczniki/pakiety (ms-balances/all)
uv run play24 counters           # liczniki (dane/minuty/SMS) z wyliczonymi GB/min
uv run play24 account            # dane konta/klienta (ms-clients)
uv run play24 offers             # oferty
uv run play24 finances           # podsumowanie finansów
uv run play24 invoices           # faktury / dokumenty
uv run play24 components         # usługi / komponenty taryfy (surowo)
uv run play24 notifications      # powiadomienia
uv run play24 history            # historia aktywności
uv run play24 sim                # informacje o SIM

uv run play24 numbers            # numery na koncie (jedno konto, wiele numerów)
uv run play24 switch <msisdn>    # przełącz numer w obrębie jednego konta + pokaż saldo

uv run play24 packages           # pakiety/usługi + daty odnowienia/wygaśnięcia
uv run play24 packages --all     # cały katalog + id + cena (potrzebne do activate)
uv run play24 packages --json    # surowy JSON zamiast tabeli
uv run play24 activate <id>      # WŁĄCZ pakiet (realny zakup; zapyta o potwierdzenie) → ACTIVATION.md
uv run play24 deactivate <id>    # WYŁĄCZ pakiet
```

`activate`/`deactivate` przyjmują `--otp <KOD>` (gdy serwer poprosi o SMS), `--email`
(wymagany raz na konto przy 1. zakupie), `--yes` (pomiń potwierdzenie), `--no-stepup`
(nie próbuj auto-autoryzacji FIDO). Mechanika SCA: [ACTIVATION.md](ACTIVATION.md).

## Dowolny endpoint
```bash
uv run play24 raw GET  ms-finances v4 finances/{userId}/info
uv run play24 raw POST ms-balances v3 balances/{userId}/main --body '{"serviceKind":"VOICE","serviceType":"PREPAID"}'
```
`{userId}` jest podstawiany automatycznie (msisdn z prefiksem 48). Pełny katalog ścieżek:
[endpoints.txt](endpoints.txt), opis: [API.md](API.md).

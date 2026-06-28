# Changelog

Wszystkie istotne zmiany w projekcie. Format wg [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie wg [SemVer](https://semver.org/lang/pl/).

## [0.1.0] — 2026-06-28

Pierwsze spójne wydanie: jeden rdzeń (`play24lib.py`) i cztery interfejsy nad nim
(**CLI**, **JSON-CLI**, **biblioteka**, **serwer MCP**), środowisko przez `uv`.

### Added
- **Serwer MCP** (`play24_mcp.py`, FastMCP/stdio) — pełny protokół jako 13 typowanych narzędzi
  (`play24_summary/balance/counters/packages/account/numbers/raw/accounts`,
  `play24_register_start/register_complete`, `play24_switch`, `play24_activate/deactivate`)
  + zasób `play24://accounts`. Gotowe dla Claude Desktop/Code i dowolnego klienta MCP.
- **`uv` / `pyproject.toml`** — zależności (requests, cryptography; extra `mcp`) i skrypty
  konsolowe `play24`, `play24-json`, `play24-mcp` (`uv sync`, `uv run …`).
- **`QUICKSTART.md`** — szybki start (środowisko, onboarding, CLI/JSON/biblioteka/MCP, cron).
- **CLI**: komendy `summary`, `counters`, `use` (domyślny numer), `packages --json`.
- Onboarding programowy w bibliotece: `register_start()` / `register_complete()`.

### Changed
- **Deduplikacja kodu**: `play24lib.py` to teraz jedyny rdzeń z całym protokołem (transport,
  logowanie passkeyem, onboarding, store, `numbers/switch`, `activate/deactivate` z SCA step-up,
  parsery). `play24.py` i `play24_json.py` to cienkie warstwy nad biblioteką — brak duplikacji.
- **Autentykator WebAuthn/FIDO2 wbudowany** w `play24lib.py` (`Passkey`, `make_credential`,
  `get_assertion`, `cbor`, `b64`) — wcześniej osobny moduł.
- CLI loguje się passkeyem **automatycznie przy każdej komendzie** (nie ma już osobnego `auth`);
  numer wskazujesz przez `--msisdn` lub `use`.
- `~/.play24/session.json` trzyma teraz **profile + device_id + aktywny numer** (nie cookies —
  sesja cookie jest krótkotrwała, tylko na czas procesu).
- README/SKILL/CLAUDE zaktualizowane o `uv`, MCP i nowy zestaw komend.

### Removed
- `play24_passkey.py` — scalony do `play24lib.py` (bez zmiany zachowania).
- Z CLI usunięto eksperymentalne/niszowe drogi logowania (`login-ip`, `login` hasłem,
  `--token`/`--cookie`) — klient standaryzuje na passkey (działa z każdej sieci). Opis tych
  alternatyw pozostaje w `docs/API.md` dla celów dokumentacyjnych.

---

## [0.0.x] — 2026-06-27 (rozwój początkowy)

Reverse-engineering API Play24 (`com.play.play24m`, v11.9.0) i pierwsza wersja narzędzi.

### Added
- Klient CLI (`play24.py`): saldo, pakiety, faktury, dane konta, historia, SIM, dowolny endpoint.
- Logowanie od zera bez apki: onboarding numeru kodem SMS + własny **passkey FIDO2**
  (software'owy autentykator WebAuthn, klucz EC P-256 w pliku); działa z dowolnej sieci.
- Obsługa wielu kont/numerów (osobne profile oraz `numbers`/`switch` w obrębie jednego konta).
- **Włączanie/wyłączanie pakietów** z autoryzacją SCA (step-up FIDO: 409 `MP0174` →
  `authorize/direct` → ponowienie z `operationId`).
- Biblioteka `play24lib.py` (`Play24(numer).login().summary()`) i helpery parsujące.
- Monitor do crona (`examples/monitor.py`): progi (saldo, ważność konta/pakietów, GB, minuty)
  dla wielu numerów, kolorowe alerty 🟢🟠🔴 na nazwane notyfikatory (Telegram); rozróżnienie
  pakietów cyklicznych (odnowienie) od jednorazowych (wygaśnięcie); rozdział danych krajowych
  od roamingu UE.
- Integracja z agentami AI: JSON-owe CLI (`play24_json.py`, read-only) + `SKILL.md`.
- Dokumentacja RE: `API.md`, `ACTIVATION.md`, `endpoints.txt`, `METHODS.md`, `CLAUDE.md`;
  narzędzia dynamiki w `re/` (Frida unpinning). Licencja MIT.

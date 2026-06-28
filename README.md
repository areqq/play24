# play24 — nieoficjalny klient API Play24

Narzędzia w Pythonie do zarządzania kontem **Play** (`com.play.play24m`) bez oficjalnej apki —
wynik reverse-engineeringu API self-care. Jeden rdzeń (`play24lib.py`), cztery interfejsy:
**CLI**, **JSON-CLI**, **biblioteka**, **serwer MCP**.

> ⚠️ Nieoficjalne. Używaj wyłącznie do **własnego konta**. To self-care operatora — nic nie atakuje,
> jedynie odtwarza to, co robi oficjalna apka. Niezwiązane z P4 sp. z o.o.

## Co to potrafi
- 🔑 **Logowanie od zera, z dowolnej sieci** — podpięcie numeru kodem SMS + własny **passkey FIDO2**;
  potem każde logowanie bez SMS. → [auth](docs/auth.md)
- 📊 **Odczyt konta** — saldo, ważność konta, GB (krajowe/roaming), minuty, pakiety z datami
  odnowienia/wygaśnięcia, faktury, SIM, historia. → [CLI](docs/cli.md)
- 🛒 **Włączanie/wyłączanie pakietów** — z autoryzacją SCA (step-up FIDO) jak w apce. → [ACTIVATION](docs/ACTIVATION.md)
- 👥 **Wiele numerów** — osobne konta albo wiele numerów na jednym koncie. → [wiele numerów](docs/multi-number.md)
- 🤖 **Dla agentów AI** — JSON-owe CLI, manifest skilla i **serwer MCP** (pełny protokół jako
  typowane narzędzia). → [agenci / MCP](docs/agents-mcp.md)
- 🔔 **Monitor do crona** — progi (saldo/ważność/GB/minuty/pakiety) dla wielu numerów, kolorowe
  alerty 🟢🟠🔴 na nazwane notyfikatory (Telegram). → [monitor](docs/monitor.md)

## Szybki start (60 sekund)
```bash
uv sync                                                        # środowisko (requests, cryptography)
uv run play24 register-start --msisdn 48xxxxxxxxx             # przyjdzie SMS
uv run play24 register-otp  --msisdn 48xxxxxxxxx --code 1234  # zapisze passkey w ~/.play24/
uv run play24 summary                                         # saldo, GB, minuty, pakiety
```
Pełny przewodnik (CLI / JSON / biblioteka / MCP / cron): **[QUICKSTART.md](QUICKSTART.md)**.
Bez `uv`: `pip install requests cryptography` i `python3 play24.py …`.

## Dokumentacja
| Dokument | O czym |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | Szybki start dla wszystkich czterech interfejsów |
| [docs/cli.md](docs/cli.md) | Referencja komend CLI |
| [docs/auth.md](docs/auth.md) | Logowanie passkeyem (FIDO2) i alternatywy |
| [docs/multi-number.md](docs/multi-number.md) | Obsługa wielu numerów/kont |
| [docs/agents-mcp.md](docs/agents-mcp.md) | Biblioteka, JSON-CLI, serwer MCP, skill |
| [docs/monitor.md](docs/monitor.md) | Monitor progów do crona |
| [docs/API.md](docs/API.md) · [docs/ACTIVATION.md](docs/ACTIVATION.md) | Rozpracowane API + recepta na aktywację |
| [docs/endpoints.txt](docs/endpoints.txt) · [docs/METHODS.md](docs/METHODS.md) | Katalog endpointów + techniki RE |
| [CHANGELOG.md](CHANGELOG.md) | Historia zmian |

## Mapa kodu
- `play24lib.py` — **rdzeń**: cały protokół (klasa `Play24`, onboarding, store, parsery, autentykator WebAuthn/FIDO2)
- `play24.py` / `play24_json.py` / `play24_mcp.py` — cienkie warstwy: CLI / JSON-CLI / serwer MCP
- `examples/monitor.py` — monitor progów do crona · `SKILL.md` — manifest skilla
- `pyproject.toml` — projekt/zależności/skrypty (`uv`) · `re/` — narzędzia RE (Frida)

> Repo zawiera wyłącznie własny kod i dokumentację. **Nie zawiera** APK, dekompilatu ani danych konta.
> Sekrety i passkey trzymane są lokalnie w `~/.play24/` (poza repo).

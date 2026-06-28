# QUICKSTART — Play24 w 5 minut

Nieoficjalny klient self-care API Play24 (`com.play.play24m`). Cztery sposoby użycia z jednego
rdzenia (`play24lib.py`): **CLI**, **JSON-CLI** (dla agentów AI), **biblioteka** (Python), **serwer MCP**.

> Wszystko działa z **dowolnej sieci** (nie tylko Play) — logowanie to FIDO2/passkey.
> Sekrety i passkey trzymane są w `~/.play24/` (poza repo).

## 0. Środowisko (uv)

[uv](https://docs.astral.sh/uv/) zarządza środowiskiem i zależnościami.

```bash
# instalacja uv (jeśli nie masz): curl -LsSf https://astral.sh/uv/install.sh | sh
cd play24
uv sync                 # tylko CLI / biblioteka (requests + cryptography)
uv sync --extra mcp     # dodatkowo serwer MCP (pakiet 'mcp')
```

Każdą komendę odpalasz przez `uv run …` (środowisko aktywuje się samo). Bez uv: zwykłady poniżej
działają też jako `python3 play24.py …`, o ile masz `requests` i `cryptography`.

## 1. Podpięcie numeru OD ZERA (raz na numer) — ZWERYFIKOWANE NA ŻYWO

Działa z każdej sieci. Wymaga tylko kodu z SMS (dlatego robi to człowiek, nie agent).

```bash
uv run play24 register-start --msisdn 48XXXXXXXXX   # przyjdzie SMS z kodem
uv run play24 register-otp   --msisdn 48XXXXXXXXX --code 1234
```

Po tym w `~/.play24/` jest passkey — kolejne logowania są **bez SMS**. Lista numerów:

```bash
uv run play24 accounts
uv run play24 use 48XXXXXXXXX        # ustaw domyślny (potem --msisdn opcjonalny)
```

## 2. CLI (człowiek)

```bash
uv run play24 summary                 # skrót: saldo, ważność, GB, minuty, pakiety
uv run play24 packages --all          # cały katalog z id i ceną
uv run play24 activate <id>           # WŁĄCZ pakiet (realny koszt — zapyta o potwierdzenie)
uv run play24 balance                 # surowe saldo
uv run play24 numbers                 # numery na jednym koncie (jeśli konto ma kilka)
uv run play24 raw GET ms-finances 4 finances/{userId}/info
```

## 3. JSON-CLI (agent AI / skrypt)

Każda komenda wypisuje jeden obiekt JSON i ustawia kod wyjścia (0/1):

```bash
uv run play24-json accounts
uv run play24-json summary  --msisdn 48XXXXXXXXX
uv run play24-json packages --msisdn 48XXXXXXXXX
```

Kontrakt: `{"ok":true,"cmd":...,"data":...}` / `{"ok":false,"error":...}`. Szczegóły: `SKILL.md`.

## 4. Biblioteka (Python)

```python
from play24lib import Play24, register_start, register_complete, accounts

for a in accounts():                       # lokalnie zarejestrowane numery
    s = Play24(a["msisdn"]).login().summary()
    print(a["msisdn"], s["balance_pln"], "zł", s["minutes"], "min")
```

Onboarding programowo: `register_start("48...")` → (SMS) → `register_complete("48...", "1234")`.
Włączanie pakietu: `Play24("48...").login().activate("<id>")` (SCA/step-up FIDO robi się sam).

## 5. Serwer MCP (agenci: Claude Desktop / Claude Code / dowolny klient MCP)

MCP udostępnia **pełny** protokół jako narzędzia (odczyty, onboarding, wiele numerów,
włączanie/wyłączanie pakietów). Uruchomienie:

```bash
uv run play24-mcp           # transport stdio (JSON-RPC 2.0)
```

Konfiguracja klienta (np. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "play24": { "command": "uv", "args": ["run", "--directory", "/ABS/ŚCIEŻKA/play24", "play24-mcp"] }
  }
}
```

Narzędzia: `play24_accounts`, `play24_summary`, `play24_balance`, `play24_counters`,
`play24_packages`, `play24_account`, `play24_numbers`, `play24_raw`, `play24_register_start`,
`play24_register_complete`, `play24_switch`, `play24_activate`, `play24_deactivate`
oraz zasób `play24://accounts`. Operacje płatne (`activate`) wymagają potwierdzenia ceny z użytkownikiem.

## 6. Monitoring w cron (progi → Telegram)

Przykład w `examples/monitor.py` (saldo / ważność konta / GB / minuty / pakiety, alerty 🟢🟠🔴).
Konfiguracja w `~/.play24/monitor.json` (poza repo). Szczegóły: [docs/monitor.md](docs/monitor.md).

```bash
# raz na dobę o 9:00:
0 9 * * *  cd /ABS/ŚCIEŻKA/play24 && uv run python examples/monitor.py >> ~/.play24/monitor.log 2>&1
```

> 💡 Monitor jest lekki (raz dziennie, kilka żądań) — spokojnie postawisz go na darmowym serwerze,
> np. [frog.mikr.us](https://frog.mikr.us) (darmowy mikro-VPS; wystarczy `cron` + `uv`).

---
Pełne API: [`docs/API.md`](docs/API.md), [`docs/ACTIVATION.md`](docs/ACTIVATION.md),
[`docs/endpoints.txt`](docs/endpoints.txt). Techniki RE: [`docs/METHODS.md`](docs/METHODS.md). Kontekst: `CLAUDE.md`.

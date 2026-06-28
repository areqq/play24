# Biblioteka, agenci AI i MCP

Trzy warstwy integracji nad rdzeniem `play24lib.py` — od najprostszej.

← [README](../README.md) · [Szybki start](../QUICKSTART.md) · [CLI](cli.md)

## 1. Biblioteka (Python)
Wymaga wcześniejszego onboardingu numeru ([Uwierzytelnianie](auth.md)) — zapisuje profil + passkey w `~/.play24/`.
```python
from play24lib import Play24

p = Play24("48500100200").login()      # logowanie passkeyem (FIDO2)
s = p.summary()                        # zwięzłe dane do progów
print(s["balance_pln"], s["balance_unit"])      # np. 13.51 PLN
print(s["account_expires"], s["account_expires_days"])
print(s["data_gb"], "GB |", s["minutes"], "min")
for pkg in s["packages"]:              # aktywne pakiety + daty
    print(pkg["title"], pkg["activationDate"], pkg["expirationDate"], pkg["nextApplyDate"])

# dane surowe i operacje też dostępne:
p.balance(); p.account(); p.counters(); p.packages()
p.numbers(); p.switch("48...")
p.activate("<id>"); p.deactivate("<id>")     # step-up FIDO robi się sam
```
Onboarding programowo: `register_start("48...")` → (SMS) → `register_complete("48...", "1234")`.

`summary()` zwraca m.in.: `balance_pln`, `account_expires(_days)`, `data_gb` (**tylko krajowe**),
`data_gb_roaming`, `minutes`, `counters[]`, `packages[]` (każdy z `paid`/`price_pln`/`cyclic`),
`package_expire_days`, `package_renew_days`. Helpery: `parse_amount`, `to_gb`, `to_minutes`,
`days_until`, `package_status`.

## 2. JSON-owe CLI (read-only) — `play24_json.py`
Agent „shell-uje" i parsuje JSON ze stdout:
```bash
uv run play24-json summary --msisdn 48XXXXXXXXX
# {"ok": true, "cmd": "summary", "msisdn": "...", "data": { "balance_pln": 6.47, ... }}
```
Kontrakt: `{"ok":true,"data":{...}}` / `{"ok":false,"error":"..."}`, kod wyjścia 0/1.
Komendy: `accounts`, `summary`, `balance`, `counters`, `packages`, `account`. Operacji płatnych
**nie ma** w JSON-CLI (wymagają potwierdzenia człowieka).

[`SKILL.md`](../SKILL.md) to gotowy manifest skilla (`name` + `description` „kiedy użyć” + instrukcje) —
wystarczy wskazać go agentowi.

## 3. Serwer MCP — `play24_mcp.py`
Najnatywniej dla agentów (typowane narzędzia). Udostępnia **pełny** protokół:
```bash
uv sync --extra mcp
uv run play24-mcp           # transport stdio (JSON-RPC 2.0)
```
Konfiguracja klienta MCP (np. `claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "play24": { "command": "uv", "args": ["run", "--directory", "/ABS/play24", "play24-mcp"] }
  }
}
```
Narzędzia: `play24_accounts`, `play24_summary`, `play24_balance`, `play24_counters`,
`play24_packages`, `play24_account`, `play24_numbers`, `play24_raw`, `play24_register_start`,
`play24_register_complete`, `play24_switch`, `play24_activate`, `play24_deactivate`
oraz zasób `play24://accounts`.

> Operacje płatne (`play24_activate`) wydają pieniądze — najpierw potwierdź cenę z użytkownikiem
> (`play24_packages` z `active_only=False` pokazuje `id` i `price_pln`); step-up FIDO robi się sam.

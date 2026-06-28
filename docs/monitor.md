# Monitor progów do crona

`examples/monitor.py` buduje **kolorowy status** konta i **wysyła go na Telegram TYLKO gdy jest 🔴**
(wtedy raport zawiera pełny status). Dla wielu numerów, z elastycznymi, nazwanymi notyfikatorami.

← [README](../README.md) · [Biblioteka](agents-mcp.md)

## Co sprawdza
Legenda: 🟢 OK · 🟠 uwaga (blisko progu = 2× próg) · 🔴 reaguj (próg przekroczony) · ⚪ brak danych.
Sprawdza: saldo, ważność konta, GB, minuty oraz **tylko płatne pakiety** (`price>0`) — cykliczne
*kiedy się odnowią*, jednorazowe *kiedy wygasną*; darmowe usługi/limity pomijane. `exit≠0` gdy 🔴
(cron wyśle też maila). Opcjonalny `label` w configu dopisuje opis do numeru.

Przykładowy raport:
```
📱 48XXXXXXXXX (PREPAID) — Mój numer
🔴 saldo: 2.17 PLN  (min 5.0)
🟢 konto: do 2027-06-24 (za 361 dni)
🟢 dane: 8.98 GB
🟢 minuty: 50
Pakiety płatne:
  🟢 Pakiet Data 4 GB [8.00 zł] (cykl.) — odnowi się za 30 dni (2026-07-28)
  🟢 50 min, 50 SMS, 250MB [3.00 zł] (jedn.) — wygasa za 30 dni (2026-07-28)
```

## Konfiguracja — `~/.play24/monitor.json`
Poza repo (sekrety i numery; wzór: `examples/monitor.config.example.json`). Model: **nazwane
notyfikatory** (globalnie, z `type`) + per numer **dowolnie wiele sekcji alertów** (własne progi →
na wskazane notyfikatory):
```json
{
  "notifiers": {
    "admin":    { "type": "telegram", "bot_token": "111:bot", "chat_id": "111", "insecure": false },
    "domownik": { "type": "telegram", "bot_token": "222:bot", "chat_id": "222" }
  },
  "watch": {
    "48XXXXXXXXX": {
      "label": "Domownik",
      "alerts": [
        { "notify": ["admin"], "min_pln": 5.0, "account_days": 7 },
        { "notify": ["domownik"], "min_pln": 20.0, "min_gb": 1.0, "package_expire_days": 5 }
      ]
    }
  }
}
```
- **`notifiers`** — kanały zdefiniowane raz, po nazwie; `type` na razie `telegram` (rozszerzalne).
- Każdy numer ma **`alerts`** — listę sekcji. Sekcja = własne progi + `notify` (lista nazw
  notyfikatorów). Gdy w sekcji jest 🔴 → raport leci na te notyfikatory. Sekcji może być ile chcesz.
- Progi (pomiń klucz, by nie sprawdzać): `min_pln`, `min_gb` (krajowe), `min_minutes`,
  `account_days`, `package_renew_days`, `package_expire_days`, `package_validity_days`.
- `exit≠0` gdy gdziekolwiek 🔴 (cron wyśle maila); gdy wszystko OK — ciche jednolinijki na stdout.

W powyższym przykładzie *admin* dostaje tylko poważne (saldo <5 zł / koniec konta <7 dni),
a *domownik* — czulsze progi (saldo <20 zł, dane <1 GB) na swój własny Telegram. Niezależnie, każdy
ze swoimi progami.

## Uruchomienie
```bash
cp examples/monitor.config.example.json ~/.play24/monitor.json   # i uzupełnij
uv run python examples/monitor.py
# cron (codziennie 9:00):
# 0 9 * * *  cd /ABS/play24 && uv run python examples/monitor.py >> ~/.play24/monitor.log 2>&1
```
> Token bota Telegram i numery trzymaj **tylko** w `~/.play24/monitor.json` — `.gitignore`
> blokuje `monitor.json`, ale i tak nigdy nie commituj sekretów.

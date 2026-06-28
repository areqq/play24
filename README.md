# play24 — nieoficjalny klient API Play24

Rozpracowane API self-care **Play24** (`com.play.play24m`) + narzędzia w Pythonie do zarządzania
kontem bez oficjalnej apki. Reverse-engineering APK v11.9.0 (statyka + podsłuch).

Jeden rdzeń (`play24lib.py`), cztery interfejsy: **CLI**, **JSON-CLI**, **biblioteka**, **serwer MCP**.
Najkrótsza ścieżka: **[QUICKSTART.md](QUICKSTART.md)**.

## Co to potrafi (w skrócie)
- 📱 **Klient CLI** (`play24.py`) — saldo, pakiety, faktury, dane konta, historia, SIM, dowolny endpoint.
- 🔑 **Logowanie od zera bez apki** — onboarding numeru kodem SMS, własny **passkey FIDO2** (klucz w pliku),
  logowanie na dowolnej sieci. Obsługa **wielu kont/numerów** i przełączania.
- 🛒 **Włączanie/wyłączanie pakietów** — z autoryzacją operacji (SCA/step-up FIDO) jak w apce.
- 🧩 **Biblioteka** (`play24lib.py`) — `Play24(numer).login().summary()` zwraca saldo, ważność konta,
  GB (krajowe/roaming), minuty, pakiety (z datami odnowienia/wygaśnięcia). Tu mieszka cały protokół.
- 🤖 **Serwer MCP** (`play24_mcp.py`) — **pełny** protokół (odczyty + onboarding + wiele numerów +
  włączanie/wyłączanie pakietów) jako narzędzia dla agentów AI (Claude Desktop/Code, dowolny klient MCP).
- 🔔 **Monitor do crona** (`examples/monitor.py`) — pilnuje progów (saldo, ważność konta/pakietów,
  GB, minuty) dla wielu numerów i śle **kolorowe** alerty 🟢🟠🔴 na **nazwane notyfikatory** (Telegram).
- 🧠 **Gotowe do agentów AI** — JSON-owe CLI (`play24_json.py`, read-only) + `SKILL.md` (manifest skilla).
- 📖 **Dokumentacja RE** — [`API.md`](API.md), [`ACTIVATION.md`](ACTIVATION.md),
  [`endpoints.txt`](endpoints.txt), [`METHODS.md`](METHODS.md).

> ⚠️ Nieoficjalne. Używaj wyłącznie do **własnego konta**. To self-care operatora — nic nie atakuje,
> jedynie odtwarza to, co robi oficjalna apka.

## Wymagania / instalacja (uv)
Środowiskiem zarządza [uv](https://docs.astral.sh/uv/) (`pyproject.toml`):
```bash
uv sync                 # CLI + biblioteka (requests, cryptography)
uv sync --extra mcp     # dodatkowo serwer MCP
```
Komendy odpalasz przez `uv run …` (np. `uv run play24 summary`). Bez uv: `pip install requests cryptography`
i `python3 play24.py …`.

> Logowanie to **FIDO2/passkey**. Biblioteka loguje się passkeyem przy każdym wywołaniu i trzyma
> cookie jar tylko na czas procesu; w `~/.play24/session.json` zapisane są **profile + device_id**
> (nie cookies). Klucz passkey: `~/.play24/passkey_<48msisdn>.json` (chmod 600). Szczegóły: `API.md §2`.

## Uwierzytelnianie — passkey FIDO2 (dowolna sieć)

**Działa na każdej sieci (WiFi też), nie wymaga hasła ani przechwytywania.** Rejestrujesz własny
passkey (WebAuthn) przez weryfikację kodem SMS; klient jest własnym autentykatorem (klucz EC P-256
w `~/.play24/passkey_<48msisdn>.json`). Zweryfikowane na żywo.
```bash
uv run play24 register-start --msisdn 48xxxxxxxxx              # wyśle SMS (numer 9-cyfrowy też OK)
# (przychodzi kod SMS)
uv run play24 register-otp --msisdn 48xxxxxxxxx --code 1234    # weryfikuje kod + rejestruje passkey
# ✅ numer podpięty. Od teraz KAŻDA komenda loguje się passkeyem automatycznie (bez SMS):
uv run play24 summary --msisdn 48xxxxxxxxx
uv run play24 use 48xxxxxxxxx                                  # ustaw domyślny → --msisdn opcjonalny
uv run play24 summary
```
Nie ma osobnej komendy „login” — onboardowany numer jest logowany passkeyem przy każdym wywołaniu
(CLI, biblioteka, MCP). Szczegóły protokołu (patrz `API.md §2`):
- `kyc/register?hint=MSISDN_OTP_REQUIRED` `{type:STANDARD,input:msisdn}` → SMS; kod → `PUT kyc/register/{nonce} {password:<kod>}` (kod OTP idzie w polu `password`!).
- `POST api/fido/register` **wymaga** `authenticatorSelection` (bez niego 500), `attestation:"none"`, alg ES256 (-7), `rpId="https://sso.play.pl"` (origin = ten sam string).
- Sesja: cookies domenowe `.play.pl` (`access-token`/`refresh-token` JWE) ustawiane przez `fido/authenticate/finish` — działają też na bramce.
- Gateway `{userId}` = **msisdn z prefiksem 48** (np. `48500100200`), `accessLevel: MSISDN`.

> Alternatywne drogi logowania odkryte podczas RE (autoryzacja po IP z sieci Play `oauth/authorize-ip`,
> wstrzyknięcie cookies/tokenu z podsłuchu, SSO hasłem) są opisane w `API.md §2` — klient CLI celowo
> standaryzuje na passkey (jedna spójna ścieżka, działa wszędzie).

## Wiele numerów — dwa modele

Play24 rozróżnia dwa przypadki (klient obsługuje oba):

### A) Osobne konta (różni właściciele) — `accounts` + `--msisdn`/`use` ⭐ zweryfikowane
Każdy numer to osobne konto/profil z własnym passkey (np. numery różnych osób w rodzinie).
Onboardujesz każdy numer raz, a potem wskazujesz, którego dotyczy komenda (`--msisdn` albo `use`):
```bash
uv run play24 register-start --msisdn <NUMER>   # + register-otp (raz na numer)
uv run play24 accounts                          # lista lokalnych kont (* = domyślne)
uv run play24 summary --msisdn 500100200        # dane tego konta (logowanie passkeyem auto)
uv run play24 use 500100201                     # ustaw inne konto jako domyślne
uv run play24 summary                           # dotyczy domyślnego
```
Każda komenda loguje passkey'em wskazanego numeru (osobny `profileId`, świeża sesja). Tak działa
zarządzanie numerami należącymi do **różnych** kont.

### B) Jedno konto, wiele numerów — `numbers` + `switch`
Jeśli do JEDNEGO konta podpięto kilka numerów, przełączasz numer w obrębie tej samej sesji:
```bash
uv run play24 numbers --msisdn <NUMER_KONTA>   # lista numerów na koncie
uv run play24 switch 48xxxxxxxxx               # przełącz numer (msisdn-switch → nowy token) + pokaż saldo
```
`switch` przełącza w obrębie jednego konta. `{userId}` bramki = msisdn z prefiksem 48; przełączanie
re-issuuje token sesji scoped na wybrany numer. (Próba przełączenia na numer spoza konta → `MP0038`.)

### Jak AUTORYZOWAĆ (dodać) nowy numer do konta
`switch` działa tylko dla numerów już podpiętych. Żeby dodać nowy numer, musisz **udowodnić, że go
posiadasz** — kodem SMS wysłanym na ten numer (to ta sama bramka KYC co przy onboardingu; nie ma obejścia,
to zabezpieczenie). Robisz to onboardingiem dla nowego numeru:
```bash
uv run play24 register-start --msisdn <NOWY_NUMER>              # SMS na nowy numer
uv run play24 register-otp --msisdn <NOWY_NUMER> --code XXXX    # dowód posiadania
```
Ponieważ jesteś już zalogowany, `register-start` dołącza Twój istniejący profil do `find-handlers`
(`userHandles=[profileId]`) — zgodnie z flow „Dodaj numer" (`UpgradeOnboarding.ADD`) w apce — więc nowy
numer **przypina się do tego samego konta**. Potem `numbers` go pokaże, a `switch` przełączy.
> ⚠️ Ten dokładny krok (przypięcie 2. numeru do istniejącego profilu) nie był testowany na żywo — konto
> testowe ma jeden numer. Format żądań jest zgodny z apką; finalna walidacja wymaga realnego 2. numeru.

## Komendy
```
uv run play24 summary            # skrót: saldo, ważność konta, GB (krajowe/roaming), minuty, pakiety
uv run play24 accounts           # lokalne konta (osobne profile); ustaw domyślny: use <msisdn>
uv run play24 use <msisdn>       # ustaw domyślny numer (potem --msisdn opcjonalny)
uv run play24 numbers            # numery na koncie (jedno konto, wiele numerów)
uv run play24 switch <msisdn>    # przełącz numer w obrębie jednego konta
uv run play24 packages           # pakiety/usługi + daty odnowienia/wygaśnięcia (--all = katalog + id + cena, --json)
uv run play24 activate <id>      # WŁĄCZ pakiet (POST ms-services/v1/components → 409 SCA → step-up passkey → retry); ACTIVATION.md
uv run play24 deactivate <id>    # WYŁĄCZ pakiet
uv run play24 balance            # saldo główne (POST ms-balances/v3/balances/{userId}/main)
uv run play24 balances-all       # wszystkie liczniki/pakiety
uv run play24 counters           # liczniki (dane/minuty/SMS) z wyliczonymi GB/min
uv run play24 offers             # oferty
uv run play24 finances           # podsumowanie finansów
uv run play24 invoices           # faktury / dokumenty
uv run play24 account            # dane konta/klienta
uv run play24 components         # usługi / komponenty taryfy (surowo)
uv run play24 notifications      # powiadomienia
uv run play24 history            # historia aktywności
uv run play24 sim                # informacje o SIM
uv run play24 whoami             # lokalny stan (profile, domyślny numer)
```
Każda komenda przyjmuje `--msisdn`, a saldo dodatkowo `--kind`/`--type` (domyślnie `VOICE`/`PREPAID`).

### Dowolny endpoint
```bash
uv run play24 raw GET  ms-finances v4 finances/{userId}/info
uv run play24 raw POST ms-balances v3 balances/{userId}/main --body '{"serviceKind":"VOICE","serviceType":"PREPAID"}'
```
`{userId}` jest podstawiany automatycznie (msisdn z prefiksem 48).

## Jak przechwycić token / dokładny format (mitmproxy)

Statyka daje strukturę; ostatnie 5% (dokładne pola POST `oauth/access_token`, kształt JSON
odpowiedzi) najłatwiej potwierdzić jednym podsłuchem oficjalnej apki:

1. Zainstaluj mitmproxy: `pipx install mitmproxy` (lub `pip install mitmproxy`).
2. `mitmweb --listen-port 8080` — na PC; zapisz cert CA z `http://mitm.it`.
3. Na telefonie (Android): ustaw proxy WiFi na IP PC:8080, zainstaluj cert CA jako **systemowy**
   (wymaga roota lub `/system` z Magisk; user-cert nie wystarczy od Androida 7+).
4. **Cert pinning**: apka pinuje certy `*.play.pl` (8 SHA256, patrz `API.md §2.3`).
   Aby podsłuchać apkę, trzeba obejść pinning — najprościej **Frida** + skrypt
   `frida-multiple-unpinning`, albo `objection`. Dla samego *logowania* tokenu czasem wystarczy
   przechwycić ruch zaraz po logowaniu z gotowym tokenem w nagłówku `Authorization`.
5. W mitmweb filtruj `play24-cloud.play.pl` → podejrzyj nagłówki/ciało żądań, by potwierdzić
   dokładny format. (CLI standaryzuje na passkey; ręczne wstrzyknięcie tokenu/cookies opisuje `API.md §2`.)

Alternatywa bez roota/pinningu: zaloguj się na [24.play.pl](https://24.play.pl) w przeglądarce
i podejrzyj token w DevTools → Network (web używa zbliżonego backendu OAuth).

## Użycie jako biblioteka (`play24lib`)

Do skryptów (np. monitoring w cron). Wymaga wcześniejszego onboardingu numeru przez CLI
(`play24.py register-start` + `register-otp`) — to zapisuje profil + passkey w `~/.play24/`.

```python
from play24lib import Play24

p = Play24("48500100200").login()      # logowanie passkeyem (FIDO2)
s = p.summary()                        # zwięzłe dane do progów
print(s["balance_pln"], s["balance_unit"])      # np. 13.51 PLN
print(s["account_expires"], s["account_expires_days"])
print(s["data_gb"], "GB |", s["minutes"], "min")
for pkg in s["packages"]:              # aktywne pakiety + daty
    print(pkg["title"], pkg["activationDate"], pkg["expirationDate"], pkg["nextApplyDate"])

# dane surowe też dostępne:
p.balance(); p.account(); p.counters(); p.packages()
```

`summary()` zwraca m.in.: `balance_pln`, `account_expires(_days)`, `data_gb` (**tylko krajowe**),
`data_gb_roaming`, `minutes`, `counters[]`, `packages[]` (każdy z `paid`/`price_pln`/`cyclic`),
`package_expire_days`, `package_renew_days`. Helpery: `parse_amount`, `to_gb`, `to_minutes`,
`days_until`, `package_status`.

### Gotowy monitor do crona — `examples/monitor.py`
Buduje **kolorowy status** konta i **wysyła go na Telegram TYLKO gdy jest 🔴** (wtedy raport
zawiera pełny status). Legenda: 🟢 OK · 🟠 uwaga (blisko progu = 2× próg) · 🔴 reaguj
(próg przekroczony) · ⚪ brak danych. Sprawdza: saldo, ważność konta, GB, minuty oraz
**tylko płatne pakiety** (`price>0`) — cykliczne *kiedy się odnowią*, jednorazowe *kiedy
wygasną*; darmowe usługi/limity pomijane. `exit≠0` gdy 🔴 (cron wyśle też maila).
Opcjonalny `label` w configu dopisuje opis do numeru. Przykładowy raport:
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

Konfiguracja w **`~/.play24/monitor.json`** (poza repo — sekrety i numery; wzór:
`examples/monitor.config.example.json`). Model: **nazwane notyfikatory** (globalnie, z `type`)
+ per numer **dowolnie wiele sekcji alertów** (własne progi → na wskazane notyfikatory):
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

Wyżej: *admin* dostaje tylko poważne (saldo <5 zł / koniec konta <7 dni), a *domownik* — czulsze
progi (saldo <20 zł, dane <1 GB) na swój własny Telegram. Niezależnie, każdy ze swoimi progami.
```bash
cp examples/monitor.config.example.json ~/.play24/monitor.json   # i uzupełnij
uv run python examples/monitor.py
# cron (codziennie 9:00):
# 0 9 * * *  cd /sciezka/do/repo && uv run python examples/monitor.py >> ~/.play24/monitor.log 2>&1
```
> Token bota Telegram i numery trzymaj **tylko** w `~/.play24/monitor.json` — `.gitignore`
> blokuje `monitor.json`, ale i tak nigdy nie commituj sekretów.

## Użycie w agentach AI (skill / MCP)
Trzy warstwy integracji — od najprostszej:
1. **Biblioteka** — agent w Pythonie: `from play24lib import Play24; Play24(n).login().summary()`.
2. **JSON-owe CLI** (`play24_json.py`, read-only) — agent „shell-uje" i parsuje JSON ze stdout:
   ```bash
   uv run play24-json summary --msisdn 48XXXXXXXXX
   # {"ok": true, "cmd": "summary", "msisdn": "...", "data": { "balance_pln": 6.47, ... }}
   ```
   Kontrakt: `{"ok":true,"data":{...}}` / `{"ok":false,"error":"..."}`, kod wyjścia 0/1.
   Komendy: `accounts`, `summary`, `balance`, `counters`, `packages`, `account`.
3. **MCP** (`play24_mcp.py`) — najnatywniej dla agentów (typowane narzędzia). Udostępnia **pełny**
   protokół: odczyty, onboarding (`register_start`/`register_complete`), `numbers`/`switch` oraz
   `activate`/`deactivate`. Uruchom `uv run play24-mcp` (stdio) i wskaż w kliencie MCP:
   ```json
   { "mcpServers": { "play24": { "command": "uv",
       "args": ["run", "--directory", "/ABS/play24", "play24-mcp"] } } }
   ```

[`SKILL.md`](SKILL.md) to gotowy manifest skilla (`name` + `description` „kiedy użyć” + instrukcje).
Operacje płatne (`activate`) wymagają potwierdzenia ceny z człowiekiem — w JSON-CLI ich **nie ma**;
w MCP są, ale opisane jako kosztowne. Pełny krok po kroku: [QUICKSTART.md](QUICKSTART.md).

## Pliki w repo
- `play24lib.py` — **rdzeń**: cały protokół (klasa `Play24` + onboarding/store/parsery + autentykator WebAuthn/FIDO2)
- `play24.py` — klient CLI (cienka warstwa nad `play24lib`)
- `play24_json.py` — JSON-owe CLI (read-only) dla agentów AI
- `play24_mcp.py` — serwer MCP (pełny protokół jako narzędzia)
- `pyproject.toml` — projekt/zależności/skrypty (`uv`); `QUICKSTART.md` — szybki start
- `CHANGELOG.md` — historia zmian
- `SKILL.md` — manifest skilla (dla agentów AI)
- `examples/monitor.py` — przykładowy monitor progów do crona
- `API.md` — dokumentacja rozpracowanego API (hosty, mikroserwisy, auth)
- `ACTIVATION.md` — recepta na aktywację pakietów (flow SCA/step-up)
- `endpoints.txt` — pełna lista endpointów (metoda + ścieżka)
- `METHODS.md` — jakie techniki RE zostały użyte
- `CLAUDE.md` — zwięzły kontekst projektu (szybki powrót do tematu)
- `re/` — narzędzia reverse-engineeringu (skrypt Frida-unpinning, runner)

> Repo zawiera wyłącznie własny kod i dokumentację. **Nie zawiera** APK, dekompilatu
> ani żadnych danych konta — to materiały objęte prawami autorskimi / dane osobowe.

## Status

Klient jest wynikiem reverse-engineeringu i edukacyjnym dowodem działania (interoperacyjność).
Nieoficjalny, niezwiązany z P4 sp. z o.o. Używaj wyłącznie do **własnego** konta i na własną odpowiedzialność.


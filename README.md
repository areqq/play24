# play24 — nieoficjalny klient API Play24

Rozpracowane API self-care **Play24** (`com.play.play24m`) + narzędzia w Pythonie do zarządzania
kontem bez oficjalnej apki. Reverse-engineering APK v11.9.0 (statyka + podsłuch).

## Co to potrafi (w skrócie)
- 📱 **Klient CLI** (`play24.py`) — saldo, pakiety, faktury, dane konta, historia, SIM, dowolny endpoint.
- 🔑 **Logowanie od zera bez apki** — onboarding numeru kodem SMS, własny **passkey FIDO2** (klucz w pliku),
  logowanie na dowolnej sieci. Obsługa **wielu kont/numerów** i przełączania.
- 🛒 **Włączanie/wyłączanie pakietów** — z autoryzacją operacji (SCA/PIN) jak w apce.
- 🧩 **Biblioteka** (`play24lib.py`) — `Play24(numer).login().summary()` zwraca saldo, ważność konta,
  GB (krajowe/roaming), minuty, pakiety (z datami odnowienia/wygaśnięcia).
- 🔔 **Monitor do crona** (`examples/monitor.py`) — pilnuje progów (saldo, ważność konta/pakietów,
  GB, minuty) dla wielu numerów i śle **kolorowe** alerty 🟢🟠🔴 na **nazwane notyfikatory** (Telegram).
- 🤖 **Gotowe do agentów AI** — JSON-owe CLI (`play24_json.py`, read-only) + `SKILL.md` (manifest skilla).
- 📖 **Dokumentacja RE** — [`API.md`](API.md), [`ACTIVATION.md`](ACTIVATION.md),
  [`endpoints.txt`](endpoints.txt), [`METHODS.md`](METHODS.md).

> ⚠️ Nieoficjalne. Używaj wyłącznie do **własnego konta**. To self-care operatora — nic nie atakuje,
> jedynie odtwarza to, co robi oficjalna apka.

## Wymagania
```bash
python3 -m pip install requests
```

> **Sesja jest cookie-based** (jak w apce — globalny CookieManager), nie `Bearer`. Klient trzyma
> cookie jar w `~/.play24/session.json`. Szczegóły: `API.md §2`.

## Uwierzytelnianie — drogi

### 1. ⭐ ZALECANE — podpięcie numeru OD ZERA (FIDO2/passkey, dowolna sieć)
**Działa na każdej sieci (WiFi też), nie wymaga hasła ani przechwytywania.** Rejestrujesz własny
passkey (WebAuthn) przez weryfikację kodem SMS; klient jest własnym autentykatorem (klucz EC P-256
w `~/.play24/passkey_<msisdn>.json`). Zweryfikowane na żywo.
```bash
./play24.py register-start --msisdn 48xxxxxxxxx   # wyśle SMS (numer 9-cyfrowy też OK)
# (przychodzi 4-cyfrowy kod SMS)
./play24.py register-otp --code 1234              # weryfikuje kod + rejestruje passkey
# ✅ numer podpięty. Kolejne logowania (dowolna sieć, bez SMS):
./play24.py auth --msisdn 48xxxxxxxxx             # logowanie passkeyem → sesja
./play24.py balance                               # i już działają dane konta
```
Po onboardingu kolejne uruchomienia (CLI i biblioteka) logują się **samym passkeyem** — bez SMS.
Szczegóły protokołu (patrz `API.md §2`):
- `kyc/register?hint=MSISDN_OTP_REQUIRED` `{type:STANDARD,input:msisdn}` → SMS; kod → `PUT kyc/register/{nonce} {password:<kod>}` (kod OTP idzie w polu `password`!).
- `POST api/fido/register` **wymaga** `authenticatorSelection` (bez niego 500), `attestation:"none"`, alg ES256 (-7), `rpId="https://sso.play.pl"` (origin = ten sam string).
- Sesja: cookies domenowe `.play.pl` (`access-token`/`refresh-token` JWE) ustawiane przez `fido/authenticate/finish` — działają też na bramce.
- Gateway `{userId}` = **msisdn z prefiksem 48** (np. `48500100200`), `accessLevel: MSISDN`.

### 2. `login-ip` — autoryzacja po IP (tylko z sieci mobilnej Play)
Bramka rozpoznaje numer po IP transmisji danych — bez PIN-u i SMS, ale **musisz być na internecie
mobilnym Play** (nie WiFi; żądanie przez GGSN operatora). Z zewnątrz serwer zwraca
`access_denied ... GGSN server name pattern` (potwierdza poprawność flow — brak tylko sieci Play).
```bash
./play24.py login-ip --msisdn 48500100200 --user-id <ID_ABONENTA>
```

### 3. `--cookie` / `--token` — wstrzyknięcie sesji (dowolna sieć)
Przechwyć **cookies** sesji (lub token) z apki (mitmproxy, patrz niżej) — gdy nie chcesz onboardingu:
```bash
./play24.py --cookie "access-token=...; SSOWWW_SESSION_PROD=..." --user-id 48xxxxxxxxx balance
```
Sesja zapisuje się w `~/.play24/session.json` (chmod 600) — kolejne komendy już bez flag.

### 4. `login` — hasłem (EKSPERYMENTALNE, SSO)
Odtwarza kroki SSO `find-handlers → kyc/register` (podanie hasła). Kroki authorize/direct + OTP
wymagają pól `hash`/`operationId` — komenda wypisuje surowe odpowiedzi serwera. Patrz `API.md §2.1.B`.
```bash
./play24.py login --msisdn 48xxxxxxxxx --user-id <ID_ABONENTA>   # zapyta o hasło
```

## Wiele numerów — dwa modele

Play24 rozróżnia dwa przypadki (klient obsługuje oba):

### A) Osobne konta (różni właściciele) — `accounts` + `auth` ⭐ zweryfikowane
Każdy numer to osobne konto/profil z własnym passkey (np. numery różnych osób w rodzinie).
Onboardujesz każdy numer raz, a potem przełączasz aktywne konto logowaniem:
```bash
./play24.py register-start --msisdn <NUMER>   # + register-otp (raz na numer)
./play24.py accounts                          # lista lokalnych kont (* = aktywne)
./play24.py auth --msisdn 500100200           # zaloguj/przełącz na to konto
./play24.py balance                           # dane tego konta
./play24.py auth --msisdn 500100201           # przełącz na inne konto
```
`auth` czyści sesję i loguje passkey'em danego numeru (osobny `profileId`). Tak działa zarządzanie
numerami należącymi do **różnych** kont.

### B) Jedno konto, wiele numerów — `numbers` + `switch`
Jeśli do JEDNEGO konta podpięto kilka numerów, logujesz się raz i przełączasz numer bez ponownego logowania:
```bash
./play24.py numbers              # lista numerów na aktywnym koncie (* = aktywny)
./play24.py switch 48xxxxxxxxx   # przełącz aktywny numer (msisdn-switch → nowy token sesji)
./play24.py balance              # od teraz dotyczy przełączonego numeru
```
`switch` przełącza w obrębie jednego konta. `{userId}` bramki = msisdn z prefiksem 48; przełączanie
re-issuuje token sesji scoped na wybrany numer. (Próba przełączenia na numer spoza konta → `MP0038`.)

### Jak AUTORYZOWAĆ (dodać) nowy numer do konta
`switch` działa tylko dla numerów już podpiętych. Żeby dodać nowy numer, musisz **udowodnić, że go
posiadasz** — kodem SMS wysłanym na ten numer (to ta sama bramka KYC co przy onboardingu; nie ma obejścia,
to zabezpieczenie). Robisz to onboardingiem dla nowego numeru:
```bash
./play24.py register-start --msisdn <NOWY_NUMER>   # SMS na nowy numer
./play24.py register-otp --code XXXX               # dowód posiadania
```
Ponieważ jesteś już zalogowany, `register-start` dołącza Twój istniejący profil do `find-handlers`
(`userHandles=[profileId]`) — zgodnie z flow „Dodaj numer" (`UpgradeOnboarding.ADD`) w apce — więc nowy
numer **przypina się do tego samego konta**. Potem `numbers` go pokaże, a `switch` przełączy.
> ⚠️ Ten dokładny krok (przypięcie 2. numeru do istniejącego profilu) nie był testowany na żywo — konto
> testowe ma jeden numer. Format żądań jest zgodny z apką; finalna walidacja wymaga realnego 2. numeru.

## Komendy
```
./play24.py accounts           # lokalne konta (osobne profile) — przełączasz przez auth --msisdn
./play24.py numbers            # numery na aktywnym koncie (jedno konto, wiele numerów)
./play24.py switch <msisdn>    # przełącz numer w obrębie jednego konta
./play24.py packages           # aktywne pakiety/usługi + daty aktywacji/odnowienia (--all = cały katalog + id)
./play24.py activate <id>      # WŁĄCZ pakiet (POST ms-services/v1/components → 409 SCA → step-up passkey → retry); szczegóły: ACTIVATION.md
./play24.py deactivate <id>    # WYŁĄCZ pakiet
./play24.py balance            # saldo główne (POST ms-balances/v3/balances/{userId}/main)
./play24.py balances-all       # wszystkie liczniki/pakiety
./play24.py offers             # oferty
./play24.py finances           # podsumowanie finansów
./play24.py invoices           # faktury / dokumenty
./play24.py account            # dane konta/klienta
./play24.py components         # usługi / komponenty taryfy
./play24.py notifications      # powiadomienia
./play24.py history            # historia aktywności
./play24.py sim                # informacje o SIM
./play24.py whoami             # pokaż zapisaną sesję
```
Saldo: domyślnie `--kind VOICE --type POSTPAID`. Dla prepaid: `./play24.py --type PREPAID balance`.

### Dowolny endpoint
```bash
./play24.py raw GET  ms-finances v4 finances/{userId}/info
./play24.py raw POST ms-balances v3 balances/{userId}/main --body '{"serviceKind":"VOICE","serviceType":"POSTPAID"}'
```
`{userId}` jest podstawiany automatycznie z sesji.

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
5. W mitmweb filtruj `play24-cloud.play.pl` → skopiuj `Authorization: Bearer ...` i `{userId}`
   z dowolnego żądania. Podaj je do `play24.py --token ... --user-id ...`.

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
python3 examples/monitor.py
# cron (codziennie 9:00):
# 0 9 * * *  cd /sciezka/do/repo && /usr/bin/python3 examples/monitor.py
```
> Token bota Telegram i numery trzymaj **tylko** w `~/.play24/monitor.json` — `.gitignore`
> blokuje `monitor.json`, ale i tak nigdy nie commituj sekretów.

## Użycie w agentach AI (skill)
Trzy warstwy integracji — od najprostszej:
1. **Biblioteka** — agent w Pythonie: `from play24lib import Play24; Play24(n).login().summary()`.
2. **JSON-owe CLI** (`play24_json.py`, read-only) — agent „shell-uje" i parsuje JSON ze stdout:
   ```bash
   python3 play24_json.py summary --msisdn 48XXXXXXXXX
   # {"ok": true, "cmd": "summary", "msisdn": "...", "data": { "balance_pln": 6.47, ... }}
   ```
   Kontrakt: `{"ok":true,"data":{...}}` / `{"ok":false,"error":"..."}`, kod wyjścia 0/1.
   Komendy: `accounts`, `summary`, `balance`, `counters`, `packages`, `account`.
3. **MCP** — najnatywniej dla agentów (typowane narzędzia); do dołożenia w razie potrzeby.

[`SKILL.md`](SKILL.md) to gotowy manifest skilla (`name` + `description` „kiedy użyć” + instrukcje) —
wystarczy wskazać go agentowi. Operacje płatne (`activate`) celowo **nie** są w JSON-CLI (wymagają
potwierdzenia człowieka) — patrz `play24.py activate` / `ACTIVATION.md`.

## Pliki w repo
- `play24.py` — klient CLI
- `play24lib.py` — biblioteka (klasa `Play24`) do użycia w skryptach
- `play24_json.py` — JSON-owe CLI (read-only) dla agentów AI
- `SKILL.md` — manifest skilla (dla agentów AI)
- `examples/monitor.py` — przykładowy monitor progów do crona
- `play24_passkey.py` — software'owy autentykator WebAuthn/FIDO2
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


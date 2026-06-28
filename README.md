# play24-cli — nieoficjalny klient CLI do Play24

Prosty klient wiersza poleceń do API aplikacji **Play24** (`com.play.play24m`), powstały z
**statycznej analizy APK v11.9.0**. Pełna dokumentacja API: [`API.md`](API.md),
lista endpointów: [`endpoints.txt`](endpoints.txt).

> ⚠️ Narzędzie nieoficjalne. Używaj wyłącznie do **własnego konta**. To self-care operatora —
> nie atakuje żadnej infrastruktury, jedynie odtwarza to, co robi oficjalna apka.

## Wymagania
```bash
python3 -m pip install requests
```

> **Sesja jest cookie-based** (jak w apce — globalny CookieManager), nie `Bearer`. Klient trzyma
> cookie jar w `~/.play24/session.json`. Szczegóły: `API.md §2`.

## Uwierzytelnianie — drogi

### 1. `login-ip` — autoryzacja po IP (najprostsza, ale tylko w sieci Play)
Bramka Play rozpoznaje Twój numer po adresie IP transmisji danych — bez PIN-u i SMS.
**Musisz być na aktywnym internecie mobilnym Play** (nie WiFi). Żądanie musi przejść przez
GGSN operatora; z zewnątrz serwer odpowiada `access_denied ... GGSN server name pattern`
(to potwierdza, że flow jest poprawny — brakuje tylko sieci Play).
```bash
./play24.py login-ip --msisdn 48500100200 --user-id <ID_ABONENTA>
```

### 2. `login` — hasłem (EKSPERYMENTALNE, SSO)
Odtwarza kroki SSO `find-handlers → kyc/register → kyc/register/{nonce}` (podanie hasła).
Zweryfikowane na żywo (serwer poprawnie parsuje żądania). Kroki authorize/direct + OTP wymagają
pól `hash`/`operationId`, których nie da się ustalić statycznie — komenda wypisuje surowe
odpowiedzi serwera, byś mógł je dograć. Patrz `API.md §2.1.B`.
```bash
./play24.py login --msisdn 48xxxxxxxxx --user-id <ID_ABONENTA>   # zapyta o hasło
```

### 3. `--cookie` / `--token` — wstrzyknięcie sesji (dowolna sieć)
Najpewniejsza droga. Przechwyć **cookies** sesji (lub token) z apki (mitmproxy, patrz niżej):
```bash
./play24.py --cookie "JSESSIONID=...; SESSION=..." --user-id 12345678 balance
./play24.py --token "..." --user-id 12345678 balance     # gdyby któryś endpoint używał tokenu
```
Sesja zapisuje się w `~/.play24/session.json` (chmod 600) — kolejne komendy już bez flag.

### 4. ⭐ Podpięcie numeru OD ZERA (FIDO2/passkey, dowolna sieć) — ZWERYFIKOWANE NA ŻYWO
Rejestracja własnego passkey (WebAuthn) przez weryfikację kodem SMS — działa poza siecią Play.
Klient pełni rolę autentykatora (klucz EC P-256 w `~/.play24/passkey_<msisdn>.json`).
```bash
./play24.py register-start --msisdn 48xxxxxxxxx   # wyśle SMS (numer 9-cyfrowy też OK)
# (przychodzi 4-cyfrowy kod SMS)
./play24.py register-otp --code 1234              # weryfikuje kod + rejestruje passkey
# ✅ numer podpięty. Kolejne logowania (dowolna sieć):
./play24.py auth --msisdn 48xxxxxxxxx             # logowanie passkeyem → sesja
./play24.py balance                               # i już działają dane konta
```
Szczegóły protokołu i niuanse (patrz `API.md §2`):
- `kyc/register?hint=MSISDN_OTP_REQUIRED` `{type:STANDARD,input:msisdn}` → SMS; kod → `PUT kyc/register/{nonce} {password:<kod>}` (kod OTP idzie w polu `password`!).
- `POST api/fido/register` **wymaga** `authenticatorSelection` w body (bez niego 500), `attestation:"none"`, alg ES256 (-7), `rpId="https://sso.play.pl"` (origin = ten sam string).
- Sesja: cookies domenowe `.play.pl` (`access-token`/`refresh-token` JWE) ustawiane przez `fido/authenticate/finish` — działają też na bramce.
- Gateway `{userId}` = **msisdn z prefiksem 48** (np. `48500100200`), `accessLevel: MSISDN`.

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

`summary()` zwraca m.in.: `balance_pln`, `account_expires(_days)`, `data_gb`, `minutes`,
`counters[]`, `packages[]`, `package_expire_days`, `package_renew_days`. Helpery:
`parse_amount`, `to_gb`, `to_minutes`, `days_until`.

### Gotowy monitor do crona — `examples/monitor.py`
Pilnuje progów (saldo, ważność konta, GB, minuty, wiek pakietu od aktywacji, bliskość
wygaśnięcia/odnowienia), wypisuje ostrzeżenia, **wysyła powiadomienie na Telegram** gdy są
alerty i kończy kodem ≠0 (cron wyśle też maila).

Konfiguracja w **`~/.play24/monitor.json`** (poza repo — sekrety i numery; wzór:
`examples/monitor.config.example.json`):
```json
{
  "telegram": { "bot_token": "123456:ABC-...", "chat_id": "123456789", "insecure": false },
  "watch": { "48XXXXXXXXX": { "min_pln": 5.0, "min_gb": 0.5, "min_minutes": 10, "account_days": 14,
                              "package_renew_days": 3, "package_expire_days": 3, "package_validity_days": 31 } }
}
```
```bash
cp examples/monitor.config.example.json ~/.play24/monitor.json   # i uzupełnij
python3 examples/monitor.py
# cron (codziennie 9:00):
# 0 9 * * *  cd /sciezka/do/repo && /usr/bin/python3 examples/monitor.py
```
> Token bota Telegram i numery trzymaj **tylko** w `~/.play24/monitor.json` — `.gitignore`
> blokuje `monitor.json`, ale i tak nigdy nie commituj sekretów.

## Pliki w repo
- `play24.py` — klient CLI
- `play24lib.py` — biblioteka (klasa `Play24`) do użycia w skryptach
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


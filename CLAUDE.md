# CLAUDE.md — kontekst projektu (Play24 CLI, reverse-engineering)

Plik dla asystenta, by szybko wrócić do tematu mając tylko to repo. Wszystko poniżej pochodzi
z reverse-engineeringu apki **Play24** (`com.play.play24m`, v11.9.0, build Miquido `com.miquido.play360`).
Repo jest **publiczne i zanonimizowane** — nie commituj danych konta (numery/tokeny/passkey/APK).

## Co to jest
Nieoficjalny klient CLI (Python, stdlib + `requests` + `cryptography`) do self-care API Play24:
odczyt salda/pakietów/faktur/konta, wiele numerów, oraz włączanie/wyłączanie pakietów.

## Architektura API
- **API główne (self-care):** `https://play24-cloud.play.pl/cloud/play24/gateway/{ms}/v{N}/{ścieżka}`
- **SSO/logowanie:** `https://login-cloud.play.pl/cloud/sso-customers/gateway/sso-mobile/`
- **OAuth:** `https://oauth.play.pl/oauth/` (client_id=`play24_app`, redirect `https://firebase.play.pl/oauth-callback/`)
- **Mikroserwisy** (nazwa + wersja): ms-balances v3, ms-offers v12, ms-finances v4, ms-clients v3,
  ms-components v8 (ODCZYT katalogu), **ms-services v1** (ZAPIS/modyfikacja komponentów), ms-payments v6,
  ms-activities v2, ms-sim v2, ms-notifications v4, ms-appinfo v1 … (pełny katalog: `endpoints.txt`, `API.md`).
- **Gateway `{userId}` = msisdn z prefiksem 48** (np. `48XXXXXXXXX`), `accessLevel: MSISDN`.

## Auth (najważniejsze)
- **Sesja jest COOKIE-based, NIE Bearer.** Globalny CookieManager w apce; cookies domenowe `.play.pl`
  (`access-token`/`refresh-token` JWE + `SSOWWW_*`) ustawiane przez `fido/authenticate/finish` działają
  też na bramce. Klient MUSI trzymać cookie jar.
- **Logowanie = FIDO2/WebAuthn passkey** (alg ES256/-7, attestation `none`, rpId `https://sso.play.pl`,
  origin = rpId). Klient jest własnym autentykatorem (klucz EC P-256 w pliku zamiast Android Keystore).
- **Onboarding numeru:** `POST sso-mobile/api/standard/find-handlers/{msisdn}` → `POST api/kyc/register?hint=MSISDN_OTP_REQUIRED`
  `{type:STANDARD,input:msisdn}` (SMS, kod 4-cyfr) → `PUT api/kyc/register/{nonce} {password:<KOD_SMS>}`
  (**kod OTP idzie w polu `password`**) → requiredAction `FINISH_FIDO` →
  `POST api/fido/register {nonce,identifier:<msisdn>,attestation:"none",authenticatorSelection:{platform,requireResidentKey:true,userVerification:required}}`
  (**authenticatorSelection WYMAGANE** — bez niego 500) → makeCredential → `POST api/fido/register/finish` → ProfileDto.
- **Logowanie passkeyem:** `POST api/fido/authenticate {profileId,authenticatorSelection}` → AuthenticateOptions
  (challenge, allowCredentials) → podpis → `POST api/fido/authenticate/finish` → cookies sesji.
- Refresh tokenu na 401: `DELETE api/fido/token/refresh/{profileId}/{userId}` + retry z `X-Retry-Disallowed: true`.

## Aktywacja pakietu (write transakcyjny + SCA) — patrz ACTIVATION.md
- **Endpoint: `POST ms-services/v1/components/{userId}`** (NIE ms-components/v8). Brak nagłówka OperationToken.
- Nagłówki wymagane przez bramkę: **`OS-Type: android`, `OS-Version: 33`**, App-Version, cookies.
- Body: `{type:ACTIVATE|DEACTIVATE, componentId, componentType, params:[], email, otp:null, operationId:null}`.
- Flow SCA: POST → **409 `MP0174`** `{operationId, hash(sha512), acrType:FIDO}` → step-up
  `POST/PUT api/standard/{profileId}/authorize/direct` (FIDO, nagłówki Device-Id/Manufacturer/Model;
  characteristic start: challenge/public-key=credId/rpId/timeout; finish: id/clientDataJSON/authenticatorData/signature)
  → `action:TOKEN` → ponów POST components z `operationId` z 409 → sukces.
- Aktywne pakiety mają w `ms-components` pola `activationDate`/`nextApplyDate`/`expirationDate`/`cyclicType`.

## Wiele numerów
- **Osobne konta** (różni właściciele): każdy numer = własny passkey/profil; przełączanie = `auth --msisdn`
  (czyści cookie jar, bierze profile_id z metadanych numeru — inaczej cross-account 401).
- **Jedno konto, wiele numerów:** `GET api/standard/{profileId}/msisdn/list` + `POST api/standard/{profileId}/token/msisdn-switch/{msisdn}`.

## Mapa plików
- `play24lib.py` — **RDZEŃ** (cały protokół, brak duplikacji): klasa `Play24(msisdn).login()` +
  `summary()/balance()/balances_all()/counters()/packages()/account()/numbers()/switch()/activate()/deactivate()/raw()`;
  funkcje modułu `register_start/register_complete/accounts/load_store/save_store/build_headers/webauthn_login`
  i helpery (`parse_amount`, `to_gb`, `to_minutes`, `days_until`, `package_status`). Loguje passkeyem z `~/.play24/`.
  **Zawiera też autentykator WebAuthn/FIDO2** (`Passkey`, `make_credential`, `get_assertion`, `cbor`, `b64`) —
  wcześniej osobny `play24_passkey.py`, teraz wbudowany (EC P-256, mini-CBOR, base64 NO_WRAP).
- `play24.py` — **cienki** CLI nad `play24lib` (komendy: register-start/otp, accounts, use, numbers, switch,
  summary, balance, balances-all, counters, offers, finances, invoices, account, components, packages,
  activate/deactivate, notifications, history, sim, raw, whoami). Logowanie passkeyem przy każdej komendzie (brak `auth`).
- `play24_json.py` — JSON-owe CLI (read-only) dla agentów AI; `SKILL.md` — manifest skilla.
- `play24_mcp.py` — serwer MCP (FastMCP, stdio): PEŁNY protokół jako narzędzia `play24_*` (odczyty +
  onboarding + numbers/switch + activate/deactivate) + zasób `play24://accounts`.
- `pyproject.toml` — uv: zależności (requests, cryptography; extra `mcp`) + skrypty `play24`/`play24-json`/`play24-mcp`.
- `QUICKSTART.md` — szybki start (uv, onboarding, CLI/JSON/lib/MCP, cron).
- `examples/monitor.py` — przykładowy monitor progów do crona (saldo/ważność/GB/minuty/pakiety; exit≠0 przy alarmie).
- `API.md` / `ACTIVATION.md` / `endpoints.txt` — dokumentacja.
- `METHODS.md` — techniki RE. `re/unpin.js` + `re/frida_run.py` — narzędzia dynamiki.
- Środowisko: `uv sync` (+`--extra mcp`); komendy przez `uv run …`.
- Sesja runtime (NIE w repo): `~/.play24/session.json` (profiles + device_id + active; NIE cookies)
  + `~/.play24/passkey_<48msisdn>.json`.

## Jak wrócić do głębszej analizy (repo nie zawiera APK)
1. Pobierz APK Play24 (XAPK z mirrora), rozpakuj splity, `jadx -d out base.apk`.
2. Dekoder adnotacji Retrofit i mapowanie klas — patrz METHODS.md.
3. Dynamika: ReDroid (Android w kontenerze) + `re/unpin.js` (Frida) + mitmproxy; sterowanie `adb`.

## Gotchas
- OkHttp/Retrofit są zobfuskowane R8 — adnotacje i klasy mają krótkie nazwy (np. CertificatePinner=`okhttp3.b`).
- ms-components (odczyt) ≠ ms-services (zapis) — pomyłka = 401.
- Cert pinning (8× SHA256 dla `*.play.pl`) dotyczy tylko apki; własny klient łączy się normalnie.
- Auth po IP (`oauth/authorize-ip`) działa tylko z sieci mobilnej operatora (GGSN) — nie z WiFi.

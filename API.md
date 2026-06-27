# Play24 (com.play.play24m) — rozpracowane API

> Reverse engineering aplikacji **Play24 v11.9.0** (versionCode 20849), wydawca P4 sp. z o.o.,
> build wykonany przez Miquido (`com.miquido.play360`). Analiza **statyczna** (jadx) dekompilatu
> `base.apk` z XAPK pobranego z apkpure.net. Stan: 2026-06-27.
>
> Backend = natywny klient Retrofit2/OkHttp (Kotlin). Adnotacje Retrofit są zobfuskowane przez R8
> (`@AJ0`=`@GET`, `@NI2`=`@POST`, `@PI2`=`@PUT`, `@MI2`=`@PATCH`, `@DN0`=`@DELETE`,
> `@P63`=`@Query`, `@InterfaceC9746vO2`=`@Path`, `@InterfaceC9286tw`=`@Body`, `@YN0`=`@Header`).

---

## 1. Architektura — hosty i bazowe URL-e

Źródło: `app/JT.java`, `play/config/{Api,Endpoint}.java`.

| Rola | Host | Bazowa ścieżka |
|---|---|---|
| **API główne** (self-care) | `play24-cloud.play.pl` | `/cloud/play24/gateway` |
| **SSO / logowanie** | `login-cloud.play.pl` | `/cloud/sso-customers/gateway/sso-mobile` |
| **OAuth2** | `oauth.play.pl` | `/oauth` |
| Push / wiadomości (CMG, n7mobile) | `cmg.play.pl` | `/api/mobile` (osobny system, `Authorization: Basic CMG:<redacted-w-APK>`) |
| OAuth redirect (callback) | `firebase.play.pl` | `/oauth-callback/` |

### Wzorzec URL API głównego — mikroserwisy

`Api.b()` składa URL tak:

```
https://play24-cloud.play.pl/cloud/play24/gateway/{ms-nazwa}/v{wersja}/{ścieżka-endpointu}
```

Przykład (saldo główne):
```
POST https://play24-cloud.play.pl/cloud/play24/gateway/ms-balances/v3/balances/{userId}/main
```

### Rejestr mikroserwisów (nazwa + wersja)

Źródło: klasy implementujące `InterfaceC9208th2` (`getName()` + `MicroServiceConfig(version)`).

| Mikroserwis | v | Obszar |
|---|---|---|
| ms-appinfo | 1 | wersja/konfiguracja appki |
| ms-activities | 2 | historia, koszty dodatkowe |
| ms-authorization | 1 | autoryzacje operacji |
| ms-balances | 3 | **saldo / pakiety / liczniki** |
| ms-benefits | 1 | benefity |
| ms-chatgpt | 1 | asystent/chat |
| ms-clients | 3 | **dane klienta / konta** |
| ms-complaints | 2 | reklamacje |
| ms-components | 8 | **usługi / komponenty taryfy** |
| ms-customerservice | 4 | BOK, chat, kontakt |
| ms-deliverymanager | 1 | dostawy |
| ms-device | 1 | urządzenia |
| ms-eid | 2 | e-dokumenty / weryfikacja tożsamości |
| ms-events | 2 | telemetria zdarzeń |
| ms-externalsystems | 1 | systemy zewnętrzne |
| ms-fbb | 1 | internet stacjonarny (modem) |
| ms-finances | 4 | **faktury / płatności / finanse** |
| ms-groups | 3 | grupy (multi-numer) |
| ms-notifications | 4 | **powiadomienia** |
| ms-offers | 12 | **oferty / pakiety na sprzedaż / retencja** |
| ms-order | 1 | zamówienia |
| ms-payments | 6 | **płatności / doładowania / transakcje** |
| ms-ren | 1 | (renewal/retencja) |
| ms-salesmanager | 4 | sprzedaż / oferty hub |
| ms-services | 1 | usługi |
| ms-sim | 2 | **SIM / eSIM / multiSIM** |

---

## 2. Uwierzytelnianie

> **NAJWAŻNIEJSZE:** sesja jest **oparta na cookies**, a **nie** na nagłówku `Authorization: Bearer`.
> Klient OkHttp używa globalnego `CookieManager(ACCEPT_ALL)` (`play/core/networking/cookies/b.java`).
> W całej apce **nie ma** interceptora dodającego `Authorization`. Po zalogowaniu kolejne żądania
> do bramki uwierzytelniają **ciasteczka sesji**. Odświeżenie odbywa się przez OkHttp `Authenticator`
> (`play/services/sso/api/authenticator/a.java`) reagujący na **HTTP 401** (retry z `X-Retry-Disallowed: true`).
> ⇒ **Własny klient musi trzymać cookie jar** i przenosić ciasteczka między hostami sso/oauth/gateway.

### 2.1 Ścieżki logowania

**A) `authorize-ip` — autoryzacja po IP (najprostsza, tylko z sieci Play)**
Bramka mapuje źródłowy IP → MSISDN. Źródło: `app/InterfaceC0132Az2.java`,
`play/services/oauth/usecase/SimCardCodeUseCase$getCode$1.java:68` (4 ostatnie parametry hardcoded).
```
GET https://oauth.play.pl/oauth/authorize-ip
      ?hint={msisdn}&client_id=play24_app&response_type=code&display=ip+end
      &redirect_uri=https://firebase.play.pl/oauth-callback/
→ redirect na redirect_uri z ?code=...  (+ ustawione cookies sesji)
```
Zweryfikowane na żywo: z poza sieci Play serwer zwraca
`302 …?error=access_denied&error_description=Server name (oauth.play.pl) does not match GGSN server name pattern`
— co potwierdza poprawność parametrów; brakuje tylko ścieżki przez GGSN operatora.
**Brak osobnej wymiany `oauth/access_token`** dla tej ścieżki — sesję ustanawiają cookies przy
redirekcie na `firebase.play.pl/oauth-callback/`. Klient powinien podążać za redirectami i zapisać cookies.

**B) Logowanie hasłem + OTP (SSO, host `login-cloud.play.pl/.../sso-mobile/`)**
Pełny ciąg (interfejs `app/InterfaceC9059tC3.java`, orchestracja `play/services/sso/usecase/*`):
```
1. POST api/standard/find-handlers/{msisdn}     Body {userHandles:[...]} → {userHandle}   (userHandle = profileId)
2. POST api/kyc/register?hint={hint}            Body {type:"STANDARD", input:"{msisdn}"} → {nonce, requiredAction, characteristic[]}
3. PUT  api/kyc/register/{nonce}                Body {password:"{hasło}", value:null}     → {nonce, requiredAction, characteristic[]}
4. POST api/standard/{profileId}/authorize/direct
                                                Body {acr:"FIDO|OTP|FIDO_OTP", hash, operationId, loginHintType?:"OTP_CONTACT_NO|OTP_CUSTOM"}
                                                → {nonce, requiredAction:"FIDO_REQUIRED|OTP_REQUIRED", characteristic[]}
5. PUT  api/standard/{profileId}/authorize/direct/{nonce}
                                                Body {action:"OTP_REQUIRED|FIDO_REQUIRED", characteristic:[{name,value}, …]}
                                                → {action:"TOKEN", token:"…", characteristic[]}   (TOKEN = sukces)
```
- **Hasło** leci w kroku 3 (`KycFinishRequestDto.password`). **Kod OTP (SMS)** w kroku 5 jako jedna z par
  `characteristic{name,value}` — *nazwa pola jest sterowana serwerem* (echo z odpowiedzi 2/3), nie da się
  jej ustalić statycznie. Enumy: `acr` ∈ {FIDO, OTP, FIDO_OTP} (`AcrDto`), `action`/`requiredAction`
  ∈ {TOKEN, OTP_REQUIRED, FIDO_REQUIRED} (`ActionDto`/`RequiredActionDto`).
- **Luki (do potwierdzenia podsłuchem):** sposób wyliczenia `hash`/`operationId` w kroku 4 (ustawiane
  wyżej, prawdopodobnie z redirectu OAuth/CIBA) oraz dokładna nazwa klucza OTP w `characteristic`.

**C) FIDO2 / passkey (PIN, WiFi — domyślne w apce)**
`api/fido/register[/finish]`, `api/fido/authenticate[/finish]` → `ProfileDto`. Klucz prywatny w Android
Keystore (alias `play24_key_pair_alias`); PIN tylko odblokowuje klucz. Replikacja = własny WebAuthn
(software passkey, `cryptography`) + onboarding OTP. Duży nakład.

**D) Tryb wstrzyknięcia sesji (pragmatyczny, dowolna sieć)** — przechwyć cookies (lub token) z apki
przez mitmproxy i podaj do klienta: `play24.py --cookie "<Cookie>"` lub `--token "<token>"`. Patrz `README.md`.

### 2.2 Token refresh (na 401)
- `DELETE api/fido/token/refresh/{profileId}/{userId}` (`app/InterfaceC4414eR3.java`)
- `POST api/epd/{profileId}/token/refresh-once/{nonce}` → `ProfileDto`
- `POST api/standard/{profileId}/token/msisdn-switch/{userId}` — przełączenie aktywnego numeru.

### 2.3 Nagłówki HTTP

| Nagłówek | Wartość | Uwagi |
|---|---|---|
| `Cookie` / `Set-Cookie` | ciasteczka sesji | **podstawowy mechanizm auth** (cookie jar, `CookieManager ACCEPT_ALL`) |
| `App-Version` | `11.9.0` | wersja aplikacji |
| `deviceId` | identyfikator urządzenia | UUID/Firebase Installation ID, generowany i trzymany lokalnie |
| `User-Agent` | API gł.: `play24/android`; OAuth: domyślny UA WebView | `play/services/oauth/api/a.java` |
| `Accept-Language` | `pl` | |
| `Content-Type` | `application/json` | (krok kyc/authorize: JSON; kyc-register bywa form-url-encoded) |
| `Authorization: Bearer` | — | **NIE występuje** w apce; nie polegaj na nim |

### 2.3 Certificate pinning

OkHttp pinuje 8 certyfikatów SHA256 dla `*.play.pl` (`play/core/networking/a.java:99-106`).
**To nie utrudnia naszego klienta** — pinning chroni tylko *oryginalną apkę* przed MITM.
Nasz klient łączy się normalnie (publiczny, zaufany łańcuch cert). Pinning ma znaczenie tylko,
gdyby ktoś chciał podsłuchać ruch apki (trzeba go wtedy obejść, np. Frida).

---

## 3. Katalog endpointów (API główne)

Ścieżki względne; pełny URL = `…/gateway/{ms}/v{wersja}/<ścieżka>`. `{userId}` = identyfikator
abonenta/konta (z odpowiedzi logowania), `{profileId}` = profil SSO.
Kontekst `BalancesRequestDto` body = `{ "serviceKind": VOICE|DATA|FIX|TV, "serviceType": PREPAID|POSTPAID|MIX }`.

### Saldo / pakiety (ms-balances v3) — `app/InterfaceC11126zq.java`
| Metoda | Ścieżka | Opis |
|---|---|---|
| POST | `balances/{userId}/main` | saldo główne (body: serviceKind/serviceType) → MainBalancesDto (Pre/Postpaid) |
| POST | `balances/{userId}/all` | wszystkie liczniki → `{ balances: [BalanceDto] }` |
| GET | `balances/{userId}/{id}/grants` | szczegóły przydziału → `[ {availableValue, valueUnit, expireDate} ]` |

### Oferty / pakiety (ms-offers v12)
`offers/{userId}` · `offers/{userId}/current-offer` · `offers/{userId}/details` ·
`offers/{userId}/hub` · `offers/{userId}/regulations` · `offers/{userId}/retention` ·
`offers/{userId}/retention-recommendation` · POST `offers/{userId}/save-order`

### Finanse / faktury (ms-finances v4)
`finances/{userId}/info` · `finances/{userId}/overdue` · `finances/{userId}/documents?onlyPaid=true&offset=0` ·
`finances/{userId}/financial-settings` · `finances/{userId}/recharges-settings` ·
`finances/{userId}/transfer-details` · `e-invoices/{userId}/is-available` · POST `e-invoices/{userId}/pdf`

### Konto / klient (ms-clients v3)
GET `customers/{userId}` · GET `clients/{userId}` · PATCH `customers/{userId}` ·
PATCH `customers/{userId}/bank-account` · GET `agreements/{userId}` · PATCH `agreements/{userId}`

### Usługi / komponenty (ms-components v8)
GET `components/{userId}` · POST `components/{userId}` · GET `components/{userId}/multisim` ·
GET `components/{userId}/{componentId}/promo-conditions`

### Płatności / doładowania / transakcje (ms-payments v6)
GET `payments/{userId}/methods` · POST `payments/{userId}` · POST `payments/{userId}/status` ·
POST `payments/{userId}/order/{orderId}` · POST `payments/{userId}/deactivate-recurring` ·
GET `recharges/{userId}/check` · GET `recharges/{userId}/history` ·
GET `transactions/{userId}/create` · POST `transactions/{userId}/run` ·
POST `transactions/{userId}/status` · POST `transactions/{userId}/instruments`

### Aktywności / historia (ms-activities v2)
GET `activities/{userId}/history` · GET `activities/{userId}/additional-costs`

### SIM / eSIM (ms-sim v2)
GET `sim/{userId}/information` · GET `sim/{userId}/information/multisim/{multiSimInstanceId}` ·
POST `sim/{userId}/components/multisim` · POST `esim/{userId}/order` · POST `verify/{userId}/puk`

### Powiadomienia (ms-notifications v4)
GET `notifications/{userId}` · GET `notifications/{userId}/{notificationId}` ·
POST `notifications/{userId}` · PATCH `notifications/{userId}/{notificationId}`

### Pozostałe (wybór)
`limits/{userId}` · `complaints/{userId}` · `devices/{userId}/details` · `failures/{userId}` ·
`groups/postpaid/{userId}` · `groups/prepaid/{userId}` · `modem/{userId}/info|config|restart|led|ssid|password` ·
`parental/{userId}/...` · `cybersecurity/{userId}/...` · `sales/{userId}/offers/list|banners|details` ·
`order/{userId}/list|details/{orderId}|status|cancel` · `teryt/{userId}/city|street|building` (słowniki adresowe) ·
GET `version` (ms-appinfo, sprawdzenie wersji)

> Pełna lista (~120 endpointów) z metodami HTTP: patrz `endpoints.txt`.

---

## 4. Jak zbudować własnego klienta — podsumowanie

1. **Najłatwiej (sieć Play):** `authorize-ip` → `access_token` → wołaj endpointy z `Bearer`.
2. **Dowolna sieć, bez creds w kodzie:** tryb `--token` (wklej Bearer z podsłuchu apki/sesji).
3. **Pełna replikacja PIN:** zaimplementuj WebAuthn (passkey software) + onboarding OTP — największy nakład.

Do potwierdzenia *dokładnego* formatu (pola POST `oauth/access_token`, kształt `FinishAuthorizationResponseDto`,
realne nazwy pól JSON w odpowiedziach) najpewniej: jednorazowy **podsłuch mitmproxy** na telefonie
(instrukcja w `README.md`). Statyka daje strukturę; podsłuch daje ostatnie 5%.

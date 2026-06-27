# Aktywacja pakietu (write transakcyjny) — recepta z podsłuchu (ReDroid + mitmproxy + Frida)

Przechwycone na żywo z oficjalnej apki (konto testowe, przykładowy pakiet).

## Kluczowe ustalenia (dlaczego CLI dostawał 401)
- Endpoint modyfikacji to **`ms-services/v1/components/{userId}`** — NIE `ms-components/v8` (ten jest tylko do *odczytu* katalogu).
- Wymagane nagłówki bramki: **`OS-Type: android`**, **`OS-Version: 33`** (+ standardowe App-Version, Accept-Language, cookies). 
- **Brak nagłówka `OperationToken`** w tym flow. `operationId` idzie w **body** (z odpowiedzi 409), nie w nagłówku.
- Krok SCA (authorize/direct) wymaga nagłówków: **`Device-Id`**, **`Device-Manufacturer`**, **`Device-Model`**.

## Sekwencja
### 1. Inicjacja (→ 409 wyzwanie SCA)
```
POST https://play24-cloud.play.pl/cloud/play24/gateway/ms-services/v1/components/{userId}
Headers: OS-Type: android | OS-Version: 33 | App-Version: 11.9.0 | Accept-Language: pl | Content-Type: application/json | Cookie: <sesja>
Body: { "type":"ACTIVATE", "componentId":"86009", "componentType":"BILLING_OTB",
        "params":[], "email":"<email>", "otp":null, "operationId":null }
→ 409 { "operationId":"<uuid>", "acrType":"FIDO", "hash":"<sha512 hex>",
        "responseCode":"MP0174", "responseMessage":"Wymagana autoryzacja operacji." }
```

### 2. Step-up start (FIDO)
```
POST https://login-cloud.play.pl/cloud/sso-customers/gateway/sso-mobile/api/standard/{profileId}/authorize/direct
Headers: Device-Id, Device-Manufacturer, Device-Model
Body: { "acr":"FIDO", "hash":"<z 409>", "operationId":"<z 409>",
        "bindingMessage":null,"loginHint":null,"loginHintType":null,"nonce":null,"payload":null,"redirectUri":null,"state":null }
→ 200 { "nonce":"<uuid>", "requiredAction":"FIDO_REQUIRED",
        "characteristic":[ {"name":"challenge","value":"<b64url>"},
                           {"name":"public-key","value":"<credentialId b64>"},
                           {"name":"rpId","value":"https://sso.play.pl"},
                           {"name":"timeout","value":"120000"} ] }
```

### 3. Step-up finish (podpis passkey)
```
PUT .../api/standard/{profileId}/authorize/direct/{nonce}
Body: { "action":"FIDO_REQUIRED",
        "characteristic":[ {"name":"id","value":"<credentialId = public-key z kroku 2>"},
                           {"name":"clientDataJSON","value":"<b64 {type:webauthn.get,challenge,origin:rpId}>"},
                           {"name":"authenticatorData","value":"<b64 rpIdHash|flags|signCount>"},
                           {"name":"signature","value":"<b64 ECDSA-SHA256 DER>"} ] }
→ 200 { "action":"TOKEN", ... }   (operacja autoryzowana)
```

### 4. Ponowienie (→ sukces)
```
POST ms-services/v1/components/{userId}  (te same nagłówki)
Body: { ...jak w kroku 1, "operationId":"<z 409>" }
→ 200/204  → pakiet włączony
```

Uwaga: `clientDataJSON` dla operacji = `webauthn.get`, origin = rpId ("https://sso.play.pl"); podpis jak przy logowaniu FIDO. `id` w finish = wartość `public-key` zwrócona w kroku 2 (= credentialId zarejestrowanego passkey).

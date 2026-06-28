# Jak rozpracowano protokół Play24 — metody

Krótki przegląd technik użytych do reverse-engineeringu API.

## 1. Analiza statyczna APK
- **Pozyskanie APK** — pobranie XAPK z mirrora, rozpakowanie split-APK (base + config.*).
- **Dekompilacja** — `jadx` (dex → Java) + `strings` na `.dex` do szybkiego rekonu hostów/URL-i.
- **Czytanie zobfuskowanego kodu (R8)** — śledzenie referencji między klasami o krótkich nazwach,
  odczyt adnotacji Retrofit mimo obfuskacji (`@AJ0`=GET, `@NI2`=POST, `@PI2`=PUT, `@MI2`=PATCH,
  `@DN0`=DELETE, `@P63`=Query, `@…vO2`=Path, `@…tw`=Body), mapowanie pól z `@Metadata d2` (Kotlin)
  i z enumów. Przykłady: `okhttp3.b` = CertificatePinner, klasy `ms-*` = rejestr mikroserwisów.
- **Rekonstrukcja architektury** — z `play/config/*` (hosty, wzorzec `gateway/{ms}/v{N}/...`),
  pakietów `play/services/*` i `play/features/login/*` (OAuth, SSO, FIDO2, KYC).

## 2. Weryfikacja na żywo (czarna skrzynka)
- **Sondowanie endpointów** (curl / Python `requests`) i czytanie kodów błędów domenowych
  (`MP00xx`) jako wskazówek — np. `access_denied / GGSN` (auth po IP tylko w sieci operatora),
  `MP0015` (zły numer), `MP0174` (wymagana autoryzacja operacji), `MP0035/MP0038` (numer/uprawnienia).
- **Implementacja klienta jako test hipotez** — odtworzenie WebAuthn/FIDO2 w Pythonie
  (`cryptography` + własny mini-enkoder CBOR, bez zależności) i walidacja przez odpowiedzi serwera.

## 3. Analiza dynamiczna (instrumentacja) — gdy blokował cert-pinning / SCA
- **Emulacja Androida** — ReDroid (Android w kontenerze; `modprobe binder_linux` + binderfs).
  Obraz z translacją ARM (`libnb.so`) → apka arm64 działa na hoście x86_64.
- **Sterowanie headless** — `adb` (`input tap/text`, `screencap`) + analiza zrzutów ekranu.
- **Przechwytywanie HTTPS** — `mitmproxy` (`adb reverse` + cert jako systemowy w `/system/etc/security/cacerts`).
- **Obejście cert-pinningu** — `frida` + własny skrypt unpinning (hooki na obfuskowany
  `okhttp3.b.check`, Conscrypt `TrustManagerImpl`, `SSLContext.init`). Patrz `re/unpin.js`.

## Wniosek
Pętla: **statyka (jadx/strings) → hipotezy → weryfikacja na żywo (curl)**; tam gdzie blokował
pinning lub silne uwierzytelnienie operacji (SCA) → **dynamika (ReDroid + Frida + mitmproxy)**,
co dało dokładny zapis flow (m.in. recepta aktywacji w `ACTIVATION.md`).

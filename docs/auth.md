# Uwierzytelnianie — passkey FIDO2

Logowanie do Play24 odtwarza mechanizm passkey (WebAuthn/FIDO2) z oficjalnej apki, ale klucz
prywatny trzymamy w pliku zamiast w Android Keystore. **Działa z dowolnej sieci** (WiFi też),
nie wymaga hasła ani przechwytywania ruchu.

← [README](../README.md) · [Szybki start](../QUICKSTART.md) · [CLI](cli.md)

## Onboarding numeru (raz na numer)
```bash
uv run play24 register-start --msisdn 48xxxxxxxxx              # wyśle SMS (numer 9-cyfrowy też OK)
# (przychodzi kod SMS)
uv run play24 register-otp --msisdn 48xxxxxxxxx --code 1234    # weryfikuje kod + rejestruje passkey
```
Po tym w `~/.play24/passkey_<48msisdn>.json` (chmod 600) jest klucz EC P-256. **Nie ma osobnej
komendy „login”** — onboardowany numer jest logowany passkeyem przy każdym wywołaniu (CLI,
biblioteka, MCP).

## Co siedzi pod spodem (protokół)
- `kyc/register?hint=MSISDN_OTP_REQUIRED` `{type:STANDARD,input:msisdn}` → SMS; kod →
  `PUT kyc/register/{nonce} {password:<kod>}` (**kod OTP idzie w polu `password`**!).
- `POST api/fido/register` **wymaga** `authenticatorSelection` (bez niego 500), `attestation:"none"`,
  alg ES256 (-7), `rpId="https://sso.play.pl"` (origin = ten sam string).
- Logowanie: `POST api/fido/authenticate` → challenge → podpis → `…/authenticate/finish`.
- Sesja: cookies domenowe `.play.pl` (`access-token`/`refresh-token` JWE) ustawiane przez
  `fido/authenticate/finish` — działają też na bramce. Klient trzyma cookie jar tylko na czas procesu;
  w `~/.play24/session.json` zapisane są **profile + device_id + aktywny numer** (nie cookies).
- Gateway `{userId}` = **msisdn z prefiksem 48** (np. `48500100200`), `accessLevel: MSISDN`.

Pełny opis: [API.md §2](API.md). Implementacja autentykatora: `play24lib.py` (sekcja WebAuthn/FIDO2).

## Alternatywne drogi logowania (niszowe, nieobsługiwane w CLI)
Odkryte podczas reverse-engineeringu, opisane w [API.md §2](API.md) — klient CLI celowo
standaryzuje na passkey (jedna spójna ścieżka, działa wszędzie):
- **Autoryzacja po IP** (`oauth/authorize-ip`) — bez SMS/PIN, ale tylko z internetu mobilnego Play
  (żądanie przez GGSN; z WiFi serwer zwraca `access_denied … GGSN server name pattern`).
- **Wstrzyknięcie cookies/tokenu** z podsłuchu apki — patrz niżej.
- **SSO hasłem** (`find-handlers → kyc/register`) — krok authorize/direct + OTP, patrz [API.md §2.1.B](API.md).

## Podsłuch / potwierdzenie formatu (mitmproxy)
Statyka daje strukturę; ostatnie szczegóły (dokładne pola, kształt JSON) najłatwiej potwierdzić
jednym podsłuchem oficjalnej apki:
1. `pipx install mitmproxy` (lub `pip install mitmproxy`).
2. `mitmweb --listen-port 8080` na PC; zapisz cert CA z `http://mitm.it`.
3. Android: proxy WiFi na `IP_PC:8080`, cert CA jako **systemowy** (root/Magisk; user-cert nie
   wystarczy od Androida 7+).
4. **Cert pinning**: apka pinuje certy `*.play.pl` (8× SHA256, [API.md §2.3](API.md)). Aby podsłuchać —
   obejdź pinning **Fridą** (`re/unpin.js`, `frida-multiple-unpinning`) lub `objection`.
5. W mitmweb filtruj `play24-cloud.play.pl` → podejrzyj nagłówki/ciało żądań.

Alternatywa bez roota/pinningu: zaloguj się na [24.play.pl](https://24.play.pl) w przeglądarce
i podejrzyj token w DevTools → Network (web używa zbliżonego backendu OAuth). Techniki RE: [METHODS.md](METHODS.md).

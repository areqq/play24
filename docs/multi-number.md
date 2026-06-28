# Wiele numerów — dwa modele

Play24 rozróżnia dwa przypadki; klient obsługuje oba.

← [README](../README.md) · [CLI](cli.md) · [Uwierzytelnianie](auth.md)

## A) Osobne konta (różni właściciele) — `accounts` + `--msisdn`/`use` ⭐ zweryfikowane
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

## B) Jedno konto, wiele numerów — `numbers` + `switch`
Jeśli do JEDNEGO konta podpięto kilka numerów, przełączasz numer w obrębie tej samej sesji:
```bash
uv run play24 numbers --msisdn <NUMER_KONTA>   # lista numerów na koncie
uv run play24 switch 48xxxxxxxxx               # przełącz numer (msisdn-switch → nowy token) + pokaż saldo
```
`{userId}` bramki = msisdn z prefiksem 48; przełączanie re-issuuje token sesji scoped na wybrany
numer. (Próba przełączenia na numer spoza konta → `MP0038`.)

## Jak AUTORYZOWAĆ (dodać) nowy numer do konta
`switch` działa tylko dla numerów już podpiętych. Żeby dodać nowy numer, musisz **udowodnić, że go
posiadasz** — kodem SMS na ten numer (ta sama bramka KYC co przy onboardingu; brak obejścia — to
zabezpieczenie). Robisz to onboardingiem dla nowego numeru:
```bash
uv run play24 register-start --msisdn <NOWY_NUMER>              # SMS na nowy numer
uv run play24 register-otp --msisdn <NOWY_NUMER> --code XXXX    # dowód posiadania
```
Ponieważ jesteś już zalogowany, `register-start` dołącza Twój istniejący profil do `find-handlers`
(`userHandles=[profileId]`) — zgodnie z flow „Dodaj numer" (`UpgradeOnboarding.ADD`) w apce — więc
nowy numer **przypina się do tego samego konta**. Potem `numbers` go pokaże, a `switch` przełączy.

> ⚠️ Ten dokładny krok (przypięcie 2. numeru do istniejącego profilu) nie był testowany na żywo —
> konto testowe ma jeden numer. Format żądań jest zgodny z apką; finalna walidacja wymaga realnego
> 2. numeru.

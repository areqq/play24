#!/usr/bin/env python3
"""
play24 — nieoficjalny klient CLI do API aplikacji Play24 (com.play.play24m).

Zbudowany na podstawie statycznej analizy APK v11.9.0. Szczegóły API: API.md.
NIE jest to oficjalne narzędzie Play / P4 sp. z o.o. Używasz na własną odpowiedzialność,
wyłącznie do własnego konta.

Tryby uwierzytelniania:
  1) authorize-ip  — działa TYLKO gdy łączysz się z sieci mobilnej Play (bramka rozpoznaje
                     numer po adresie IP). Nie wymaga PIN-u ani SMS.
  2) --token       — wklejasz gotowy access_token (Bearer) przechwycony z apki/sesji.

Przykłady:
  ./play24.py login-ip --msisdn 48500100200          # auth po IP (sieć Play)
  ./play24.py --token "eyJ..." --user-id 123 balance # użyj gotowego tokenu
  ./play24.py balance                                # saldo (token z ~/.play24)
  ./play24.py offers
  ./play24.py raw GET ms-finances v4 finances/{userId}/info
"""
import argparse
import getpass
import json
import os
import sys
import time
import uuid

try:
    import requests
except ImportError:
    sys.exit("Brakuje biblioteki 'requests'. Zainstaluj: pip install requests")

try:
    import play24_passkey as wa
except ImportError:
    wa = None   # potrzebne tylko dla register/auth (FIDO2)

# ----------------------------------------------------------------------------- config
GW          = "https://play24-cloud.play.pl/cloud/play24/gateway"
SSO         = "https://login-cloud.play.pl/cloud/sso-customers/gateway/sso-mobile"
OAUTH       = "https://oauth.play.pl/oauth"
REDIRECT    = "https://firebase.play.pl/oauth-callback/"
CLIENT_ID   = "play24_app"
APP_VERSION = "11.9.0"

STORE = os.path.expanduser("~/.play24/session.json")

# Sesja Play24 jest COOKIE-based (globalny CookieManager w apce), NIE Bearer.
# Trzymamy więc jeden cookie jar przez całe życie procesu.
SESSION = requests.Session()

# mikroserwis + wersja dla typowych obszarów (z rejestru ms-* w APK)
SERVICES = {
    "balances":      ("ms-balances", 3),
    "offers":        ("ms-offers", 12),
    "finances":      ("ms-finances", 4),
    "e-invoices":    ("ms-finances", 4),
    "clients":       ("ms-clients", 3),
    "customers":     ("ms-clients", 3),
    "agreements":    ("ms-clients", 3),
    "components":    ("ms-components", 8),
    "payments":      ("ms-payments", 6),
    "recharges":     ("ms-payments", 6),
    "transactions":  ("ms-payments", 6),
    "activities":    ("ms-activities", 2),
    "sim":           ("ms-sim", 2),
    "esim":          ("ms-sim", 2),
    "verify":        ("ms-sim", 2),
    "notifications": ("ms-notifications", 4),
    "complaints":    ("ms-complaints", 2),
    "limits":        ("ms-balances", 3),
    "groups":        ("ms-groups", 3),
    "order":         ("ms-order", 1),
    "sales":         ("ms-salesmanager", 4),
    "version":       ("ms-appinfo", 1),
}


# ----------------------------------------------------------------------------- session
def load_session():
    try:
        with open(STORE) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return {}
    for k, v in (s.get("cookies") or {}).items():   # przywróć cookie jar
        SESSION.cookies.set(k, v)
    return s


def save_session(s):
    s["cookies"] = SESSION.cookies.get_dict()
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w") as f:
        json.dump(s, f, indent=2)
    os.chmod(STORE, 0o600)


def add_cookie_header(raw):
    """Wstrzyknięcie surowego nagłówka Cookie: 'a=1; b=2'."""
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            SESSION.cookies.set(k, v)


def device_id(s):
    if not s.get("device_id"):
        s["device_id"] = str(uuid.uuid4())
    return s["device_id"]


# ----------------------------------------------------------------------------- http
def headers(s, oauth=False):
    h = {
        "App-Version": APP_VERSION,
        "OS-Type": "android",
        "OS-Version": "33",
        "deviceId": device_id(s),
        "Device-Id": device_id(s),
        "Device-Manufacturer": "cli",
        "Device-Model": "play24-cli",
        "Accept-Language": "pl",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
            if oauth else "play24/android"
        ),
    }
    if not oauth and s.get("access_token"):
        h["Authorization"] = "Bearer " + s["access_token"]
    return h


def show(resp):
    print(f"HTTP {resp.status_code} {resp.reason}", file=sys.stderr)
    body = resp.text
    try:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(body)
    if not resp.ok:
        sys.exit(2)


# ----------------------------------------------------------------------------- auth
def login_ip(s, msisdn, debug=False):
    """authorize-ip: zwraca authorization code (tylko z sieci Play)."""
    params = {
        "hint": msisdn,
        "client_id": CLIENT_ID,
        "response_type": "code",
        "display": "ip end",
        "redirect_uri": REDIRECT,
    }
    r = SESSION.get(f"{OAUTH}/authorize-ip", params=params, headers=headers(s, oauth=True),
                    allow_redirects=False, timeout=30)
    if debug:
        print(f"[authorize-ip] HTTP {r.status_code}", file=sys.stderr)
        print(f"[authorize-ip] Location: {r.headers.get('Location')}", file=sys.stderr)
        print(f"[authorize-ip] body: {r.text[:500]}", file=sys.stderr)
    from urllib.parse import urlparse, parse_qs, unquote
    code = None
    loc = r.headers.get("Location", "")
    # serwer zwraca wynik jako redirect na redirect_uri z ?code=... lub ?error=...
    if loc:
        q = parse_qs(urlparse(loc).query)
        if q.get("error"):
            sys.exit("Serwer odmówił autoryzacji: "
                     f"{q['error'][0]} — {unquote(q.get('error_description', [''])[0])}\n"
                     "Wskazówka: 'authorize-ip' działa tylko z aktywnej transmisji danych "
                     "w sieci Play (żądanie musi przejść przez GGSN operatora).")
        if q.get("code"):
            code = q["code"][0]
    if not code:
        try:
            code = r.json().get("code")
        except ValueError:
            pass
    if not code:
        for c in r.cookies:
            if "code" in c.name.lower():
                code = c.value
    if not code:
        sys.exit("Nie udało się uzyskać kodu autoryzacji. Czy jesteś w sieci mobilnej Play?\n"
                 "Uruchom z --debug, by zobaczyć surową odpowiedź.")
    return code


def exchange_code(s, code, debug=False):
    """Wymiana authorization code -> access_token (oauth/access_token).

    UWAGA: dokładny zestaw pól potwierdź podsłuchem (mitmproxy). Poniżej standard OAuth2.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
    }
    h = headers(s, oauth=True)
    h["Content-Type"] = "application/x-www-form-urlencoded"
    r = SESSION.post(f"{OAUTH}/access_token", data=data, headers=h, timeout=30)
    if debug:
        print(f"[access_token] HTTP {r.status_code}: {r.text[:500]}", file=sys.stderr)
    if not r.ok:
        sys.exit(f"Wymiana kodu nie powiodła się (HTTP {r.status_code}): {r.text[:300]}")
    tok = r.json()
    s["access_token"]  = tok.get("access_token")
    s["refresh_token"] = tok.get("refresh_token")
    s["expires_at"]    = int(time.time()) + int(tok.get("expires_in", 0) or 0)
    return tok


# ----------------------------------------------------------------------------- gateway calls
def call(s, method, ms, version, path, query=None, body=None):
    if not (SESSION.cookies or s.get("access_token")):
        sys.exit("Brak sesji. Zaloguj się (login-ip / login) albo podaj --cookie / --token.")
    path = path.replace("{userId}", str(s.get("user_id", "")))
    version = str(version).lstrip("vV")          # akceptuj zarówno "3" jak i "v3"
    url = f"{GW}/{ms}/v{version}/{path}"
    return SESSION.request(method, url, headers=headers(s), params=query, json=body, timeout=30)


def gw_for(first_segment):
    if first_segment not in SERVICES:
        sys.exit(f"Nieznany obszar '{first_segment}'. Użyj 'raw' i podaj ms+wersję ręcznie.")
    return SERVICES[first_segment]


def balances_body(args):
    return {"serviceKind": args.kind, "serviceType": args.type}


# ----------------------------------------------------------------------------- commands
def cmd_login_ip(s, args):
    # 1) authorize-ip → authorization code + cookies sesji (Set-Cookie na 302)
    code = login_ip(s, args.msisdn, args.debug)
    print(f"code = {code}", file=sys.stderr)
    # 2) sesja jest cookie-based: "skonsumuj" redirect na callback, by dociągnąć cookies
    SESSION.get(f"{REDIRECT}?code={code}", headers=headers(s, oauth=True),
                allow_redirects=True, timeout=30)
    s["msisdn"] = args.msisdn
    if args.user_id:
        s["user_id"] = args.user_id
    save_session(s)
    cookies = SESSION.cookies.get_dict()
    print(f"Zalogowano (cookie-based). Cookies: {list(cookies)} → zapis w {STORE}", file=sys.stderr)
    if not s.get("user_id"):
        print("UWAGA: ustaw --user-id (identyfikator abonenta) do wywołań bramki.", file=sys.stderr)


def cmd_login(s, args):
    """EKSPERYMENTALNE: logowanie hasłem przez SSO (find-handlers → kyc).

    W pełni odtworzone są kroki 1-3 (rozpoznanie numeru + podanie hasła). Kroki 4-5
    (authorize/direct + OTP) wymagają pól `hash`/`operationId` i nazwy klucza OTP, których nie
    da się ustalić statycznie — ta komenda wypisuje surowe odpowiedzi serwera, byś mógł je
    dograć podsłuchem. Po sukcesie sesja jest cookie-based (zapisywana automatycznie).
    """
    msisdn = args.msisdn
    pwd = args.password or getpass.getpass("Hasło Play24: ")
    h = headers(s)

    def post(path, body):
        r = SESSION.post(f"{SSO}/{path}", headers=h, json=body, timeout=30)
        print(f"\n# POST {path} → HTTP {r.status_code}", file=sys.stderr)
        try:
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))
        except ValueError:
            print(r.text[:800])
        return r

    def put(path, body):
        r = SESSION.put(f"{SSO}/{path}", headers=h, json=body, timeout=30)
        print(f"\n# PUT {path} → HTTP {r.status_code}", file=sys.stderr)
        try:
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))
        except ValueError:
            print(r.text[:800])
        return r

    print("[1/3] find-handlers", file=sys.stderr)
    post(f"api/standard/find-handlers/{msisdn}", {"userHandles": []})
    print("[2/3] kyc/register (start)", file=sys.stderr)
    r2 = post("api/kyc/register", {"type": "STANDARD", "input": msisdn})
    try:
        nonce = r2.json().get("nonce")
    except ValueError:
        nonce = None
    if not nonce:
        sys.exit("Brak nonce z kroku 2 — patrz odpowiedź serwera powyżej.")
    print("[3/3] kyc/register/{nonce} (hasło)", file=sys.stderr)
    put(f"api/kyc/register/{nonce}", {"password": pwd, "value": None})
    save_session(s)
    print("\nKroki 1-3 wykonane. Dalsze kroki (authorize/direct + OTP) — patrz API.md §2.1.B.\n"
          "Jeśli pojawił się token/cookies sesji, kolejne komendy zadziałają. Sprawdź: ./play24.py whoami",
          file=sys.stderr)


# ----------------------------------------------------------------------------- onboarding FIDO2 (rejestracja od zera, off-network)
def passkey_path(msisdn):
    return os.path.join(os.path.dirname(STORE), f"passkey_{_norm_msisdn(msisdn)}.json")


def sso(method, path, body=None, query=None, debug=False):
    r = SESSION.request(method, f"{SSO}/{path}", headers=headers({}),
                        params=query, json=body, timeout=30)
    print(f"# {method} {path} → HTTP {r.status_code}", file=sys.stderr)
    if os.environ.get("PLAY24_DEBUG"):
        interesting = {k: v for k, v in r.headers.items()
                       if k.lower() in ("location", "x-user-id", "userid", "x-profile-id")}
        if interesting:
            print(f"  headers: {interesting}", file=sys.stderr)
    try:
        j = r.json()
        print(json.dumps(j, indent=2, ensure_ascii=False), file=sys.stderr)
    except ValueError:
        j = None
        if r.text:
            print(r.text[:800], file=sys.stderr)
    return r, j


def cmd_register_start(s, args):
    """Krok 1: rozpoznanie numeru + wysłanie kodu SMS (kyc/register)."""
    if wa is None:
        sys.exit("Brak modułu play24_passkey.py / biblioteki 'cryptography' (pip install cryptography).")
    msisdn = args.msisdn   # format jak podany (9-cyfr działa; nie normalizujemy do API)
    # find-handlers: dołącz handle istniejących profili (jak apka) → nowy numer przypnie się
    # do TEGO SAMEGO konta (flow "dodaj numer"). Pusta lista = pierwszy numer (nowy profil).
    handles = [h for h in {s.get("profile_id")} if h]
    sso("POST", f"api/standard/find-handlers/{msisdn}", body={"userHandles": handles})
    r, j = sso("POST", "api/kyc/register",
               body={"type": args.profile_type, "input": msisdn},
               query={"hint": "MSISDN_OTP_REQUIRED"})
    if not j or not j.get("nonce"):
        sys.exit("Nie otrzymano nonce — patrz odpowiedź serwera wyżej.")
    s["msisdn"] = msisdn
    s["reg_nonce"] = j["nonce"]
    s["reg_required"] = j.get("requiredAction")
    save_session(s)
    ch = j.get("characteristic") or {}
    length = ch.get("length")
    print(f"\n✅ Kod SMS wysłany na {msisdn}"
          + (f" (oczekiwana długość: {length})" if length else "")
          + f"\nNastępnie: ./play24.py register-otp --code <KOD_Z_SMS>", file=sys.stderr)


def _fido_register(s, identifier, debug=False, full_body=True):
    """Krok 3-4: FIDO register-start → lokalny passkey → register-finish.

    UWAGA (zweryfikowane na żywo): serwer WYMAGA pola authenticatorSelection w body —
    bez niego zwraca 500 MP0023. Dlatego wysyłamy pełny body domyślnie.
    """
    nonce = s.get("reg_nonce")
    body = {
        "nonce": nonce,
        "identifier": identifier,
        "attestation": "none",
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",
            "requireResidentKey": True,
            "userVerification": "required",
        },
    }
    r, opts = sso("POST", "api/fido/register", body=body)
    if not opts:
        sys.exit("Brak RegisterOptions — patrz odpowiedź serwera (może zła wartość identifier?).")
    rp = opts.get("relayingParty") or opts.get("rp") or {}
    rp_id = rp.get("id") or opts.get("rpId")
    if not rp_id:
        sys.exit(f"Nie znaleziono rpId w RegisterOptions: {list(opts)}")
    pk, credential = wa.make_credential(opts, rp_id, rp_id)
    r2, profile = sso("POST", "api/fido/register/finish", body=credential)
    if not r2.ok:
        sys.exit("register/finish odrzucone — patrz odpowiedź wyżej.")
    # sukces — zapisz passkey i profil
    pk.save(passkey_path(s["msisdn"]))
    s["rp_id"] = rp_id
    if isinstance(profile, dict):
        s["profile"] = profile
        s["profile_id"] = profile.get("profileId") or profile.get("id")
        # do wywołań bramki {userId} = identifier (msisdn z prefiksem, accessLevel MSISDN)
        s["user_id"] = profile.get("identifier") or s.get("user_id") or s["profile_id"]
        # metadane PER NUMER — każdy numer to osobne konto/profil/passkey
        key = _norm_msisdn(s.get("msisdn") or s["user_id"])
        s.setdefault("profiles", {})[key] = {
            "profile_id": s["profile_id"], "user_id": s["user_id"], "rp_id": rp_id,
        }
        s["active"] = key
    save_session(s)
    print(f"\n✅ Numer {s['msisdn']} podpięty! Passkey: {passkey_path(s['msisdn'])}\n"
          f"   Logowanie kolejnym razem: ./play24.py auth --msisdn {s['msisdn']}", file=sys.stderr)


def cmd_register_otp(s, args):
    """Krok 2: weryfikacja kodu SMS → automatyczne podpięcie passkey."""
    if wa is None:
        sys.exit("Brak modułu play24_passkey.py / 'cryptography'.")
    nonce = s.get("reg_nonce")
    if not nonce:
        sys.exit("Najpierw uruchom: ./play24.py register-start --msisdn <numer>")
    # KycFinishRequestDto: 'password' wymagane, 'value' opcjonalne — kod OTP idzie w 'password'
    r, j = sso("PUT", f"api/kyc/register/{nonce}", body={"password": args.code})
    if not r.ok:
        sys.exit("Kod odrzucony — sprawdź SMS i spróbuj ponownie (register-start, register-otp).")
    # po OTP serwer zwraca kolejny nonce + requiredAction (oczekiwane FINISH_FIDO)
    if j and j.get("nonce"):
        s["reg_nonce"] = j["nonce"]
    s["reg_required"] = (j or {}).get("requiredAction")
    save_session(s)
    req = (j or {}).get("requiredAction")
    if req and req != "FINISH_FIDO":
        print(f"\nServer wymaga jeszcze: {req}. Zatrzymuję — przyjrzyjmy się odpowiedzi wyżej.", file=sys.stderr)
        return
    if args.no_fido:
        print(f"\n✅ OTP OK, requiredAction=FINISH_FIDO, nonce zapisany.\n"
              f"   Teraz: ./play24.py register-fido", file=sys.stderr)
        return
    identifier = args.identifier or s.get("user_id") or s["msisdn"]
    _fido_register(s, identifier, args.debug)


def cmd_register_fido(s, args):
    """Awaryjnie: ponów sam krok FIDO (gdy register-otp przeszło, ale FIDO trzeba dostroić)."""
    if wa is None:
        sys.exit("Brak modułu play24_passkey.py / 'cryptography'.")
    identifier = args.identifier or s.get("user_id") or s.get("msisdn")
    _fido_register(s, identifier, args.debug, full_body=args.full_body)


def cmd_auth(s, args):
    """Logowanie zarejestrowanym passkeyem (FIDO2) — wybiera konto wg numeru.

    Każdy numer = osobne konto/profil/passkey. Przy logowaniu CZYŚCIMY cookies (świeża sesja),
    a profile_id bierzemy z metadanych TEGO numeru (nie z poprzednio aktywnego konta).
    """
    if wa is None:
        sys.exit("Brak modułu play24_passkey.py / 'cryptography'.")
    msisdn = args.msisdn or s.get("msisdn")
    if not msisdn:
        sys.exit("Podaj numer: ./play24.py auth --msisdn <numer>")
    key = _norm_msisdn(msisdn)
    prof = (s.get("profiles") or {}).get(key)
    if not prof:
        sys.exit(f"Numer {key} nie jest zarejestrowany lokalnie. "
                 f"Najpierw: ./play24.py register-start --msisdn {msisdn} (lista: ./play24.py accounts)")
    if not os.path.exists(passkey_path(msisdn)):
        sys.exit(f"Brak pliku passkey dla {key}. Zarejestruj numer ponownie.")
    pk = wa.Passkey.load(passkey_path(msisdn))
    SESSION.cookies.clear()                       # świeża sesja — bez cookies innego konta
    r, opts = sso("POST", "api/fido/authenticate", body={
        "profileId": prof["profile_id"],
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",
            "requireResidentKey": True,
            "userVerification": "required",
        },
    })
    if not r.ok or not opts:
        sys.exit("authenticate (start) odrzucone — patrz odpowiedź wyżej.")
    rp_id = opts.get("rpId") or prof.get("rp_id")
    assertion = wa.get_assertion(opts, pk, rp_id, rp_id)
    r2, profile = sso("POST", "api/fido/authenticate/finish", body=assertion)
    if not r2.ok:
        sys.exit("authenticate/finish odrzucone — patrz wyżej.")
    pk.save(passkey_path(msisdn))   # zapisz zwiększony sign_count
    if isinstance(profile, dict):
        s["profile"] = profile
        s["profile_id"] = profile.get("profileId") or prof["profile_id"]
        s["user_id"] = profile.get("identifier") or prof["user_id"]
    s["msisdn"] = msisdn
    s["active"] = key
    s["rp_id"] = rp_id
    save_session(s)
    print(f"\n✅ Aktywne konto: {s.get('user_id')} "
          f"({(s.get('profile') or {}).get('characteristic',{})}). ", file=sys.stderr)


def cmd_accounts(s, args):
    """Lista lokalnie zarejestrowanych numerów/kont (osobne profile)."""
    profs = s.get("profiles") or {}
    if not profs:
        print("Brak zarejestrowanych numerów. Dodaj: ./play24.py register-start --msisdn <numer>",
              file=sys.stderr)
        return
    active = s.get("active")
    print("Zarejestrowane konta (osobne profile):", file=sys.stderr)
    for key, p in profs.items():
        mark = " *" if key == active else "  "
        has_pk = "✓" if os.path.exists(passkey_path(key)) else "BRAK passkey"
        print(f"{mark} {key}  profil={p.get('profile_id','')[:8]}…  passkey:{has_pk}", file=sys.stderr)
    print("\nPrzełącz konto: ./play24.py auth --msisdn <numer>", file=sys.stderr)


# ----------------------------------------------------------------------------- wiele numerów (jedno konto)
def _norm_msisdn(m):
    """'48 723 011 111' / '500100200' / '+48500100200' → '48500100200'."""
    d = "".join(ch for ch in str(m) if ch.isdigit())
    if len(d) == 9:
        d = "48" + d
    return d


def cmd_numbers(s, args):
    """Lista numerów na profilu (jedno konto, wiele numerów)."""
    pid = s.get("profile_id")
    if not pid:
        sys.exit("Brak profilu. Zaloguj się: ./play24.py auth --msisdn <numer>")
    r, j = sso("GET", f"api/standard/{pid}/msisdn/list")
    if r.ok and isinstance(j, list):
        s["msisdns"] = j
        save_session(s)
        active = s.get("user_id")
        print("\nNumery na koncie:", file=sys.stderr)
        for it in j:
            m = _norm_msisdn(it.get("msisdn"))
            mark = " *" if m == active else "  "
            print(f"{mark} {m}  {it.get('serviceType','')}/{it.get('serviceKind','')}  {it.get('brand','')}",
                  file=sys.stderr)
        print("\nPrzełącz: ./play24.py switch <numer>", file=sys.stderr)


def cmd_switch(s, args):
    """Przełącz aktywny numer (msisdn-switch → nowy token sesji scoped na numer).

    {userId} w msisdn-switch to HASH numeru (z msisdn/list), nie surowe cyfry.
    """
    pid = s.get("profile_id")
    if not pid:
        sys.exit("Brak profilu. Zaloguj się: ./play24.py auth --msisdn <numer>")
    target = _norm_msisdn(args.msisdn)
    if target == _norm_msisdn(s.get("user_id")):
        print(f"Numer {target} jest już aktywny — nie trzeba przełączać.", file=sys.stderr)
        return
    r, j = sso("POST", f"api/standard/{pid}/token/msisdn-switch/{target}")
    if not r.ok:
        code = (j or {}).get("responseCode") if isinstance(j, dict) else None
        hint = ""
        if code == "MP0035":
            hint = (" (serwer odmówił logowania na ten numer — sprawdź, czy jest na koncie: "
                    "./play24.py numbers)")
        sys.exit(f"Przełączenie na {target} nieudane{hint}.")
    s["user_id"] = target
    save_session(s)
    print(f"\n✅ Aktywny numer: {target}. Kolejne komendy (balance/offers/...) dotyczą tego numeru.",
          file=sys.stderr)


def cmd_balance(s, args):
    ms, v = gw_for("balances")
    show(call(s, "POST", ms, v, "balances/{userId}/main", body=balances_body(args)))


def cmd_balances_all(s, args):
    ms, v = gw_for("balances")
    show(call(s, "POST", ms, v, "balances/{userId}/all", body=balances_body(args)))


def _fmt_date(d):
    return d[:10] if isinstance(d, str) and len(d) >= 10 else "—"


def cmd_packages(s, args):
    """Aktywne pakiety/usługi z datami aktywacji/odnowienia (ms-components)."""
    r = call(s, "GET", "ms-components", 8, "components/{userId}")
    if not r.ok:
        show(r)
        return
    items = r.json()
    rows = []
    for it in items:
        c = it.get("component", {})
        if not args.all and c.get("state") != "ACTIVE":
            continue
        rows.append((
            str(c.get("id") or ""),
            (c.get("title") or "")[:42],
            _fmt_date(c.get("activationDate")),
            _fmt_date(c.get("nextApplyDate")),
            (_price_str(it) or "")[:10] if args.all else (c.get("cyclicType") or ""),
            c.get("state") or "",
        ))
    if not rows:
        print("Brak pakietów do pokazania.", file=sys.stderr)
        return
    last = "Cena" if args.all else "Cykl"
    hdr = ("id", "Pakiet / usługa", "Aktywacja", "Odnowienie", last)
    w = [max(len(hdr[i]), max(len(r[i]) for r in rows)) for i in range(5)]
    print(f"Konto/numer: {s.get('user_id')}  ({len(rows)} pozycji)\n")
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr)))
    print("  ".join("-" * w[i] for i in range(5)))
    for r0 in rows:
        print("  ".join(str(r0[i]).ljust(w[i]) for i in range(5))
              + (f"  [{r0[5]}]" if args.all else ""))
    if args.all:
        print("\nWłącz: ./play24.py activate <id>   (wyłącz: deactivate <id>)", file=sys.stderr)


def _find_component(s, component_id):
    r = call(s, "GET", "ms-components", 8, "components/{userId}")
    if not r.ok:
        show(r); sys.exit(2)
    for it in r.json():
        c = it.get("component", {})
        if str(c.get("id")) == str(component_id):
            return it, c
    sys.exit(f"Nie znaleziono komponentu id={component_id}. Lista: ./play24.py packages --all")


def _price_str(it):
    p = it.get("price") or {}
    if isinstance(p, dict):
        return p.get("formatted") or p.get("amount") or ""
    return str(p or "")


def _refresh_token(s):
    """DELETE api/fido/token/refresh/{profileId}/{userId} — odświeża token sesji (jak Authenticator)."""
    pid, uid = s.get("profile_id"), s.get("user_id")
    return SESSION.delete(f"{SSO}/api/fido/token/refresh/{pid}/{uid}", headers=headers(s), timeout=30)


def _components_post(s, body, debug=False):
    """POST modyfikacji komponentu (ms-services/v1/components — write; ms-components/v8 to tylko odczyt)."""
    url = f"{GW}/ms-services/v1/components/{s.get('user_id')}"
    r = SESSION.post(url, headers=headers(s), json=body, timeout=30)
    try:
        return r, r.json()
    except ValueError:
        return r, None


def _char_get(chars, name):
    for c in chars or []:
        if c.get("name") == name:
            return c.get("value")
    return None


def _step_up_and_retry(s, args, comp, op_type, conflict, base_body):
    """SCA step-up (recepta z podsłuchu): authorize/direct FIDO → podpis passkey → ponowienie z operationId."""
    if wa is None:
        sys.exit("Brak modułu play24_passkey.py do step-upu.")
    pid = s.get("profile_id")
    op_id = conflict.get("operationId")
    pk = wa.Passkey.load(passkey_path(s.get("msisdn") or s.get("user_id")))
    # 1) start: authorize/direct (acr/hash/operationId z 409, reszta null)
    start_body = {"acr": "FIDO", "hash": conflict.get("hash"), "operationId": op_id,
                  "bindingMessage": None, "loginHint": None, "loginHintType": None,
                  "nonce": None, "payload": None, "redirectUri": None, "state": None}
    r1, j1 = sso("POST", f"api/standard/{pid}/authorize/direct", body=start_body, debug=args.debug)
    if not r1.ok or not isinstance(j1, dict):
        sys.exit("Step-up start (authorize/direct) nieudany — patrz wyżej.")
    nonce = j1.get("nonce")
    chars = j1.get("characteristic") or []
    challenge = _char_get(chars, "challenge")
    cred_id = _char_get(chars, "public-key")       # credentialId zarejestrowanego passkey
    rp_id = _char_get(chars, "rpId") or s.get("rp_id")
    if not challenge or not nonce:
        sys.exit(f"Brak challenge/nonce: {list(j1)}")
    # 2) podpis passkey (clientDataJSON typ webauthn.get, origin=rpId)
    assertion = wa.get_assertion({"challenge": challenge, "nonce": nonce}, pk, rp_id, rp_id)
    resp = assertion["response"]
    # 3) finish: characteristic [id, clientDataJSON, authenticatorData, signature]
    fin_body = {"action": "FIDO_REQUIRED", "characteristic": [
        {"name": "id", "value": cred_id or assertion["id"]},
        {"name": "clientDataJSON", "value": resp["clientDataJSON"]},
        {"name": "authenticatorData", "value": resp["authenticatorData"]},
        {"name": "signature", "value": resp["signature"]},
    ]}
    r2, j2 = sso("PUT", f"api/standard/{pid}/authorize/direct/{nonce}", body=fin_body, debug=args.debug)
    if not r2.ok or not isinstance(j2, dict) or j2.get("action") != "TOKEN":
        sys.exit("Step-up finish nieudany (brak action=TOKEN) — patrz wyżej.")
    print("\n→ Step-up OK (action=TOKEN). Ponawiam aktywację z operationId…", file=sys.stderr)
    # 4) ponowienie components z operationId z 409
    retry_body = dict(base_body); retry_body["operationId"] = op_id
    r3, j3 = _components_post(s, retry_body, debug=args.debug)
    print(f"\n[retry] HTTP {r3.status_code}", file=sys.stderr)
    if j3 is not None:
        print(json.dumps(j3, indent=2, ensure_ascii=False))
    if r3.ok:
        print(f"\n✅ {op_type} zakończone — pakiet włączy się w ciągu kilku minut.", file=sys.stderr)
    else:
        sys.exit(2)


def _modify_component(s, args, op_type):
    """Wspólna logika ACTIVATE/DEACTIVATE z potwierdzeniem i obsługą OTP."""
    import uuid
    it, c = _find_component(s, args.component_id)
    # znajdź operację danego typu
    op = next((o for o in (it.get("operations") or []) if o.get("type") == op_type), None)
    title = c.get("title")
    price = _price_str(it)
    label = (op or {}).get("title") or op_type
    print(f"\n{op_type}: '{title}'  (id={c.get('id')}, typ={c.get('componentType') or c.get('type')})",
          file=sys.stderr)
    if price:
        print(f"  Cena/koszt: {price}", file=sys.stderr)
    if op and op.get("regulation"):
        import re
        reg = re.sub("<[^>]+>", "", op["regulation"])[:300]
        print(f"  Regulamin: {reg}", file=sys.stderr)
    if not op:
        print(f"  UWAGA: brak operacji typu {op_type} w danych komponentu — próbuję mimo to.", file=sys.stderr)
    # POTWIERDZENIE (chyba że --yes); to realny zakup/zmiana na koncie
    if not args.yes:
        ans = input(f"Potwierdź {op_type} '{title}' {('('+price+') ') if price else ''}— wpisz TAK: ")
        if ans.strip().upper() != "TAK":
            sys.exit("Anulowano.")
    body = {
        "type": op_type,
        "componentId": str(c.get("id")),
        "componentType": c.get("componentType") or c.get("type"),
        "params": [],
        "email": args.email or (s.get("profile") or {}).get("email"),
        "otp": args.otp,
        "operationId": None,
    }
    r, j = _components_post(s, body, debug=args.debug)
    print(f"\nHTTP {r.status_code}", file=sys.stderr)
    if j is not None:
        print(json.dumps(j, indent=2, ensure_ascii=False))

    # 409 MP0174 = wyzwanie SCA (step-up). Serwer podaje operationId/hash/acrType.
    if r.status_code == 409 and isinstance(j, dict) and (j.get("operationId") or j.get("hash")):
        acr = j.get("acrType") or j.get("acr")
        print(f"\n→ Operacja wymaga autoryzacji (SCA): acrType={acr} operationId={j.get('operationId')}", file=sys.stderr)
        if str(acr).upper().startswith("FIDO") and not args.no_stepup:
            print("   → step-up passkey'em (authorize/direct)…", file=sys.stderr)
            _step_up_and_retry(s, args, c, op_type, j, body)
            return
        if j.get("requiresOTP"):
            sys.exit(f"\n→ Wymagany kod SMS. Ponów: ./play24.py {op_type.lower()} {c.get('id')} --otp <KOD>")
        sys.exit("\n(step-up pominięty / nieobsługiwany acrType)")
    if r.ok:
        for k in ("pending_op_token", "pending_op_id", "pending_op_hash"):
            s.pop(k, None)
        save_session(s)
        link = (j or {}).get("redirectLink")
        print(f"\n✅ {op_type} wysłane." + (f" Link/płatność: {link}" if link else
              " Usługa włączy się w ciągu kilku minut."), file=sys.stderr)
    else:
        sys.exit(2)


def cmd_activate(s, args):
    _modify_component(s, args, "ACTIVATE")


def cmd_deactivate(s, args):
    _modify_component(s, args, "DEACTIVATE")


def cmd_offers(s, args):
    ms, v = gw_for("offers")
    show(call(s, "GET", ms, v, "offers/{userId}"))


def cmd_finances(s, args):
    ms, v = gw_for("finances")
    show(call(s, "GET", ms, v, "finances/{userId}/info"))


def cmd_invoices(s, args):
    ms, v = gw_for("finances")
    show(call(s, "GET", ms, v, "finances/{userId}/documents",
              query={"onlyPaid": "false", "offset": "0"}))


def cmd_account(s, args):
    ms, v = gw_for("customers")
    show(call(s, "GET", ms, v, "customers/{userId}"))


def cmd_components(s, args):
    ms, v = gw_for("components")
    show(call(s, "GET", ms, v, "components/{userId}"))


def cmd_notifications(s, args):
    ms, v = gw_for("notifications")
    show(call(s, "GET", ms, v, "notifications/{userId}"))


def cmd_history(s, args):
    ms, v = gw_for("activities")
    show(call(s, "GET", ms, v, "activities/{userId}/history"))


def cmd_sim(s, args):
    ms, v = gw_for("sim")
    show(call(s, "GET", ms, v, "sim/{userId}/information"))


def cmd_raw(s, args):
    body = json.loads(args.body) if args.body else None
    show(call(s, args.method.upper(), args.ms, args.version, args.path, body=body))


def cmd_whoami(s, args):
    print(json.dumps({k: v for k, v in s.items() if k != "refresh_token"},
                     indent=2, ensure_ascii=False))


# ----------------------------------------------------------------------------- CLI
def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--token", help="gotowy access_token (rzadko używany — apka działa na cookies)")
    common.add_argument("--cookie", help="surowy nagłówek Cookie z przechwyconej sesji: 'a=1; b=2'")
    common.add_argument("--user-id", help="identyfikator abonenta {userId}")
    common.add_argument("--kind", default="VOICE", choices=["VOICE", "DATA", "FIX", "TV"],
                        help="serviceKind dla saldo (domyślnie VOICE)")
    common.add_argument("--type", default="POSTPAID", choices=["PREPAID", "POSTPAID", "MIX"],
                        help="serviceType dla saldo (domyślnie POSTPAID)")
    common.add_argument("--debug", action="store_true")

    p = argparse.ArgumentParser(description="Nieoficjalny klient CLI Play24", parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("login-ip", help="logowanie po IP (sieć Play)", parents=[common])
    sp.add_argument("--msisdn", required=True, help="numer telefonu, np. 48500100200")
    sp.set_defaults(fn=cmd_login_ip)

    sl = sub.add_parser("login", help="EKSPERYMENTALNE: logowanie hasłem (SSO find-handlers→kyc)",
                        parents=[common])
    sl.add_argument("--msisdn", required=True, help="numer telefonu, np. 48500100200")
    sl.add_argument("--password", help="hasło (pominięte = pytanie interaktywne)")
    sl.set_defaults(fn=cmd_login)

    rs = sub.add_parser("register-start", parents=[common],
                        help="onboarding krok 1: wyślij kod SMS na numer")
    rs.add_argument("--msisdn", required=True, help="numer, np. 48500100200")
    rs.add_argument("--profile-type", default="STANDARD",
                    choices=["STANDARD", "EMAIL_PREPAID_DIGITAL"])
    rs.set_defaults(fn=cmd_register_start)

    ro = sub.add_parser("register-otp", parents=[common],
                        help="onboarding krok 2: podaj kod SMS → podpięcie passkey")
    ro.add_argument("--code", required=True, help="kod z SMS")
    ro.add_argument("--identifier", help="identyfikator do FIDO register (domyślnie userId/msisdn)")
    ro.add_argument("--no-fido", action="store_true", help="zatrzymaj po weryfikacji OTP (sam krok FIDO osobno)")
    ro.set_defaults(fn=cmd_register_otp)

    rf = sub.add_parser("register-fido", parents=[common],
                        help="krok FIDO register (po register-otp --no-fido)")
    rf.add_argument("--identifier", help="identyfikator do FIDO register")
    rf.add_argument("--full-body", action="store_true",
                    help="wyślij pełny body (attestation+authenticatorSelection) zamiast minimalnego")
    rf.set_defaults(fn=cmd_register_fido)

    au = sub.add_parser("auth", parents=[common],
                        help="logowanie zarejestrowanym passkeyem (FIDO2)")
    au.add_argument("--msisdn", help="numer (domyślnie z sesji)")
    au.set_defaults(fn=cmd_auth)

    ac = sub.add_parser("accounts", parents=[common],
                        help="lista lokalnie zarejestrowanych numerów/kont (osobne profile)")
    ac.set_defaults(fn=cmd_accounts)

    nu = sub.add_parser("numbers", parents=[common],
                        help="lista numerów na AKTYWNYM koncie (msisdn/list)")
    nu.set_defaults(fn=cmd_numbers)

    sw = sub.add_parser("switch", parents=[common], help="przełącz aktywny numer (msisdn-switch)")
    sw.add_argument("msisdn", help="numer docelowy, np. 48500100200 lub 500100200")
    sw.set_defaults(fn=cmd_switch)

    pkg = sub.add_parser("packages", parents=[common],
                         help="aktywne pakiety/usługi z datami aktywacji i odnowienia")
    pkg.add_argument("--all", action="store_true", help="pokaż też nieaktywne (cały katalog + id + cena)")
    pkg.set_defaults(fn=cmd_packages)

    actv = sub.add_parser("activate", parents=[common],
                          help="WŁĄCZ pakiet/usługę (realny zakup — wymaga potwierdzenia)")
    actv.add_argument("component_id", help="id komponentu (z: packages --all)")
    actv.add_argument("--otp", help="kod SMS, gdy operacja wymaga potwierdzenia OTP")
    actv.add_argument("--email", help="e-mail do regulaminu (wymagany raz na konto przy 1. zakupie)")
    actv.add_argument("--yes", action="store_true", help="pomiń interaktywne potwierdzenie")
    actv.add_argument("--no-stepup", action="store_true", help="nie próbuj auto-autoryzacji FIDO (tylko pokaż wyzwanie)")
    actv.set_defaults(fn=cmd_activate)

    deactv = sub.add_parser("deactivate", parents=[common],
                            help="WYŁĄCZ pakiet/usługę (wymaga potwierdzenia)")
    deactv.add_argument("component_id", help="id komponentu (z: packages)")
    deactv.add_argument("--otp", help="kod SMS, gdy operacja wymaga potwierdzenia")
    deactv.add_argument("--email", help="e-mail (zwykle niepotrzebny przy wyłączaniu)")
    deactv.add_argument("--yes", action="store_true", help="pomiń interaktywne potwierdzenie")
    deactv.add_argument("--no-stepup", action="store_true", help="nie próbuj auto-autoryzacji FIDO")
    deactv.set_defaults(fn=cmd_deactivate)

    for name, fn, helptxt in [
        ("balance",       cmd_balance,       "saldo główne"),
        ("balances-all",  cmd_balances_all,  "wszystkie liczniki/pakiety"),
        ("offers",        cmd_offers,        "oferty"),
        ("finances",      cmd_finances,      "podsumowanie finansów"),
        ("invoices",      cmd_invoices,      "faktury / dokumenty"),
        ("account",       cmd_account,       "dane konta/klienta"),
        ("components",    cmd_components,    "usługi / komponenty taryfy"),
        ("notifications", cmd_notifications, "powiadomienia"),
        ("history",       cmd_history,       "historia aktywności"),
        ("sim",           cmd_sim,           "informacje o SIM"),
        ("whoami",        cmd_whoami,        "pokaż zapisaną sesję"),
    ]:
        spx = sub.add_parser(name, help=helptxt)
        spx.set_defaults(fn=fn)

    spr = sub.add_parser("raw", help="dowolny endpoint: raw METHOD MS VERSION PATH [--body JSON]")
    spr.add_argument("method")
    spr.add_argument("ms")
    spr.add_argument("version")
    spr.add_argument("path")
    spr.add_argument("--body")
    spr.set_defaults(fn=cmd_raw)

    args = p.parse_args()
    s = load_session()
    if args.token:
        s["access_token"] = args.token
    if getattr(args, "cookie", None):
        add_cookie_header(args.cookie)
    if args.user_id:
        s["user_id"] = args.user_id
    args.fn(s, args)


if __name__ == "__main__":
    main()

"""
play24lib — Play24 jako biblioteka (do skryptów, np. monitoring w cron).

Wymaga wcześniejszego onboardingu numeru klientem CLI (`play24.py register-start/otp`),
który zapisuje profil + passkey w ~/.play24/. Biblioteka loguje się passkeyem (FIDO2)
i zwraca sparsowane dane.

Przykład:
    from play24lib import Play24
    p = Play24("48500100200").login()
    s = p.summary()
    print(s["balance_pln"], s["account_expires"], s["data_gb"], s["minutes"])
"""
import base64
import datetime as _dt
import hashlib
import json
import os
import re
import struct

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

GW = "https://play24-cloud.play.pl/cloud/play24/gateway"
SSO = "https://login-cloud.play.pl/cloud/sso-customers/gateway/sso-mobile"
OAUTH = "https://oauth.play.pl/oauth"
REDIRECT = "https://firebase.play.pl/oauth-callback/"
CLIENT_ID = "play24_app"
APP_VERSION = "11.9.0"
STORE = os.path.expanduser("~/.play24/session.json")
_AUTH_SEL = {"authenticatorAttachment": "platform", "requireResidentKey": True,
             "userVerification": "required"}

# mikroserwis + wersja dla typowych obszarów (rejestr ms-* z APK)
SERVICES = {
    "balances": ("ms-balances", 3), "offers": ("ms-offers", 12), "finances": ("ms-finances", 4),
    "e-invoices": ("ms-finances", 4), "clients": ("ms-clients", 3), "customers": ("ms-clients", 3),
    "agreements": ("ms-clients", 3), "components": ("ms-components", 8), "payments": ("ms-payments", 6),
    "recharges": ("ms-payments", 6), "transactions": ("ms-payments", 6), "activities": ("ms-activities", 2),
    "sim": ("ms-sim", 2), "esim": ("ms-sim", 2), "verify": ("ms-sim", 2),
    "notifications": ("ms-notifications", 4), "complaints": ("ms-complaints", 2), "limits": ("ms-balances", 3),
    "groups": ("ms-groups", 3), "order": ("ms-order", 1), "sales": ("ms-salesmanager", 4),
    "version": ("ms-appinfo", 1), "services": ("ms-services", 1),
}

_WEBVIEW_UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/131.0.0.0 Mobile Safari/537.36")


# ============================================================================= autentykator WebAuthn/FIDO2
# Software'owy autentykator: odtwarza dokładnie to, co robi apka Play24 (play.fido2.*), ale klucz
# prywatny trzymamy w pliku zamiast w Android Keystore. Format zweryfikowany z dekompilatu:
#   - attestation = "none";  attestationObject = CBOR {authData, fmt:"none", attStmt:{}}
#   - authData = rpIdHash(32) || flags(1) || signCount(4 BE) || attestedCredentialData
#   - attestedCredentialData = AAGUID(16×0) || credIdLen(2 BE) || credId || COSE_pubkey
#   - COSE_pubkey (ES256/EC2/P-256) = {1:2, 3:-7, -1:1, -2:x(32), -3:y(32)}
#   - clientDataJSON = {type, challenge:<echo>, origin:<rpId>};  klucz secp256r1, podpis ES256(-7)
#   - base64 pól = STANDARD (Android Base64.NO_WRAP, z paddingiem, bez url-safe)

def _cbor_head(major, n):
    if n < 24:
        return bytes([(major << 5) | n])
    if n < 256:
        return bytes([(major << 5) | 24, n])
    if n < 65536:
        return bytes([(major << 5) | 25]) + struct.pack(">H", n)
    if n < 2 ** 32:
        return bytes([(major << 5) | 26]) + struct.pack(">I", n)
    return bytes([(major << 5) | 27]) + struct.pack(">Q", n)


def cbor(v):
    """Minimalny enkoder CBOR (z zachowaniem kolejności kluczy, jak LinkedHashMap w apce)."""
    if isinstance(v, bool):
        return bytes([0xF5 if v else 0xF4])
    if isinstance(v, int):
        return _cbor_head(0, v) if v >= 0 else _cbor_head(1, -1 - v)
    if isinstance(v, bytes):
        return _cbor_head(2, len(v)) + v
    if isinstance(v, str):
        b = v.encode()
        return _cbor_head(3, len(b)) + b
    if isinstance(v, list):
        return _cbor_head(4, len(v)) + b"".join(cbor(x) for x in v)
    if isinstance(v, dict):
        out = _cbor_head(5, len(v))
        for k, val in v.items():
            out += cbor(k) + cbor(val)
        return out
    raise TypeError(f"CBOR: nieobsługiwany typ {type(v)}")


def b64(data: bytes) -> str:
    """Base64 standard (jak Android NO_WRAP, z paddingiem)."""
    return base64.b64encode(data).decode()


def b64d(s: str) -> bytes:
    s = s.strip()
    pad = (-len(s)) % 4
    s2 = s.replace("-", "+").replace("_", "/") + ("=" * pad)   # toleruj standard i url-safe
    return base64.b64decode(s2)


class Passkey:
    """Para kluczy EC P-256 + credentialId + licznik podpisów, trzymane w pliku."""

    def __init__(self, private_key, cred_id: bytes, sign_count: int = 0):
        self.private_key = private_key
        self.cred_id = cred_id
        self.sign_count = sign_count

    @classmethod
    def create(cls):
        return cls(ec.generate_private_key(ec.SECP256R1()), os.urandom(32), 0)

    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "private_key": self.private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
            "cred_id": b64(self.cred_id),
            "sign_count": self.sign_count,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(path, 0o600)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            d = json.load(f)
        pk = serialization.load_pem_private_key(d["private_key"].encode(), password=None)
        return cls(pk, b64d(d["cred_id"]), int(d.get("sign_count", 0)))

    def cose_key(self) -> bytes:
        """COSE public key (ES256 / EC2 / P-256)."""
        nums = self.private_key.public_key().public_numbers()
        x = nums.x.to_bytes(32, "big")
        y = nums.y.to_bytes(32, "big")
        return cbor({1: 2, 3: -7, -1: 1, -2: x, -3: y})

    def sign(self, data: bytes) -> bytes:
        return self.private_key.sign(data, ec.ECDSA(hashes.SHA256()))   # ECDSA-SHA256, DER


def _client_data(typ: str, challenge: str, origin: str) -> bytes:
    # kolejność pól jak w play.fido2.client.model.a: type, challenge, origin
    return json.dumps({"type": typ, "challenge": challenge, "origin": origin},
                      separators=(",", ":")).encode()


def _auth_data(rp_id: str, flags: int, sign_count: int, attested: bytes = b"") -> bytes:
    rp_id_hash = hashlib.sha256(rp_id.encode()).digest()
    return rp_id_hash + bytes([flags]) + struct.pack(">I", sign_count) + attested


# flagi authenticatorData: UP=0x01, UV=0x04, AT=0x40
FLAGS_REGISTER = 0x45  # UP | UV | AT
FLAGS_ASSERT = 0x05    # UP | UV


def make_credential(options: dict, rp_id: str, origin: str):
    """Rejestracja: z RegisterOptions buduje nowy passkey + RegisterServerPublicKeyCredential."""
    pk = Passkey.create()
    client_data = _client_data("webauthn.create", options["challenge"], origin)
    attested = (
        b"\x00" * 16                              # AAGUID
        + struct.pack(">H", len(pk.cred_id))      # credIdLen
        + pk.cred_id                              # credId
        + pk.cose_key()                           # COSE pubkey
    )
    auth_data = _auth_data(rp_id, FLAGS_REGISTER, pk.sign_count, attested)
    attestation_object = cbor({"authData": auth_data, "fmt": "none", "attStmt": {}})
    cid_b64 = b64(pk.cred_id)
    credential = {
        "nonce": options.get("nonce"), "id": cid_b64, "rawId": cid_b64,
        "response": {"clientDataJSON": b64(client_data),
                     "attestationObject": b64(attestation_object)},
        "type": "public-key",
    }
    return pk, credential


def get_assertion(options: dict, pk: "Passkey", rp_id: str, origin: str) -> dict:
    """Logowanie: z AuthenticateOptions buduje podpisaną asercję."""
    client_data = _client_data("webauthn.get", options["challenge"], origin)
    pk.sign_count += 1
    auth_data = _auth_data(rp_id, FLAGS_ASSERT, pk.sign_count)
    signature = pk.sign(auth_data + hashlib.sha256(client_data).digest())
    cid_b64 = b64(pk.cred_id)
    return {
        "nonce": options.get("nonce"), "id": cid_b64, "rawId": cid_b64,
        "response": {"clientDataJSON": b64(client_data), "authenticatorData": b64(auth_data),
                     "signature": b64(signature), "userHandle": None},
        "type": "public-key",
    }


# ============================================================================= klient / transport
def build_headers(device_id, oauth=False, token=None):
    """Jedyny budowniczy nagłówków (współdzielony przez bibliotekę i CLI)."""
    h = {
        "App-Version": APP_VERSION, "OS-Type": "android", "OS-Version": "33",
        "deviceId": device_id, "Device-Id": device_id,
        "Device-Manufacturer": "cli", "Device-Model": "play24-cli",
        "Accept-Language": "pl", "Accept": "application/json", "Content-Type": "application/json",
        "User-Agent": _WEBVIEW_UA if oauth else "play24/android",
    }
    if token and not oauth:
        h["Authorization"] = "Bearer " + token
    return h


def webauthn_login(session, profile_id, pk, rp_id, headers):
    """Wspólny flow logowania passkeyem (FIDO2): authenticate start→podpis→finish.
    Ustawia cookies w 'session'. Zwraca ProfileDto (dict). Rzuca Play24Error przy błędzie."""
    session.cookies.clear()
    r = session.post(f"{SSO}/api/fido/authenticate", headers=headers,
                     json={"profileId": profile_id, "authenticatorSelection": _AUTH_SEL}, timeout=30)
    if not r.ok:
        raise Play24Error(f"authenticate start: HTTP {r.status_code} {r.text[:200]}")
    opts = r.json()
    rpid = opts.get("rpId") or rp_id
    assertion = get_assertion({"challenge": opts["challenge"], "nonce": opts.get("nonce")}, pk, rpid, rpid)
    r2 = session.post(f"{SSO}/api/fido/authenticate/finish", headers=headers, json=assertion, timeout=30)
    if not r2.ok:
        raise Play24Error(f"authenticate finish: HTTP {r2.status_code} {r2.text[:200]}")
    return r2.json() if r2.content else {}


def norm_msisdn(m):
    d = "".join(ch for ch in str(m) if ch.isdigit())
    return ("48" + d) if len(d) == 9 else d


def passkey_path(msisdn, store=STORE):
    return os.path.join(os.path.dirname(store), f"passkey_{norm_msisdn(msisdn)}.json")


# ----------------------------------------------------------------------------- store (persystencja)
def load_store(store=STORE):
    try:
        with open(store) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_store(data, store=STORE):
    import uuid as _uuid  # tylko tu
    data.setdefault("device_id", str(_uuid.uuid4()))
    os.makedirs(os.path.dirname(store), exist_ok=True)
    with open(store, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.chmod(store, 0o600)


def device_id(data):
    if not data.get("device_id"):
        import uuid as _uuid
        data["device_id"] = str(_uuid.uuid4())
    return data["device_id"]


def accounts(store=STORE):
    """Lokalnie zarejestrowane numery: [{msisdn, profile_id, registered}]."""
    profs = (load_store(store).get("profiles") or {})
    return [{"msisdn": k, "profile_id": v.get("profile_id"),
             "registered": os.path.exists(passkey_path(k, store))} for k, v in profs.items()]


# ----------------------------------------------------------------------------- onboarding (2 kroki — SMS pomiędzy)
def register_start(msisdn, store=STORE, profile_type="STANDARD"):
    """Krok 1: find-handlers + kyc/register → wysyła kod SMS. Zwraca {nonce, characteristic}."""
    data = load_store(store)
    dev = device_id(data)
    sess = requests.Session()
    h = build_headers(dev)
    handles = [v["profile_id"] for v in (data.get("profiles") or {}).values() if v.get("profile_id")]
    sess.post(f"{SSO}/api/standard/find-handlers/{msisdn}", headers=h,
              json={"userHandles": handles}, timeout=30)
    r = sess.post(f"{SSO}/api/kyc/register", headers=h,
                  json={"type": profile_type, "input": str(msisdn)},
                  params={"hint": "MSISDN_OTP_REQUIRED"}, timeout=30)
    j = r.json() if r.content else {}
    if not r.ok or not j.get("nonce"):
        raise Play24Error(f"kyc/register: HTTP {r.status_code} {j or r.text[:200]}")
    data.setdefault("_pending", {})[norm_msisdn(msisdn)] = {
        "nonce": j["nonce"], "cookies": sess.cookies.get_dict(), "device_id": dev, "input": str(msisdn)}
    save_store(data, store)
    ch = j.get("characteristic") or {}
    return {"nonce": j["nonce"], "requiredAction": j.get("requiredAction"),
            "sms_length": ch.get("length"), "characteristic": ch}


def register_complete(msisdn, otp, store=STORE):
    """Krok 2: kyc/register/{nonce} {password:otp} → fido register → zapis profilu+passkey. Zwraca ProfileDto."""
    data = load_store(store)
    key = norm_msisdn(msisdn)
    pend = (data.get("_pending") or {}).get(key)
    if not pend:
        raise Play24Error("Brak rozpoczętej rejestracji — najpierw register_start.")
    sess = requests.Session()
    for k, v in (pend.get("cookies") or {}).items():
        sess.cookies.set(k, v)
    dev = pend.get("device_id") or device_id(data)
    h = build_headers(dev)
    # kyc finish — kod OTP w polu 'password'
    r = sess.put(f"{SSO}/api/kyc/register/{pend['nonce']}", headers=h, json={"password": str(otp)}, timeout=30)
    j = r.json() if r.content else {}
    if not r.ok:
        raise Play24Error(f"OTP odrzucony: HTTP {r.status_code} {j or r.text[:200]}")
    if j.get("requiredAction") != "FINISH_FIDO":
        raise Play24Error(f"requiredAction={j.get('requiredAction')} (oczekiwano FINISH_FIDO): {j}")
    nonce = j.get("nonce") or pend["nonce"]
    # fido register (authenticatorSelection WYMAGANE)
    rr = sess.post(f"{SSO}/api/fido/register", headers=h,
                   json={"nonce": nonce, "identifier": pend["input"],
                         "attestation": "none", "authenticatorSelection": _AUTH_SEL}, timeout=30)
    opts = rr.json() if rr.content else {}
    if not rr.ok or not isinstance(opts, dict) or not opts.get("challenge"):
        raise Play24Error(f"fido/register: HTTP {rr.status_code} {opts or rr.text[:200]}")
    rp = opts.get("relayingParty") or opts.get("rp") or {}
    rp_id = rp.get("id") or opts.get("rpId")
    pk, credential = make_credential(opts, rp_id, rp_id)
    rf = sess.post(f"{SSO}/api/fido/register/finish", headers=h, json=credential, timeout=30)
    profile = rf.json() if rf.content else {}
    if not rf.ok:
        raise Play24Error(f"fido/register/finish: HTTP {rf.status_code} {profile or rf.text[:200]}")
    pk.save(passkey_path(key, store))
    data.setdefault("profiles", {})[key] = {
        "profile_id": profile.get("profileId"),
        "user_id": profile.get("identifier") or key, "rp_id": rp_id}
    (data.get("_pending") or {}).pop(key, None)
    save_store(data, store)
    return profile


# ----------------------------------------------------------------------------- parsery
def parse_amount(v):
    """'13,51' / '1.19' / 13 → float (None gdy się nie da)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def to_gb(value, unit):
    """Zamień wartość+jednostkę na GB (float)."""
    a = parse_amount(value)
    if a is None:
        return None
    u = (unit or "").upper()
    return {"GB": a, "MB": a / 1024, "KB": a / 1024 / 1024, "TB": a * 1024}.get(u, a)


def to_minutes(value):
    """'46:14' (mm:ss) lub '90' → minuty (float)."""
    if value is None:
        return None
    s = str(value).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            mm = int(parts[0]); ss = int(parts[1]) if len(parts) > 1 else 0
            return mm + ss / 60.0
        except ValueError:
            return None
    return parse_amount(s)


def parse_dt(s):
    """ISO-8601 (z apki) → datetime aware. None gdy brak/parse error."""
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(str(s))
    except ValueError:
        try:
            return _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except ValueError:
            return None


def days_until(s):
    """Ile dni do daty (float). None gdy brak."""
    d = parse_dt(s)
    if not d:
        return None
    now = _dt.datetime.now(d.tzinfo) if d.tzinfo else _dt.datetime.now()
    return (d - now).total_seconds() / 86400.0


def package_status(p, validity_days=31):
    """Inteligentna klasyfikacja pakietu:
    - cykliczny (cyclicType≠NONE lub jest nextApplyDate) → event 'renew', data = nextApplyDate
    - jednorazowy → event 'expire', data = expirationDate, a gdy brak: activationDate + validity_days
    - usługa stała (brak dat) → event None
    Zwraca {cyclic, event, date, days, title}.
    """
    cyclic = bool(p.get("cyclicType") and p["cyclicType"] != "NONE") or bool(p.get("nextApplyDate"))
    if cyclic:
        d = p.get("nextApplyDate")
        return {"cyclic": True, "event": "renew", "date": d, "days": days_until(d), "title": p.get("title")}
    exp = p.get("expirationDate")
    if not exp and p.get("activationDate"):
        a = parse_dt(p["activationDate"])
        if a:
            exp = (a + _dt.timedelta(days=validity_days)).isoformat()
    event = "expire" if exp else None
    return {"cyclic": False, "event": event, "date": exp, "days": days_until(exp), "title": p.get("title")}


class Play24Error(Exception):
    pass


class Play24:
    """Klient Play24 dla jednego numeru. Loguje się passkeyem zapisanym przez CLI."""

    def __init__(self, msisdn, store=STORE, kind="VOICE", service_type="PREPAID"):
        self.msisdn = norm_msisdn(msisdn)
        self.kind = kind
        self.service_type = service_type
        self._store = store
        self.session = requests.Session()
        data = load_store(store)
        prof = (data.get("profiles") or {}).get(self.msisdn)
        if not prof:
            raise Play24Error(f"Numer {self.msisdn} nie jest zarejestrowany lokalnie "
                              f"(najpierw: register_start + register_complete).")
        self.profile_id = prof["profile_id"]
        self.user_id = prof.get("user_id") or self.msisdn
        self.rp_id = prof.get("rp_id") or "https://sso.play.pl"
        self._device_id = device_id(data)
        self.pk = Passkey.load(passkey_path(self.msisdn, store))

    # ---- transport
    def _headers(self):
        return build_headers(self._device_id)

    def login(self):
        """Uwierzytelnienie passkeyem (FIDO2) → cookies sesji."""
        prof = webauthn_login(self.session, self.profile_id, self.pk, self.rp_id, self._headers())
        self.pk.save(passkey_path(self.msisdn, self._store))   # zapisz zwiększony sign_count
        if isinstance(prof, dict):
            self.user_id = prof.get("identifier") or self.user_id
        return self

    def _gw(self, method, ms, ver, path, body=None, query=None):
        url = f"{GW}/{ms}/v{ver}/{path.replace('{userId}', self.user_id)}"
        r = self.session.request(method, url, headers=self._headers(),
                                 json=body, params=query, timeout=30)
        if not r.ok:
            raise Play24Error(f"{method} {ms}/{path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json() if r.content else None

    def _sso(self, method, path, body=None):
        r = self.session.request(method, f"{SSO}/{path}", headers=self._headers(), json=body, timeout=30)
        if not r.ok:
            raise Play24Error(f"{method} sso/{path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json() if r.content else None

    def raw(self, method, ms, ver, path, body=None, query=None):
        """Dowolny endpoint bramki ({userId} podstawiany)."""
        return self._gw(method.upper(), ms, str(ver).lstrip("vV"), path, body=body, query=query)

    # ---- wiele numerów na jednym koncie (jeden profil)
    def numbers(self):
        """Lista numerów na profilu (GET api/standard/{profileId}/msisdn/list)."""
        return self._sso("GET", f"api/standard/{self.profile_id}/msisdn/list") or []

    def switch(self, msisdn):
        """Przełącz aktywny numer w obrębie konta (msisdn-switch). Zwraca nowy user_id."""
        target = norm_msisdn(msisdn)
        if target == norm_msisdn(self.user_id):
            return self.user_id
        r = self.session.post(f"{SSO}/api/standard/{self.profile_id}/token/msisdn-switch/{target}",
                              headers=self._headers(), timeout=30)
        if not r.ok:
            j = r.json() if r.content else {}
            code = j.get("responseCode") if isinstance(j, dict) else None
            hint = " (numer nie jest na koncie? sprawdź numbers())" if code == "MP0035" else ""
            raise Play24Error(f"msisdn-switch {target}: HTTP {r.status_code} {code or ''}{hint}")
        self.user_id = target
        return self.user_id

    # ---- surowe dane
    def balance(self):
        """ms-balances/main → {type, main:{...}, balances:[...]} (saldo „Konto" + ważność konta)."""
        return self._gw("POST", "ms-balances", 3, "balances/{userId}/main",
                        body={"serviceKind": self.kind, "serviceType": self.service_type})

    def balances_all(self):
        """ms-balances/all → {balances:[...]} (KOMPLET liczników: dane + minuty + SMS itd.)."""
        return self._gw("POST", "ms-balances", 3, "balances/{userId}/all",
                        body={"serviceKind": self.kind, "serviceType": self.service_type})

    def account(self):
        return self._gw("GET", "ms-clients", 3, "clients/{userId}")

    def packages(self, active_only=True):
        """ms-components → lista aktywnych pakietów/usług (z activationDate/nextApplyDate/expirationDate)."""
        items = self._gw("GET", "ms-components", 8, "components/{userId}") or []
        out = []
        for it in items:
            c = it.get("component", {})
            if active_only and c.get("state") != "ACTIVE":
                continue
            price = it.get("price") or {}
            pv = price.get("value")
            out.append({
                "id": c.get("id"), "title": c.get("title"), "state": c.get("state"),
                "cyclicType": c.get("cyclicType"),
                "cyclic": bool(c.get("cyclicType") and c["cyclicType"] != "NONE") or bool(c.get("nextApplyDate")),
                "price_value": pv,                                  # grosze (z it.price)
                "price_pln": (pv / 100.0) if isinstance(pv, (int, float)) else None,
                "paid": bool(isinstance(pv, (int, float)) and pv > 0),
                "currency": price.get("currency"),
                "activationDate": c.get("activationDate"),
                "nextApplyDate": c.get("nextApplyDate"),
                "expirationDate": c.get("expirationDate"),
            })
        return out

    # ---- modyfikacja pakietów (write transakcyjny + SCA step-up) — patrz docs/ACTIVATION.md
    def _find_component(self, component_id):
        """Znajdź pozycję komponentu w katalogu (ms-components/v8 = ODCZYT)."""
        for it in (self._gw("GET", "ms-components", 8, "components/{userId}") or []):
            c = it.get("component", {})
            if str(c.get("id")) == str(component_id):
                return it, c
        raise Play24Error(f"Nie znaleziono komponentu id={component_id} (lista: packages(active_only=False)).")

    def _components_post(self, body):
        """POST do ms-services/v1/components/{userId} (ZAPIS). Zwraca (status_code, json)."""
        r = self.session.post(f"{GW}/ms-services/v1/components/{self.user_id}",
                              headers=self._headers(), json=body, timeout=30)
        try:
            return r.status_code, (r.json() if r.content else None)
        except ValueError:
            return r.status_code, None

    def _step_up(self, conflict):
        """SCA step-up FIDO (z 409 MP0174): authorize/direct start→podpis passkey→finish → action:TOKEN."""
        op_id = conflict.get("operationId")
        start = {"acr": "FIDO", "hash": conflict.get("hash"), "operationId": op_id,
                 "bindingMessage": None, "loginHint": None, "loginHintType": None,
                 "nonce": None, "payload": None, "redirectUri": None, "state": None}
        j1 = self._sso("POST", f"api/standard/{self.profile_id}/authorize/direct", body=start)
        if not isinstance(j1, dict):
            raise Play24Error("Step-up start (authorize/direct) bez odpowiedzi.")
        nonce = j1.get("nonce")
        chars = {c.get("name"): c.get("value") for c in (j1.get("characteristic") or [])}
        challenge = chars.get("challenge")
        cred_id = chars.get("public-key")
        rp_id = chars.get("rpId") or self.rp_id
        if not challenge or not nonce:
            raise Play24Error(f"Step-up: brak challenge/nonce ({list(j1)}).")
        assertion = get_assertion({"challenge": challenge, "nonce": nonce}, self.pk, rp_id, rp_id)
        self.pk.save(passkey_path(self.msisdn, self._store))
        resp = assertion["response"]
        fin = {"action": "FIDO_REQUIRED", "characteristic": [
            {"name": "id", "value": cred_id or assertion["id"]},
            {"name": "clientDataJSON", "value": resp["clientDataJSON"]},
            {"name": "authenticatorData", "value": resp["authenticatorData"]},
            {"name": "signature", "value": resp["signature"]},
        ]}
        j2 = self._sso("PUT", f"api/standard/{self.profile_id}/authorize/direct/{nonce}", body=fin)
        if not isinstance(j2, dict) or j2.get("action") != "TOKEN":
            raise Play24Error(f"Step-up finish bez action=TOKEN ({j2}).")
        return op_id

    def _modify(self, component_id, op_type, email=None, otp=None, auto_stepup=True):
        """Wspólna logika ACTIVATE/DEACTIVATE. Zwraca {ok, op_type, component_id, title, price, stepup, result}.
        NIE pyta interaktywnie — to robi warstwa CLI/MCP."""
        it, c = self._find_component(component_id)
        body = {
            "type": op_type, "componentId": str(c.get("id")),
            "componentType": c.get("componentType") or c.get("type"),
            "params": [], "email": email, "otp": otp, "operationId": None,
        }
        status, j = self._components_post(body)
        price = (it.get("price") or {})
        meta = {"op_type": op_type, "component_id": str(c.get("id")), "title": c.get("title"),
                "price": price.get("formatted") or price.get("amount")}
        # 409 MP0174 = wyzwanie SCA (step-up)
        if status == 409 and isinstance(j, dict) and (j.get("operationId") or j.get("hash")):
            acr = (j.get("acrType") or j.get("acr") or "")
            if str(acr).upper().startswith("FIDO") and auto_stepup:
                op_id = self._step_up(j)
                retry = dict(body); retry["operationId"] = op_id
                status, j = self._components_post(retry)
                if status >= 400:
                    raise Play24Error(f"{op_type} po step-upie: HTTP {status} {j}")
                return {**meta, "ok": True, "stepup": "fido", "result": j}
            if j.get("requiresOTP"):
                raise Play24Error(f"{op_type} wymaga kodu SMS — podaj otp=<KOD> (component_id={c.get('id')}).")
            raise Play24Error(f"{op_type} wymaga autoryzacji acrType={acr} (auto_stepup wyłączone).")
        if status >= 400:
            raise Play24Error(f"{op_type} {component_id}: HTTP {status} {j}")
        return {**meta, "ok": True, "stepup": None, "result": j}

    def activate(self, component_id, email=None, otp=None, auto_stepup=True):
        """WŁĄCZ pakiet/usługę (realny zakup). Auto step-up passkeyem przy SCA (409 MP0174)."""
        return self._modify(component_id, "ACTIVATE", email=email, otp=otp, auto_stepup=auto_stepup)

    def deactivate(self, component_id, email=None, otp=None, auto_stepup=True):
        """WYŁĄCZ pakiet/usługę. Auto step-up passkeyem przy SCA."""
        return self._modify(component_id, "DEACTIVATE", email=email, otp=otp, auto_stepup=auto_stepup)

    # ---- wygodne podsumowanie do monitoringu
    def counters(self):
        """Lista WSZYSTKICH liczników (z balances/all): [{type,name,available,unit,gb,minutes,expiresAt,isLow}]."""
        b = self.balances_all()
        res = []
        for x in (b.get("balances") or []):
            val = x.get("value") or {}
            res.append({
                "type": x.get("type"), "name": x.get("name"),
                "available": val.get("available"), "unit": val.get("unit"),
                "gb": to_gb(val.get("available"), val.get("unit")) if "INTERNET" in (x.get("type") or "") else None,
                "minutes": to_minutes(val.get("available")) if (x.get("type") == "MINUTES") else None,
                "expiresAt": x.get("expiresAt") or val.get("expiresAt"),
                "isLow": val.get("isLow"),
            })
        return res

    def summary(self):
        """Zwięzłe dane do progów: saldo, ważność konta, suma GB/minut, najbliższe wygaśnięcie pakietu."""
        b = self.balance()
        main = b.get("main") or {}
        mval = main.get("value") or {}
        cnts = self.counters()

        def _is_roam(t):
            t = (t or "").upper()
            return "EU" in t or "ROAM" in t
        data_gb = sum(c["gb"] for c in cnts if c["gb"] is not None and not _is_roam(c["type"]))
        data_gb_roaming = sum(c["gb"] for c in cnts if c["gb"] is not None and _is_roam(c["type"]))
        minutes = sum(c["minutes"] for c in cnts if c["minutes"] is not None)
        pkgs = self.packages()
        # najbliższa data wygaśnięcia/odnowienia aktywnego pakietu
        exp = [days_until(p["expirationDate"]) for p in pkgs if p["expirationDate"]]
        nxt = [days_until(p["nextApplyDate"]) for p in pkgs if p["nextApplyDate"]]
        return {
            "msisdn": self.user_id,
            "type": b.get("type"),
            "balance_pln": parse_amount(mval.get("available")),
            "balance_unit": mval.get("unit"),
            "account_expires": main.get("expiresAt"),
            "account_expires_days": days_until(main.get("expiresAt")),
            "data_gb": round(data_gb, 3),              # tylko krajowe (bez roamingu)
            "data_gb_roaming": round(data_gb_roaming, 3),
            "minutes": round(minutes, 2),
            "counters": cnts,
            "packages": pkgs,
            "package_expire_days": min(exp) if exp else None,
            "package_renew_days": min(nxt) if nxt else None,
        }

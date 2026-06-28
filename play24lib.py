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
import json
import os
import re
import datetime as _dt

import requests
import play24_passkey as wa

GW = "https://play24-cloud.play.pl/cloud/play24/gateway"
SSO = "https://login-cloud.play.pl/cloud/sso-customers/gateway/sso-mobile"
APP_VERSION = "11.9.0"
STORE = os.path.expanduser("~/.play24/session.json")
_AUTH_SEL = {"authenticatorAttachment": "platform", "requireResidentKey": True,
             "userVerification": "required"}


def norm_msisdn(m):
    d = "".join(ch for ch in str(m) if ch.isdigit())
    return ("48" + d) if len(d) == 9 else d


def passkey_path(msisdn, store=STORE):
    return os.path.join(os.path.dirname(store), f"passkey_{norm_msisdn(msisdn)}.json")


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
        self.session = requests.Session()
        with open(store) as f:
            data = json.load(f)
        prof = (data.get("profiles") or {}).get(self.msisdn)
        if not prof:
            raise Play24Error(f"Numer {self.msisdn} nie jest zarejestrowany lokalnie "
                              f"(uruchom: play24.py register-start --msisdn {msisdn}).")
        self.profile_id = prof["profile_id"]
        self.user_id = prof.get("user_id") or self.msisdn
        self.rp_id = prof.get("rp_id") or "https://sso.play.pl"
        self._device_id = data.get("device_id") or "play24lib"
        self.pk = wa.Passkey.load(passkey_path(self.msisdn, store))

    # ---- transport
    def _headers(self):
        return {
            "App-Version": APP_VERSION, "OS-Type": "android", "OS-Version": "33",
            "deviceId": self._device_id, "Accept-Language": "pl",
            "Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": "play24/android",
        }

    def login(self):
        """Uwierzytelnienie passkeyem (FIDO2) → cookies sesji."""
        self.session.cookies.clear()
        r = self.session.post(f"{SSO}/api/fido/authenticate",
                              headers=self._headers(),
                              json={"profileId": self.profile_id, "authenticatorSelection": _AUTH_SEL},
                              timeout=30)
        if not r.ok:
            raise Play24Error(f"authenticate start: HTTP {r.status_code} {r.text[:200]}")
        opts = r.json()
        rp_id = opts.get("rpId") or self.rp_id
        assertion = wa.get_assertion({"challenge": opts["challenge"], "nonce": opts.get("nonce")},
                                     self.pk, rp_id, rp_id)
        r2 = self.session.post(f"{SSO}/api/fido/authenticate/finish",
                               headers=self._headers(), json=assertion, timeout=30)
        if not r2.ok:
            raise Play24Error(f"authenticate finish: HTTP {r2.status_code} {r2.text[:200]}")
        self.pk.save(passkey_path(self.msisdn))   # zapisz zwiększony sign_count
        prof = r2.json() if r2.content else {}
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
        data_gb = sum(c["gb"] for c in cnts if c["gb"] is not None)
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
            "data_gb": round(data_gb, 3),
            "minutes": round(minutes, 2),
            "counters": cnts,
            "packages": pkgs,
            "package_expire_days": min(exp) if exp else None,
            "package_renew_days": min(nxt) if nxt else None,
        }

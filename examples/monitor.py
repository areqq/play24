#!/usr/bin/env python3
"""
Przykładowy monitor Play24 do crona — pilnuje progów na koncie.

Sprawdza: saldo (PLN), ważność konta, ilość GB i minut z pakietu, wiek pakietu od
aktywacji oraz bliskość wygaśnięcia/odnowienia pakietu. Wypisuje ostrzeżenia i kończy
kodem ≠0 gdy któryś próg przekroczony (cron wtedy wyśle maila).

Uruchom: python3 examples/monitor.py
Cron (codziennie 9:00):  0 9 * * *  cd /sciezka/do/repo && /usr/bin/python3 examples/monitor.py
Wymaga wcześniejszego onboardingu numeru przez CLI (play24.py register-start/otp).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from play24lib import Play24, days_until  # noqa: E402

# ── KONFIGURACJA: numer → progi (pomiń klucz, by nie sprawdzać danego progu) ──
WATCH = {
    "48500100200": dict(
        min_pln=5.0,             # alarm gdy saldo < 5 zł
        min_gb=0.5,              # alarm gdy łącznie < 0.5 GB
        min_minutes=10,          # alarm gdy łącznie < 10 min
        account_days=14,         # alarm gdy konto wygasa za < 14 dni
        package_age_days=25,     # alarm gdy pakiet aktywny od >= 25 dni (po dacie uruchomienia)
        package_expire_days=3,   # alarm gdy pakiet wygasa/odnowi się za <= 3 dni
    ),
    # "48500100201": dict(min_pln=10.0, min_gb=1.0),
}


def check(msisdn, t):
    s = Play24(msisdn).login().summary()
    a = []
    if t.get("min_pln") is not None and (s["balance_pln"] or 0) < t["min_pln"]:
        a.append(f"saldo {s['balance_pln']} {s['balance_unit']} < {t['min_pln']}")
    if t.get("account_days") is not None and s["account_expires_days"] is not None \
            and s["account_expires_days"] < t["account_days"]:
        a.append(f"konto wygasa za {s['account_expires_days']:.0f} dni ({s['account_expires'][:10]})")
    if t.get("min_gb") is not None and s["data_gb"] < t["min_gb"]:
        a.append(f"dane {s['data_gb']} GB < {t['min_gb']}")
    if t.get("min_minutes") is not None and s["minutes"] < t["min_minutes"]:
        a.append(f"minuty {s['minutes']:.0f} < {t['min_minutes']}")
    for p in s["packages"]:
        if t.get("package_age_days") and p["activationDate"]:
            age = -(days_until(p["activationDate"]) or 0)   # dni od aktywacji
            if age >= t["package_age_days"]:
                a.append(f"pakiet '{p['title']}' aktywny od {age:.0f} dni (>= {t['package_age_days']})")
        for key, label in (("expirationDate", "wygasa"), ("nextApplyDate", "odnowi się")):
            du = days_until(p.get(key))
            if t.get("package_expire_days") and du is not None and du <= t["package_expire_days"]:
                a.append(f"pakiet '{p['title']}' {label} za {du:.0f} dni")
    return s, a


def main():
    alarm = False
    for msisdn, t in WATCH.items():
        try:
            s, alerts = check(msisdn, t)
        except Exception as e:
            print(f"✗ [{msisdn}] BŁĄD: {e}")
            alarm = True
            continue
        head = (f"[{s['msisdn']}] {s['balance_pln']} {s['balance_unit']} | "
                f"{s['data_gb']} GB | {s['minutes']:.0f} min | konto do {str(s['account_expires'])[:10]}")
        if alerts:
            alarm = True
            print("⚠ " + head)
            for x in alerts:
                print("    - " + x)
        else:
            print("✓ " + head)
    sys.exit(1 if alarm else 0)


if __name__ == "__main__":
    main()

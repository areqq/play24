#!/usr/bin/env python3
"""
Monitor Play24 do crona — pilnuje progów i wysyła alerty (np. na Telegram).

Konfiguracja w ~/.play24/monitor.json (POZA repo — trzyma sekrety i numery), wzór:
examples/monitor.config.example.json. Jeśli brak pliku, używa wbudowanego WATCH (placeholder).

Sprawdza: saldo (PLN), ważność konta, GB i minuty z pakietu, wiek pakietu od aktywacji
oraz bliskość wygaśnięcia/odnowienia. Wypisuje ostrzeżenia, wysyła powiadomienie gdy są
alerty i kończy kodem ≠0 (cron wyśle też maila).

Cron (codziennie 9:00):  0 9 * * *  cd /sciezka/repo && /usr/bin/python3 examples/monitor.py
Wymaga onboardingu numeru przez CLI (play24.py register-start/otp).
"""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from play24lib import Play24, days_until  # noqa: E402

CONFIG_PATH = os.path.expanduser("~/.play24/monitor.json")

# Fallback gdy brak ~/.play24/monitor.json (placeholder — realne dane trzymaj w configu):
WATCH_DEFAULT = {
    "48500100200": dict(min_pln=5.0, min_gb=0.5, min_minutes=10,
                        account_days=14, package_age_days=25, package_expire_days=3),
}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    watch = cfg.get("watch") or WATCH_DEFAULT
    return watch, cfg.get("telegram")


def notify_telegram(tg, text):
    """Wyślij wiadomość na Telegram (config: {bot_token, chat_id, insecure?})."""
    if not tg or not tg.get("bot_token") or not tg.get("chat_id"):
        return
    url = f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage"
    if tg.get("insecure"):
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        r = requests.post(url, data={"chat_id": tg["chat_id"], "text": text},
                          timeout=20, verify=not tg.get("insecure"))
        if not r.ok:
            print(f"(telegram HTTP {r.status_code})", file=sys.stderr)
    except requests.RequestException as e:
        print(f"(telegram błąd: {e})", file=sys.stderr)


def check(msisdn, t):
    s = Play24(msisdn).login().summary()
    a = []
    if t.get("min_pln") is not None and (s["balance_pln"] or 0) < t["min_pln"]:
        a.append(f"saldo {s['balance_pln']} {s['balance_unit']} < {t['min_pln']}")
    if t.get("account_days") is not None and s["account_expires_days"] is not None \
            and s["account_expires_days"] < t["account_days"]:
        a.append(f"konto wygasa za {s['account_expires_days']:.0f} dni ({str(s['account_expires'])[:10]})")
    if t.get("min_gb") is not None and s["data_gb"] < t["min_gb"]:
        a.append(f"dane {s['data_gb']} GB < {t['min_gb']}")
    if t.get("min_minutes") is not None and s["minutes"] < t["min_minutes"]:
        a.append(f"minuty {s['minutes']:.0f} < {t['min_minutes']}")
    for p in s["packages"]:
        if t.get("package_age_days") and p["activationDate"]:
            age = -(days_until(p["activationDate"]) or 0)
            if age >= t["package_age_days"]:
                a.append(f"pakiet '{p['title']}' aktywny od {age:.0f} dni (>= {t['package_age_days']})")
        for key, label in (("expirationDate", "wygasa"), ("nextApplyDate", "odnowi się")):
            du = days_until(p.get(key))
            if t.get("package_expire_days") and du is not None and du <= t["package_expire_days"]:
                a.append(f"pakiet '{p['title']}' {label} za {du:.0f} dni")
    return s, a


def main():
    watch, tg = load_config()
    alarm = False
    tg_lines = []
    for msisdn, t in watch.items():
        try:
            s, alerts = check(msisdn, t)
        except Exception as e:
            print(f"✗ [{msisdn}] BŁĄD: {e}")
            tg_lines.append(f"✗ {msisdn}: BŁĄD {e}")
            alarm = True
            continue
        head = (f"[{s['msisdn']}] {s['balance_pln']} {s['balance_unit']} | "
                f"{s['data_gb']} GB | {s['minutes']:.0f} min | konto do {str(s['account_expires'])[:10]}")
        if alerts:
            alarm = True
            print("⚠ " + head)
            for x in alerts:
                print("    - " + x)
            tg_lines.append("⚠ " + head + "\n" + "\n".join("  - " + x for x in alerts))
        else:
            print("✓ " + head)
    if tg_lines:
        notify_telegram(tg, "Play24 monitor:\n" + "\n".join(tg_lines))
    sys.exit(1 if alarm else 0)


if __name__ == "__main__":
    main()

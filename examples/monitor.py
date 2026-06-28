#!/usr/bin/env python3
"""
Monitor Play24 do crona — status konta z kolorowymi emoji + alerty na Telegram.

Buduje pełny status (saldo, ważność konta, GB, minuty, PŁATNE pakiety) z oznaczeniami:
  🟢 OK   🟠 uwaga (zbliża się próg)   🔴 reaguj (próg przekroczony)   ⚪ brak danych
Powiadomienie na Telegram leci TYLKO gdy jest 🔴 (i wtedy zawiera cały kolorowy status);
exit≠0 gdy 🔴 (cron wyśle też maila). Darmowe usługi/limity są pomijane. Pakiety cykliczne
→ "odnowi się", jednorazowe → "wygasa".

Konfiguracja: ~/.play24/monitor.json (poza repo). Wzór: examples/monitor.config.example.json.
Cron:  0 9 * * *  cd /sciezka/repo && /usr/bin/python3 examples/monitor.py
Wymaga onboardingu numeru przez CLI (play24.py register-start/otp).
"""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from play24lib import Play24, package_status  # noqa: E402

CONFIG_PATH = os.path.expanduser("~/.play24/monitor.json")
GREEN, ORANGE, RED, GRAY = "🟢", "🟠", "🔴", "⚪"

WATCH_DEFAULT = {
    "48500100200": dict(label="Mój numer", min_pln=5.0, min_gb=0.5, min_minutes=10, account_days=14,
                        package_renew_days=3, package_expire_days=3, package_validity_days=31),
}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    return (cfg.get("watch") or WATCH_DEFAULT), cfg.get("telegram")


def emoji_low(value, red, orange_factor=2.0):
    """Mniej = gorzej (saldo/GB/minuty/dni). 🔴<red, 🟠<red*factor, 🟢 wyżej."""
    if value is None:
        return GRAY
    if red is None:
        return GREEN
    if value < red:
        return RED
    if value < red * orange_factor:
        return ORANGE
    return GREEN


def notify_telegram(tg, text):
    if not tg or not tg.get("bot_token") or not tg.get("chat_id"):
        return
    if tg.get("insecure"):
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        r = requests.post(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                          data={"chat_id": tg["chat_id"], "text": text},
                          timeout=20, verify=not tg.get("insecure"))
        if not r.ok:
            print(f"(telegram HTTP {r.status_code})", file=sys.stderr)
    except requests.RequestException as e:
        print(f"(telegram błąd: {e})", file=sys.stderr)


def build_report(msisdn, t):
    """Zwraca (linie_raportu[list[str]], any_red[bool])."""
    s = Play24(msisdn).login().summary()
    label = t.get("label")
    head = f"📱 {s['msisdn']} ({s.get('type') or '?'})" + (f" — {label}" if label else "")
    lines = [head]
    flags = []

    def add(emoji, text):
        flags.append(emoji)
        lines.append(f"{emoji} {text}")

    add(emoji_low(s["balance_pln"], t.get("min_pln")),
        f"saldo: {s['balance_pln']} {s['balance_unit']}" + (f"  (min {t['min_pln']})" if t.get("min_pln") else ""))
    add(emoji_low(s["account_expires_days"], t.get("account_days")),
        f"konto: do {str(s['account_expires'])[:10]}"
        + (f" (za {s['account_expires_days']:.0f} dni)" if s["account_expires_days"] is not None else ""))
    add(emoji_low(s["data_gb"], t.get("min_gb")), f"dane: {s['data_gb']} GB")
    add(emoji_low(s["minutes"], t.get("min_minutes")), f"minuty: {s['minutes']:.0f}")

    paid = []
    for p in s["packages"]:
        if not p.get("paid"):
            continue   # tylko PŁATNE pakiety (darmowe usługi/limity pomijamy — bez uwag)
        st = package_status(p, validity_days=t.get("package_validity_days", 31))
        if not st["event"]:
            continue
        cena = f" [{p['price_pln']:.2f} zł]" if p.get("price_pln") else ""
        if st["event"] == "renew":
            e = emoji_low(st["days"], t.get("package_renew_days"))
            paid.append(f"{e} {st['title']}{cena} (cykl.) — odnowi się za {st['days']:.0f} dni ({str(st['date'])[:10]})")
        else:
            e = emoji_low(st["days"], t.get("package_expire_days"))
            paid.append(f"{e} {st['title']}{cena} (jedn.) — wygasa za {st['days']:.0f} dni ({str(st['date'])[:10]})")
        flags.append(e)
    if paid:
        lines.append("Pakiety płatne:")
        lines.extend("  " + x for x in paid)

    return lines, (RED in flags)


def main():
    watch, tg = load_config()
    all_lines, any_red = [], False
    for msisdn, t in watch.items():
        try:
            lines, red = build_report(msisdn, t)
        except Exception as e:
            lines, red = [f"{RED} {msisdn}: BŁĄD {e}"], True
        block = "\n".join(lines)
        print(block + "\n")
        all_lines.append(block)
        any_red = any_red or red

    if tg and any_red:    # powiadomienie TYLKO gdy coś na czerwono (🔴)
        notify_telegram(tg, "Play24 monitor:\n\n" + "\n\n".join(all_lines))
    sys.exit(1 if any_red else 0)


if __name__ == "__main__":
    main()

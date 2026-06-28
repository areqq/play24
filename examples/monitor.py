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


def render_report(s, t):
    """Czysty render (bez sieci): (linie[list[str]], any_red[bool]) dla danego zestawu progów."""
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
    add(emoji_low(s["data_gb"], t.get("min_gb")), f"dane (krajowe): {s['data_gb']} GB")
    if s.get("data_gb_roaming"):
        lines.append(f"🌍 roaming UE: {s['data_gb_roaming']} GB")
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
    watch, global_tg = load_config()
    global_blocks, any_red = [], False
    for msisdn, t in watch.items():
        # 1) pobierz dane RAZ
        try:
            s = Play24(msisdn).login().summary()
        except Exception as e:
            err = f"{RED} {msisdn} ({t.get('label', '')}): BŁĄD {e}"
            print(err + "\n")
            any_red = True
            if t.get("notify_global", True):
                global_blocks.append(err)
            for n in (t.get("notify") or []):     # błąd też do prywatnych odbiorców
                if n.get("telegram"):
                    notify_telegram(n["telegram"], "Play24 monitor:\n\n" + err)
            continue

        # 2) widok GLOBALNY (progi bazowe numeru) — do stdout/maila i globalnego telegramu
        base_lines, base_red = render_report(s, t)
        print("\n".join(base_lines) + "\n")
        any_red = any_red or base_red
        if base_red and t.get("notify_global", True):
            global_blocks.append("\n".join(base_lines))

        # 3) NIEZALEŻNE powiadomienia per numer (własny telegram + własne progi)
        for n in (t.get("notify") or []):
            merged = {**t, **n}            # progi z 'n' nadpisują bazowe; label dziedziczony
            merged.pop("notify", None)
            n_lines, n_red = render_report(s, merged)
            if n_red and n.get("telegram"):
                notify_telegram(n["telegram"], "Play24 monitor:\n\n" + "\n".join(n_lines))

    if global_tg and global_blocks:        # globalny: tylko numery z 🔴 (i notify_global≠false)
        notify_telegram(global_tg, "Play24 monitor:\n\n" + "\n\n".join(global_blocks))
    sys.exit(1 if any_red else 0)


if __name__ == "__main__":
    main()

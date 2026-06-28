#!/usr/bin/env python3
"""
Monitor Play24 do crona — elastyczne, nazwane notyfikatory + sekcje alertów per numer.

Konfiguracja: ~/.play24/monitor.json (POZA repo — sekrety/numery). Wzór:
examples/monitor.config.example.json.

Model:
  "notifiers": { "<nazwa>": { "type": "telegram", "bot_token": "...", "chat_id": "...", "insecure": false } }
      — globalnie zdefiniowane kanały (typ na razie 'telegram', rozszerzalny w przyszłości).
  "watch": { "<48msisdn>": { "label": "...", "alerts": [
        { "notify": ["<nazwa>", ...], <progi> }, ...
      ] } }
      — dowolnie wiele sekcji; każda ma własne progi i listę notyfikatorów, na które leci alert.

Progi (pomiń klucz, by nie sprawdzać): min_pln, min_gb (krajowe), min_minutes, account_days,
package_renew_days, package_expire_days, package_validity_days.
Status: 🟢 OK · 🟠 uwaga (<2× próg) · 🔴 reaguj (próg przekroczony) · ⚪ brak danych.
Powiadomienie leci gdy w sekcji jest 🔴. exit≠0 gdy jakiekolwiek 🔴 (cron wyśle maila).

Cron (raz na dobę):  0 9 * * *  cd /sciezka/repo && uv run python examples/monitor.py
Lekki — postawisz go na darmowym mikro-VPS, np. https://frog.mikr.us (cron + uv).
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


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def emoji_low(value, red, orange_factor=2.0):
    """Mniej = gorzej. 🔴<red, 🟠<red*factor, 🟢 wyżej, ⚪ brak danych."""
    if value is None:
        return GRAY
    if red is None:
        return GREEN
    if value < red:
        return RED
    if value < red * orange_factor:
        return ORANGE
    return GREEN


# ── notyfikatory (rozszerzalne wg "type") ──────────────────────────────────
def _send_telegram(n, text):
    if not n.get("bot_token") or not n.get("chat_id"):
        return
    if n.get("insecure"):
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        r = requests.post(f"https://api.telegram.org/bot{n['bot_token']}/sendMessage",
                          data={"chat_id": n["chat_id"], "text": text},
                          timeout=20, verify=not n.get("insecure"))
        if not r.ok:
            print(f"(telegram '{n.get('_name')}' HTTP {r.status_code})", file=sys.stderr)
    except requests.RequestException as e:
        print(f"(telegram '{n.get('_name')}' błąd: {e})", file=sys.stderr)


SENDERS = {"telegram": _send_telegram}


def dispatch(notifier, text):
    typ = (notifier or {}).get("type", "telegram")
    sender = SENDERS.get(typ)
    if sender:
        sender(notifier, text)
    else:
        print(f"(nieznany typ notyfikatora: {typ})", file=sys.stderr)


# ── render statusu ─────────────────────────────────────────────────────────
def render_report(s, t):
    """Pełny kolorowy status dla zestawu progów t. Zwraca (linie, any_red)."""
    label = t.get("label")
    lines = [f"📱 {s['msisdn']} ({s.get('type') or '?'})" + (f" — {label}" if label else "")]
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
            continue
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


def oneliner(s, label):
    return (f"✓ 📱 {s['msisdn']}" + (f" — {label}" if label else "")
            + f" | {s['balance_pln']} {s['balance_unit']} | {s['data_gb']} GB | "
              f"{s['minutes']:.0f} min | konto do {str(s['account_expires'])[:10]}")


def main():
    cfg = load_config()
    notifiers = cfg.get("notifiers") or {}
    for name, n in notifiers.items():
        n.setdefault("_name", name)
    any_red = False

    for msisdn, t in (cfg.get("watch") or {}).items():
        label = t.get("label")
        try:
            s = Play24(msisdn).login().summary()
        except Exception as e:
            err = f"{RED} {msisdn} ({label or ''}): BŁĄD {e}"
            print(err)
            any_red = True
            for name in {n for sec in t.get("alerts", []) for n in sec.get("notify", [])}:
                dispatch(notifiers.get(name), "Play24 monitor:\n\n" + err)
            continue

        fired = False
        for sec in (t.get("alerts") or []):
            lines, red = render_report(s, {**sec, "label": label})
            if not red:
                continue
            fired = True
            any_red = True
            block = "\n".join(lines)
            targets = sec.get("notify", [])
            print(block + f"\n   → {', '.join(targets) or '(brak notyfikatora)'}\n")
            for name in targets:
                nt = notifiers.get(name)
                if nt:
                    dispatch(nt, "Play24 monitor:\n\n" + block)
                else:
                    print(f"(brak notyfikatora '{name}' w 'notifiers')", file=sys.stderr)
        if not fired:
            print(oneliner(s, label))

    sys.exit(1 if any_red else 0)


if __name__ == "__main__":
    main()

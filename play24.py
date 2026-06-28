#!/usr/bin/env python3
"""
play24 — nieoficjalny klient CLI do API aplikacji Play24 (com.play.play24m).

Cienka warstwa nad biblioteką `play24lib` (cały protokół jest tam). NIE jest to oficjalne
narzędzie Play / P4 sp. z o.o. Używasz na własną odpowiedzialność, wyłącznie do własnego konta.

Logowanie = FIDO2/passkey (działa z dowolnej sieci). Najpierw onboarding numeru:
  ./play24.py register-start --msisdn 48500100200    # wyśle SMS
  ./play24.py register-otp   --code 1234             # zapisze passkey w ~/.play24/
Potem dowolna komenda loguje się passkeyem automatycznie:
  ./play24.py summary
  ./play24.py packages --all
  ./play24.py activate <id>

Pełna lista numerów / przełączanie / dane: ./play24.py --help. Szczegóły API: API.md, ACTIVATION.md.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import play24lib as lib


# ----------------------------------------------------------------------------- helpers
def _p(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _resolve_msisdn(args):
    """Numer z --msisdn, a w razie braku: aktywny / jedyny zarejestrowany."""
    if getattr(args, "msisdn", None):
        return args.msisdn
    data = lib.load_store()
    profs = data.get("profiles") or {}
    if data.get("active") in profs:
        return data["active"]
    if len(profs) == 1:
        return next(iter(profs))
    avail = ", ".join(profs) or "brak — najpierw register-start"
    sys.exit(f"Podaj --msisdn. Zarejestrowane: {avail}")


def _client(args):
    return lib.Play24(_resolve_msisdn(args), kind=args.kind, service_type=args.type).login()


def _set_active(msisdn):
    data = lib.load_store()
    data["active"] = lib.norm_msisdn(msisdn)
    lib.save_store(data)


# ----------------------------------------------------------------------------- onboarding
def cmd_register_start(args):
    r = lib.register_start(args.msisdn, profile_type=args.profile_type)
    ln = r.get("sms_length")
    print(f"✅ Kod SMS wysłany na {args.msisdn}"
          + (f" (długość: {ln})" if ln else "")
          + f"\nNastępnie: ./play24.py register-otp --msisdn {args.msisdn} --code <KOD>", file=sys.stderr)


def cmd_register_otp(args):
    msisdn = args.msisdn or (lib.load_store().get("_pending") and next(iter(lib.load_store()["_pending"])))
    if not msisdn:
        sys.exit("Podaj --msisdn (ten, dla którego robiłeś register-start).")
    prof = lib.register_complete(msisdn, args.code)
    _set_active(msisdn)
    print(f"✅ Numer {lib.norm_msisdn(msisdn)} podpięty (passkey w ~/.play24/). "
          f"profil={prof.get('profileId','')[:8]}…\n"
          f"   Sprawdź: ./play24.py summary --msisdn {lib.norm_msisdn(msisdn)}", file=sys.stderr)


def cmd_accounts(args):
    accs = lib.accounts()
    if not accs:
        print("Brak zarejestrowanych numerów. Dodaj: ./play24.py register-start --msisdn <numer>", file=sys.stderr)
        return
    active = lib.load_store().get("active")
    for a in accs:
        mark = " *" if a["msisdn"] == active else "  "
        pk = "✓" if a["registered"] else "BRAK passkey"
        print(f"{mark} {a['msisdn']}  profil={(a['profile_id'] or '')[:8]}…  passkey:{pk}", file=sys.stderr)
    print("\nDomyślny numer ustaw: ./play24.py use <numer>", file=sys.stderr)


def cmd_use(args):
    if lib.norm_msisdn(args.msisdn) not in (lib.load_store().get("profiles") or {}):
        sys.exit(f"Numer {args.msisdn} nie jest zarejestrowany (./play24.py accounts).")
    _set_active(args.msisdn)
    print(f"✅ Domyślny numer: {lib.norm_msisdn(args.msisdn)}", file=sys.stderr)


# ----------------------------------------------------------------------------- wiele numerów na koncie
def cmd_numbers(args):
    _p(_client(args).numbers())


def cmd_switch(args):
    c = lib.Play24(_resolve_msisdn(args), kind=args.kind, service_type=args.type).login()
    new = c.switch(args.target)
    print(f"✅ Aktywny numer (w obrębie konta): {new}", file=sys.stderr)
    _p(c.balance())


# ----------------------------------------------------------------------------- odczyty
def cmd_summary(args):
    _p(_client(args).summary())


def cmd_balance(args):
    _p(_client(args).balance())


def cmd_balances_all(args):
    _p(_client(args).balances_all())


def cmd_counters(args):
    _p(_client(args).counters())


def cmd_account(args):
    _p(_client(args).account())


def cmd_offers(args):
    _p(_client(args).raw("GET", "ms-offers", 12, "offers/{userId}"))


def cmd_finances(args):
    _p(_client(args).raw("GET", "ms-finances", 4, "finances/{userId}/info"))


def cmd_invoices(args):
    _p(_client(args).raw("GET", "ms-finances", 4, "finances/{userId}/documents",
                         query={"onlyPaid": "false", "offset": "0"}))


def cmd_components(args):
    _p(_client(args).raw("GET", "ms-components", 8, "components/{userId}"))


def cmd_notifications(args):
    _p(_client(args).raw("GET", "ms-notifications", 4, "notifications/{userId}"))


def cmd_history(args):
    _p(_client(args).raw("GET", "ms-activities", 2, "activities/{userId}/history"))


def cmd_sim(args):
    _p(_client(args).raw("GET", "ms-sim", 2, "sim/{userId}/information"))


def cmd_raw(args):
    body = json.loads(args.body) if args.body else None
    _p(_client(args).raw(args.method, args.ms, args.version, args.path, body=body))


def cmd_whoami(args):
    data = lib.load_store()
    _p({"active": data.get("active"), "device_id": data.get("device_id"),
        "profiles": data.get("profiles") or {}})


# ----------------------------------------------------------------------------- pakiety
def _fmt_date(d):
    return d[:10] if isinstance(d, str) and len(d) >= 10 else "—"


def cmd_packages(args):
    pkgs = _client(args).packages(active_only=not args.all)
    if args.json:
        _p(pkgs)
        return
    if not pkgs:
        print("Brak pakietów do pokazania.", file=sys.stderr)
        return
    rows = []
    for p in pkgs:
        st = lib.package_status(p)
        when = "odnowi" if st["cyclic"] else "wygasa"
        rows.append((
            str(p.get("id") or ""), (p.get("title") or "")[:40],
            _fmt_date(p.get("activationDate")),
            f"{when} {_fmt_date(st['date'])}" if st["date"] else "—",
            (f"{p['price_pln']:.2f} zł" if p.get("price_pln") else "—") if args.all else (p.get("state") or ""),
        ))
    hdr = ("id", "Pakiet / usługa", "Aktywacja", "Odnowienie/wygaśnięcie", "Cena" if args.all else "Stan")
    w = [max(len(hdr[i]), max(len(r[i]) for r in rows)) for i in range(len(hdr))]
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr)))
    print("  ".join("-" * w[i] for i in range(len(hdr))))
    for r0 in rows:
        print("  ".join(str(r0[i]).ljust(w[i]) for i in range(len(hdr))))
    if args.all:
        print("\nWłącz: ./play24.py activate <id>   (wyłącz: deactivate <id>)", file=sys.stderr)


def _modify(args, op):
    c = _client(args)
    it, comp = c._find_component(args.component_id)
    price = (it.get("price") or {})
    price_s = price.get("formatted") or (f"{price.get('value')/100:.2f} zł" if isinstance(price.get("value"), (int, float)) else "")
    title = comp.get("title")
    op_obj = next((o for o in (it.get("operations") or []) if o.get("type") == op), None)
    print(f"\n{op}: '{title}' (id={comp.get('id')})" + (f"  koszt: {price_s}" if price_s else ""), file=sys.stderr)
    if op_obj and op_obj.get("regulation"):
        print(f"  Regulamin: {re.sub('<[^>]+>', '', op_obj['regulation'])[:300]}", file=sys.stderr)
    if not args.yes:
        if input(f"Potwierdź {op} '{title}' {('('+price_s+') ') if price_s else ''}— wpisz TAK: ").strip().upper() != "TAK":
            sys.exit("Anulowano.")
    fn = c.activate if op == "ACTIVATE" else c.deactivate
    res = fn(args.component_id, email=args.email, otp=args.otp, auto_stepup=not args.no_stepup)
    if res.get("stepup"):
        print("→ Autoryzacja SCA passkeyem OK.", file=sys.stderr)
    print(f"✅ {op} wysłane — usługa zmieni się w ciągu kilku minut.", file=sys.stderr)
    _p(res.get("result"))


def cmd_activate(args):
    _modify(args, "ACTIVATE")


def cmd_deactivate(args):
    _modify(args, "DEACTIVATE")


# ----------------------------------------------------------------------------- CLI
def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--msisdn", help="numer (domyślnie: aktywny/jedyny zarejestrowany)")
    common.add_argument("--kind", default="VOICE", choices=["VOICE", "DATA", "FIX", "TV"])
    common.add_argument("--type", default="PREPAID", choices=["PREPAID", "POSTPAID", "MIX"])

    p = argparse.ArgumentParser(description="Nieoficjalny klient CLI Play24 (cienka warstwa nad play24lib)")
    sub = p.add_subparsers(dest="cmd", required=True)

    rs = sub.add_parser("register-start", help="onboarding krok 1: wyślij kod SMS")
    rs.add_argument("--msisdn", required=True)
    rs.add_argument("--profile-type", default="STANDARD", choices=["STANDARD", "EMAIL_PREPAID_DIGITAL"])
    rs.set_defaults(fn=cmd_register_start)

    ro = sub.add_parser("register-otp", help="onboarding krok 2: kod SMS → passkey")
    ro.add_argument("--code", required=True)
    ro.add_argument("--msisdn")
    ro.set_defaults(fn=cmd_register_otp)

    sub.add_parser("accounts", help="lokalnie zarejestrowane numery").set_defaults(fn=cmd_accounts)
    u = sub.add_parser("use", help="ustaw domyślny numer")
    u.add_argument("msisdn")
    u.set_defaults(fn=cmd_use)

    sw = sub.add_parser("switch", parents=[common], help="przełącz numer w obrębie jednego konta (msisdn-switch)")
    sw.add_argument("target", help="numer docelowy")
    sw.set_defaults(fn=cmd_switch)

    pkg = sub.add_parser("packages", parents=[common], help="pakiety/usługi (daty odnowienia/wygaśnięcia)")
    pkg.add_argument("--all", action="store_true", help="też nieaktywne (cały katalog + id + cena)")
    pkg.add_argument("--json", action="store_true", help="surowy JSON zamiast tabeli")
    pkg.set_defaults(fn=cmd_packages)

    for name, fn, paid in [("activate", cmd_activate, True), ("deactivate", cmd_deactivate, True)]:
        sp = sub.add_parser(name, parents=[common],
                            help=("WŁĄCZ pakiet (realny zakup)" if name == "activate" else "WYŁĄCZ pakiet"))
        sp.add_argument("component_id", help="id komponentu (z: packages --all)")
        sp.add_argument("--otp", help="kod SMS, gdy operacja go wymaga")
        sp.add_argument("--email", help="e-mail do regulaminu (raz na konto przy 1. zakupie)")
        sp.add_argument("--yes", action="store_true", help="pomiń interaktywne potwierdzenie")
        sp.add_argument("--no-stepup", action="store_true", help="nie próbuj auto-autoryzacji FIDO")
        sp.set_defaults(fn=fn)

    for name, fn, helptxt in [
        ("summary",       cmd_summary,       "skrót: saldo, ważność, GB, minuty, pakiety"),
        ("balance",       cmd_balance,       "saldo główne"),
        ("balances-all",  cmd_balances_all,  "wszystkie liczniki"),
        ("counters",      cmd_counters,      "liczniki (dane/minuty/SMS)"),
        ("numbers",       cmd_numbers,       "numery na aktywnym koncie (msisdn/list)"),
        ("offers",        cmd_offers,        "oferty"),
        ("finances",      cmd_finances,      "podsumowanie finansów"),
        ("invoices",      cmd_invoices,      "faktury / dokumenty"),
        ("account",       cmd_account,       "dane konta/klienta"),
        ("components",    cmd_components,    "usługi / komponenty taryfy (surowo)"),
        ("notifications", cmd_notifications, "powiadomienia"),
        ("history",       cmd_history,       "historia aktywności"),
        ("sim",           cmd_sim,           "informacje o SIM"),
    ]:
        sp = sub.add_parser(name, parents=[common], help=helptxt)
        sp.set_defaults(fn=fn)

    sub.add_parser("whoami", help="pokaż lokalny stan (profile, aktywny numer)").set_defaults(fn=cmd_whoami)

    spr = sub.add_parser("raw", parents=[common], help="dowolny endpoint: raw METHOD MS VERSION PATH [--body JSON]")
    spr.add_argument("method"); spr.add_argument("ms"); spr.add_argument("version"); spr.add_argument("path")
    spr.add_argument("--body")
    spr.set_defaults(fn=cmd_raw)

    args = p.parse_args()
    try:
        args.fn(args)
    except lib.Play24Error as e:
        sys.exit(f"Błąd: {e}")


if __name__ == "__main__":
    main()

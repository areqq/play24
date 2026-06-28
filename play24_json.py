#!/usr/bin/env python3
"""
play24_json — JSON-owy interfejs do Play24 dla agentów AI / skryptów.

Każda komenda wypisuje na stdout JEDEN obiekt JSON i ustawia kod wyjścia (0=ok, 1=błąd):
  {"ok": true,  "cmd": "...", "msisdn": "...", "data": {...}}
  {"ok": false, "cmd": "...", "error": "...", "type": "..."}

READ-ONLY (nie wydaje pieniędzy / nie zmienia konta). Aktywacja pakietów: interaktywne play24.py.
Wymaga wcześniejszego onboardingu numeru przez CLI (play24.py register-start/otp).

Komendy:
  accounts                      # lokalnie zarejestrowane numery (bez sieci)
  summary  --msisdn 48...       # saldo, ważność konta, GB(krajowe/roaming), minuty, pakiety
  balance  --msisdn 48...       # surowe ms-balances/main
  counters --msisdn 48...       # liczniki (dane/minuty/SMS) z gb/minutes
  packages --msisdn 48...       # aktywne pakiety (z paid/price/cyclic/daty)
  account  --msisdn 48...       # dane klienta
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import play24lib as lib


def _out(obj, code=0):
    json.dump(obj, sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    sys.exit(code)


def cmd_accounts(args):
    _out({"ok": True, "cmd": "accounts", "data": lib.accounts()})


def _client(args):
    return lib.Play24(args.msisdn, kind=args.kind, service_type=args.type).login()


def cmd_summary(args):
    _out({"ok": True, "cmd": "summary", "msisdn": args.msisdn, "data": _client(args).summary()})


def cmd_balance(args):
    _out({"ok": True, "cmd": "balance", "msisdn": args.msisdn, "data": _client(args).balance()})


def cmd_counters(args):
    _out({"ok": True, "cmd": "counters", "msisdn": args.msisdn, "data": _client(args).counters()})


def cmd_packages(args):
    _out({"ok": True, "cmd": "packages", "msisdn": args.msisdn,
          "data": _client(args).packages(active_only=not args.all)})


def cmd_account(args):
    _out({"ok": True, "cmd": "account", "msisdn": args.msisdn, "data": _client(args).account()})


def main():
    p = argparse.ArgumentParser(description="JSON-owy interfejs Play24 (read-only, dla agentów)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("accounts").set_defaults(fn=cmd_accounts)
    for name, fn in [("summary", cmd_summary), ("balance", cmd_balance),
                     ("counters", cmd_counters), ("packages", cmd_packages), ("account", cmd_account)]:
        sp = sub.add_parser(name)
        sp.add_argument("--msisdn", required=True)
        sp.add_argument("--kind", default="VOICE", choices=["VOICE", "DATA", "FIX", "TV"])
        sp.add_argument("--type", default="PREPAID", choices=["PREPAID", "POSTPAID", "MIX"])
        if name == "packages":
            sp.add_argument("--all", action="store_true", help="też nieaktywne (cały katalog)")
        sp.set_defaults(fn=fn)
    args = p.parse_args()
    try:
        args.fn(args)
    except lib.Play24Error as e:
        _out({"ok": False, "cmd": args.cmd, "error": str(e), "type": "Play24Error"}, 1)
    except Exception as e:  # noqa: BLE001
        _out({"ok": False, "cmd": args.cmd, "error": str(e), "type": type(e).__name__}, 1)


if __name__ == "__main__":
    main()

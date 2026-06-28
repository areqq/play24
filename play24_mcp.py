#!/usr/bin/env python3
"""
play24_mcp — serwer MCP (Model Context Protocol) dla Play24.

Udostępnia PEŁNY protokół Play24 jako narzędzia MCP, których może użyć agent AI
(Claude Desktop, Claude Code, dowolny klient MCP): odczyt statusu konta, onboarding
numeru (SMS+passkey), obsługa wielu numerów oraz włączanie/wyłączanie pakietów (płatne).

Transport: stdio (JSON-RPC 2.0). Uruchomienie (środowisko przez uv):
    uv run play24-mcp
albo bezpośrednio:
    uv run python play24_mcp.py

Konfiguracja klienta (np. Claude Desktop, claude_desktop_config.json):
    {
      "mcpServers": {
        "play24": { "command": "uv", "args": ["run", "--directory", "/ścieżka/do/play24", "play24-mcp"] }
      }
    }

Sekrety/passkey trzymane są w ~/.play24/ (poza repo). Każde narzędzie czytające loguje się
passkeyem (FIDO2) — onboarding numeru (register_start/complete) wymaga kodu SMS od człowieka.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402
import play24lib as lib  # noqa: E402

mcp = FastMCP("play24")


def _ok(cmd, **data):
    return {"ok": True, "cmd": cmd, **data}


def _err(cmd, e):
    return {"ok": False, "cmd": cmd, "error": str(e), "type": type(e).__name__}


def _client(msisdn, kind="VOICE", service_type="PREPAID"):
    return lib.Play24(msisdn, kind=kind, service_type=service_type).login()


# ----------------------------------------------------------------------------- odczyty (read-only)
@mcp.tool()
def play24_accounts() -> dict:
    """Lista lokalnie zarejestrowanych numerów Play (bez sieci). Zwraca msisdn, profile_id, registered."""
    try:
        return _ok("accounts", data=lib.accounts())
    except Exception as e:  # noqa: BLE001
        return _err("accounts", e)


@mcp.tool()
def play24_summary(msisdn: str, kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """NAJWAŻNIEJSZE: skrót statusu numeru — saldo (PLN), ważność konta (data + dni),
    dane GB (krajowe i roaming), minuty, liczniki oraz pakiety z datami odnowienia/wygaśnięcia."""
    try:
        return _ok("summary", msisdn=msisdn, data=_client(msisdn, kind, service_type).summary())
    except Exception as e:  # noqa: BLE001
        return _err("summary", e)


@mcp.tool()
def play24_balance(msisdn: str, kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """Saldo główne (ms-balances/main): kwota „Konto" + data ważności konta."""
    try:
        return _ok("balance", msisdn=msisdn, data=_client(msisdn, kind, service_type).balance())
    except Exception as e:  # noqa: BLE001
        return _err("balance", e)


@mcp.tool()
def play24_counters(msisdn: str, kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """Wszystkie liczniki (dane/minuty/SMS) z wyliczonymi GB i minutami."""
    try:
        return _ok("counters", msisdn=msisdn, data=_client(msisdn, kind, service_type).counters())
    except Exception as e:  # noqa: BLE001
        return _err("counters", e)


@mcp.tool()
def play24_packages(msisdn: str, active_only: bool = True,
                    kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """Pakiety/usługi. active_only=False = cały katalog z id (potrzebne do activate/deactivate)
    i ceną. Każdy: title, paid, price_pln, cyclic, activationDate, nextApplyDate, expirationDate."""
    try:
        data = _client(msisdn, kind, service_type).packages(active_only=active_only)
        return _ok("packages", msisdn=msisdn, data=data)
    except Exception as e:  # noqa: BLE001
        return _err("packages", e)


@mcp.tool()
def play24_account(msisdn: str, kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """Dane klienta/konta (ms-clients)."""
    try:
        return _ok("account", msisdn=msisdn, data=_client(msisdn, kind, service_type).account())
    except Exception as e:  # noqa: BLE001
        return _err("account", e)


@mcp.tool()
def play24_numbers(msisdn: str, kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """Numery przypięte do JEDNEGO konta (msisdn/list) — gdy jedno konto obsługuje wiele numerów."""
    try:
        return _ok("numbers", msisdn=msisdn, data=_client(msisdn, kind, service_type).numbers())
    except Exception as e:  # noqa: BLE001
        return _err("numbers", e)


@mcp.tool()
def play24_raw(msisdn: str, method: str, ms: str, version: str, path: str,
               body: dict | None = None, kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """Dowolny endpoint bramki (zaawansowane). path może zawierać {userId} (podstawiane).
    Np. method=GET ms=ms-finances version=4 path=finances/{userId}/info."""
    try:
        data = _client(msisdn, kind, service_type).raw(method, ms, version, path, body=body)
        return _ok("raw", msisdn=msisdn, data=data)
    except Exception as e:  # noqa: BLE001
        return _err("raw", e)


# ----------------------------------------------------------------------------- onboarding (wymaga człowieka — kod SMS)
@mcp.tool()
def play24_register_start(msisdn: str, profile_type: str = "STANDARD") -> dict:
    """Onboarding krok 1: wyślij kod SMS na numer (kyc/register). Następnie człowiek odczytuje SMS
    i wywołuje play24_register_complete z kodem. Zwraca m.in. oczekiwaną długość kodu."""
    try:
        return _ok("register_start", msisdn=msisdn, data=lib.register_start(msisdn, profile_type=profile_type))
    except Exception as e:  # noqa: BLE001
        return _err("register_start", e)


@mcp.tool()
def play24_register_complete(msisdn: str, code: str) -> dict:
    """Onboarding krok 2: zweryfikuj kod SMS i utwórz passkey (FIDO2). Po tym numer jest gotowy,
    a kolejne logowania są bez SMS, z dowolnej sieci. Zwraca ProfileDto."""
    try:
        prof = lib.register_complete(msisdn, code)
        return _ok("register_complete", msisdn=lib.norm_msisdn(msisdn),
                   data={"profile_id": prof.get("profileId"), "identifier": prof.get("identifier")})
    except Exception as e:  # noqa: BLE001
        return _err("register_complete", e)


@mcp.tool()
def play24_switch(msisdn: str, target: str, kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """Przełącz aktywny numer w obrębie JEDNEGO konta (msisdn-switch). msisdn = numer do logowania,
    target = numer docelowy z play24_numbers."""
    try:
        c = _client(msisdn, kind, service_type)
        new = c.switch(target)
        return _ok("switch", msisdn=msisdn, data={"active": new, "balance": c.balance()})
    except Exception as e:  # noqa: BLE001
        return _err("switch", e)


# ----------------------------------------------------------------------------- operacje PŁATNE (włączanie/wyłączanie)
@mcp.tool()
def play24_activate(msisdn: str, component_id: str, email: str | None = None, otp: str | None = None,
                    kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """WŁĄCZ pakiet/usługę (REALNY KOSZT). Autoryzacja SCA (FIDO step-up) dzieje się automatycznie
    passkeyem. UWAGA: to wydaje pieniądze — najpierw potwierdź z użytkownikiem cenę (play24_packages
    z active_only=False pokazuje id i price_pln). email bywa wymagany przy pierwszym zakupie na koncie;
    otp tylko gdy serwer poprosi o kod SMS."""
    try:
        res = _client(msisdn, kind, service_type).activate(component_id, email=email, otp=otp)
        return _ok("activate", msisdn=msisdn, data=res)
    except Exception as e:  # noqa: BLE001
        return _err("activate", e)


@mcp.tool()
def play24_deactivate(msisdn: str, component_id: str, otp: str | None = None,
                      kind: str = "VOICE", service_type: str = "PREPAID") -> dict:
    """WYŁĄCZ pakiet/usługę. Autoryzacja SCA (FIDO step-up) automatycznie passkeyem.
    Potwierdź z użytkownikiem, którą usługę wyłączasz (id z play24_packages)."""
    try:
        res = _client(msisdn, kind, service_type).deactivate(component_id, otp=otp)
        return _ok("deactivate", msisdn=msisdn, data=res)
    except Exception as e:  # noqa: BLE001
        return _err("deactivate", e)


# ----------------------------------------------------------------------------- resource: szybki przegląd kont
@mcp.resource("play24://accounts")
def accounts_resource() -> str:
    """Lokalnie zarejestrowane numery Play (do szybkiego wglądu przez klienta MCP)."""
    import json
    return json.dumps(lib.accounts(), ensure_ascii=False, indent=2)


def main():
    mcp.run()


if __name__ == "__main__":
    main()

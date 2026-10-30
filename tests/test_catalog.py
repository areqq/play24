"""Adapter katalogu komponentów: ms-services/v1 (zagnieżdżony, jak w apce) → płaski kształt v8-like,
którego używają packages()/_find_component()/_modify(). Uruchom: python3 -m unittest tests/test_catalog.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import play24lib as lib

# Próbka 1:1 wg kontraktu ComponentDto/StateDto/PriceDto/OperationDto (APK) i żywej odpowiedzi 2026-10-30.
SAMPLE = {"categories": [
  {"type": "MOBILE_PACKETS", "name": "Pakiety", "sections": [
    {"type": "MINUTES", "name": "Minuty", "components": [
      {"id": "86009", "name": "50 min, 50 SMS, 250MB za 3 zł", "type": "BILLING_OTB", "description": "d",
       "state": {"status": "INACTIVE", "activationsLimit": 998, "isCyclic": False, "renewalDate": None},
       "price": {"value": "3 zł", "discounts": []},
       "operations": [{"type": "ACTIVATE", "name": "Zamów i zapłać", "legal": "Możesz odstąpić <b>x</b>", "params": []}],
       "regulations": [], "details": [], "icon": None, "badge": None, "promo": None},
      {"id": "64434", "name": "Rozmowy 19,95", "type": "BILLING_OTB", "description": None,
       "state": {"status": "DURING_CHANGE", "activationsLimit": 20, "isCyclic": False, "renewalDate": None},
       "price": {"value": "19,95 zł", "discounts": []}, "operations": [], "regulations": [], "details": []}]},
    {"type": "INTERNET", "name": "Internet", "components": [
      {"id": "86000", "name": "Usługa - Maksymalnie 15PLN/m-c", "type": "BILLING", "description": None,
       "state": {"status": "ACTIVE", "activationsLimit": None, "isCyclic": True, "renewalDate": "2026-11-01T23:59:59+01:00"},
       "price": {"value": "0 zł miesięcznie", "discounts": [{"period": "przez 1 miesiąc", "value": "0 zł"}]},
       "operations": [{"type": "DEACTIVATE", "name": "Wyłącz usługę", "legal": None, "params": []}],
       "regulations": [], "details": []}]}]},
  {"type": "MOBILE_SETTINGS", "name": "Ustawienia", "sections": [
    {"type": "VOICEMAIL", "name": "Poczta", "components": [
      {"id": "23852", "name": "Poczta głosowa standard", "type": "VIRTUAL", "description": None,
       "state": {"status": "ACTIVE", "activationsLimit": None, "isCyclic": False, "renewalDate": None},
       "price": None, "operations": [{"type": "MODIFY", "name": "Zmień"}, {"type": "DEACTIVATE", "name": "Wyłącz"}],
       "regulations": [], "details": []}]}]}]}


class FlattenCatalog(unittest.TestCase):
    def setUp(self):
        self.items = lib.flatten_catalog(SAMPLE)
        self.by_id = {str(it["component"]["id"]): it for it in self.items}

    def test_all_leaves_flattened_in_order(self):
        self.assertEqual([it["component"]["id"] for it in self.items], [86009, 64434, 86000, 23852])

    def test_v8_like_component_fields(self):
        c = self.by_id["86009"]["component"]
        self.assertEqual(c["id"], 86009)                      # int jak w v8 (CLI/MCP porównują str(id))
        self.assertEqual(c["title"], "50 min, 50 SMS, 250MB za 3 zł")
        self.assertEqual(c["state"], "INACTIVE")
        self.assertEqual(c["type"], "BILLING_OTB")           # → body.componentType przy POST
        self.assertEqual(c["componentType"], "BILLING_OTB")
        self.assertEqual(c["cyclicType"], "NONE")
        self.assertIsNone(c["activationDate"]); self.assertIsNone(c["expirationDate"]); self.assertIsNone(c["nextApplyDate"])
        self.assertEqual(c["description"], "d")

    def test_cyclic_and_renewal_date(self):
        c = self.by_id["86000"]["component"]
        self.assertEqual(c["state"], "ACTIVE")
        self.assertEqual(c["cyclicType"], "MONTHLY")
        self.assertEqual(c["nextApplyDate"], "2026-11-01T23:59:59+01:00")

    def test_price_parsed_to_grosze_and_formatted_kept(self):
        self.assertEqual(self.by_id["86009"]["price"], {"value": 300, "currency": "PLN", "formatted": "3 zł", "discounts": []})
        self.assertEqual(self.by_id["64434"]["price"]["value"], 1995)
        self.assertEqual(self.by_id["64434"]["price"]["formatted"], "19,95 zł")
        p = self.by_id["86000"]["price"]
        self.assertEqual(p["value"], 0); self.assertEqual(p["formatted"], "0 zł miesięcznie"); self.assertEqual(len(p["discounts"]), 1)
        self.assertIsNone(self.by_id["23852"]["price"])      # VIRTUAL bez ceny → None jak w v8

    def test_operations_keep_type_and_expose_regulation(self):
        ops = self.by_id["86009"]["operations"]
        self.assertEqual(ops[0]["type"], "ACTIVATE")
        self.assertEqual(ops[0]["regulation"], "Możesz odstąpić <b>x</b>")   # CLI czyta 'regulation' (v8)
        self.assertEqual(ops[0]["legal"], "Możesz odstąpić <b>x</b>")        # oryginał zachowany
        self.assertEqual(ops[0]["title"], "Zamów i zapłać")
        self.assertEqual([o["type"] for o in self.by_id["23852"]["operations"]], ["MODIFY", "DEACTIVATE"])

    def test_category_section_and_activations_left(self):
        it = self.by_id["86009"]
        self.assertEqual(it["category"], {"title": "Pakiety", "type": "MOBILE_PACKETS"})
        self.assertEqual(it["section"], {"title": "Minuty", "type": "MINUTES"})
        self.assertEqual(it["numberOfActivationsLeft"], 998)

    def test_only_active_status_counts_as_active(self):
        states = {k: v["component"]["state"] for k, v in self.by_id.items()}
        self.assertEqual(states, {"86009": "INACTIVE", "64434": "DURING_CHANGE", "86000": "ACTIVE", "23852": "ACTIVE"})

    def test_empty_and_malformed_input(self):
        self.assertEqual(lib.flatten_catalog(None), [])
        self.assertEqual(lib.flatten_catalog({}), [])
        self.assertEqual(lib.flatten_catalog({"categories": None}), [])


class ParsePln(unittest.TestCase):
    def test_grosze(self):
        for s, g in [("3 zł", 300), ("19,95 zł", 1995), ("8 zł miesięcznie", 800), ("0 zł", 0), ("13,99 zł miesięcznie", 1399),
                     ("100 zł", 10000), ("2.5 zł", 250), (None, None), ("", None), ("brak", None)]:
            self.assertEqual(lib.parse_pln_grosze(s), g, s)


if __name__ == "__main__":
    unittest.main()

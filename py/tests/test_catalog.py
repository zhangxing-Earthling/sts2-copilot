# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rules"))

import catalog  # noqa: E402


class CatalogTests(unittest.TestCase):
    def test_catalog_covers_all_real_models(self):
        data = catalog.load()
        self.assertEqual(data["counts"]["cards"], 578)
        self.assertEqual(data["counts"]["relics"], 298)
        self.assertEqual(data["counts"]["powers"], 260)
        self.assertEqual(data["counts"]["potions"], 64)
        self.assertEqual(data["counts"]["events"], 68)
        self.assertEqual(data["counts"]["encounters"], 88)

    def test_every_entity_has_a_model_level_and_unique_class(self):
        data = catalog.load()
        for collection in ("cards", "relics", "powers", "potions", "events", "encounters"):
            classes = [item["class"] for item in data[collection]]
            self.assertEqual(len(classes), len(set(classes)), collection)
            for item in data[collection]:
                self.assertIn(
                    item.get("model", {}).get("level"),
                    {"exact", "partial", "catalog_only"},
                    (collection, item["class"]),
                )

    def test_card_metadata_and_effects(self):
        strike = catalog.card("StrikeSilent")
        self.assertEqual(strike["type"], "Attack")
        self.assertEqual(strike["target"], "any_enemy")
        self.assertIn("Strike", strike["tags"])
        self.assertEqual(strike["effects"][0]["kind"], "damage")

        backflip = catalog.card("Backflip")
        self.assertEqual([e["kind"] for e in backflip["effects"]], ["block", "draw"])
        self.assertEqual(backflip["model"]["level"], "partial")

    def test_known_relic_and_power(self):
        dummy = catalog.relic("StrikeDummy")
        self.assertEqual(dummy["model"]["level"], "exact")
        self.assertEqual(dummy["effects"][0]["kind"], "strike_damage_bonus")
        self.assertEqual(dummy["effects"][0]["value"], 3)

        thorns = catalog.power("ThornsPower")
        self.assertEqual(thorns["model"]["level"], "exact")
        self.assertEqual(thorns["type"], "Buff")

    def test_localized_relic_names_do_not_false_match(self):
        state = {"RelicIds": ["RingOfTheSnake"], "Relics": ["蛇之戒指"]}
        self.assertEqual(catalog.relic_ids_from_state(state), {"ringofthesnake"})
        self.assertFalse(catalog.has_relic(state, "STRIKE_DUMMY", "打击木偶"))

        owned = {"RelicIds": ["StrikeDummy"], "Relics": ["打击木偶"]}
        self.assertTrue(catalog.has_relic(owned, "STRIKE_DUMMY", "打击木偶"))

    def test_turn_end_hand_status_is_recorded(self):
        beckon = catalog.card("Beckon")
        self.assertEqual(beckon["type"], "Status")
        self.assertEqual(beckon["turn_end_effects"][0]["kind"], "self_damage")
        self.assertEqual(beckon["turn_end_effects"][0]["amount"], "HpLoss")

    def test_coverage_totals_match_counts(self):
        data = catalog.load()
        for collection, levels in data["coverage"].items():
            self.assertEqual(sum(levels.values()), data["counts"][collection])


if __name__ == "__main__":
    unittest.main()

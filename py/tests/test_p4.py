from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rules"))

import engine  # noqa: E402


def card(name: str, cost: int = 1, damage: int = 6) -> dict:
    return {
        "Id": "StrikeSilent",
        "Name": name,
        "Cost": cost,
        "CostsX": False,
        "Type": 1,
        "Target": 2,
        "Rarity": 1,
        "Upgraded": 0,
        "Playable": True,
        "Damage": damage,
        "Block": 0,
        "Poison": 0,
        "Hits": 1,
        "Vars": {},
    }


class P4Tests(unittest.TestCase):
    def test_shop_recommends_affordable_item(self):
        state = {
            "ValidationError": None,
            "InShop": True,
            "Gold": 100,
            "Hp": 60,
            "MaxHp": 70,
            "DeckCards": [card("打击")],
            "Potions": [],
            "ShopItems": [
                {"Kind": "relic", "Name": "昂贵遗物", "Cost": 200, "Affordable": False},
                {"Kind": "card", "Name": "优质攻击", "Cost": 50, "Affordable": True,
                 "Card": card("优质攻击", cost=0, damage=12)},
            ],
        }
        result = engine.advise(state)
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("shop.recommend", ids)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "shop.recommend")
        self.assertIn("优质攻击", recommend["text"])

    def test_rest_prefers_heal_when_low(self):
        state = {
            "ValidationError": None,
            "InRestSite": True,
            "Hp": 20,
            "MaxHp": 70,
            "DeckCards": [card("打击")],
            "RestOptions": [
                {"Index": 0, "OptionId": "HEAL", "Title": "休息", "Description": "", "Enabled": True, "HealAmount": 21},
                {"Index": 1, "OptionId": "SMITH", "Title": "锻造", "Description": "", "Enabled": True, "HealAmount": 0},
            ],
        }
        result = engine.advise(state)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "rest.recommend")
        self.assertIn("休息", recommend["text"])

    def test_treasure_prefers_higher_rarity(self):
        state = {
            "ValidationError": None,
            "InTreasure": True,
            "RelicChoices": [
                {"Index": 0, "Name": "普通遗物", "Description": "", "Rarity": 1},
                {"Index": 1, "Name": "稀有遗物", "Description": "", "Rarity": 4},
            ],
        }
        result = engine.advise(state)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "treasure.recommend")
        self.assertIn("稀有遗物", recommend["text"])

    def test_potion_inventory_flags_worst_when_full(self):
        state = {
            "ValidationError": None,
            "Hp": 60,
            "MaxHp": 70,
            "DeckCards": [card("打击")],
            "Potions": ["铁心药水", "爆炸安瓿", "甲虫汁"],
            "PotionIds": ["HeartOfIron", "ExplosiveAmpoule", "BeetleJuice"],
        }
        result = engine.advise(state)
        inventory = next(item for item in result["advice"] if item["ruleId"] == "potion.inventory")
        self.assertIn("药水已满", inventory["text"])
        self.assertIn("爆炸安瓿", inventory["text"])

    def test_potion_reward_discards_worst_when_full(self):
        state = {
            "ValidationError": None,
            "Hp": 60,
            "MaxHp": 70,
            "DeckCards": [card("打击")],
            "CardChoices": [card("切割", cost=0, damage=6)],
            "Potions": ["铁心药水", "爆炸安瓿", "甲虫汁"],
            "PotionIds": ["HeartOfIron", "ExplosiveAmpoule", "BeetleJuice"],
            "RewardPotions": ["幽灵罐"],
            "RewardPotionIds": ["GhostInAJar"],
        }
        result = engine.advise(state)
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("potion.reward", ids)
        discard = next(item for item in result["advice"] if item["ruleId"] == "potion.discard")
        self.assertIn("爆炸安瓿", discard["text"])
        self.assertIn("幽灵罐", discard["text"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rules"))

import engine  # noqa: E402


def option(title: str, description: str = "", relic: str | None = None, rarity: int = 0,
           locked: bool = False, proceed: bool = False, text_key: str | None = None) -> dict:
    return {
        "TextKey": text_key,
        "Title": title,
        "Description": description,
        "RelicId": "Relic" if relic else None,
        "RelicName": relic,
        "RelicRarity": rarity,
        "Locked": locked,
        "Proceed": proceed,
    }


def abyssal_state(hp: int, max_hp: int, damage: int, description: str = "") -> dict:
    return {
        "ValidationError": None,
        "InEvent": True,
        "EventId": "AbyssalBaths",
        "EventTitle": "深渊浴场",
        "EventDescription": description,
        "EventVars": {"MaxHp": 2, "Damage": damage, "Heal": 10},
        "Hp": hp,
        "MaxHp": max_hp,
        "EventOptions": [
            option(
                "沉溺",
                "获得点最大生命值。受到点伤害。",
                text_key="ABYSSAL_BATHS.pages.ALL.options.LINGER",
            ),
            option("离开浴场", "", text_key="ABYSSAL_BATHS.pages.ALL.options.EXIT_BATHS"),
        ],
    }


class EventAndMapTests(unittest.TestCase):
    def test_event_recommends_relic_over_curse(self):
        state = {
            "ValidationError": None,
            "InEvent": True,
            "EventTitle": "先古之民",
            "EventDescription": "选择一件遗物",
            "EventOptions": [
                option("获得稀有遗物", "获得一件稀有遗物", relic="稀有遗物", rarity=4),
                option("失去生命", "失去 10 点生命并获得诅咒",),
                option("离开", "不选择任何东西", locked=False, proceed=True),
            ],
        }
        result = engine.advise(state)
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("event.recommend", ids)
        self.assertNotIn("event.options", ids)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "event.recommend")
        self.assertIn("获得稀有遗物", recommend["text"])

    def test_event_without_options_is_context_only(self):
        state = {
            "ValidationError": None,
            "InEvent": True,
            "EventTitle": "事件",
            "EventDescription": "等待玩家选择",
            "EventOptions": [],
        }
        result = engine.advise(state)
        self.assertEqual([item["ruleId"] for item in result["advice"]], ["event.context"])

    def test_all_locked_options_report_no_option(self):
        state = {
            "ValidationError": None,
            "InEvent": True,
            "EventTitle": "事件",
            "EventOptions": [option("锁住的选项", locked=True)],
        }
        result = engine.advise(state)
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("event.no_option", ids)

    def test_abyssal_baths_lethal_linger_is_rejected(self):
        # Exact death-warning state from run_1792325581: HP 2/92, next linger
        # costs 14 unblockable damage (net 12 after +2 max HP).
        state = abyssal_state(
            2, 92, 14,
            description="再泡下去，你就死定了。",
        )
        result = engine.advise(state)
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("event.lethal", ids)
        lethal = next(item for item in result["advice"] if item["ruleId"] == "event.lethal")
        self.assertIn("会死亡", lethal["text"])
        recommend = next(item for item in result["advice"] if item["ruleId"] == "event.recommend")
        self.assertIn("离开浴场", recommend["text"])
        self.assertNotIn("推荐：沉溺", recommend["text"])

    def test_abyssal_baths_first_immerse_is_calculated(self):
        state = abyssal_state(68, 70, 3)
        result = engine.advise(state)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "event.recommend")
        self.assertIn("沉溺", recommend["text"])
        self.assertIn("净损失 1 HP", recommend["text"])
        self.assertNotIn("event.lethal", [item["ruleId"] for item in result["advice"]])

    def test_abyssal_baths_stops_at_net_four(self):
        # Third click leaves HP 62/76; the next click is net 4 for +2 max HP,
        # which is the stop point used by the A10 policy.
        state = abyssal_state(62, 76, 6)
        result = engine.advise(state)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "event.recommend")
        self.assertIn("离开浴场", recommend["text"])
        self.assertIn("净损失 4 HP", recommend["text"])

    def test_abyssal_baths_stops_before_hp_is_too_low(self):
        # Damage 12, +2 max HP => net 10; 23 HP would leave 13, and the next
        # click would leave 2. A10 should exit before that spiral.
        state = abyssal_state(23, 88, 12)
        result = engine.advise(state)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "event.recommend")
        self.assertIn("离开浴场", recommend["text"])
        self.assertIn("不划算", recommend["text"])

    def test_abyssal_baths_death_warning_without_vars_is_safe(self):
        state = abyssal_state(13, 90, 0)
        state["EventDescription"] = "再泡下去，你就死定了。"
        state.pop("EventVars")
        result = engine.advise(state)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "event.recommend")
        self.assertIn("离开浴场", recommend["text"])
        self.assertIn("event.lethal", [item["ruleId"] for item in result["advice"]])

    def test_map_start_with_three_choices_has_recommendation(self):
        state = {
            "ValidationError": None,
            "InCombat": False,
            "Hp": 70,
            "MaxHp": 70,
            "Gold": 100,
            "Act": 1,
            "Floor": 0,
            "MapChoices": [
                {"Col": 3, "Row": 1, "Type": 5, "TypeName": "战斗"},
                {"Col": 4, "Row": 1, "Type": 1, "TypeName": "未知"},
                {"Col": 5, "Row": 1, "Type": 6, "TypeName": "精英"},
            ],
            "MapNodes": [],
            "MapEdges": [],
        }
        result = engine.advise(state)
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("map.recommend", ids)
        self.assertIn("map.route", ids)

    def test_map_dp_uses_future_path_when_start_not_in_graph(self):
        state = {
            "ValidationError": None,
            "InCombat": False,
            "Hp": 70,
            "MaxHp": 70,
            "Act": 1,
            "Ascension": 0,
            "MapCol": 0,
            "MapRow": 0,
            "MapChoices": [
                {"Col": 0, "Row": 1, "Type": 6, "TypeName": "精英"},
                {"Col": 1, "Row": 1, "Type": 5, "TypeName": "战斗"},
            ],
            "MapNodes": [
                {"Col": 0, "Row": 1, "Type": 6, "TypeName": "精英"},
                {"Col": 0, "Row": 2, "Type": 6, "TypeName": "精英"},
                {"Col": 1, "Row": 1, "Type": 5, "TypeName": "战斗"},
                {"Col": 1, "Row": 2, "Type": 4, "TypeName": "营地"},
                {"Col": 0, "Row": 3, "Type": 7, "TypeName": "Boss"},
                {"Col": 1, "Row": 3, "Type": 7, "TypeName": "Boss"},
            ],
            "MapEdges": [
                {"FromCol": 0, "FromRow": 1, "ToCol": 0, "ToRow": 2},
                {"FromCol": 0, "FromRow": 2, "ToCol": 0, "ToRow": 3},
                {"FromCol": 1, "FromRow": 1, "ToCol": 1, "ToRow": 2},
                {"FromCol": 1, "FromRow": 2, "ToCol": 1, "ToRow": 3},
            ],
        }
        result = engine.advise(state)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "map.recommend")
        # The second choice wins only if the DP sees the rest before the boss
        # and the elite-stacking penalty; an immediate-only score would pick
        # the elite (2.8 > 1.0).
        self.assertIn("战斗(1,1)", recommend["text"])
        self.assertIn("营地(1,2)", recommend["text"])
        self.assertIn("Boss(1,3)", recommend["text"])
        self.assertIn("综合评分", recommend["text"])
        route = next(item for item in result["advice"] if item["ruleId"] == "map.route")
        self.assertIn("下一步（分数已包含之后到 Boss 的路径）", route["text"])
        self.assertIn("战斗（1,1）", route["text"])

    def test_map_close_call_when_future_scores_are_close(self):
        state = {
            "ValidationError": None,
            "InCombat": False,
            "Hp": 70,
            "MaxHp": 70,
            "Act": 1,
            "Ascension": 0,
            "MapCol": 0,
            "MapRow": 0,
            "MapChoices": [
                {"Col": 0, "Row": 1, "Type": 5, "TypeName": "战斗"},
                {"Col": 1, "Row": 1, "Type": 5, "TypeName": "战斗"},
            ],
            "MapNodes": [
                {"Col": 0, "Row": 1, "Type": 5, "TypeName": "战斗"},
                {"Col": 1, "Row": 1, "Type": 5, "TypeName": "战斗"},
                {"Col": 0, "Row": 2, "Type": 7, "TypeName": "Boss"},
                {"Col": 1, "Row": 2, "Type": 7, "TypeName": "Boss"},
            ],
            "MapEdges": [
                {"FromCol": 0, "FromRow": 1, "ToCol": 0, "ToRow": 2},
                {"FromCol": 1, "FromRow": 1, "ToCol": 1, "ToRow": 2},
            ],
        }
        result = engine.advise(state)
        self.assertIn("map.close_call", [item["ruleId"] for item in result["advice"]])

    def test_map_lookahead_when_boss_node_is_missing(self):
        state = {
            "ValidationError": None,
            "InCombat": False,
            "Hp": 70,
            "MaxHp": 70,
            "Act": 1,
            "Ascension": 0,
            "MapCol": 0,
            "MapRow": 0,
            "MapChoices": [
                {"Col": 0, "Row": 1, "Type": 5, "TypeName": "战斗"},
                {"Col": 1, "Row": 1, "Type": 6, "TypeName": "精英"},
            ],
            "MapNodes": [
                {"Col": 0, "Row": 1, "Type": 5, "TypeName": "战斗"},
                {"Col": 0, "Row": 2, "Type": 4, "TypeName": "营地"},
                {"Col": 1, "Row": 1, "Type": 6, "TypeName": "精英"},
                {"Col": 1, "Row": 2, "Type": 4, "TypeName": "营地"},
            ],
            "MapEdges": [
                {"FromCol": 0, "FromRow": 1, "ToCol": 0, "ToRow": 2},
                {"FromCol": 1, "FromRow": 1, "ToCol": 1, "ToRow": 2},
            ],
        }
        result = engine.advise(state)
        recommend = next(item for item in result["advice"] if item["ruleId"] == "map.recommend")
        self.assertIn("局部前瞻", recommend["text"])
        self.assertIn("营地", recommend["text"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import digest  # noqa: E402


def turn(seq: int, turn_number: int, hp: int, solver: dict, encounter: str = "SlimesNormal") -> dict:
    return {
        "seq": seq,
        "type": "turn",
        "state": {
            "Turn": turn_number,
            "Hp": hp,
            "MaxHp": 70,
            "Act": 1,
            "Floor": 3,
            "Energy": 3,
            "Encounter": encounter,
            "DeckCount": 15,
            "Hand": [{"Name": "打击", "Cost": 1}],
            "Enemies": [{"Name": "史莱姆", "Hp": 10, "MaxHp": 10}],
        },
        "solver": solver,
        "advice": [{"RuleId": "combat.solver", "Text": "打击"}],
    }


def solver(hp_after: int, lethal: bool = False, unmodeled: list[str] | None = None) -> dict:
    return {
        "version": 1,
        "sequence": ["打击"],
        "hpLoss": 0,
        "hpAfter": hp_after,
        "lethal": lethal,
        "unmodeled": unmodeled or [],
    }


def sample_events() -> list[dict]:
    return [
        {
            "seq": 1,
            "type": "run_start",
            "payload": {
                "GameVersion": "0.107.1",
                "Seed": "TESTSEED",
                "Character": "静默猎手",
                "Ascension": 0,
                "Act": 1,
                "Floor": 2,
                "Hp": 70,
                "MaxHp": 70,
                "DeckCount": 15,
            },
        },
        {"seq": 2, "type": "combat_start", "payload": {"Floor": 3, "Encounter": "SlimesNormal", "Hp": 70}},
        turn(3, 1, 70, solver(60, unmodeled=["早有准备"])),
        {"seq": 4, "type": "card_play", "turn": 1, "payload": {"Name": "打击", "Id": "StrikeSilent"}},
        turn(5, 2, 58, solver(58)),
        {"seq": 6, "type": "combat_end", "payload": {"Hp": 50, "MaxHp": 70, "Turn": 2}},
        {
            "seq": 7,
            "type": "reward",
            "floor": 3,
            "choices": [{"Name": "后空翻"}],
            "advice": [{"RuleId": "reward.recommend", "Text": "推荐：后空翻"}],
        },
        {
            "seq": 8,
            "type": "reward_pick",
            "floor": 3,
            "skipped": False,
            "options": [{"Name": "后空翻"}, {"Name": "飞镖"}],
            "picked": [{"Name": "后空翻"}],
        },
        {
            "seq": 9,
            "type": "map_pick",
            "floor": 4,
            "from": {"col": 3, "row": 8, "type": "战斗"},
            "to": {"col": 3, "row": 9, "type": "宝箱"},
        },
        {"seq": 10, "type": "run_end", "payload": {"reason": "app_closed"}},
    ]


class DigestTests(unittest.TestCase):
    def test_run_and_metrics(self):
        data = digest.build_digest(sample_events(), "run.jsonl")
        self.assertEqual(data["run"]["seed"], "TESTSEED")
        self.assertEqual(data["run"]["character"], "静默猎手")
        self.assertEqual(data["run"]["floor_reached"], 4)
        self.assertEqual(data["metrics"]["turns"], 2)
        self.assertEqual(data["metrics"]["combats"], 1)
        self.assertTrue(data["metrics"]["low_sample"])
        self.assertEqual(data["metrics"]["turns_evaluated"], 2)
        self.assertEqual(data["metrics"]["mae"], 5.0)
        self.assertEqual(data["metrics"]["within_one"], 0.0)
        self.assertEqual(data["metrics"]["card_plays"], 1)
        self.assertEqual(data["metrics"]["reward_picks"], 1)
        self.assertEqual(data["metrics"]["map_picks"], 1)
        self.assertEqual(data["metrics"]["unmodeled"]["早有准备"], 1)
        self.assertEqual(data["metrics"]["hp_loss_by_act"], [20])

    def test_decisions_have_stable_event_ids(self):
        data = digest.build_digest(sample_events(), "run.jsonl")
        ids = [decision["event_id"] for decision in data["decisions"]]
        self.assertIn("evt_0003", ids)
        self.assertIn("evt_0008", ids)
        self.assertIn("evt_0009", ids)
        self.assertEqual(len(ids), len(set(ids)))

        combat = next(d for d in data["decisions"] if d["event_id"] == "evt_0003")
        self.assertEqual(combat["kind"], "combat")
        self.assertEqual(combat["loss_hp"], 12)
        self.assertEqual(combat["error"], -2)

        reward = next(d for d in data["decisions"] if d["event_id"] == "evt_0008")
        self.assertEqual(reward["chosen"], "后空翻")
        self.assertIn("后空翻", reward["advice"])

        map_decision = next(d for d in data["decisions"] if d["event_id"] == "evt_0009")
        self.assertIn("宝箱(3,9)", map_decision["chosen"])

    def test_lethal_false_is_counted(self):
        events = sample_events()
        events[2] = turn(3, 1, 70, solver(70, lethal=True))
        data = digest.build_digest(events, "run.jsonl")
        self.assertEqual(data["metrics"]["lethal_false"], 1)

    def test_markdown_contains_metrics(self):
        data = digest.build_digest(sample_events(), "run.jsonl")
        text = digest.render_markdown(data)
        self.assertIn("TESTSEED", text)
        self.assertIn("MAE", text)
        self.assertIn("evt_0003", text)


if __name__ == "__main__":
    unittest.main()

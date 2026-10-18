from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import calibrate  # noqa: E402


def turn(turn_number: int, hp: int, solver: dict | None = None, encounter: str | None = None) -> dict:
    state = {"Turn": turn_number, "Hp": hp, "InCombat": True}
    if encounter is not None:
        state["Encounter"] = encounter
    event = {
        "type": "turn",
        "state": state,
    }
    if solver is not None:
        event["solver"] = solver
    return event


def solver(hp_after: int, hp_loss: int = 0, lethal: bool = False) -> dict:
    return {
        "version": 1,
        "sequence": ["打击"],
        "hpLoss": hp_loss,
        "hpAfter": hp_after,
        "lethal": lethal,
        "unmodeled": ["刀扇"],
    }


class CalibrationTests(unittest.TestCase):
    def test_pairs_with_next_turn_and_combat_end(self):
        events = [
            {"type": "combat_start", "payload": {"Hp": 70}},
            turn(1, 70, solver(60, hp_loss=10)),
            turn(2, 58, solver(58, hp_loss=0)),
            {"type": "combat_end", "payload": {"Hp": 50}},
        ]
        result = calibrate.analyze_events(events, "run.jsonl")
        self.assertEqual(result.evaluated, 2)
        self.assertEqual([s.error for s in result.samples], [-2, -8])
        self.assertEqual(result.mae, 5.0)
        self.assertEqual(result.missing, 0)
        self.assertEqual(result.unmodeled["刀扇"], 2)

    def test_pascal_case_log_shape(self):
        events = [
            turn(1, 70, {
                "Version": 1,
                "Sequence": ["打击→虫"],
                "HpLoss": 10,
                "HpAfter": 60,
                "Lethal": False,
                "Unmodeled": ["刀扇"],
            }),
            turn(2, 58, solver(58)),
            {"type": "combat_end", "payload": {"Hp": 58}},
        ]
        result = calibrate.analyze_events(events)
        self.assertEqual(result.evaluated, 2)
        self.assertEqual(result.samples[0].predicted_hp, 60)
        self.assertEqual(result.samples[0].error, -2)
        self.assertEqual(result.unmodeled["刀扇"], 2)

    def test_missing_solver_is_counted_not_zero_error(self):
        events = [
            turn(1, 70, solver(60)),
            turn(2, 58, None),
        ]
        result = calibrate.analyze_events(events)
        self.assertEqual(result.evaluated, 1)
        self.assertEqual(result.missing, 1)
        self.assertEqual(result.samples[0].error, -2)

    def test_followed_sequence_is_detected(self):
        events = [
            turn(1, 70, solver(60, hp_loss=10)),
            {"type": "action", "kind": "card_play", "played": [{"name": "打击"}]},
            turn(2, 58, solver(58)),
            {"type": "combat_end", "payload": {"Hp": 58}},
        ]
        result = calibrate.analyze_events(events)
        self.assertTrue(result.samples[0].followed)
        self.assertEqual(result.followed, 1)

    def test_precise_card_play_event_is_detected(self):
        events = [
            turn(1, 70, solver(60, hp_loss=10)),
            {"type": "card_play", "payload": {"Name": "打击", "Target": "虫"}},
            turn(2, 58, solver(58)),
            {"type": "combat_end", "payload": {"Hp": 58}},
        ]
        result = calibrate.analyze_events(events)
        self.assertTrue(result.samples[0].followed)
        self.assertEqual(result.followed, 1)

    def test_upgrade_marker_is_ignored_for_followed_sequence(self):
        upgraded = solver(60, hp_loss=10)
        upgraded["sequence"] = ["打击+→虫"]
        events = [
            turn(1, 70, upgraded),
            {"type": "card_play", "payload": {"Name": "打击", "Target": "虫"}},
            turn(2, 58, solver(58)),
            {"type": "combat_end", "payload": {"Hp": 58}},
        ]
        result = calibrate.analyze_events(events)
        self.assertTrue(result.samples[0].followed)

    def test_auto_play_is_not_part_of_player_sequence(self):
        events = [
            turn(1, 70, solver(60, hp_loss=10)),
            {"type": "card_play", "payload": {"Name": "打击", "AutoPlay": False}},
            {"type": "card_play", "payload": {"Name": "匕首", "AutoPlay": True}},
            turn(2, 58, solver(58)),
            {"type": "combat_end", "payload": {"Hp": 58}},
        ]
        result = calibrate.analyze_events(events)
        self.assertTrue(result.samples[0].followed)

    def test_other_play_is_not_followed(self):
        events = [
            turn(1, 70, solver(60, hp_loss=10)),
            {"type": "action", "kind": "card_play", "played": [{"name": "防御"}]},
            turn(2, 58, solver(58)),
            {"type": "combat_end", "payload": {"Hp": 58}},
        ]
        result = calibrate.analyze_events(events)
        self.assertFalse(result.samples[0].followed)
        self.assertEqual(result.followed, 0)

    def test_no_action_events_means_unknown(self):
        events = [
            turn(1, 70, solver(60, hp_loss=10)),
            turn(2, 58, solver(58)),
            {"type": "combat_end", "payload": {"Hp": 58}},
        ]
        result = calibrate.analyze_events(events)
        self.assertIsNone(result.samples[0].followed)

    def test_solver_error_is_not_a_sample(self):
        events = [
            turn(1, 70, {"version": 1, "error": "没有可精确模拟的牌"}),
            turn(2, 70, solver(70)),
            {"type": "combat_end", "payload": {"Hp": 70}},
        ]
        result = calibrate.analyze_events(events)
        self.assertEqual(result.errors, 1)
        self.assertEqual(result.evaluated, 1)

    def test_lethal_false_positive(self):
        events = [
            turn(1, 70, solver(70, lethal=True)),
            turn(2, 70, solver(70)),
        ]
        result = calibrate.analyze_events(events)
        self.assertEqual(result.lethal_false, 1)
        # No card_play events, so the sequence cannot be confirmed as followed.
        self.assertEqual(result.lethal_false_followed, 0)

    def test_lethal_false_counts_followed_plays_as_model_error(self):
        events = [
            turn(1, 70, solver(70, lethal=True)),
            {"type": "card_play", "payload": {"Name": "打击", "Target": "虫"}},
            turn(2, 63, solver(63)),
        ]
        result = calibrate.analyze_events(events)
        self.assertEqual(result.lethal_false, 1)
        self.assertEqual(result.lethal_false_followed, 1)

    def test_lethal_false_is_not_a_model_error_when_player_diverges(self):
        events = [
            turn(1, 70, solver(70, lethal=True)),
            {"type": "card_play", "payload": {"Name": "防御", "Target": None}},
            turn(2, 63, solver(63)),
        ]
        result = calibrate.analyze_events(events)
        self.assertEqual(result.lethal_false, 1)
        self.assertEqual(result.lethal_false_followed, 0)

    def test_sample_keeps_encounter_name(self):
        events = [
            turn(3, 70, solver(60), encounter="LagavulinMatriarchBoss"),
            turn(4, 58, solver(58), encounter="LagavulinMatriarchBoss"),
        ]
        result = calibrate.analyze_events(events)
        self.assertEqual(result.samples[0].encounter, "LagavulinMatriarchBoss")
        self.assertIn("encounter", calibrate.to_json(result)["samples"][0])

    def test_new_encounter_without_combat_end_is_not_lethal_false(self):
        # The app can miss combat_end when CombatState stays non-null between
        # fights. A new encounter means the old lethal prediction did come true.
        events = [
            turn(6, 30, solver(30, lethal=True), encounter="FlyconidNormal"),
            turn(1, 30, solver(30), encounter="MawlerNormal"),
        ]
        result = calibrate.analyze_events(events)
        self.assertEqual(result.evaluated, 1)
        self.assertEqual(result.lethal_false, 0)

    def test_same_encounter_still_counts_lethal_false(self):
        events = [
            turn(1, 70, solver(70, lethal=True), encounter="NibbitsWeak"),
            turn(2, 63, solver(63), encounter="NibbitsWeak"),
        ]
        result = calibrate.analyze_events(events)
        self.assertEqual(result.lethal_false, 1)

    def test_replay_mode_ignores_the_logged_solver(self):
        events = [
            turn(1, 70, solver(60, hp_loss=10)),
            turn(2, 58, solver(58)),
            {"type": "combat_end", "payload": {"Hp": 58}},
        ]
        seen = []

        def resolve(state):
            seen.append(state)
            return {
                "HpAfter": 65,
                "HpLoss": 5,
                "Lethal": False,
                "Sequence": [],
                "Unmodeled": ["杂技"],
                "Truncated": False,
            }

        result = calibrate.analyze_events(events, "run.jsonl", resolve)
        self.assertEqual(len(seen), 2)
        self.assertEqual(result.samples[0].predicted_hp, 65)
        self.assertEqual(result.samples[0].error, -7)
        self.assertEqual(result.unmodeled["杂技"], 2)

    def test_replay_resolver_uses_current_rules_code(self):
        resolver = calibrate.replay_resolver()
        payload = {
            "ValidationError": None,
            "InCombat": True,
            "Hp": 70,
            "MaxHp": 70,
            "Block": 0,
            "Energy": 3,
            "MaxEnergy": 3,
            "DrawCount": 0,
            "PlayerPowers": {},
            "Enemies": [{
                "Name": "虫", "Hp": 6, "MaxHp": 6, "Block": 0,
                "Damage": 8, "Hits": 1, "Powers": {},
                "Attacks": [{"BaseDamage": 8, "Hits": 1}],
            }],
            "Hand": [{
                "Id": "StrikeSilent", "Name": "打击", "Cost": 1, "Type": 1, "Target": 2,
                "Damage": 6, "Hits": 1, "Vars": {"Damage": 6},
            }],
            "DeckCards": [],
            "Relics": [],
            "RelicIds": [],
            "RelicCounters": {},
        }
        solved = resolver(payload)
        self.assertIsNotNone(solved)
        self.assertEqual(solved["HpAfter"], 70)
        self.assertTrue(solved["Lethal"])
        self.assertEqual(solved["Sequence"], ["打击"])

    def test_json_file_round_trip(self):
        events = [
            turn(1, 70, solver(60, hp_loss=10)),
            turn(2, 58, solver(58)),
            {"type": "combat_end", "payload": {"Hp": 58}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
            result = calibrate.analyze_files([str(path)])
        payload = calibrate.to_json(result)
        self.assertEqual(payload["evaluated"], 2)
        self.assertEqual(payload["mae"], 1.0)
        self.assertEqual(len(payload["samples"]), 2)


if __name__ == "__main__":
    unittest.main()

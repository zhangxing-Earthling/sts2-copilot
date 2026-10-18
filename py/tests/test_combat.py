from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rules"))

import combat  # noqa: E402
import engine  # noqa: E402


def card(
    card_id: str,
    name: str,
    cost: int,
    card_type: int,
    target: int,
    damage: int = 0,
    block: int = 0,
    poison: int = 0,
    hits: int = 1,
    vars: dict | None = None,
) -> dict:
    return {
        "Id": card_id,
        "Name": name,
        "Cost": cost,
        "CostsX": False,
        "Type": card_type,
        "Target": target,
        "Damage": damage,
        "Block": block,
        "Poison": poison,
        "Hits": hits,
        "Playable": True,
        "Vars": vars or {},
    }


def enemy(
    name: str,
    hp: int,
    damage: int = 0,
    hits: int = 1,
    block: int = 0,
    powers: dict | None = None,
) -> dict:
    return {
        "Name": name,
        "Hp": hp,
        "MaxHp": hp,
        "Block": block,
        "Damage": damage * hits,
        "Hits": hits,
        "Powers": powers or {},
        "Attacks": [{"BaseDamage": damage, "Hits": hits, "Damage": damage * hits}]
        if damage
        else [],
    }


def state(hand: list[dict], enemies: list[dict], energy: int = 3, hp: int = 70, block: int = 0) -> dict:
    return {
        "ValidationError": None,
        "InCombat": True,
        "Hp": hp,
        "MaxHp": 70,
        "Block": block,
        "Energy": energy,
        "MaxEnergy": 3,
        "PlayerPowers": {},
        "Hand": hand,
        "Enemies": enemies,
        "CardChoices": [],
        "MapChoices": [],
        "DeckCards": hand,
    }


class CombatSolverTests(unittest.TestCase):
    def solve(self, payload: dict):
        result, error = combat.solve(payload)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        return result

    def test_two_strikes_are_lethal(self):
        result = self.solve(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("DefendSilent", "防御", 1, 2, 1, block=5),
            ],
            [enemy("虫", 10, damage=8)],
            energy=2,
        ))
        self.assertTrue(result.outcome.lethal)
        self.assertEqual([p.name for p in result.plays], ["打击", "打击"])
        self.assertEqual(result.outcome.hp_loss, 0)
        self.assertEqual(result.outcome.enemy_hp_left, 0)

    def test_block_is_chosen_to_minimize_hp_loss(self):
        result = self.solve(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("DefendSilent", "防御", 1, 2, 1, block=5),
            ],
            [enemy("虫", 20, damage=8)],
            energy=2,
        ))
        self.assertFalse(result.outcome.lethal)
        self.assertEqual(len(result.plays), 2)
        self.assertEqual(result.outcome.hp_loss, 3)
        self.assertEqual(result.block_left, 5)
        self.assertEqual(result.outcome.enemy_hp_left, 14)

    def test_weak_reduces_enemy_damage(self):
        result = self.solve(state(
            [
                card(
                    "Neutralize",
                    "中和",
                    0,
                    1,
                    2,
                    damage=3,
                    vars={"Damage": 3, "WeakPower": 1},
                )
            ],
            [enemy("虫", 20, damage=8)],
            energy=0,
        ))
        self.assertEqual([p.name for p in result.plays], ["中和"])
        self.assertEqual(result.outcome.incoming, 6)
        self.assertEqual(result.outcome.hp_loss, 6)

    def test_poison_ticks_before_enemy_attack(self):
        result = self.solve(state(
            [
                card(
                    "PoisonedStab",
                    "带毒刺击",
                    1,
                    1,
                    2,
                    damage=6,
                    poison=3,
                    vars={"Damage": 6, "PoisonPower": 3},
                )
            ],
            [enemy("虫", 8, damage=10)],
            energy=1,
        ))
        self.assertTrue(result.outcome.lethal)
        self.assertEqual(result.outcome.poison_kills, 1)
        self.assertEqual(result.outcome.hp_loss, 0)

    def test_attack_targets_enemy_that_would_attack(self):
        result = self.solve(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("小虫", 5, damage=10), enemy("木桩", 20, damage=0)],
            energy=1,
        ))
        self.assertEqual(result.plays[0].target_index, 0)
        self.assertEqual(result.outcome.hp_loss, 0)
        self.assertEqual(result.outcome.enemy_hp_left, 20)

    def test_all_enemies_attack_hits_all(self):
        result = self.solve(state(
            [
                card("DaggerSpray", "匕首雨", 1, 1, 3, damage=4, hits=2),
            ],
            [enemy("虫A", 8, damage=0), enemy("虫B", 8, damage=0)],
            energy=1,
        ))
        self.assertEqual(result.outcome.enemy_hp_left, 0)
        self.assertTrue(result.plays[0].target_all)

    def test_survivor_discards_a_card(self):
        result = self.solve(state(
            [
                card("Survivor", "生存者", 1, 2, 1, block=8),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 20, damage=10)],
            energy=1,
        ))
        self.assertEqual([p.name for p in result.plays], ["生存者"])
        self.assertIsNotNone(result.plays[0].discard_index)
        self.assertEqual(result.outcome.hp_loss, 2)
        self.assertEqual(result.block_left, 8)

    def test_unmodeled_card_is_reported_not_guessed(self):
        result = self.solve(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("Acrobatics", "杂技", 1, 2, 1, vars={"Cards": 3}),
            ],
            [enemy("虫", 20, damage=8)],
            energy=2,
        ))
        self.assertEqual([p.name for p in result.plays], ["打击"])
        self.assertEqual(result.unmodeled[0][0], "杂技")
        self.assertIn("Cards", result.unmodeled[0][1])

    def test_multi_hit_respects_enemy_block(self):
        result = self.solve(state(
            [
                card("StrikeSilent", "连击", 1, 1, 2, damage=3, hits=2),
            ],
            [enemy("虫", 10, block=2)],
            energy=1,
        ))
        self.assertEqual(result.outcome.enemy_hp_left, 6)

    def test_strength_weak_vulnerable_and_frail(self):
        payload = state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("DefendSilent", "防御", 1, 2, 1, block=5),
            ],
            [enemy("虫", 30, damage=8, powers={"VulnerablePower": 1})],
            energy=2,
        )
        payload["PlayerPowers"] = {
            "StrengthPower": 2,
            "DexterityPower": 2,
            "WeakPower": 1,
            "FrailPower": 1,
        }
        result = self.solve(payload)
        # Strike: (6 + 2) * 0.75 * 1.5 = 9; Defend: (5 + 2) * 0.75 = 5.
        self.assertEqual(result.damage_dealt, 9)
        self.assertEqual(result.block_left, 5)
        self.assertEqual(result.outcome.hp_loss, 3)

    def test_vulnerable_player_takes_more_damage(self):
        payload = state(
            [card("DefendSilent", "防御", 1, 2, 1, block=5)],
            [enemy("虫", 30, damage=8)],
            energy=1,
        )
        payload["PlayerPowers"] = {"VulnerablePower": 1}
        result = self.solve(payload)
        self.assertEqual(result.outcome.incoming, 12)
        self.assertEqual(result.outcome.hp_loss, 7)

    def test_lethal_beats_zero_damage_taken(self):
        payload = state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("DefendSilent", "防御", 1, 2, 1, block=5),
            ],
            [enemy("虫", 6, damage=10)],
            energy=2,
        )
        result = self.solve(payload)
        self.assertTrue(result.outcome.lethal)
        self.assertEqual([p.name for p in result.plays], ["打击"])
        self.assertEqual(result.outcome.hp_loss, 0)

    def test_legacy_state_without_target_falls_back(self):
        legacy = state(
            [
                {
                    "Id": "StrikeSilent",
                    "Name": "打击",
                    "Cost": 1,
                    "Type": 1,
                    "Damage": 6,
                    "Block": 0,
                    "Poison": 0,
                    "Hits": 1,
                }
            ],
            [enemy("虫", 10, damage=8)],
            energy=1,
        )
        result = engine.advise(legacy)
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("combat.solver_unavailable", ids)
        self.assertIn("combat.incoming", ids)

    def test_engine_returns_solver_advice(self):
        result = engine.advise(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 10, damage=8)],
            energy=2,
        ))
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("combat.solver", ids)
        self.assertNotIn("combat.lethal_available", ids)


if __name__ == "__main__":
    unittest.main()

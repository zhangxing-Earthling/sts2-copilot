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
    costs_x: bool = False,
    upgraded: int = 0,
) -> dict:
    return {
        "Id": card_id,
        "Name": name,
        "Cost": cost,
        "CostsX": costs_x,
        "Type": card_type,
        "Target": target,
        "Damage": damage,
        "Block": block,
        "Poison": poison,
        "Hits": hits,
        "Upgraded": upgraded,
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
        "Attacks": [{"BaseDamage": damage, "Hits": hits}]
        if damage
        else [],
    }


def state(hand: list[dict], enemies: list[dict], energy: int = 3, hp: int = 70, block: int = 0,
          draw_count: int = 0, relics: list[str] | None = None, relic_ids: list[str] | None = None,
          potions: list[str] | None = None, potion_ids: list[str] | None = None) -> dict:
    return {
        "ValidationError": None,
        "InCombat": True,
        "Hp": hp,
        "MaxHp": 70,
        "Block": block,
        "Energy": energy,
        "MaxEnergy": 3,
        "DrawCount": draw_count,
        "PlayerPowers": {},
        "Hand": hand,
        "Enemies": enemies,
        "CardChoices": [],
        "MapChoices": [],
        "DeckCards": hand,
        "Relics": relics or [],
        "RelicIds": relic_ids or [],
        "Potions": potions or [],
        "PotionIds": potion_ids or [],
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

    def test_localized_relic_names_do_not_grant_strike_dummy(self):
        # Regression: Chinese relic names normalize to "" and used to make
        # has_relic(..., "STRIKE_DUMMY") true for every run, adding +3 to
        # every Strike. Two 6-damage Strikes must leave a 13 HP enemy alive.
        result = self.solve(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 13)],
            energy=2,
            relics=["蛇之戒指", "白银熔炉"],
            relic_ids=["RingOfTheSnake", "SilverCrucible"],
        ))
        self.assertFalse(result.outcome.lethal)
        self.assertEqual(result.outcome.enemy_hp_left, 1)
        self.assertEqual(result.damage_dealt, 12)

    def test_x_cost_skewer_uses_energy_as_hit_count(self):
        result = self.solve(state(
            [
                card("Skewer", "串刺", 0, 1, 2, damage=8, costs_x=True),
            ],
            [enemy("虫", 24)],
            energy=3,
        ))
        self.assertTrue(result.outcome.lethal)
        self.assertEqual([p.name for p in result.plays], ["串刺"])
        self.assertEqual(result.plays[0].cost, 3)
        self.assertEqual(result.damage_dealt, 24)
        self.assertEqual(result.outcome.hp_after, 70)
        self.assertEqual(result.unmodeled, ())

    def test_fisticuffs_gains_block_from_damage(self):
        result = self.solve(state(
            [
                card("Fisticuffs", "拳斗", 1, 1, 2, damage=7),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 41, damage=10)],
            energy=3,
            hp=4,
        ))
        # Fisticuffs + two Strikes deal 19 and gain 7 block; the 10 attack
        # leaves HP 1. Three Strikes would leave HP 0.
        self.assertIn("拳斗", [p.name for p in result.plays])
        self.assertEqual(result.outcome.hp_after, 1)

    def test_immediate_inflame_buffs_later_strike(self):
        result = self.solve(state(
            [
                card("Inflame", "燃烧", 1, 3, 1, vars={"StrengthPower": 2}),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 20)],
            energy=2,
        ))
        self.assertEqual([p.name for p in result.plays], ["燃烧", "打击"])
        self.assertEqual(result.damage_dealt, 8)

    def test_immediate_footwork_buffs_later_block(self):
        result = self.solve(state(
            [
                card("Footwork", "步法", 1, 3, 1, vars={"DexterityPower": 2}),
                card("DefendSilent", "防御", 1, 2, 1, block=5),
            ],
            [enemy("虫", 20, damage=10)],
            energy=2,
        ))
        self.assertEqual([p.name for p in result.plays], ["步法", "防御"])
        self.assertEqual(result.block_left, 7)

    def test_artifact_blocks_one_debuff(self):
        payload = state(
            [card("Neutralize", "中和", 0, 1, 2, damage=3, vars={"WeakPower": 1})],
            [enemy("虫", 20, powers={"ArtifactPower": 1})],
            energy=3,
        )
        solver, modeled, unmodeled, error = combat.build_solver(payload)
        self.assertIsNone(error)
        card_model = next(c for c in modeled if c.name == "中和")
        after = combat._play(solver.state, card_model, 0, None)
        self.assertIsNotNone(after)
        self.assertEqual(after.enemies[0].weak, 0)
        self.assertEqual(after.enemies[0].artifact, 0)

    def test_artifact_blocks_poison(self):
        payload = state(
            [card("DeadlyPoison", "致命毒药", 1, 2, 2, poison=7)],
            [enemy("虫", 20, powers={"ArtifactPower": 1})],
            energy=3,
        )
        solver, modeled, unmodeled, error = combat.build_solver(payload)
        self.assertIsNone(error)
        card_model = next(c for c in modeled if c.name == "致命毒药")
        after = combat._play(solver.state, card_model, 0, None)
        self.assertIsNotNone(after)
        self.assertEqual(after.enemies[0].poison, 0)
        self.assertEqual(after.enemies[0].artifact, 0)

    def test_pen_nib_counter_doubles_next_attack(self):
        payload = state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 20)],
            energy=2,
        )
        payload["RelicCounters"] = {"PenNib": 9}
        result = self.solve(payload)
        self.assertEqual(result.damage_dealt, 18)
        self.assertEqual(result.outcome.enemy_hp_left, 2)

    def test_gremlin_horn_gives_energy_on_kill(self):
        result = self.solve(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 1), enemy("虫2", 20)],
            energy=2,
            relic_ids=["GremlinHorn"],
        ))
        self.assertEqual(len(result.plays), 3)
        self.assertEqual(result.damage_dealt, 13)

    def test_paper_phrog_and_cruelty_change_vulnerable_multiplier(self):
        def attack(player):
            return combat._attack_value(
                combat.Card(index=0, name="打击", cost=1, target=2, damage=6,
                            block=0, poison=0, hits=1, weak=0, vulnerable=0,
                            frail=0, strength=0, dexterity=0),
                player,
                combat.Enemy(name="虫", hp=20, block=0, attacks=(), strength=0,
                             weak=0, vulnerable=1, poison=0),
            )

        base_player = combat.Player(hp=70, block=0, energy=3, strength=0, dexterity=0,
                                    weak=0, vulnerable=0, frail=0, shrink=False)
        phrog_player = combat.Player(hp=70, block=0, energy=3, strength=0, dexterity=0,
                                     weak=0, vulnerable=0, frail=0, shrink=False,
                                     paper_phrog=True)
        cruelty_player = combat.Player(hp=70, block=0, energy=3, strength=0, dexterity=0,
                                       weak=0, vulnerable=0, frail=0, shrink=False,
                                       cruelty=50)
        self.assertEqual(attack(base_player), 9)
        self.assertEqual(attack(phrog_player), 10)
        self.assertEqual(attack(cruelty_player), 12)

        debilitated_enemy = combat.Enemy(
            name="虫", hp=20, block=0, attacks=(), strength=0, weak=0,
            vulnerable=1, poison=0, debilitate=1,
        )
        self.assertEqual(
            combat._attack_value(
                combat.Card(index=0, name="打击", cost=1, target=2, damage=6,
                            block=0, poison=0, hits=1, weak=0, vulnerable=0,
                            frail=0, strength=0, dexterity=0),
                base_player,
                debilitated_enemy,
            ),
            12,
        )
        weak_player = combat.Player(hp=70, block=0, energy=3, strength=0, dexterity=0,
                                    weak=1, vulnerable=0, frail=0, shrink=False,
                                    debilitate=1)
        self.assertEqual(attack(weak_player), 4)

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

    def test_shrink_reduces_card_damage(self):
        payload = state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("虫", 15, damage=7)],
            energy=1,
        )
        payload["PlayerPowers"] = {"ShrinkPower": -1}
        result = self.solve(payload)
        self.assertEqual(result.damage_dealt, 4)  # floor(6 * 0.7)
        self.assertFalse(result.outcome.lethal)

    def test_shrink_can_turn_predicted_lethal_into_survival(self):
        payload = state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 15, damage=7, powers={"PoisonPower": 2})],
            energy=3,
        )
        payload["PlayerPowers"] = {"ShrinkPower": -1}
        result = self.solve(payload)
        self.assertFalse(result.outcome.lethal)
        self.assertEqual(result.outcome.enemy_hp_left, 1)
        self.assertEqual(result.outcome.poison_kills, 0)

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

    def test_combat_takes_priority_over_stale_map_choices(self):
        payload = state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("虫", 10, damage=8)],
            energy=1,
        )
        payload["MapChoices"] = [{"Col": 4, "Row": 3, "Type": 5, "TypeName": "战斗"}]
        result = engine.advise(payload)
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("combat.solver", ids)
        self.assertNotIn("map.recommend", ids)

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
        self.assertIn("solver", result)
        self.assertTrue(result["solver"]["lethal"])
        self.assertEqual(result["solver"]["hpLoss"], 0)
        self.assertEqual(result["solver"]["modeled"], 2)

    def test_solver_sequence_marks_upgraded_cards(self):
        result = engine.advise(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=9, upgraded=1)],
            [enemy("虫", 20)],
            energy=1,
        ))
        solver = next(item for item in result["advice"] if item["ruleId"] == "combat.solver")
        self.assertIn("打击+→虫", solver["text"])
        self.assertIn("打击+→虫", result["solver"]["sequence"][0])

    def test_thorns_damages_attacker_per_hit(self):
        result = self.solve(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("蟾蜍蝌蚪", 12, powers={"ThornsPower": 2})],
            energy=2,
        ))
        self.assertTrue(result.outcome.lethal)
        self.assertEqual(result.outcome.hp_loss, 4)

    def test_strike_dummy_adds_three_to_strikes(self):
        result = self.solve(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("虫", 9)],
            energy=1,
            relic_ids=["STRIKE_DUMMY"],
        ))
        self.assertTrue(result.outcome.lethal)
        self.assertEqual(result.outcome.enemy_hp_left, 0)

    def test_backflip_block_is_modeled_even_with_draw(self):
        backflip = card("Backflip", "后空翻", 1, 2, 1, block=5,
                        vars={"Block": 5, "Cards": 2})
        result = self.solve(state(
            [backflip],
            [enemy("虫", 30, damage=10)],
            energy=1,
        ))
        self.assertEqual(result.block_left, 5)
        self.assertEqual(result.outcome.hp_loss, 5)
        self.assertEqual(result.partial[0][0], "后空翻")

    def test_blur_block_is_modeled_and_retain_is_partial(self):
        # Blur: 5 block now, BlurPower only keeps the block next turn, so this
        # turn's prediction is exact and the retain is reported as partial.
        result = self.solve(state(
            [
                card("Blur", "残影", 1, 2, 1, block=5, vars={"Block": 5, "Blur": 1}),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 40, damage=10)],
            energy=2,
        ))
        self.assertEqual(result.block_left, 5)
        self.assertEqual(result.outcome.hp_loss, 5)
        self.assertNotIn("残影", [name for name, _ in result.unmodeled])
        self.assertIn("残影", [name for name, _ in result.partial])

    def test_flechettes_hits_scale_with_skill_cards_in_hand(self):
        # Flechettes deals 5 damage per Skill card in hand, including skills the
        # solver cannot play (Acrobatics draws, so it stays unmodeled).
        flechettes = card(
            "Flechettes", "飞镖", 1, 1, 2, damage=5,
            vars={"Damage": 5, "CalculationBase": 0, "CalculationExtra": 1,
                  "CalculatedHits": 0},
        )
        acrobatics = card("Acrobatics", "杂技", 1, 2, 1, vars={"Cards": 3})
        result = self.solve(state(
            [
                flechettes,
                card("DefendSilent", "防御", 1, 2, 1, block=5),
                card("DefendSilent", "防御", 1, 2, 1, block=5),
                acrobatics,
            ],
            [enemy("虫", 40)],
            energy=3,
        ))
        # Three skill cards are in hand: two Defends + Acrobatics.
        self.assertEqual(result.damage_dealt, 15)
        self.assertNotIn("飞镖", [name for name, _ in result.unmodeled])
        self.assertIn("杂技", [name for name, _ in result.unmodeled])

    def test_precise_cut_damage_drops_with_hand_size(self):
        precise_cut = card(
            "PreciseCut", "精确切击", 0, 1, 2, damage=13,
            vars={"CalculationBase": 13, "ExtraDamage": 2, "CalculatedDamage": 13},
        )
        result = self.solve(state(
            [
                precise_cut,
                card("DefendSilent", "防御", 1, 2, 1, block=5),
                card("DefendSilent", "防御", 1, 2, 1, block=5),
            ],
            [enemy("虫", 40)],
            energy=0,
        ))
        # 13 - 2 * (3 cards - 1) = 9.
        self.assertEqual(result.damage_dealt, 9)
        self.assertNotIn("精确切击", [name for name, _ in result.unmodeled])

    def test_random_target_is_modeled_when_only_one_enemy_is_alive(self):
        ricochet = card("Ricochet", "连续反弹", 2, 1, 4, damage=3, hits=4,
                        vars={"Damage": 3, "Repeat": 4})
        result = self.solve(state(
            [ricochet],
            [enemy("虫", 12, damage=8)],
            energy=2,
        ))
        self.assertTrue(result.outcome.lethal)
        self.assertEqual(result.damage_dealt, 12)
        self.assertEqual(result.unmodeled, ())

    def test_random_target_stays_unmodeled_with_two_enemies(self):
        ricochet = card("Ricochet", "连续反弹", 2, 1, 4, damage=3, hits=4,
                        vars={"Damage": 3, "Repeat": 4})
        result = self.solve(state(
            [ricochet],
            [enemy("虫", 12, damage=8), enemy("虫", 12, damage=8)],
            energy=2,
        ))
        self.assertNotIn("连续反弹", [p.name for p in result.plays])
        self.assertIn("连续反弹", [name for name, _ in result.unmodeled])

    def test_orichalcum_grants_six_block_when_turn_ends_without_block(self):
        result = self.solve(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("虫", 40, damage=10)],
            energy=1,
            relic_ids=["Orichalcum"],
        ))
        # 6 unpowered block from Orichalcum; 10 - 6 = 4 damage.
        self.assertEqual(result.outcome.hp_loss, 4)

    def test_orichalcum_does_not_trigger_with_block_left(self):
        # A 5 block Defend ends the turn with block, so Orichalcum stays idle
        # and the solver prefers to skip it: 10 - 6 = 4 beats 10 - 5 = 5.
        result = self.solve(state(
            [card("DefendSilent", "防御", 1, 2, 1, block=5)],
            [enemy("虫", 40, damage=10)],
            energy=1,
            relic_ids=["Orichalcum"],
        ))
        self.assertEqual(result.outcome.hp_loss, 4)
        self.assertEqual(result.block_left, 0)

    def test_dagger_throw_discards_a_burden(self):
        # DaggerThrow deals damage, draws 1, then discards 1. The draw is
        # unknowable, but the discard can dump an end-of-turn burden.
        dagger = card("DaggerThrow", "投掷匕首", 1, 1, 2, damage=12)
        beckon = {
            "Id": "Beckon", "Name": "呼唤", "Cost": 1, "CostsX": False, "Type": 2,
            "Target": 1, "Playable": False, "Damage": 0, "Block": 0, "Poison": 0,
            "Hits": 1, "Vars": {"HpLoss": 6},
        }
        result = self.solve(state(
            [dagger, beckon, card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("虫", 60, damage=10)],
            energy=3,
        ))
        self.assertEqual([p.name for p in result.plays][0], "投掷匕首")
        self.assertEqual(result.plays[0].discard_index, 1)
        # Discarding the burden removes its end-of-turn damage.
        self.assertEqual(result.outcome.end_turn_damage, 0)

    def test_dagger_throw_is_playable_without_another_card_to_discard(self):
        result = self.solve(state(
            [card("DaggerThrow", "投掷匕首", 1, 1, 2, damage=12)],
            [enemy("虫", 40)],
            energy=1,
        ))
        self.assertEqual([p.name for p in result.plays], ["投掷匕首"])
        self.assertEqual(result.damage_dealt, 12)
        self.assertEqual(result.unmodeled, ())
        self.assertIn("投掷匕首", [name for name, _ in result.partial])

    def test_dagger_throw_shows_discard_advice_without_a_burden(self):
        result = engine.advise(state(
            [card("DaggerThrow", "投掷匕首", 1, 1, 2, damage=12)],
            [enemy("虫", 40)],
            energy=1,
        ))
        text = next(item for item in result["advice"] if item["ruleId"] == "combat.solver")["text"]
        self.assertIn("投掷匕首→虫（弃抽到的牌）", text)

    def test_memento_mori_scales_with_discards_this_turn(self):
        # MementoMori: 11 + 5 per card discarded this turn (0.107.1 source).
        memento = card(
            "MementoMori", "铭记死亡", 1, 1, 2, damage=16,
            vars={"CalculationBase": 11, "ExtraDamage": 5, "CalculatedDamage": 11},
        )
        survivor = card("Survivor", "生存者", 1, 2, 1, block=8)
        result = self.solve(state(
            [survivor, memento, card("DefendSilent", "防御", 1, 2, 1, block=5)],
            [enemy("虫", 40)],
            energy=2,
        ))
        self.assertEqual([p.name for p in result.plays][0], "生存者")
        # Survivor discards one card, then MementoMori deals 11 + 5.
        self.assertEqual(result.damage_dealt, 16)

    def test_memento_mori_without_discard_uses_base(self):
        memento = card(
            "MementoMori", "铭记死亡", 1, 1, 2, damage=16,
            vars={"CalculationBase": 11, "ExtraDamage": 5, "CalculatedDamage": 11},
        )
        result = self.solve(state([memento], [enemy("虫", 40)], energy=1))
        self.assertEqual(result.damage_dealt, 11)

    def test_shriek_power_stuns_when_hp_drops_to_threshold(self):
        # ShriekPower 70: unblocked damage that leaves 100 HP at <= 70 stuns the
        # enemy (TerrorEel), so it skips this turn's attack.
        result = self.solve(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=30)],
            [enemy("骇鳗", 100, damage=10, powers={"ShriekPower": 70})],
            energy=1,
        ))
        self.assertEqual(result.outcome.hp_loss, 0)
        self.assertEqual(result.outcome.enemy_hp_left, 70)

    def test_shriek_power_does_not_stun_above_threshold(self):
        result = self.solve(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=10)],
            [enemy("骇鳗", 100, damage=10, powers={"ShriekPower": 70})],
            energy=1,
        ))
        self.assertEqual(result.outcome.hp_loss, 10)

    def test_vigor_adds_damage_before_weak(self):
        # VigorPower 6 is additive on the next powered attack, before Weak.
        result = self.solve(state(
            [card("DefendSilent", "防御", 1, 2, 1, block=5)],
            [enemy("骇鳗", 100, damage=16, powers={"VigorPower": 6, "WeakPower": 1})],
            energy=1,
        ))
        # floor((16 + 6) * 0.75) = 16, minus 5 block = 11.
        self.assertEqual(result.outcome.incoming, 16)
        self.assertEqual(result.outcome.hp_loss, 11)

    def test_steam_eruption_kill_is_not_lethal(self):
        # WaterfallGiant: SteamEruptionPower turns a lethal hit into a delayed
        # explosion, so the solver must not claim the combat is over.
        result = self.solve(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=12)],
            [enemy("瀑布巨兽", 10, damage=20, powers={"SteamEruptionPower": 20})],
            energy=1,
        ))
        self.assertFalse(result.outcome.lethal)
        self.assertEqual(result.outcome.enemy_hp_left, 0)
        self.assertEqual(result.outcome.hp_loss, 0)

    def test_engine_warns_about_steam_eruption(self):
        result = engine.advise(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("瀑布巨兽", 100, damage=10, powers={"SteamEruptionPower": 42})],
            energy=1,
        ))
        warning = next(item for item in result["advice"] if item["ruleId"] == "combat.eruption")
        self.assertIn("42", warning["text"])
        self.assertIn("蒸汽喷发", warning["text"])

    def test_engine_marks_steam_eruption_fatal_when_hp_is_low(self):
        result = engine.advise(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("瀑布巨兽", 100, damage=10, powers={"SteamEruptionPower": 42})],
            energy=1,
            hp=13,
        ))
        warning = next(item for item in result["advice"] if item["ruleId"] == "combat.eruption")
        self.assertEqual(warning["severity"], "danger")
        self.assertIn("击杀会致死", warning["text"])

    def test_solver_sequence_is_one_action_per_line(self):
        result = engine.advise(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 40, damage=8)],
            energy=2,
        ))
        text = next(item for item in result["advice"] if item["ruleId"] == "combat.solver")["text"]
        self.assertIn("\n  1. 打击→虫", text)
        self.assertIn("\n  2. 打击→虫", text)
        self.assertNotIn(" → ", text)

    def test_malformed_var_value_does_not_crash_solver(self):
        weird = card("Mystery", "神秘", 1, 1, 2, damage=5,
                     vars={"Damage": 5, "Cards": "???"})
        result = self.solve(state([weird], [enemy("虫", 30)], energy=1))
        self.assertEqual(result.damage_dealt, 5)
        self.assertEqual(result.outcome.hp_loss, 0)

    def test_solver_detail_reports_orichalcum_block(self):
        result = engine.advise(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("虫", 40, damage=10)],
            energy=1,
            relic_ids=["Orichalcum"],
        ))
        detail = next(item for item in result["advice"] if item["ruleId"] == "combat.solver_detail")
        self.assertIn("含遗物 6 格挡", detail["text"])

    def test_bouncing_flask_applies_poison_once_per_repeat(self):
        flask = card("BouncingFlask", "弹跳药瓶", 2, 2, 4, poison=3, hits=3,
                     vars={"PoisonPower": 3, "Repeat": 3})
        result = self.solve(state(
            [flask],
            [enemy("虫", 50)],
            energy=2,
        ))
        # 3 applications of 3 poison = 9 poison, which ticks once: 50 - 9 = 41.
        self.assertEqual(result.outcome.enemy_hp_left, 41)
        self.assertEqual(result.unmodeled, ())

    def test_ravenous_ally_death_stuns_survivor(self):
        result = self.solve(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [
                enemy("噬尸蛞蝓", 5, powers={"RavenousPower": 4}),
                enemy("噬尸蛞蝓", 30, damage=8, powers={"RavenousPower": 4}),
            ],
            energy=1,
        ))
        self.assertEqual(result.outcome.incoming, 0)
        self.assertEqual(result.outcome.hp_loss, 0)

    def test_strangle_triggers_after_followup_card(self):
        strangle = card("Strangle", "紧勒", 1, 1, 2, damage=8,
                        vars={"Damage": 8, "StranglePower": 2})
        result = self.solve(state(
            [strangle, card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("虫", 30)],
            energy=2,
        ))
        # 8 direct + 6 Strike + 2 Strangle trigger.
        self.assertEqual(result.damage_dealt, 16)
        self.assertEqual(result.outcome.enemy_hp_left, 14)

    def test_shrink_potion_recommended_at_low_hp(self):
        result = engine.advise(state(
            [card("DefendSilent", "防御", 1, 2, 1, block=5)],
            [enemy("虫", 20, damage=10)],
            energy=0,
            hp=10,
            potions=["甲虫汁"],
            potion_ids=["BeetleJuice"],
        ))
        ids = [item["ruleId"] for item in result["advice"]]
        self.assertIn("potion.use", ids)
        potion = next(item for item in result["advice"] if item["ruleId"] == "potion.use")
        self.assertIn("甲虫汁", potion["text"])

    def test_lethal_with_block_potion_is_called_out(self):
        payload = state(
            [card("DefendSilent", "防御", 1, 2, 1, block=5)],
            [enemy("虫", 40, damage=20)],
            energy=1,
            hp=10,
            potions=["格挡药水"],
            potion_ids=["BLOCK_POTION"],
        )
        advice = engine.advise(payload)["advice"]
        self.assertIn("potion.lethal", [item["ruleId"] for item in advice])

    def test_intangible_caps_each_damage_hit(self):
        result = self.solve(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("灵魂异鱼", 20, powers={"IntangiblePower": 1})],
            energy=1,
        ))
        self.assertEqual(result.damage_dealt, 1)
        self.assertEqual(result.outcome.enemy_hp_left, 19)

    def test_player_intangible_caps_each_incoming_hit(self):
        payload = state(
            [card("DefendSilent", "防御", 1, 2, 1, block=5)],
            [enemy("虫", 20, damage=10, hits=2)],
            energy=0,
            hp=10,
        )
        payload["PlayerPowers"] = {"IntangiblePower": 1}
        result = self.solve(payload)
        # Two 10-damage hits are each capped at 1, not 10.
        self.assertEqual(result.outcome.incoming, 2)
        self.assertEqual(result.outcome.hp_after, 8)

    def test_beckon_deals_unblockable_damage_at_turn_end(self):
        beckon = {
            "Id": "Beckon", "Name": "呼唤", "Cost": 1, "CostsX": False,
            "Type": 4, "Target": 0, "Rarity": 5, "Upgraded": 0,
            "Playable": False, "Damage": 0, "Block": 0, "Poison": 0, "Hits": 1,
            "Vars": {"HpLoss": 6},
        }
        result = self.solve(state([beckon], [enemy("虫", 20)], energy=0))
        self.assertEqual(result.outcome.hp_loss, 6)
        self.assertEqual(result.outcome.hp_after, 64)

    def test_survivor_can_discard_beckon(self):
        beckon = {
            "Id": "Beckon", "Name": "呼唤", "Cost": 1, "CostsX": False,
            "Type": 4, "Target": 0, "Rarity": 5, "Upgraded": 0,
            "Playable": False, "Damage": 0, "Block": 0, "Poison": 0, "Hits": 1,
            "Vars": {"HpLoss": 6},
        }
        survivor = card("Survivor", "生存者", 1, 2, 1, block=8)
        result = self.solve(state([survivor, beckon], [enemy("虫", 20)], energy=1))
        self.assertEqual(result.outcome.hp_loss, 0)
        self.assertIsNotNone(result.plays[0].discard_index)

    def test_thorns_mutual_death_is_a_warning(self):
        # Killing the last enemy with Thorns up can still kill the player.
        result = engine.advise(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6)],
            [enemy("虫", 1, powers={"ThornsPower": 6})],
            energy=1,
            hp=6,
            potions=["格挡药水"],
            potion_ids=["BLOCK_POTION"],
        ))
        solver = next(item for item in result["advice"] if item["ruleId"] == "combat.solver")
        self.assertEqual(solver["severity"], "danger")
        self.assertIn("同归于尽", solver["text"])
        self.assertNotIn("可斩杀", solver["text"])
        potion = next(item for item in result["advice"] if item["ruleId"] == "potion.lethal")
        self.assertIn("格挡药水", potion["text"])

    def test_end_turn_burden_is_skipped_when_combat_ends(self):
        # 0.107.1 log: killing the last enemy ends combat before the turn-end
        # hand damage, so Beckon must not be counted.
        beckon = {
            "Id": "Beckon", "Name": "呼唤", "Cost": 1, "CostsX": False,
            "Type": 4, "Target": 0, "Rarity": 5, "Upgraded": 0,
            "Playable": False, "Damage": 0, "Block": 0, "Poison": 0, "Hits": 1,
            "Vars": {"HpLoss": 6},
        }
        result = self.solve(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=6), beckon],
            [enemy("虫", 1)],
            energy=1,
            hp=6,
        ))
        self.assertTrue(result.outcome.lethal)
        self.assertEqual(result.outcome.hp_loss, 0)
        self.assertEqual(result.outcome.hp_after, 6)

    def test_infection_at_turn_end_is_blockable(self):
        infection = {
            "Id": "Infection", "Name": "感染", "Cost": -1, "CostsX": False,
            "Type": 4, "Target": 0, "Rarity": 5, "Upgraded": 0,
            "Playable": False, "Damage": 3, "Block": 0, "Poison": 0, "Hits": 1,
            "Vars": {"Damage": 3},
        }
        result = self.solve(state(
            [card("DefendSilent", "防御", 1, 2, 1, block=5), infection],
            [enemy("虫", 30)],
            energy=1,
        ))
        self.assertEqual(result.outcome.end_turn_damage, 3)
        self.assertEqual(result.outcome.end_turn_unblockable, 0)
        self.assertEqual(result.outcome.hp_loss, 0)

    def test_beckon_at_turn_end_ignores_block(self):
        beckon = {
            "Id": "Beckon", "Name": "呼唤", "Cost": 1, "CostsX": False,
            "Type": 4, "Target": 0, "Rarity": 5, "Upgraded": 0,
            "Playable": False, "Damage": 0, "Block": 0, "Poison": 0, "Hits": 1,
            "Vars": {"HpLoss": 6},
        }
        result = self.solve(state(
            [card("DefendSilent", "防御", 1, 2, 1, block=5), beckon],
            [enemy("虫", 30)],
            energy=0,
        ))
        self.assertEqual(result.outcome.end_turn_unblockable, 6)
        self.assertEqual(result.outcome.hp_loss, 6)

    def test_adrenaline_gains_energy_and_reports_draw_partial(self):
        adrenaline = card("Adrenaline", "肾上腺素", 0, 2, 1, vars={"Energy": 1, "Cards": 2})
        result = self.solve(state(
            [
                adrenaline,
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("虫", 20)],
            energy=1,
        ))
        # The 0-cost +1 energy gain lets both Strikes be played (12 damage).
        self.assertEqual(result.damage_dealt, 12)
        self.assertIn("肾上腺素", [name for name, _ in result.partial])

    def test_slippery_power_caps_the_first_hit(self):
        # Inklets: SlipperyPower 1 clamps the first unblocked hit to 1 HP and
        # is consumed, so the second strike deals full damage.
        result = self.solve(state(
            [
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
                card("StrikeSilent", "打击", 1, 1, 2, damage=6),
            ],
            [enemy("墨宝", 20, powers={"SlipperyPower": 1})],
            energy=2,
        ))
        self.assertEqual(result.damage_dealt, 7)
        self.assertEqual(result.outcome.enemy_hp_left, 13)


    def test_damage_potion_can_finish_before_unblockable_end_damage(self):
        beckon = {
            "Id": "Beckon", "Name": "呼唤", "Cost": 1, "CostsX": False,
            "Type": 4, "Target": 0, "Rarity": 5, "Upgraded": 0,
            "Playable": False, "Damage": 0, "Block": 0, "Poison": 0, "Hits": 1,
            "Vars": {"HpLoss": 6},
        }
        result = engine.advise(state(
            [card("StrikeSilent", "打击", 1, 1, 2, damage=9), beckon],
            [enemy("Boss", 12)],
            energy=1,
            hp=6,
            potions=["爆炸药剂"],
            potion_ids=["ExplosiveAmpoule"],
        ))
        potion = next(item for item in result["advice"] if item["ruleId"] == "potion.lethal")
        self.assertIn("爆炸药剂", potion["text"])
        self.assertIn("先杀", potion["text"])

    def test_grand_finale_requires_empty_draw_pile(self):
        payload = state(
            [card("GrandFinale", "华丽收场", 0, 1, 3, damage=60)],
            [enemy("虫", 20, damage=8)],
            draw_count=17,
        )
        result = self.solve(payload)
        self.assertNotIn("华丽收场", [p.name for p in result.plays])
        self.assertTrue(any(name == "华丽收场" for name, _ in result.unmodeled))

        payload["DrawCount"] = 0
        result = self.solve(payload)
        self.assertTrue(result.outcome.lethal)
        self.assertIn("华丽收场", [p.name for p in result.plays])

    def test_duplicate_enemy_labels_are_numbered(self):
        self.assertEqual(
            engine._enemy_labels(["同族信徒", "同族信徒", "同族神官"]),
            ["同族信徒#1", "同族信徒#2", "同族神官"],
        )


if __name__ == "__main__":
    unittest.main()

"""One-turn combat solver.

The solver enumerates legal card orders for the current hand and scores the
result after the enemies act.  It only models effects it can verify from the
state payload; cards with unknown dynamic variables are reported separately
instead of being guessed.

State contract (PascalCase):
  Hand[].Cost / Damage / Block / Poison / Hits / Target / Vars
  PlayerPowers, Enemies[].Powers / Attacks / Damage / Hits
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Iterable

import catalog as model_catalog

MAX_HAND = 10
MAX_NODES = 15000
MAX_SECONDS = 0.22

# TargetType in the game: 0 None, 1 Self, 2 AnyEnemy, 3 AllEnemies, 4 RandomEnemy.
TARGET_ANY = 2
TARGET_ALL = 3
TARGET_RANDOM = 4

# DynamicVar keys we know how to turn into immediate effects.
KNOWN_VARS = {
    "Damage",
    "CalculatedDamage",
    "ExtraDamage",
    "Block",
    "CalculatedBlock",
    "Repeat",
    "Poison",
    "PoisonPower",
    "Weak",
    "WeakPower",
    "Vulnerable",
    "VulnerablePower",
    "Frail",
    "FrailPower",
    "Strength",
    "StrengthPower",
    "Dexterity",
    "DexterityPower",
    "Strangle",
    "StranglePower",
}

# Vars whose effect does not change this turn's HP outcome.  A card that also
# has a deterministic immediate effect is still modeled for that part; the
# ignored effect is reported through `partial` instead of dropping the card.
DEFERRED_VARS = {
    # Draw is unknowable without the draw pile order; the played cards stay
    # deterministic (Backflip/Finesse block, Acrobatics discard, ...).
    "Cards": "抽牌未计",
    # BlurPower only keeps block for the next turn, so this turn's block is exact.
    "Blur": "下回合保留格挡未计",
}

# Calculation vars.  Their value is computed from the live hand, so they must
# not be treated as a flat effect; only the two cards verified against the
# 0.107.1 source are interpreted (see _calculation_model).
CALC_VARS = {
    "CalculationBase",
    "CalculationExtra",
    "CalculatedDamage",
    "CalculatedHits",
    "ExtraDamage",
}

# Cards whose hardcoded (non-Var) effect is only partly modeled: the draw is not
# knowable from the state, so it stays out of the DFS and is reported as partial.
PARTIAL_NOTES = {
    "DaggerThrow": "只建模伤害/弃牌；抽 1 未计",
    "Adrenaline": "只建模回能；抽 2 未计",
}


@dataclass(frozen=True)
class Play:
    name: str
    cost: int
    target_index: int | None
    discard_index: int | None = None
    target_all: bool = False
    upgrade_level: int = 0
    # The card draws before discarding and the solver discards that drawn card
    # (the only known-safe default when the drawn card is unknown).
    discard_drawn: bool = False


@dataclass(frozen=True)
class Card:
    index: int
    name: str
    cost: int
    target: int
    damage: int
    block: int
    poison: int
    hits: int
    weak: int
    vulnerable: int
    frail: int
    strength: int
    dexterity: int
    discard: int = 0
    is_strike: bool = False
    strangle: int = 0
    end_turn_damage: int = 0
    costs_x: bool = False
    block_from_damage: bool = False
    is_attack: bool = False
    upgrade_level: int = 0
    is_skill: bool = False
    # Flechettes: hit count is the number of skill cards in hand at play time.
    hits_from_hand_skills: bool = False
    # Skill cards in hand that the solver cannot play (unmodeled), counted as
    # a constant because they never leave the simulated hand.
    hand_skill_offset: int = 0
    # PreciseCut: damage = base - extra * (hand size at play time - 1).
    hand_scaled_damage: tuple[int, int] | None = None
    # MementoMori: damage = base + extra * (cards discarded this turn).
    damage_per_discard: tuple[int, int] | None = None
    # Cards in hand that the solver does not track (unmodeled/over the cap).
    hand_card_offset: int = 0
    # DaggerThrow draws 1 before discarding, so the discard may be the drawn
    # card; the solver then also offers "discard nothing known".
    discard_may_be_drawn: bool = False
    # End-of-turn self damage: Beckon/BadLuck/Regret use ValueProp.Unblockable,
    # Burn/Decay/Infection/Toxic/Wither are normal blockable damage.
    end_turn_unblockable: bool = False
    # Adrenaline: gain energy immediately (the draw is unknown and reported
    # through PARTIAL_NOTES).
    energy_gain: int = 0


@dataclass(frozen=True)
class Attack:
    base: int
    hits: int


@dataclass(frozen=True)
class Enemy:
    name: str
    hp: int
    block: int
    attacks: tuple[Attack, ...]
    strength: int
    weak: int
    vulnerable: int
    poison: int
    thorns: int = 0
    strangle: int = 0
    ravenous: int = 0
    stunned: bool = False
    intangible: bool = False
    death_spawn: bool = False
    artifact: int = 0
    debilitate: int = 0
    # ShriekPower: unblocked damage that leaves the enemy at or below this HP
    # stuns it, so it skips the current attack.
    shriek: int = 0
    # VigorPower: additive damage on the enemy's next powered attack.
    vigor: int = 0
    # SteamEruptionPower: killing the owner does not end the fight; it turns
    # into an explosion next turn, so a kill is not lethal.
    eruption: int = 0
    # SlipperyPower: each unblocked hit loses at most 1 HP and consumes a stack.
    slippery: int = 0


@dataclass(frozen=True)
class Player:
    hp: int
    block: int
    energy: int
    strength: int
    dexterity: int
    weak: int
    vulnerable: int
    frail: int
    shrink: bool
    strike_bonus: int = 0
    paper_phrog: bool = False
    cruelty: int = 0
    debilitate: int = 0
    intangible: bool = False
    pen_nib: int = -1
    gremlin_horn: bool = False
    orichalcum: bool = False


@dataclass(frozen=True)
class SimState:
    player: Player
    enemies: tuple[Enemy, ...]
    hand: tuple[Card, ...]
    start_hp: int = 0
    # Cards discarded by the player this turn (MementoMori scales on it).
    discards: int = 0


@dataclass(frozen=True)
class Outcome:
    lethal: bool
    hp_loss: int
    hp_after: int
    enemy_hp_left: int
    incoming: int
    poison_kills: int
    end_turn_damage: int = 0
    # Part of end_turn_damage that ignores block (Beckon/BadLuck/Regret).
    end_turn_unblockable: int = 0
    # Block available when the enemies act (player block + relic block such as
    # Orichalcum). `SolverResult.block_left` stays the player's own block
    # because potion advice adds to it.
    block_used: int = 0


@dataclass(frozen=True)
class SolverResult:
    plays: tuple[Play, ...]
    outcome: Outcome
    initial_enemy_hp: int
    block_left: int
    modeled: tuple[Card, ...]
    unmodeled: tuple[tuple[str, str], ...]
    truncated: bool
    enemy_names: tuple[str, ...]
    partial: tuple[tuple[str, str], ...] = ()

    @property
    def damage_dealt(self) -> int:
        return max(0, self.initial_enemy_hp - self.outcome.enemy_hp_left)


def _num(mapping: dict, *keys: str) -> int:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def _power(powers: dict, *names: str) -> int:
    for name in names:
        if name in powers:
            try:
                return int(powers[name])
            except (TypeError, ValueError):
                continue
    for key, value in powers.items():
        if any(key.endswith(name) for name in names):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def _is_nonzero(value) -> bool:
    """True for a numeric var; malformed values must not crash the service."""
    try:
        return abs(float(value or 0)) > 1e-9
    except (TypeError, ValueError):
        return False


def _immediate_stat_power(card_id: str) -> bool:
    """Power cards are only playable in this-turn model if they immediately
    change Strength/Dexterity, which changes later attacks/blocks this turn.
    Verified against 0.107.1: Inflame -> StrengthPower, Footwork -> DexterityPower.
    """
    entity = model_catalog.card(card_id)
    if not entity or entity.get("type") != "Power":
        return False
    effects = entity.get("effects") or []
    if len(effects) != 1:
        return False
    effect = effects[0]
    return (
        effect.get("kind") == "power"
        and effect.get("target") == "self"
        and effect.get("power") in ("StrengthPower", "DexterityPower")
    )


@dataclass(frozen=True)
class Calculation:
    """Live-hand / live-history values of a card, resolved at play time."""

    hits_from_hand_skills: bool = False
    hand_scaled_damage: tuple[int, int] | None = None
    damage_per_discard: tuple[int, int] | None = None


def _calculation_model(card_id: str, vars_: dict) -> Calculation | None:
    """Resolve cards whose value is computed from the live hand/history.

    Verified against the 0.107.1 decompiled source:

    * ``Flechettes``: ``CalculatedHits = CalculationBase + CalculationExtra *
      (number of Skill cards in hand)`` with base 0 / extra 1.  Each hit deals
      ``Damage``.
    * ``PreciseCut``: ``CalculatedDamage = CalculationBase + ExtraDamage *
      -(hand size - 1)``, i.e. 2 less damage per card in hand.
    * ``MementoMori``: ``CalculatedDamage = CalculationBase + ExtraDamage *
      (cards discarded this turn)``.

    Returns ``None`` when the card is not one of these calculators or the vars
    do not match the source (a game update must not silently produce a wrong
    flat value).
    """
    base = vars_.get("CalculationBase")
    if card_id == "Flechettes":
        extra = vars_.get("CalculationExtra")
        if base is None or extra is None:
            return None
        try:
            if int(base) == 0 and int(extra) == 1:
                return Calculation(hits_from_hand_skills=True)
        except (TypeError, ValueError):
            return None
        return None
    if card_id == "PreciseCut":
        extra = vars_.get("ExtraDamage")
        if base is None or extra is None:
            return None
        try:
            return Calculation(hand_scaled_damage=(int(base), int(extra)))
        except (TypeError, ValueError):
            return None
    if card_id == "MementoMori":
        extra = vars_.get("ExtraDamage")
        if base is None or extra is None:
            return None
        try:
            return Calculation(damage_per_discard=(int(base), int(extra)))
        except (TypeError, ValueError):
            return None
    return None


def compile_card(raw: dict, index: int) -> tuple[Card | None, str | None]:
    """Return a modeled card, or (None, reason) when the effect is not known."""
    if not isinstance(raw, dict):
        return None, "数据格式错误"

    card_id = str(raw.get("Id") or "")
    name = str(raw.get("Name") or card_id or "?")
    costs_x = bool(raw.get("CostsX"))
    card_type = int(raw.get("Type") or 0)
    if card_type in (4, 5, 6):
        return None, "状态/诅咒/任务牌"
    if card_type not in (1, 2, 3):
        return None, "未知卡牌类型"
    if costs_x and card_type != 1:
        return None, "X 费非攻击牌未建模"

    cost = int(raw.get("Cost", -1))
    if cost < 0:
        return None, "费用未知"

    vars_ = raw.get("Vars") or {}
    if not isinstance(vars_, dict):
        vars_ = {}
    calculation = _calculation_model(card_id, vars_)
    # Adrenaline's energy gain is deterministic; its draw is not.
    energy_gain = _num(vars_, "Energy") if card_id == "Adrenaline" else 0
    known = KNOWN_VARS | (CALC_VARS if calculation is not None else set())
    if energy_gain > 0:
        known = known | {"Energy"}
    unknown = sorted(
        key for key, value in vars_.items() if key not in known and _is_nonzero(value)
    )
    if unknown:
        return None, "未建模变量：" + "/".join(unknown)

    damage = max(0, int(raw.get("Damage") or 0))
    damage = max(damage, _num(vars_, "Damage", "CalculatedDamage", "ExtraDamage"))
    block = max(0, int(raw.get("Block") or 0))
    block = max(block, _num(vars_, "Block", "CalculatedBlock"))
    poison = max(0, int(raw.get("Poison") or 0))
    poison = max(poison, _num(vars_, "Poison", "PoisonPower"))
    hits = max(1, int(raw.get("Hits") or 1))
    hits = max(hits, _num(vars_, "Repeat"))
    weak = max(0, _num(vars_, "Weak", "WeakPower"))
    vulnerable = max(0, _num(vars_, "Vulnerable", "VulnerablePower"))
    frail = max(0, _num(vars_, "Frail", "FrailPower"))
    strength = max(0, _num(vars_, "Strength", "StrengthPower"))
    dexterity = max(0, _num(vars_, "Dexterity", "DexterityPower"))
    strangle = max(0, _num(vars_, "Strangle", "StranglePower"))

    target = int(raw.get("Target") if raw.get("Target") is not None else 0)
    has_enemy_effect = (
        damage > 0 or poison > 0 or weak > 0 or vulnerable > 0 or frail > 0 or strangle > 0
    )
    if has_enemy_effect and target not in (TARGET_ANY, TARGET_ALL, TARGET_RANDOM):
        # Random targets are only usable when exactly one enemy is alive; the
        # caller resolves that from the enemy list instead of guessing.
        return None, "目标类型未建模"

    if card_type == 3:
        if not _immediate_stat_power(card_id):
            return None, "能力牌（本回合收益未建模）"
        if has_enemy_effect or block > 0 or not (strength > 0 or dexterity > 0):
            return None, "能力牌（非即时力量/敏捷未建模）"

    if not has_enemy_effect and block <= 0 and strength <= 0 and dexterity <= 0 and energy_gain <= 0:
        return None, "没有可模拟的即时效果"
    if costs_x:
        if damage <= 0:
            return None, "X 费无伤害未建模"
        if poison or block or weak or vulnerable or frail or strength or dexterity or strangle:
            return None, "X 费复合效果未建模"

    return (
        Card(
            index=index,
            name=name,
            cost=cost,
            target=target,
            damage=damage,
            block=block,
            poison=poison,
            hits=hits,
            weak=weak,
            vulnerable=vulnerable,
            frail=frail,
            strength=strength,
            dexterity=dexterity,
            discard=1 if card_id in ("Survivor", "DaggerThrow") else 0,
            discard_may_be_drawn=card_id == "DaggerThrow",
            is_strike="strike" in card_id.lower() or "Strike" in model_catalog.card_tags(card_id),
            strangle=strangle,
            costs_x=costs_x,
            block_from_damage=card_id == "Fisticuffs",
            is_attack=card_type == 1,
            upgrade_level=max(0, int(raw.get("Upgraded") or 0)),
            is_skill=card_type == 2,
            hits_from_hand_skills=calculation.hits_from_hand_skills if calculation else False,
            hand_scaled_damage=calculation.hand_scaled_damage if calculation else None,
            damage_per_discard=calculation.damage_per_discard if calculation else None,
            energy_gain=energy_gain,
        ),
        None,
    )


def _deferred_card(raw: dict, index: int) -> tuple[Card | None, str | None]:
    """Model the deterministic part of a card whose remaining vars are deferred.

    Draw order and next-turn block retention do not change this turn's HP, so a
    card like Backflip (block + draw) or Blur (block + retain) is still usable
    for its block.  The ignored effect is reported as partial; if the card has
    no deterministic part, it stays unmodeled with the original reason.
    """
    vars_ = raw.get("Vars")
    if not isinstance(vars_, dict):
        return None, None
    ignored: list[str] = []
    for key in vars_:
        if key not in DEFERRED_VARS:
            continue
        if _is_nonzero(vars_[key]):
            ignored.append(key)
    if not ignored:
        return None, None
    slim = dict(raw)
    slim["Vars"] = {key: value for key, value in vars_.items() if key not in ignored}
    card, _ = compile_card(slim, index)
    if card is None:
        return None, None
    notes = "；".join(DEFERRED_VARS[key] for key in sorted(ignored))
    return card, "只建模即时效果；" + notes


def _vulnerable_multiplier(player: Player, enemy: Enemy) -> float:
    """Vulnerable multiplier after the 0.107.1 modifiers we can see.

    PaperPhrog: +0.25 for the player's powered attacks (base 1.5 -> 1.75).
    CrueltyPower: +Amount/100 (e.g. 50 -> +0.5).
    DebilitatePower on the target: amount + (amount - 1), i.e. 2*amount - 1.
    """
    multiplier = 1.5
    if player.paper_phrog:
        multiplier += 0.25
    if player.cruelty > 0:
        multiplier += player.cruelty / 100.0
    if enemy.debilitate > 0:
        multiplier += multiplier - 1.0
    return multiplier


def _attack_value(card: Card, player: Player, enemy: Enemy, damage: int | None = None) -> int:
    """Damage of one hit, before block. The caller repeats it card.hits times."""
    per_hit = (card.damage if damage is None else damage) + player.strength
    if card.is_strike:
        per_hit += player.strike_bonus
    if player.weak > 0:
        per_hit *= 0.5 if player.debilitate > 0 else 0.75
    if player.shrink:
        per_hit *= 0.7  # ShrinkPower: -30% powered attack damage
    if enemy.vulnerable > 0:
        per_hit *= _vulnerable_multiplier(player, enemy)
    return max(0, int(per_hit))


def _block_value(card: Card, player: Player) -> int:
    amount = card.block + player.dexterity
    if player.frail > 0:
        amount *= 0.75
    return max(0, int(amount))


def _enemy_attack_value(enemy: Enemy, player: Player) -> int:
    if enemy.stunned:
        return 0
    total = 0
    for index, attack in enumerate(enemy.attacks):
        # VigorPower is additive damage on the next powered attack (VigorPower.
        # ModifyDamageAdditive), applied before the Weak multiplier and only
        # consumed by the first attack command.
        per_hit = attack.base + enemy.strength + (enemy.vigor if index == 0 else 0)
        if enemy.weak > 0:
            per_hit *= 0.5 if enemy.debilitate > 0 else 0.75
        if player.vulnerable > 0:
            per_hit *= 1.5
        damage = max(0, int(per_hit))
        if player.intangible and damage > 1:
            damage = 1
        total += damage * attack.hits
    return total


def _hit(enemy: Enemy, amount: int) -> tuple[Enemy, int, int]:
    """Apply one hit; returns (new enemy, damage counted for Fisticuffs, hp lost).

    ``TotalDamage + OverkillDamage`` matches the game's Fisticuffs formula:
    blocked + HP loss, plus any excess beyond the target's HP.
    """
    if enemy.intangible and amount > 1:
        amount = 1
    blocked = min(enemy.block, amount)
    unblocked = amount - blocked
    hp_loss = unblocked
    slippery = enemy.slippery
    if slippery > 0 and hp_loss > 0:
        # SlipperyPower.ModifyHpLostAfterOsty clamps the HP loss to 1; the
        # damage result itself is recorded as 1 and the stack is consumed.
        hp_loss = 1
    overkill = max(0, hp_loss - max(0, enemy.hp))
    hp = max(0, enemy.hp - hp_loss)
    return (
        replace(
            enemy,
            block=enemy.block - blocked,
            hp=hp,
            slippery=slippery - 1 if (slippery > 0 and unblocked > 0) else slippery,
        ),
        blocked + hp_loss + overkill,
        hp_loss,
    )


def _damage_player(hp: int, block: int, amount: int) -> tuple[int, int]:
    """Apply blockable damage to the player; returns (hp, block)."""
    blocked = min(block, max(0, amount))
    return max(0, hp - (max(0, amount) - blocked)), max(0, block - blocked)


def _apply_debuff(enemy: Enemy, field: str, amount: int) -> Enemy:
    """Apply one debuff stack; ArtifactPower cancels one visible debuff."""
    if amount <= 0:
        return enemy
    if enemy.artifact > 0:
        return replace(enemy, artifact=enemy.artifact - 1)
    return replace(enemy, **{field: getattr(enemy, field) + amount})


def _apply_stacks(
    enemies: list[Enemy], targets: list[int], field: str, amount: int, times: int
) -> None:
    """Apply a debuff once per hit (Repeat means the effect is applied N times)."""
    if amount <= 0 or times <= 0:
        return
    for index in targets:
        if enemies[index].hp <= 0:
            continue
        for _ in range(times):
            enemies[index] = _apply_debuff(enemies[index], field, amount)


def _maybe_shriek_stun(enemy: Enemy) -> Enemy:
    """ShriekPower 0.107.1: unblocked damage leaving HP <= amount stuns the
    owner (it skips the current attack) and removes the power."""
    if enemy.shriek <= 0 or enemy.hp <= 0 or enemy.hp > enemy.shriek:
        return enemy
    return replace(enemy, stunned=True, shriek=0)


def _outcome(state: SimState) -> Outcome:
    player = state.player
    enemies = list(state.enemies)
    poison_kills = 0

    # Poison ticks at the start of the enemy turn, before the intent executes.
    for i, enemy in enumerate(enemies):
        if enemy.hp <= 0 or enemy.poison <= 0:
            continue
        poison_damage = min(1, enemy.poison) if enemy.intangible else enemy.poison
        hp = enemy.hp - poison_damage
        deaths = 1 if hp <= 0 < enemy.hp else 0
        poison_kills += deaths
        updated = replace(
            enemy,
            hp=max(0, hp),
            poison=max(0, enemy.poison - 1),
            block=0 if hp <= 0 else enemy.block,
        )
        if hp > 0 and poison_damage > 0:
            # Poison damage counts as unblocked damage for ShriekPower, and it
            # ticks before the intent, so the stun cancels this turn's attack.
            updated = _maybe_shriek_stun(updated)
        enemies[i] = updated

    alive = [enemy for enemy in enemies if enemy.hp > 0]
    incoming = sum(_enemy_attack_value(enemy, player) for enemy in alive)
    # When the last enemy dies during the player's cards the combat ends, so
    # end-of-turn hand damage never happens (0.107.1: killing blow ends combat
    # before the turn-end hooks). Poison kills happen later, so they do not.
    combat_ended = not any(enemy.hp > 0 for enemy in enemies) and not any(
        enemy.death_spawn or enemy.eruption > 0 for enemy in enemies
    )
    blockable_end = 0
    unblockable_end = 0
    if not combat_ended:
        for card in state.hand:
            amount = card.end_turn_damage
            if amount <= 0:
                continue
            if player.intangible:
                amount = min(1, amount)
            if card.end_turn_unblockable:
                unblockable_end += amount
            else:
                blockable_end += amount

    block_pool = player.block
    if player.orichalcum and block_pool == 0:
        # Orichalcum: when the turn ends with no block, gain 6 unpowered block
        # (ValueProp.Unpowered: not modified by Dexterity/Frail).
        block_pool += 6
    # Blockable end-of-turn damage (Burn/Decay/Infection/Toxic/Wither) is
    # absorbed by block before the enemies act.
    blocked_end = min(block_pool, blockable_end)
    block_pool -= blocked_end
    end_turn_damage = blockable_end + unblockable_end
    hp_after_end_turn = max(
        0, player.hp - unblockable_end - (blockable_end - blocked_end)
    )
    blocked_now = min(block_pool, incoming)
    hp_after = max(0, hp_after_end_turn - (incoming - blocked_now))
    # Include self-damage already taken this turn (ThornsPower, Beckon, etc.).
    loss = max(0, state.start_hp - hp_after)
    enemy_hp_left = sum(enemy.hp + enemy.block for enemy in alive)
    lethal = not alive and not any(
        enemy.death_spawn or enemy.eruption > 0 for enemy in enemies
    )
    return Outcome(
        lethal=lethal,
        hp_loss=loss,
        hp_after=hp_after,
        enemy_hp_left=enemy_hp_left,
        incoming=incoming,
        poison_kills=poison_kills,
        end_turn_damage=end_turn_damage,
        end_turn_unblockable=unblockable_end,
        block_used=block_pool,
    )


def _score(state: SimState) -> tuple:
    outcome = _outcome(state)
    energy_left = state.player.energy
    if outcome.lethal:
        return (0, 0, outcome.hp_loss, 0, -energy_left)
    dead = 1 if outcome.hp_after <= 0 else 0
    return (1, dead, outcome.hp_loss, outcome.enemy_hp_left, -energy_left)


def _target_indices(card: Card, state: SimState) -> tuple[int | None, ...] | None:
    alive = [i for i, enemy in enumerate(state.enemies) if enemy.hp > 0]
    has_enemy_effect = (
        card.damage > 0
        or card.poison > 0
        or card.weak > 0
        or card.vulnerable > 0
        or card.frail > 0
        or card.strangle > 0
    )
    if not has_enemy_effect:
        return (None,)
    if card.target == TARGET_ALL:
        return (None,)
    if card.target == TARGET_ANY and alive:
        return tuple(alive)
    return None


def _play(
    state: SimState,
    card: Card,
    target_index: int | None,
    discard_index: int | None,
    x_spend: int | None = None,
) -> SimState | None:
    if card.costs_x:
        if x_spend is None or x_spend <= 0 or x_spend > state.player.energy:
            return None
        cost = x_spend
        hits = x_spend
    else:
        cost = card.cost
        hits = card.hits
    if cost > state.player.energy:
        return None

    player = state.player
    enemies = list(state.enemies)
    hand = [c for c in state.hand if c.index != card.index]
    if card.hits_from_hand_skills:
        # Flechettes: one hit per Skill card still in hand. Unmodeled skills
        # never leave the simulated hand, so they are a constant offset.
        hits = card.hand_skill_offset + sum(1 for c in hand if c.is_skill)
    card_damage = card.damage
    if card.hand_scaled_damage is not None:
        # PreciseCut: 2 less damage per card in hand, counting its own card.
        base, extra = card.hand_scaled_damage
        hand_size = card.hand_card_offset + len(state.hand)
        card_damage = max(0, base - extra * (hand_size - 1))
    if card.damage_per_discard is not None:
        # MementoMori: base + extra per card discarded this turn.
        base, extra = card.damage_per_discard
        card_damage = max(0, base + extra * state.discards)
    if card.discard and len(hand) < card.discard and not card.discard_may_be_drawn:
        return None

    energy = player.energy - cost + card.energy_gain
    block = player.block
    hp = player.hp
    strength = player.strength
    dexterity = player.dexterity
    strangle_before = tuple(enemy.strangle for enemy in enemies)
    dead_before = tuple(enemy.hp <= 0 for enemy in enemies)

    targets: list[int] = []
    if target_index is not None:
        targets = [target_index]
    elif card.target == TARGET_ALL:
        targets = [i for i, enemy in enumerate(enemies) if enemy.hp > 0]

    # Damage is applied before debuffs from the same card (Bash/Neutralize text).
    damage_done = 0
    pen_nib = player.pen_nib
    pen_nib_ready = pen_nib == 9
    if card_damage > 0:
        for index in targets:
            for _ in range(hits):
                if enemies[index].hp <= 0:
                    break
                # ThornsPower: before the hit lands, the attacker takes damage
                # per hit. It is blockable and can kill the player.
                if enemies[index].thorns > 0:
                    hp, block = _damage_player(hp, block, enemies[index].thorns)
                amount = _attack_value(card, player, enemies[index], card_damage)
                if pen_nib_ready:
                    amount *= 2
                enemies[index], dealt, unblocked = _hit(enemies[index], amount)
                damage_done += dealt
                if unblocked > 0:
                    enemies[index] = _maybe_shriek_stun(enemies[index])

    if pen_nib >= 0 and card.is_attack:
        pen_nib = (pen_nib + 1) % 10

    if player.gremlin_horn:
        for index, enemy in enumerate(enemies):
            if not dead_before[index] and enemy.hp <= 0:
                energy += 1

    if card.block > 0:
        block += _block_value(card, player)
    if card.block_from_damage:
        # Fisticuffs: GainBlock(TotalDamage + OverkillDamage) after the attack.
        block += damage_done

    if card.poison > 0:
        _apply_stacks(enemies, targets, "poison", card.poison, hits)

    if card.weak > 0:
        _apply_stacks(enemies, targets, "weak", card.weak, hits)

    if card.vulnerable > 0:
        _apply_stacks(enemies, targets, "vulnerable", card.vulnerable, hits)

    if card.frail > 0:
        _apply_stacks(enemies, targets, "frail", card.frail, hits)

    if card.strength > 0:
        strength += card.strength
    if card.dexterity > 0:
        dexterity += card.dexterity
    if card.strangle > 0:
        _apply_stacks(enemies, targets, "strangle", card.strangle, hits)

    # StranglePower triggers after each subsequent card played by the applier.
    # Snapshot the amount before this card so Strangle does not trigger on itself.
    for index, amount in enumerate(strangle_before):
        if amount > 0 and enemies[index].hp > 0:
            enemies[index] = replace(enemies[index], hp=max(0, enemies[index].hp - amount))

    # RavenousPower: when an ally dies, the owner gains Strength and is stunned
    # (it skips its attack this enemy turn).
    for index, enemy in enumerate(enemies):
        if dead_before[index] or enemy.hp > 0:
            continue
        for other_index, other in enumerate(enemies):
            if other_index == index or other.hp <= 0 or other.ravenous <= 0:
                continue
            enemies[other_index] = replace(
                other,
                strength=other.strength + other.ravenous,
                stunned=True,
            )

    discards = state.discards
    if card.discard:
        if discard_index is not None:
            hand = [c for c in hand if c.index != discard_index]
            discards += 1
        elif card.discard_may_be_drawn:
            # The freshly drawn card is discarded; that is still a discard.
            discards += 1

    return replace(
        state,
        player=replace(
            player,
            hp=hp,
            energy=energy,
            block=block,
            strength=strength,
            dexterity=dexterity,
            pen_nib=pen_nib,
        ),
        enemies=tuple(enemies),
        hand=tuple(hand),
        discards=discards,
    )


class Solver:
    def __init__(self, state: SimState):
        self.state = state
        self.nodes = 0
        self.truncated = False
        self.partial: tuple[tuple[str, str], ...] = ()
        self.memo: dict[tuple, tuple[tuple, tuple[Play, ...], SimState]] = {}
        self.deadline = time.perf_counter() + MAX_SECONDS

    def _actions(self, state: SimState) -> Iterable[tuple[SimState, Play]]:
        for card in state.hand:
            if card.cost > state.player.energy:
                continue
            targets = _target_indices(card, state)
            if targets is None:
                continue
            discards: tuple[int | None, ...] = (None,)
            if card.discard:
                discards = tuple(c.index for c in state.hand if c.index != card.index)
                if card.discard_may_be_drawn:
                    # DaggerThrow draws before discarding, so discarding the
                    # drawn card leaves the known hand intact.
                    discards += (None,)
            spends: tuple[int | None, ...] = (
                tuple(range(1, state.player.energy + 1)) if card.costs_x else (None,)
            )
            for target in targets:
                for discard in discards:
                    for spend in spends:
                        child = _play(state, card, target, discard, spend)
                        if child is None:
                            continue
                        yield child, Play(
                            card.name,
                            spend if card.costs_x else card.cost,
                            target,
                            discard,
                            target_all=card.target == TARGET_ALL
                            and card.damage + card.poison + card.weak + card.vulnerable + card.strangle > 0,
                            upgrade_level=card.upgrade_level,
                            discard_drawn=card.discard_may_be_drawn and discard is None,
                        )

    def solve(self) -> tuple[tuple[Play, ...], SimState, bool]:
        _, plays, final = self._dfs(self.state)
        return plays, final, self.truncated

    def _dfs(self, state: SimState) -> tuple[tuple, tuple[Play, ...], SimState]:
        if self.nodes >= MAX_NODES or time.perf_counter() >= self.deadline:
            self.truncated = True
            return _score(state), (), state

        key = (
            state.player.energy,
            state.player.block,
            state.player.hp,
            state.player.strength,
            state.player.dexterity,
            state.player.weak,
            state.player.vulnerable,
            state.player.frail,
            state.player.paper_phrog,
            state.player.cruelty,
            state.player.debilitate,
            state.player.intangible,
            state.player.pen_nib,
            state.player.gremlin_horn,
            state.player.orichalcum,
            tuple(
                (e.hp, e.block, e.strength, e.weak, e.vulnerable, e.poison,
                 e.thorns, e.strangle, e.ravenous, e.stunned, e.intangible,
                 e.death_spawn, e.artifact, e.debilitate, e.shriek, e.vigor, e.eruption,
                 e.slippery)
                for e in state.enemies
            ),
            tuple(sorted(c.index for c in state.hand)),
            state.discards,
        )
        if key in self.memo:
            return self.memo[key]

        self.nodes += 1
        best_score = _score(state)
        best_plays: tuple[Play, ...] = ()
        best_final = state

        for child, play in self._actions(state):
            child_score, child_plays, final = self._dfs(child)
            candidate = (child_score, (play,) + child_plays, final)
            if candidate[0] < best_score or (
                candidate[0] == best_score and len(candidate[1]) < len(best_plays)
            ):
                best_score, best_plays, best_final = candidate

        result = (best_score, best_plays, best_final)
        self.memo[key] = result
        return result


def build_solver(state: dict) -> tuple[Solver | None, tuple[Card, ...], tuple[tuple[str, str], ...], str | None]:
    """Build a solver from a GameState dict. Returns (solver, modeled, unmodeled, error)."""
    if state.get("ValidationError"):
        return None, (), (), "状态校验失败"
    if not state.get("InCombat"):
        return None, (), (), "不在战斗中"
    enemies_raw = state.get("Enemies") or []
    hand_raw = state.get("Hand") or []
    if not enemies_raw:
        return None, (), (), "没有敌人"
    if not hand_raw:
        return None, (), (), "手牌为空"

    powers = state.get("PlayerPowers") or {}
    relic_ids = {str(item).upper() for item in state.get("RelicIds") or []}
    relic_names = {str(item) for item in state.get("Relics") or []}
    relic_counters = state.get("RelicCounters") or {}
    try:
        pen_nib = int(relic_counters.get("PenNib", -1))
    except (TypeError, ValueError):
        pen_nib = -1
    if pen_nib < 0:
        pen_nib = -1
    else:
        pen_nib %= 10
    strike_bonus = 3 if (
        "STRIKE_DUMMY" in relic_ids
        or "打击木偶" in relic_names
        or model_catalog.has_relic(state, "STRIKE_DUMMY", "打击木偶")
    ) else 0
    player = Player(
        hp=int(state.get("Hp") or 0),
        block=int(state.get("Block") or 0),
        energy=int(state.get("Energy") or 0),
        strength=_power(powers, "StrengthPower", "Strength"),
        dexterity=_power(powers, "DexterityPower", "Dexterity"),
        weak=_power(powers, "WeakPower", "Weak"),
        vulnerable=_power(powers, "VulnerablePower", "Vulnerable"),
        frail=_power(powers, "FrailPower", "Frail"),
        shrink=_power(powers, "ShrinkPower", "Shrink") != 0,
        strike_bonus=strike_bonus,
        paper_phrog=model_catalog.has_relic(state, "PaperPhrog", "纸蛙"),
        cruelty=_power(powers, "CrueltyPower", "Cruelty"),
        debilitate=_power(powers, "DebilitatePower", "Debilitate"),
        intangible=_power(powers, "IntangiblePower", "Intangible") > 0,
        pen_nib=pen_nib,
        gremlin_horn=model_catalog.has_relic(state, "GremlinHorn", "地精角"),
        orichalcum="ORICHALCUM" in relic_ids or "Orichalcum" in relic_names,
    )

    if player.hp <= 0:
        return None, (), (), "玩家 HP 无效"

    enemies: list[Enemy] = []
    for raw in enemies_raw:
        if not isinstance(raw, dict):
            continue
        hp = int(raw.get("Hp") or 0)
        if hp <= 0:
            continue
        enemy_powers = raw.get("Powers") or {}
        attacks: list[Attack] = []
        for attack in raw.get("Attacks") or []:
            if not isinstance(attack, dict):
                continue
            base = int(attack.get("BaseDamage") or 0)
            hits = max(1, int(attack.get("Hits") or 1))
            if base > 0:
                attacks.append(Attack(base, hits))
        if not attacks:
            total = int(raw.get("Damage") or 0)
            hits = max(1, int(raw.get("Hits") or 1))
            if total > 0:
                # Legacy payload: only the total is available.
                attacks.append(Attack(max(1, total // hits), hits))
        enemies.append(
            Enemy(
                name=str(raw.get("Name") or raw.get("Id") or "敌人"),
                hp=hp,
                block=max(0, int(raw.get("Block") or 0)),
                attacks=tuple(attacks),
                strength=_power(enemy_powers, "StrengthPower", "Strength"),
                weak=_power(enemy_powers, "WeakPower", "Weak"),
                vulnerable=_power(enemy_powers, "VulnerablePower", "Vulnerable"),
                poison=_power(enemy_powers, "PoisonPower", "Poison"),
                thorns=_power(enemy_powers, "ThornsPower", "Thorns"),
                strangle=_power(enemy_powers, "StranglePower", "Strangle"),
                ravenous=_power(enemy_powers, "RavenousPower", "Ravenous"),
                intangible=_power(enemy_powers, "IntangiblePower", "Intangible") > 0,
                death_spawn=(
                    _power(enemy_powers, "ThieveryPower", "Thievery") > 0
                    or _power(enemy_powers, "SurprisePower", "Surprise") > 0
                ),
                artifact=_power(enemy_powers, "ArtifactPower", "Artifact"),
                debilitate=_power(enemy_powers, "DebilitatePower", "Debilitate"),
                shriek=_power(enemy_powers, "ShriekPower", "Shriek"),
                vigor=_power(enemy_powers, "VigorPower", "Vigor"),
                eruption=_power(enemy_powers, "SteamEruptionPower", "SteamEruption"),
                slippery=_power(enemy_powers, "SlipperyPower", "Slippery"),
            )
        )

    if not enemies:
        return None, (), (), "没有存活敌人"

    modeled: list[Card] = []
    unmodeled: list[tuple[str, str]] = []
    partial: list[tuple[str, str]] = []
    burden_indices: set[int] = set()
    for index, raw in enumerate(hand_raw[:MAX_HAND]):
        entity = model_catalog.card(raw.get("Id"))
        for effect in (entity or {}).get("turn_end_effects") or []:
            if effect.get("kind") != "self_damage":
                continue
            name = str(raw.get("Name") or raw.get("Id") or "?")
            if raw.get("Id") == "Regret":
                amount = len(hand_raw)
            else:
                amount = _num(raw.get("Vars") or {}, effect.get("amount") or "")
                if amount <= 0:
                    amount = int(raw.get(effect.get("amount") or "") or 0)
            if amount > 0:
                burden_indices.add(index)
                # HpLoss-based burdens (Beckon/BadLuck/Regret) are Unblockable;
                # Damage-based ones (Burn/Decay/Infection/Toxic/Wither) are
                # normal blockable damage.
                amount_key = str(effect.get("amount") or "").lower()
                unblockable = amount_key == "hploss" or raw.get("Id") == "Regret"
                modeled.append(Card(
                    index=index,
                    name=name,
                    cost=999,
                    target=0,
                    damage=0,
                    block=0,
                    poison=0,
                    hits=1,
                    weak=0,
                    vulnerable=0,
                    frail=0,
                    strength=0,
                    dexterity=0,
                    end_turn_damage=amount,
                    end_turn_unblockable=unblockable,
                ))
                partial.append((name, "回合结束手牌伤害计入；弃牌可移除"))
    alive_count = sum(1 for enemy in enemies if enemy.hp > 0)
    draw_count = int(state.get("DrawCount") or 0)
    for index, raw in enumerate(hand_raw[:MAX_HAND]):
        if index in burden_indices:
            continue
        name = str(raw.get("Name") or raw.get("Id") or "?")
        if raw.get("Id") == "GrandFinale" and draw_count > 0:
            # Grand Finale: IsPlayable only when the draw pile is empty.
            unmodeled.append((name, "抽牌堆未空"))
            continue
        card, reason = compile_card(raw, index)
        note: str | None = None
        if card is None:
            card, note = _deferred_card(raw, index)
        if card is not None and card.target == TARGET_RANDOM:
            if alive_count != 1:
                # Random targeting cannot be predicted with several enemies.
                unmodeled.append((name, "随机目标（场上多名敌人）"))
                continue
            # Only one enemy can be hit, so the random target is deterministic.
            card = replace(card, target=TARGET_ANY)
        if card is None:
            unmodeled.append((name, reason or "未建模"))
        else:
            modeled.append(card)
            if note:
                partial.append((name, note))
            card_id = str(raw.get("Id") or "")
            if card_id in PARTIAL_NOTES:
                partial.append((name, PARTIAL_NOTES[card_id]))

    # Flechettes/PreciseCut read the live hand. Cards the solver cannot play
    # never leave the simulated hand, so count them once as an offset.
    raw_hand = hand_raw[:MAX_HAND]
    modeled_indices = {card.index for card in modeled}
    untracked = [raw for index, raw in enumerate(raw_hand) if index not in modeled_indices]
    untracked_skills = sum(1 for raw in untracked if int(raw.get("Type") or 0) == 2)
    if any(card.hits_from_hand_skills or card.hand_scaled_damage is not None for card in modeled):
        modeled = [
            replace(
                card,
                hand_skill_offset=untracked_skills,
                hand_card_offset=len(untracked),
            )
            for card in modeled
        ]

    if player.gremlin_horn:
        partial.append(("GremlinHorn", "击杀回能计入；抽 1 未计"))

    simulator = SimState(
        player=player, enemies=tuple(enemies), hand=tuple(modeled),
        start_hp=player.hp,
    )
    solver = Solver(simulator)
    solver.partial = tuple(partial)
    return solver, tuple(modeled), tuple(unmodeled), None


def solve(state: dict) -> tuple[SolverResult | None, str | None]:
    solver, modeled, unmodeled, error = build_solver(state)
    if solver is None:
        return None, error

    plays, final, truncated = solver.solve()
    outcome = _outcome(final)
    initial_enemy_hp = sum(e.hp + e.block for e in solver.state.enemies)
    names = tuple(enemy.name for enemy in solver.state.enemies)
    return (
        SolverResult(
            plays=plays,
            outcome=outcome,
            initial_enemy_hp=initial_enemy_hp,
            block_left=final.player.block,
            modeled=modeled,
            unmodeled=unmodeled,
            truncated=truncated,
            enemy_names=names,
            partial=solver.partial,
        ),
        None,
    )

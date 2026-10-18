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


@dataclass(frozen=True)
class Play:
    name: str
    cost: int
    target_index: int | None
    discard_index: int | None = None
    target_all: bool = False
    upgrade_level: int = 0


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


@dataclass(frozen=True)
class SimState:
    player: Player
    enemies: tuple[Enemy, ...]
    hand: tuple[Card, ...]
    start_hp: int = 0


@dataclass(frozen=True)
class Outcome:
    lethal: bool
    hp_loss: int
    hp_after: int
    enemy_hp_left: int
    incoming: int
    poison_kills: int
    end_turn_damage: int = 0


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
    unknown = sorted(
        key
        for key, value in vars_.items()
        if key not in KNOWN_VARS and abs(float(value or 0)) > 1e-9
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
    if has_enemy_effect:
        if target == TARGET_RANDOM:
            return None, "随机目标"
        if target not in (TARGET_ANY, TARGET_ALL):
            return None, "目标类型未建模"

    if card_type == 3:
        if not _immediate_stat_power(card_id):
            return None, "能力牌（本回合收益未建模）"
        if has_enemy_effect or block > 0 or not (strength > 0 or dexterity > 0):
            return None, "能力牌（非即时力量/敏捷未建模）"

    if not has_enemy_effect and block <= 0 and strength <= 0 and dexterity <= 0:
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
            discard=1 if card_id == "Survivor" else 0,
            is_strike="strike" in card_id.lower() or "Strike" in model_catalog.card_tags(card_id),
            strangle=strangle,
            costs_x=costs_x,
            block_from_damage=card_id == "Fisticuffs",
            is_attack=card_type == 1,
            upgrade_level=max(0, int(raw.get("Upgraded") or 0)),
        ),
        None,
    )


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


def _attack_value(card: Card, player: Player, enemy: Enemy) -> int:
    """Damage of one hit, before block. The caller repeats it card.hits times."""
    per_hit = card.damage + player.strength
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
    for attack in enemy.attacks:
        per_hit = attack.base + enemy.strength
        if enemy.weak > 0:
            per_hit *= 0.5 if enemy.debilitate > 0 else 0.75
        if player.vulnerable > 0:
            per_hit *= 1.5
        damage = max(0, int(per_hit))
        if player.intangible and damage > 1:
            damage = 1
        total += damage * attack.hits
    return total


def _hit(enemy: Enemy, amount: int) -> tuple[Enemy, int]:
    """Apply one hit; returns (new enemy, damage counted for Fisticuffs).

    ``TotalDamage + OverkillDamage`` matches the game's Fisticuffs formula:
    blocked + unblocked damage, plus any excess beyond the target's HP.
    """
    if enemy.intangible and amount > 1:
        amount = 1
    blocked = min(enemy.block, amount)
    unblocked = amount - blocked
    overkill = max(0, unblocked - max(0, enemy.hp))
    return (
        replace(enemy, block=enemy.block - blocked, hp=enemy.hp - unblocked),
        amount + overkill,
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
        enemies[i] = replace(
            enemy,
            hp=max(0, hp),
            poison=max(0, enemy.poison - 1),
            block=0 if hp <= 0 else enemy.block,
        )

    alive = [enemy for enemy in enemies if enemy.hp > 0]
    incoming = sum(_enemy_attack_value(enemy, player) for enemy in alive)
    blocked_now = min(player.block, incoming)
    end_turn_damage = sum(
        min(1, card.end_turn_damage) if player.intangible else card.end_turn_damage
        for card in state.hand
    )
    hp_after_end_turn = max(0, player.hp - max(0, end_turn_damage))
    hp_after = max(0, hp_after_end_turn - (incoming - blocked_now))
    # Include self-damage already taken this turn (ThornsPower, Beckon, etc.).
    loss = max(0, state.start_hp - hp_after)
    enemy_hp_left = sum(enemy.hp + enemy.block for enemy in alive)
    lethal = not alive and not any(enemy.death_spawn for enemy in enemies)
    return Outcome(
        lethal=lethal,
        hp_loss=loss,
        hp_after=hp_after,
        enemy_hp_left=enemy_hp_left,
        incoming=incoming,
        poison_kills=poison_kills,
        end_turn_damage=end_turn_damage,
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
    if card.discard and len([c for c in state.hand if c.index != card.index]) < card.discard:
        return None

    player = state.player
    enemies = list(state.enemies)
    hand = [c for c in state.hand if c.index != card.index]
    energy = player.energy - cost
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
    if card.damage > 0:
        for index in targets:
            for _ in range(hits):
                if enemies[index].hp <= 0:
                    break
                # ThornsPower: before the hit lands, the attacker takes damage
                # per hit. It is blockable and can kill the player.
                if enemies[index].thorns > 0:
                    hp, block = _damage_player(hp, block, enemies[index].thorns)
                amount = _attack_value(card, player, enemies[index])
                if pen_nib_ready:
                    amount *= 2
                enemies[index], dealt = _hit(enemies[index], amount)
                damage_done += dealt

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
        for index in targets:
            if enemies[index].hp > 0:
                enemies[index] = _apply_debuff(enemies[index], "poison", card.poison)

    if card.weak > 0:
        for index in targets:
            if enemies[index].hp > 0:
                enemies[index] = _apply_debuff(enemies[index], "weak", card.weak)

    if card.vulnerable > 0:
        for index in targets:
            if enemies[index].hp > 0:
                enemies[index] = _apply_debuff(enemies[index], "vulnerable", card.vulnerable)

    if card.frail > 0:
        for index in targets:
            if enemies[index].hp > 0:
                enemies[index] = _apply_debuff(enemies[index], "frail", card.frail)

    if card.strength > 0:
        strength += card.strength
    if card.dexterity > 0:
        dexterity += card.dexterity
    if card.strangle > 0:
        for index in targets:
            if enemies[index].hp > 0:
                enemies[index] = _apply_debuff(enemies[index], "strangle", card.strangle)

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

    if card.discard and discard_index is not None:
        hand = [c for c in hand if c.index != discard_index]

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
            tuple(
                (e.hp, e.block, e.strength, e.weak, e.vulnerable, e.poison,
                 e.thorns, e.strangle, e.ravenous, e.stunned, e.intangible,
                 e.death_spawn, e.artifact, e.debilitate)
                for e in state.enemies
            ),
            tuple(sorted(c.index for c in state.hand)),
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
                ))
                partial.append((name, "回合结束手牌伤害计入；弃牌可移除"))
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
        if card is None and str(raw.get("Id") or "") in ("Backflip", "Finesse"):
            # These cards have a deterministic block component and a draw
            # component. Model the block; report the draw as partial instead of
            # discarding the whole card.
            partial_raw = dict(raw)
            vars_ = raw.get("Vars")
            if isinstance(vars_, dict):
                partial_raw["Vars"] = {
                    key: value for key, value in vars_.items() if key in KNOWN_VARS
                }
            card, reason = compile_card(partial_raw, index)
            if card is not None:
                modeled.append(card)
                partial.append((name, "只建模格挡；抽牌未计"))
                continue
        if card is None:
            unmodeled.append((name, reason or "未建模"))
        else:
            modeled.append(card)

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

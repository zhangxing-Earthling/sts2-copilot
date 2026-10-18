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

MAX_HAND = 10
MAX_NODES = 15000
MAX_SECONDS = 0.22

# TargetType in the game: 0 None, 1 Self, 2 AnyEnemy, 3 AllEnemies, 4 RandomEnemy.
TARGET_SELF = 1
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
}


@dataclass(frozen=True)
class Play:
    card_id: str
    name: str
    cost: int
    target_index: int | None
    discard_index: int | None = None
    target_all: bool = False


@dataclass(frozen=True)
class Card:
    index: int
    id: str
    name: str
    cost: int
    type: int
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


@dataclass(frozen=True)
class Attack:
    base: int
    hits: int


@dataclass(frozen=True)
class Enemy:
    name: str
    hp: int
    max_hp: int
    block: int
    attacks: tuple[Attack, ...]
    strength: int
    weak: int
    vulnerable: int
    poison: int


@dataclass(frozen=True)
class Player:
    hp: int
    max_hp: int
    block: int
    energy: int
    strength: int
    dexterity: int
    weak: int
    vulnerable: int
    frail: int


@dataclass(frozen=True)
class SimState:
    player: Player
    enemies: tuple[Enemy, ...]
    hand: tuple[Card, ...]
    played: tuple[Play, ...] = ()


@dataclass(frozen=True)
class Outcome:
    lethal: bool
    hp_loss: int
    hp_after: int
    enemy_hp_left: int
    incoming: int
    poison_kills: int


@dataclass(frozen=True)
class SolverResult:
    plays: tuple[Play, ...]
    outcome: Outcome
    initial_enemy_hp: int
    energy_left: int
    block_left: int
    modeled: tuple[Card, ...]
    unmodeled: tuple[tuple[str, str], ...]
    nodes: int
    truncated: bool
    enemy_names: tuple[str, ...]

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


def compile_card(raw: dict, index: int) -> tuple[Card | None, str | None]:
    """Return a modeled card, or (None, reason) when the effect is not known."""
    if not isinstance(raw, dict):
        return None, "数据格式错误"

    card_id = str(raw.get("Id") or "")
    name = str(raw.get("Name") or card_id or "?")
    if raw.get("CostsX"):
        return None, "X 费"
    card_type = int(raw.get("Type") or 0)
    if card_type == 3:
        return None, "能力牌（本回合收益未建模）"
    if card_type in (4, 5, 6):
        return None, "状态/诅咒/任务牌"
    if card_type not in (1, 2):
        return None, "未知卡牌类型"

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

    target = int(raw.get("Target") if raw.get("Target") is not None else 0)
    has_enemy_effect = damage > 0 or poison > 0 or weak > 0 or vulnerable > 0 or frail > 0
    if has_enemy_effect:
        if target == TARGET_RANDOM:
            return None, "随机目标"
        if target not in (TARGET_ANY, TARGET_ALL):
            return None, "目标类型未建模"

    if not has_enemy_effect and block <= 0 and strength <= 0 and dexterity <= 0:
        return None, "没有可模拟的即时效果"

    return (
        Card(
            index=index,
            id=card_id,
            name=name,
            cost=cost,
            type=card_type,
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
        ),
        None,
    )


def _attack_value(card: Card, player: Player, enemy: Enemy) -> int:
    """Damage of one hit, before block. The caller repeats it card.hits times."""
    per_hit = card.damage + player.strength
    if player.weak > 0:
        per_hit *= 0.75
    if enemy.vulnerable > 0:
        per_hit *= 1.5
    return max(0, int(per_hit))


def _block_value(card: Card, player: Player) -> int:
    amount = card.block + player.dexterity
    if player.frail > 0:
        amount *= 0.75
    return max(0, int(amount))


def _enemy_attack_value(enemy: Enemy, player: Player) -> int:
    total = 0
    for attack in enemy.attacks:
        per_hit = attack.base + enemy.strength
        if enemy.weak > 0:
            per_hit *= 0.75
        if player.vulnerable > 0:
            per_hit *= 1.5
        total += max(0, int(per_hit)) * attack.hits
    return total


def _hit(enemy: Enemy, amount: int) -> Enemy:
    blocked = min(enemy.block, amount)
    return replace(enemy, block=enemy.block - blocked, hp=enemy.hp - (amount - blocked))


def _outcome(state: SimState) -> Outcome:
    player = state.player
    enemies = list(state.enemies)
    poison_kills = 0

    # Poison ticks at the start of the enemy turn, before the intent executes.
    for i, enemy in enumerate(enemies):
        if enemy.hp <= 0 or enemy.poison <= 0:
            continue
        hp = enemy.hp - enemy.poison
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
    loss = max(0, incoming - player.block)
    hp_after = max(0, player.hp - loss)
    enemy_hp_left = sum(enemy.hp + enemy.block for enemy in alive)
    return Outcome(
        lethal=not alive,
        hp_loss=loss,
        hp_after=hp_after,
        enemy_hp_left=enemy_hp_left,
        incoming=incoming,
        poison_kills=poison_kills,
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
) -> SimState | None:
    if card.cost > state.player.energy:
        return None
    if card.discard and len([c for c in state.hand if c.index != card.index]) < card.discard:
        return None

    player = state.player
    enemies = list(state.enemies)
    hand = [c for c in state.hand if c.index != card.index]
    energy = player.energy - card.cost
    block = player.block
    strength = player.strength
    dexterity = player.dexterity

    targets: list[int] = []
    if target_index is not None:
        targets = [target_index]
    elif card.target == TARGET_ALL:
        targets = [i for i, enemy in enumerate(enemies) if enemy.hp > 0]

    # Damage is applied before debuffs from the same card (Bash/Neutralize text).
    if card.damage > 0:
        for index in targets:
            for _ in range(card.hits):
                if enemies[index].hp <= 0:
                    break
                enemies[index] = _hit(enemies[index], _attack_value(card, player, enemies[index]))

    if card.block > 0:
        block += _block_value(card, player)

    if card.poison > 0:
        for index in targets:
            if enemies[index].hp > 0:
                enemies[index] = replace(enemies[index], poison=enemies[index].poison + card.poison)

    if card.weak > 0:
        for index in targets:
            if enemies[index].hp > 0:
                enemies[index] = replace(enemies[index], weak=enemies[index].weak + card.weak)

    if card.vulnerable > 0:
        for index in targets:
            if enemies[index].hp > 0:
                enemies[index] = replace(
                    enemies[index], vulnerable=enemies[index].vulnerable + card.vulnerable
                )

    if card.frail > 0:
        for index in targets:
            if enemies[index].hp > 0:
                enemies[index] = replace(enemies[index], frail=enemies[index].frail + card.frail)

    if card.strength > 0:
        strength += card.strength
    if card.dexterity > 0:
        dexterity += card.dexterity

    if card.discard and discard_index is not None:
        hand = [c for c in hand if c.index != discard_index]

    return replace(
        state,
        player=replace(
            player,
            energy=energy,
            block=block,
            strength=strength,
            dexterity=dexterity,
        ),
        enemies=tuple(enemies),
        hand=tuple(hand),
    )


class Solver:
    def __init__(self, state: SimState):
        self.state = state
        self.nodes = 0
        self.truncated = False
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
            for target in targets:
                for discard in discards:
                    child = _play(state, card, target, discard)
                    if child is None:
                        continue
                    yield child, Play(
                        card.id,
                        card.name,
                        card.cost,
                        target,
                        discard,
                        target_all=card.target == TARGET_ALL
                        and card.damage + card.poison + card.weak + card.vulnerable > 0,
                    )

    def solve(self) -> tuple[tuple[Play, ...], SimState, int, bool]:
        score, plays, final = self._dfs(self.state)
        return plays, final, self.nodes, self.truncated

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
            tuple(
                (e.hp, e.block, e.strength, e.weak, e.vulnerable, e.poison)
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
    player = Player(
        hp=int(state.get("Hp") or 0),
        max_hp=max(1, int(state.get("MaxHp") or 1)),
        block=int(state.get("Block") or 0),
        energy=int(state.get("Energy") or 0),
        strength=_power(powers, "StrengthPower", "Strength"),
        dexterity=_power(powers, "DexterityPower", "Dexterity"),
        weak=_power(powers, "WeakPower", "Weak"),
        vulnerable=_power(powers, "VulnerablePower", "Vulnerable"),
        frail=_power(powers, "FrailPower", "Frail"),
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
                max_hp=max(hp, int(raw.get("MaxHp") or hp)),
                block=max(0, int(raw.get("Block") or 0)),
                attacks=tuple(attacks),
                strength=_power(enemy_powers, "StrengthPower", "Strength"),
                weak=_power(enemy_powers, "WeakPower", "Weak"),
                vulnerable=_power(enemy_powers, "VulnerablePower", "Vulnerable"),
                poison=_power(enemy_powers, "PoisonPower", "Poison"),
            )
        )

    if not enemies:
        return None, (), (), "没有存活敌人"

    modeled: list[Card] = []
    unmodeled: list[tuple[str, str]] = []
    for index, raw in enumerate(hand_raw[:MAX_HAND]):
        card, reason = compile_card(raw, index)
        if card is None:
            unmodeled.append((str(raw.get("Name") or raw.get("Id") or "?"), reason or "未建模"))
        else:
            modeled.append(card)

    simulator = SimState(player=player, enemies=tuple(enemies), hand=tuple(modeled))
    return Solver(simulator), tuple(modeled), tuple(unmodeled), None


def solve(state: dict) -> tuple[SolverResult | None, str | None]:
    solver, modeled, unmodeled, error = build_solver(state)
    if solver is None:
        return None, error

    plays, final, nodes, truncated = solver.solve()
    outcome = _outcome(final)
    initial_enemy_hp = sum(e.hp + e.block for e in solver.state.enemies)
    names = tuple(enemy.name for enemy in solver.state.enemies)
    return (
        SolverResult(
            plays=plays,
            outcome=outcome,
            initial_enemy_hp=initial_enemy_hp,
            energy_left=final.player.energy,
            block_left=final.player.block,
            modeled=modeled,
            unmodeled=unmodeled,
            nodes=nodes,
            truncated=truncated,
            enemy_names=names,
        ),
        None,
    )

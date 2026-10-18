"""Local rule engine for StS2 Copilot.

Input: the GameState JSON produced by the C# reader (PascalCase keys).
Output: {"advice": [{"ruleId", "text", "severity"}], "source": "python"}
"""

from __future__ import annotations

from combat import solve

import catalog as model_catalog

TYPE_NAMES = {
    0: "未定",
    1: "未知",
    2: "商店",
    3: "宝箱",
    4: "营地",
    5: "战斗",
    6: "精英",
    7: "Boss",
    8: "远古",
}

RARITY_SCORE = {4: 3.0, 5: 3.5, 3: 2.0, 2: 1.2, 1: 0.5}
RELIC_RARITY_SCORE = {
    "Common": 1.2, "Uncommon": 2.0, "Rare": 3.0,
    "Ancient": 4.0, "Event": 2.5, "Shop": 2.0,
}
POTION_RARITY_SCORE = {"Common": 1.0, "Uncommon": 1.5, "Rare": 2.2, "Event": 2.0}


def score_potion(value) -> float:
    entity = model_catalog.potion(value)
    if not entity:
        return 1.2
    score = POTION_RARITY_SCORE.get(str(entity.get("rarity") or ""), 1.2)
    kinds = {e.get("kind") for e in entity.get("effects") or []}
    powers = {e.get("power") for e in entity.get("effects") or []}
    if kinds & {"heal", "block", "power"}:
        score += 0.2
    if "damage" in kinds:
        score += 0.4
    if "draw" in kinds or "energy" in kinds:
        score += 0.15
    if powers & {"IntangiblePower", "ShrinkPower", "PlatingPower", "BufferPower"}:
        score += 0.5
    if "automatic" in str(entity.get("usage") or "").lower():
        score += 1.5
    return score


def score_relic(value) -> float:
    entity = model_catalog.relic(value)
    if not entity:
        return 2.0
    score = RELIC_RARITY_SCORE.get(str(entity.get("rarity") or ""), 2.0)
    score += min(1.0, 0.15 * len(entity.get("hooks") or []))
    if entity.get("model", {}).get("level") == "exact":
        score += 0.3
    return score


def _advice(rule_id: str, text: str, severity: str = "info") -> dict:
    return {"ruleId": rule_id, "text": text, "severity": severity}


def _knapsack(cards, energy, value):
    if not cards:
        return 0, []
    cards = cards[:12]
    n = len(cards)
    best_value = 0
    best_mask = 0
    for mask in range(1 << n):
        cost = 0
        total = 0
        for i in range(n):
            if mask & (1 << i):
                cost += max(0, cards[i].get("Cost", 0))
                total += value(cards[i])
        if cost <= energy and total > best_value:
            best_value = total
            best_mask = mask
    chosen = [cards[i] for i in range(n) if best_mask & (1 << i)]
    return best_value, chosen


def _names(cards) -> str:
    return "、".join(
        _upgrade_mark(str(c.get("Name", "?")), int(c.get("Upgraded") or 0))
        for c in cards
    ) or "（无）"


def _deck(state):
    return state.get("DeckCards") or []


def score_card(state, card) -> float:
    score = RARITY_SCORE.get(card.get("Rarity", 0), 0.5)
    cost = max(1, card.get("Cost", 0))
    effect = card.get("Damage", 0) * max(1, card.get("Hits", 1))
    effect += card.get("Block", 0) + int(card.get("Poison", 0) * 1.5)
    score += min(3.0, effect / (5.0 * cost))

    deck = _deck(state)
    deck_size = max(1, len(deck))
    attacks = sum(1 for c in deck if c.get("Type") == 1)
    blocks = sum(1 for c in deck if c.get("Block", 0) > 0)

    if card.get("Type") == 1 and attacks / deck_size < 0.4:
        score += 1.2
    if card.get("Block", 0) > 0 and blocks / deck_size < 0.3:
        score += 1.2
    if card.get("Type") == 3 and state.get("Act", 1) <= 1 and state.get("Floor", 0) <= 6:
        score -= 1.2
    if card.get("Poison", 0) > 0 and sum(1 for c in deck if c.get("Poison", 0) > 0) >= 2:
        score += 0.5
    if card.get("Cost", 0) >= 3 and state.get("Act", 1) <= 1:
        score -= 1.0
    if card.get("Cost", 0) == 0:
        score += 0.3

    entity = model_catalog.card(card)
    if entity:
        tags = set(entity.get("tags") or [])
        keywords = set(entity.get("keywords") or [])
        kinds = {item.get("kind") for item in entity.get("effects") or []}
        if "draw" in kinds:
            score += 0.4
        if "energy" in kinds or "stars" in kinds:
            score += 0.4
        if "generated" in kinds or "transform" in kinds:
            score -= 0.3
        if "Exhaust" in keywords:
            score -= 0.2
        if "Ethereal" in keywords:
            score -= 0.2
        if "Retain" in keywords or "Innate" in keywords:
            score += 0.2
        if "Strike" in tags and card.get("Damage", 0) > 0:
            score += 0.1
        if entity.get("model", {}).get("level") == "partial":
            # Catalog-known but not exactly simulable: do not penalize the card,
            # just avoid over-ranking it like a fully modeled one.
            score -= 0.1
    return score


def _reward(state):
    choices = state.get("CardChoices") or []
    ranked = sorted(((score_card(state, c), c) for c in choices), key=lambda x: -x[0])
    advice = []
    if ranked:
        advice.append(_advice("reward.recommend", f"推荐：{ranked[0][1].get('Name', '?')}（评分 {ranked[0][0]:.1f}）", "good"))
        lines = []
        if state.get("RewardGold", 0) > 0:
            lines.append(f"金币 +{state['RewardGold']}")
        for score, card in ranked:
            cost = "X" if card.get("CostsX") else card.get("Cost", 0)
            effect = []
            if card.get("Damage", 0) > 0:
                hit = f"×{card['Hits']}" if card.get("Hits", 1) > 1 else ""
                effect.append(f"{card['Damage']}{hit}伤")
            if card.get("Block", 0) > 0:
                effect.append(f"{card['Block']}挡")
            if card.get("Poison", 0) > 0:
                effect.append(f"{card['Poison']}毒")
            suffix = ("  " + " ".join(effect)) if effect else ""
            card_name = _upgrade_mark(str(card.get("Name", "?")), int(card.get("Upgraded") or 0))
            lines.append(f"{card_name}（{cost}费）{suffix}  评分 {score:.1f}")

        advice.append(_advice("reward.card_choice", "三选一：\n" + "\n".join(lines), "good"))
        if len(ranked) >= 2 and ranked[0][0] - ranked[1][0] < 0.5:
            advice.append(_advice("reward.close_call", "前两名差距很小，按流派偏好选即可。", "info"))
    advice.extend(_potion_reward(state))
    return advice


def map_score(state, node) -> tuple[float, str]:
    hp = state.get("Hp", 0) / max(1, state.get("MaxHp", 1))
    gold = state.get("Gold", 0)
    deck = len(_deck(state))
    point_type = node.get("Type", 1)

    if point_type == 6:  # Elite
        if hp > 0.6 and deck >= 15:
            return 3.0, "血量健康，精英给遗物"
        return -2.0, "血量/牌组不足以稳吃精英"
    if point_type == 4:  # Rest
        if hp < 0.6:
            return 2.6, "血量偏低，营地回血"
        return 1.0, "状态尚可，营地收益一般"
    if point_type == 2:  # Shop
        if gold >= 120:
            return 2.2, f"金币 {gold}，可买关键牌/遗物"
        return 0.4, f"金币 {gold}，商店暂时买不起"
    if point_type == 3:  # Treasure
        return 2.0, "宝箱稳定收益"
    if point_type == 5:  # Monster
        return 1.2 if hp > 0.5 else 0.6, "普通战斗，拿牌/金币"
    if point_type == 1:  # Unknown
        return 1.1, "未知事件，有上限也有风险"
    if point_type == 0:
        return 0.0, "未定节点"
    return 0.0, "Boss/特殊节点"


def _node_loss(state, node):
    act = min(3, max(1, int(state.get("Act", 1))))
    table = {1: (6, 20, 5), 2: (9, 28, 7), 3: (12, 35, 9)}[act]
    point_type = node.get("Type", 0)
    if point_type == 5:
        loss = table[0]
    elif point_type == 6:
        loss = table[1]
    elif point_type == 1:
        loss = table[2]
    else:
        loss = 0

    if point_type == 6 and len(state.get("DeckCards") or []) < 15:
        loss += 8
    return loss


def _node_reward(state, node):
    point_type = node.get("Type", 0)
    if point_type == 6:
        return 2.8
    if point_type == 5:
        return 1.0
    if point_type == 3:
        return 1.8
    if point_type == 4:
        return 0.8
    if point_type == 2:
        return 1.0 if int(state.get("Gold", 0)) >= 120 else 0.2
    if point_type == 1:
        return 0.9
    return 0.0


def _risk_penalty(hp, max_hp):
    ratio = hp / max(1, max_hp)
    if ratio < 0.15:
        return -5.0
    if ratio < 0.3:
        return -1.5
    return 0.0


def _map_ascension(state) -> int:
    try:
        return max(0, int(state.get("Ascension") or 0))
    except (TypeError, ValueError):
        return 0


def _boss_threshold(act: int, ascension: int) -> float:
    """HP ratio we want when entering the boss.

    A10 is the acceptance target, so at A10 the margin is deliberately higher.
    """
    return min(0.80, 0.55 + 0.05 * max(0, act - 1) + (0.15 if ascension >= 10 else 0.0))


def _boss_penalty(hp: int, max_hp: int, act: int, ascension: int) -> float:
    threshold = _boss_threshold(act, ascension)
    ratio = hp / max(1, max_hp)
    return max(0.0, threshold - ratio) * 40.0


def _path_penalty(node_type: int, last_type: int, elite_count: int,
                  hp_after: int, max_hp: int) -> float:
    """Order-sensitive risk: elite stacking, rest timing, low-HP elites."""
    penalty = 0.0
    if node_type == 6:  # Elite
        if elite_count > 0:
            penalty -= 2.0 * elite_count
        if last_type == 6:
            penalty -= 3.0
        if last_type == 4:
            penalty += 0.5
        if hp_after < int(max_hp * 0.4):
            penalty -= 1.0
    elif node_type == 4 and last_type == 6:
        penalty += 0.8  # heal immediately after an elite
    return penalty



def _map_dp(state):
    """Full DAG DP from the current node to the boss, with path-aware risk.

    State = (node, hp, previous node type, elite count). The value includes
    future nodes all the way to the boss, a low-HP risk penalty, elite
    stacking/rest-timing penalties, and a boss-entry readiness penalty.
    If the current node is not in the graph (act start / Ancient node), the
    MapChoices are used as roots so the next-step score still includes the
    whole future path.
    """
    nodes_list = state.get("MapNodes") or []
    edges = state.get("MapEdges") or []
    if not nodes_list:
        return None

    nodes = {(n.get("Col"), n.get("Row")): n for n in nodes_list}
    start = (state.get("MapCol"), state.get("MapRow"))
    boss = next((k for k, n in nodes.items() if n.get("Type") == 7), None)
    if boss is None:
        return None

    adjacency = {}
    for edge in edges:
        a = (edge.get("FromCol"), edge.get("FromRow"))
        b = (edge.get("ToCol"), edge.get("ToRow"))
        adjacency.setdefault(a, []).append(b)

    choices = [
        (node.get("Col"), node.get("Row"))
        for node in (state.get("MapChoices") or [])
        if isinstance(node, dict)
    ]
    roots = list(adjacency.get(start, []))
    if not roots:
        roots = [node for node in choices if node in nodes]
    if not roots:
        return None

    max_hp = max(1, int(state.get("MaxHp", 1)))
    start_hp = max(1, int(state.get("Hp", 1)))
    act = min(3, max(1, int(state.get("Act", 1))))
    ascension = _map_ascension(state)
    start_type = int((nodes.get(start) or {}).get("Type") or 0)
    memo = {}

    def solve(node, hp, last_type, elite_count, depth):
        key = (node, hp, last_type, elite_count, depth)
        if key in memo:
            return memo[key]

        info = nodes.get(node)
        if info is None:
            return (-1e9, (), hp)
        node_type = int(info.get("Type") or 0)
        if node_type == 7:
            penalty = _boss_penalty(hp, max_hp, act, ascension)
            result = (-penalty, (node,), hp)
            memo[key] = result
            return result

        loss = _node_loss(state, info)
        if ascension >= 10 and node_type in (5, 6):
            loss = int(loss * 1.30 + 0.999)
        missing = max(0, max_hp - hp)
        heal = min(missing, int(max_hp * 0.3)) if node_type == 4 else 0
        hp_after = max(0, min(max_hp, hp - loss + heal))
        if hp_after <= 0:
            return (-1e9, (), hp_after)

        value = (
            _node_reward(state, info)
            + _risk_penalty(hp_after, max_hp)
            + _path_penalty(node_type, last_type, elite_count, hp_after, max_hp)
        )
        next_elites = elite_count + (1 if node_type == 6 else 0)
        children = adjacency.get(node, [])
        if not children or depth <= 0:
            result = (value, (node,), hp_after)
            memo[key] = result
            return result

        best_total = -1e9
        best_path = ()
        best_hp = hp_after
        for child in children:
            child_value, child_path, child_hp = solve(
                child, hp_after, node_type, next_elites, depth - 1
            )
            total = value + child_value
            if total > best_total:
                best_total = total
                best_path = child_path
                best_hp = child_hp

        result = (best_total, (node,) + best_path, best_hp)
        memo[key] = result
        return result

    ranked = []
    for child in roots:
        value, path, hp_after = solve(child, start_hp, start_type, 0, 64)
        ranked.append((value, child, path, hp_after))

    if not ranked:
        return None

    # If the graph is missing the Boss path, do not pretend the score covers
    # the whole act; let _map_lookahead handle a bounded future instead.
    if not any(path and path[-1] == boss for _, _, path, _ in ranked):
        return None

    ranked.sort(key=lambda item: -item[0])

    def fmt_path(path):
        return " → ".join(
            f"{TYPE_NAMES.get(nodes[k].get('Type', 0), '?')}({k[0]},{k[1]})"
            for k in path
        )

    def stats(path):
        counts = {}
        for node in path:
            counts[nodes[node].get("Type", 0)] = counts.get(nodes[node].get("Type", 0), 0) + 1
        parts = []
        for node_type, label in ((6, "精英"), (4, "营地"), (2, "商店"), (3, "宝箱")):
            if counts.get(node_type):
                parts.append(f"{label}×{counts[node_type]}")
        return " ".join(parts) or "无额外节点"

    advice = []
    best_value, best_child, best_path, best_hp = ranked[0]
    advice.append(_advice(
        "map.recommend",
        f"推荐路线（到 Boss 综合）：{fmt_path(best_path)}；"
        f"预计结束 HP {best_hp}/{max_hp}（{best_hp * 100 // max_hp}%），"
        f"{stats(best_path)}，综合评分 {best_value:.1f}",
        "good"))

    lines = []
    for value, child, path, hp_after in ranked:
        preview = fmt_path(path[:6]) + ("…" if len(path) > 6 else "")
        lines.append(
            f"{TYPE_NAMES.get(nodes[child].get('Type', 0), '?')}"
            f"（{child[0]},{child[1]}）  综合评分 {value:.1f}  "
            f"HP→{hp_after}/{max_hp}  {stats(path)}  {preview}"
        )
    advice.append(_advice("map.route", "下一步（分数已包含之后到 Boss 的路径）：\n" + "\n".join(lines), "info"))
    if len(ranked) >= 2 and ranked[0][0] - ranked[1][0] < 0.5:
        first = ranked[0]
        second = ranked[1]
        safer, other = (first, second) if first[3] >= second[3] else (second, first)
        advice.append(_advice(
            "map.close_call",
            f"前两名综合分差仅 {first[0] - second[0]:.1f}："
            f"{TYPE_NAMES.get(nodes[first[1]].get('Type', 0), '?')} 预计 HP {first[3]}/{max_hp}；"
            f"{TYPE_NAMES.get(nodes[second[1]].get('Type', 0), '?')} 预计 HP {second[3]}/{max_hp}。"
            f"想稳 Boss 血线选 {TYPE_NAMES.get(nodes[safer[1]].get('Type', 0), '?')}，"
            f"想多拿遗物/收益选 {TYPE_NAMES.get(nodes[other[1]].get('Type', 0), '?')}。",
            "info",
        ))
    return advice



def _map_lookahead(state, depth=6):
    """Bounded future lookahead when the full graph/boss is unavailable."""
    nodes_list = state.get("MapNodes") or []
    edges = state.get("MapEdges") or []
    if not nodes_list or not edges:
        return None
    nodes = {(n.get("Col"), n.get("Row")): n for n in nodes_list}
    choices = [
        (node.get("Col"), node.get("Row"))
        for node in (state.get("MapChoices") or [])
        if isinstance(node, dict) and (node.get("Col"), node.get("Row")) in nodes
    ]
    if not choices:
        return None
    adjacency = {}
    for edge in edges:
        adjacency.setdefault(
            (edge.get("FromCol"), edge.get("FromRow")), []
        ).append((edge.get("ToCol"), edge.get("ToRow")))
    max_hp = max(1, int(state.get("MaxHp", 1)))
    start_hp = max(1, int(state.get("Hp", 1)))
    act = min(3, max(1, int(state.get("Act", 1))))
    ascension = _map_ascension(state)
    memo = {}

    def solve(node, hp, last_type, elite_count, remaining):
        key = (node, hp, last_type, elite_count, remaining)
        if key in memo:
            return memo[key]
        info = nodes.get(node)
        if info is None:
            return (-1e9, (), hp)
        node_type = int(info.get("Type") or 0)
        if node_type == 7:
            result = (-_boss_penalty(hp, max_hp, act, ascension), (node,), hp)
            memo[key] = result
            return result
        loss = _node_loss(state, info)
        if ascension >= 10 and node_type in (5, 6):
            loss = int(loss * 1.30 + 0.999)
        missing = max(0, max_hp - hp)
        heal = min(missing, int(max_hp * 0.3)) if node_type == 4 else 0
        hp_after = max(0, min(max_hp, hp - loss + heal))
        if hp_after <= 0:
            return (-1e9, (), hp_after)
        value = (
            _node_reward(state, info)
            + _risk_penalty(hp_after, max_hp)
            + _path_penalty(node_type, last_type, elite_count, hp_after, max_hp)
        )
        children = [child for child in adjacency.get(node, []) if child in nodes]
        if remaining <= 1 or not children:
            result = (value, (node,), hp_after)
            memo[key] = result
            return result
        best = (-1e9, (), hp_after)
        for child in children:
            child_value, child_path, child_hp = solve(
                child, hp_after, node_type,
                elite_count + (1 if node_type == 6 else 0),
                remaining - 1,
            )
            total = value + child_value
            if total > best[0]:
                best = (total, (node,) + child_path, child_hp)
        memo[key] = best
        return best

    ranked = []
    for child in choices:
        value, path, hp_after = solve(child, start_hp, 0, 0, depth)
        ranked.append((value, child, path, hp_after))
    if not ranked:
        return None
    ranked.sort(key=lambda item: -item[0])

    def fmt(path):
        return " → ".join(
            f"{TYPE_NAMES.get(nodes[k].get('Type', 0), '?')}({k[0]},{k[1]})"
            for k in path
        )

    advice = [
        _advice(
            "map.recommend",
            f"推荐路线（局部前瞻 {depth} 步，完整 Boss 图不可用）：{fmt(ranked[0][2])}；"
            f"预计 HP {ranked[0][3]}/{max_hp}，评分 {ranked[0][0]:.1f}",
            "warn",
        )
    ]
    lines = [
        f"{TYPE_NAMES.get(nodes[child].get('Type', 0), '?')}（{child[0]},{child[1]}）  "
        f"评分 {value:.1f}  HP→{hp_after}/{max_hp}  {fmt(path[:5])}"
        for value, child, path, hp_after in ranked
    ]
    advice.append(_advice(
        "map.route",
        "下一步（局部前瞻，分数包含之后节点）：\n" + "\n".join(lines),
        "info",
    ))
    return advice


_EVENT_EXIT_WORDS = (
    "离开", "敬而远之", "退出", "不选择", "放弃", "拒绝", "走开",
    "exit", "leave", "abstain", "walk away",
)
_EVENT_DAMAGE_WORDS = (
    "受到", "伤害", "掉血", "扣血", "damage", "hp loss",
)
_EVENT_DEATH_WORDS = (
    "死定了", "必死", "会死", "致命", "再泡下去", "无法生还", "死亡",
    "will kill", "certain death", "fatal",
)


def _event_num(value, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _event_option_text(option) -> str:
    return " ".join(
        str(option.get(key) or "")
        for key in ("TextKey", "Title", "Description")
    )


def _event_is_exit(option) -> bool:
    text = _event_option_text(option).lower()
    return any(word in text for word in _EVENT_EXIT_WORDS)


def _event_has_damage(option) -> bool:
    text = _event_option_text(option).lower()
    if any(word in text for word in _EVENT_DAMAGE_WORDS):
        return True
    return ("失去" in text or "lose" in text) and ("生命" in text or "hp" in text)


def _event_death_warning(state) -> bool:
    text = str(state.get("EventDescription") or "").lower()
    return any(word in text for word in _EVENT_DEATH_WORDS)


def _event_score(option):
    if option.get("Locked"):
        return -999
    text = f"{option.get('Title', '')} {option.get('Description', '')}"
    score = 0
    if option.get("Proceed"):
        score -= 10
    if option.get("RelicId") or option.get("RelicName"):
        score += score_relic(option.get("RelicId") or option.get("RelicName"))
    for word, delta in (
        ("获得", 2), ("遗物", 2), ("稀有", 2), ("升级", 2), ("移除", 2),
        ("金币", 1), ("治疗", 1), ("回复", 1), ("最大生命", 2), ("无色", 1),
        ("复制", 1), ("变化", 1),
    ):
        if word in text:
            score += delta
    for word, delta in (
        ("失去", -3), ("伤害", -2), ("诅咒", -5), ("中毒", -2),
        ("掉血", -2), ("减少", -2), ("无法", -3), ("锁定", -3),
    ):
        if word in text:
            score += delta
    return score


def _abyssal_baths_preview(state, option):
    """Known model for AbyssalBaths (fixed 0.107.1 source).

    Each immerse/linger grants +MaxHp current & max HP, then deals the
    event's current Damage (unblockable/unpowered); Damage grows by 1 after
    every click. The option preview in game subtracts the MaxHp gain, so the
    net HP loss is Damage - MaxHp.
    """
    if str(state.get("EventId") or "") != "AbyssalBaths":
        return None
    if _event_is_exit(option) or not _event_has_damage(option):
        return None

    variables = state.get("EventVars") or {}
    if not isinstance(variables, dict):
        variables = {}
    damage = _event_num(variables.get("Damage"))
    gain = _event_num(variables.get("MaxHp"))
    if damage <= 0:
        return None
    if gain <= 0:
        gain = 2.0

    hp = _event_num(state.get("Hp"))
    max_hp = _event_num(state.get("MaxHp"))
    net = max(0.0, damage - gain)
    hp_after = hp - net
    next_net = net + 1.0
    limit = max(3.0, max_hp * 0.04)
    too_risky = net > limit or hp_after <= max(8.0, max_hp * 0.30)
    return {
        "damage": damage,
        "gain": gain,
        "net": net,
        "hp_after": hp_after,
        "next_net": next_net,
        "too_risky": too_risky,
        "lethal": hp_after <= 0,
    }


def _event_analysis(state, option, index):
    score = _event_score(option)
    if option.get("Locked"):
        return {"index": index, "option": option, "score": score, "lethal": False, "risk": False, "note": ""}

    if _event_is_exit(option) and not _event_has_damage(option):
        return {"index": index, "option": option, "score": score, "lethal": False, "risk": False, "note": ""}

    warning = _event_death_warning(state)
    preview = _abyssal_baths_preview(state, option)
    if preview is not None:
        net = preview["net"]
        after = preview["hp_after"]
        note = (
            "本次净损失 %d HP（+%d 最大生命，受 %d 伤害），剩 %d；下次净损失 %d"
            % (net, preview["gain"], preview["damage"], after, preview["next_net"])
        )
        if preview["lethal"]:
            return {
                "index": index, "option": option, "score": -1000,
                "lethal": True, "risk": True,
                "note": "本次净损失 %d HP，当前 %d，会死亡" % (net, state.get("Hp", 0)),
            }
        if warning:
            return {
                "index": index, "option": option, "score": -1000,
                "lethal": True, "risk": True,
                "note": "事件已警告继续会死亡（本次净损失 %d HP，当前 %d）" % (net, state.get("Hp", 0)),
            }
        if preview["too_risky"]:
            return {
                "index": index, "option": option, "score": score - 25.0,
                "lethal": False, "risk": True,
                "note": "本次净损失 %d HP，只剩 %d；继续换 %d 最大生命不划算" % (net, after, preview["gain"]),
            }
        return {
            "index": index, "option": option,
            "score": score + max(0.0, 1.2 - 0.4 * net),
            "lethal": False, "risk": False, "note": note,
        }

    if warning and _event_has_damage(option):
        return {
            "index": index, "option": option, "score": -1000,
            "lethal": True, "risk": True,
            "note": "事件已警告继续会死亡",
        }

    hp = _event_num(state.get("Hp"))
    max_hp = _event_num(state.get("MaxHp"))
    if max_hp > 0 and _event_has_damage(option) and hp <= max(8.0, max_hp * 0.40):
        return {
            "index": index, "option": option, "score": score - 12.0,
            "lethal": False, "risk": True,
            "note": "当前 HP %d/%d 偏低，伤害/失去生命选项代价过高" % (hp, max_hp),
        }

    return {"index": index, "option": option, "score": score, "lethal": False, "risk": False, "note": ""}


_EVENT_UPGRADE_ALL_WORDS = ("所有", "全部", "每张", "all cards", "each card")


def _event_upgrade_count(option) -> int:
    """How many chosen cards the option upgrades (0 = not a deck-upgrade choice)."""
    if option.get("Locked") or option.get("Proceed"):
        return 0
    text = _event_option_text(option).lower()
    if "升级" not in text and "upgrade" not in text:
        return 0
    if "牌组" not in text and "deck" not in text:
        # "gain an upgraded card" is not a deck-card selection.
        return 0
    if any(word in text for word in _EVENT_UPGRADE_ALL_WORDS):
        # "upgrade all cards" does not need a target recommendation.
        return 0
    if any(word in text for word in ("两张", "2 张", "2张", "two cards", "2 cards")):
        return 2
    if any(word in text for word in ("一张", "1 张", "1张", "one card", "a card")):
        return 1
    return 0


def _upgrade_candidates(state, count: int):
    """Best unupgraded deck cards for an upgrade choice (deduped by card id)."""
    cards = [
        card for card in _deck(state)
        if int(card.get("Upgraded") or 0) == 0 and int(card.get("Type") or 0) in (1, 2, 3)
    ]
    ranked = sorted(cards, key=lambda card: -score_card(state, card))
    picked, seen = [], set()
    for card in ranked:
        key = str(card.get("Id") or card.get("Name") or "")
        if key in seen:
            continue
        seen.add(key)
        picked.append(card)
        if len(picked) >= count:
            break
    return picked


def _event_upgrade_advice(state, best, analysis):
    """Recommend which card to upgrade when an event option upgrades cards.

    0.107.1 events that upgrade a chosen deck card: AromaOfChaos, SpiritGrafter,
    SapphireSeed, BattlewornDummy (1) and Trial (2).  "Upgrade all cards" is
    excluded because no choice is involved.
    """
    counts = {item["index"]: _event_upgrade_count(item["option"]) for item in analysis}
    chosen = [item for item in analysis if counts.get(item["index"], 0) > 0]
    if not chosen:
        return None
    target = next((item for item in chosen if item["index"] == best["index"]), chosen[0])
    picked = _upgrade_candidates(state, counts[target["index"]])
    if not picked:
        return None
    names = "、".join(
        f"{card.get('Name', '?')}（评分 {score_card(state, card):.1f}）" for card in picked
    )
    if target["index"] == best["index"]:
        return _advice("event.upgrade_target", f"升级推荐：{names}", "info")
    title = target["option"].get("Title") or "升级选项"
    return _advice("event.upgrade_target", f"若选「{title}」：升级推荐 {names}", "info")


def _event(state):
    title = str(state.get("EventTitle") or state.get("EventId") or "事件")
    description = str(state.get("EventDescription") or "")
    options = [item for item in state.get("EventOptions") or [] if isinstance(item, dict)]
    context = f"事件：{title}" + (f"\n{description}" if description else "")
    if not options:
        return [_advice("event.context", context + "\n当前没有可选项。", "info")]

    analysis = [
        _event_analysis(state, option, index)
        for index, option in enumerate(options)
    ]
    lethal = [item for item in analysis if item["lethal"]]
    usable = [item for item in analysis if item["score"] > -900 and not item["lethal"]]
    if not usable:
        if lethal:
            notes = "；".join(
                "「%s」%s" % (item["option"].get("Title") or "选项", item["note"])
                for item in lethal
            )
            return [_advice("event.lethal", "没有安全选项，且选择会死亡：" + notes, "danger")]
        return [_advice("event.no_option", "所有选项都不可用。", "warn")]

    usable.sort(key=lambda item: (-item["score"], item["index"]))
    best = usable[0]
    advice = []
    for item in lethal:
        advice.append(_advice(
            "event.lethal",
            "「%s」%s" % (item["option"].get("Title") or "选项", item["note"]),
            "danger",
        ))

    suffix = f"；{best['note']}" if best.get("note") else ""
    if not suffix:
        risk_notes = [
            "「%s」%s" % (item["option"].get("Title") or "选项", item["note"])
            for item in analysis
            if item["risk"] and not item["lethal"] and item["index"] != best["index"]
        ]
        if risk_notes:
            suffix = "；" + "；".join(risk_notes)
    has_risk = bool(lethal) or any(
        item["risk"] for item in analysis if item["index"] != best["index"]
    )
    advice.append(_advice(
        "event.recommend",
        f"推荐：{best['option'].get('Title') or ('选项 %d' % (best['index'] + 1))}"
        f"（评分 {best['score']:.1f}）{suffix}",
        "warn" if has_risk or best["risk"] else "good",
    ))

    upgrade = _event_upgrade_advice(state, best, analysis)
    if upgrade:
        advice.append(upgrade)

    return advice


def _shop_score(state, item):
    kind = item.get("Kind")
    if kind in ("card", "colorless"):
        card = item.get("Card") or {}
        score = score_card(state, card)
        if kind == "colorless":
            score += 0.3
    elif kind == "relic":
        score = score_relic(item.get("RelicId") or item.get("RelicName"))
    elif kind == "potion":
        score = score_potion(item.get("PotionId") or item.get("Name"))
        if len(state.get("Potions") or []) >= 3:
            score -= 2.0
    elif kind == "removal":
        bad = sum(1 for c in _deck(state) if c.get("Type") in (4, 5))
        score = 2.5 if bad else 0.6
    else:
        score = 0.0
    return score


def _shop(state):
    items = [item for item in state.get("ShopItems") or [] if isinstance(item, dict)]
    if not items:
        return [_advice("shop.empty", "商店没有读到商品。", "info")]

    gold = int(state.get("Gold", 0))
    ranked = sorted(
        ((_shop_score(state, item), item) for item in items),
        key=lambda pair: -pair[0],
    )
    affordable = [pair for pair in ranked if pair[1].get("Affordable")]
    advice = []
    if affordable:
        score, best = affordable[0]
        advice.append(_advice(
            "shop.recommend",
            f"推荐购买：{best.get('Name', '?')}（{best.get('Cost', 0)} 金，评分 {score:.1f}，剩 {gold - int(best.get('Cost', 0))} 金）",
            "good"))
    else:
        advice.append(_advice("shop.no_affordable", f"金币 {gold}，没有买得起的商品；建议跳过。", "info"))

    lines = []
    for score, item in ranked:
        state_text = "可买" if item.get("Affordable") else "金币不足"
        lines.append(f"• {item.get('Name', '?')}  {item.get('Cost', 0)} 金（{state_text}，评分 {score:.1f}）")
    advice.append(_advice("shop.items", "商店：\n" + "\n".join(lines), "info"))
    return advice


def _rest(state):
    options = [item for item in state.get("RestOptions") or [] if isinstance(item, dict)]
    if not options:
        return [_advice("rest.empty", "营地没有读到选项。", "info")]

    missing = max(0, int(state.get("MaxHp", 0)) - int(state.get("Hp", 0)))
    upgrade = None
    for card in _deck(state):
        if int(card.get("Upgraded") or 0) == 0:
            if upgrade is None or score_card(state, card) > score_card(state, upgrade):
                upgrade = card

    ranked = []
    for option in options:
        if not option.get("Enabled", True):
            continue
        option_id = str(option.get("OptionId") or "").upper()
        if option_id == "HEAL":
            heal = min(missing, int(option.get("HealAmount") or 0))
            score = (heal / max(1, int(state.get("MaxHp", 1)))) * 10
            if int(state.get("Hp", 0)) * 2 < int(state.get("MaxHp", 1)):
                score += 3
        elif option_id == "SMITH":
            score = 2.0 if upgrade is not None else 0.0
        elif option_id in ("DIG", "LIFT"):
            score = 2.8
        else:
            score = 1.5
        ranked.append((score, option))

    ranked.sort(key=lambda pair: -pair[0])
    if not ranked:
        return [_advice("rest.no_option", "营地没有可用选项。", "warn")]

    score, best = ranked[0]
    advice = [_advice("rest.recommend", f"推荐：{best.get('Title', '?')}（评分 {score:.1f}）", "good")]
    if str(best.get("OptionId") or "").upper() == "SMITH" and upgrade is not None:
        advice.append(_advice("rest.smith_target", f"升级推荐：{upgrade.get('Name', '?')}（当前评分 {score_card(state, upgrade):.1f}）", "info"))

    lines = []
    for value, option in ranked:
        heal = f"  回复 {option.get('HealAmount')}" if option.get("HealAmount") else ""
        lines.append(f"• {option.get('Title', '?')}{heal}  评分 {value:.1f}")
        if option.get("Description"):
            lines.append("   " + str(option["Description"]))
    advice.append(_advice("rest.options", "营地：\n" + "\n".join(lines), "info"))
    return advice


def _treasure(state):
    relics = [item for item in state.get("RelicChoices") or [] if isinstance(item, dict)]
    if not relics:
        return [_advice("treasure.waiting", "宝箱/遗物选择还没出现。", "info")]

    ranked = sorted(
        ((score_relic(relic.get("Id") or relic.get("Name")) + 0.1 * min(5, int(relic.get("Rarity") or 0)), relic)
         for relic in relics),
        key=lambda pair: -pair[0],
    )
    score, best = ranked[0]
    advice = [_advice("treasure.recommend", f"推荐：{best.get('Name', '?')}（评分 {score:.1f}）", "good")]
    lines = []
    for value, relic in ranked:
        lines.append(f"• {relic.get('Name', '?')}  评分 {value:.1f}")
        if relic.get("Description"):
            lines.append("   " + str(relic["Description"]))
    advice.append(_advice("treasure.options", "遗物选择：\n" + "\n".join(lines), "info"))
    return advice


def _map(state):
    full = _map_dp(state)
    if full is not None:
        return full
    lookahead = _map_lookahead(state)
    if lookahead is not None:
        return lookahead

    choices = state.get("MapChoices") or []
    if not choices:
        return []
    ranked = sorted(((map_score(state, n)[0], n) for n in choices), key=lambda x: -x[0])
    lines = []
    for score, node in ranked:
        lines.append(f"{TYPE_NAMES.get(node.get('Type', 0), '?')}（{node.get('Col')},{node.get('Row')}）  评分 {score:.1f}")
    best_score, best = ranked[0]
    advice = [_advice("map.recommend", f"下一层推荐：{TYPE_NAMES.get(best.get('Type', 0), '?')}（评分 {best_score:.1f}）", "good")]
    advice.append(_advice("map.route", "下一层：\n" + "\n".join(lines), "info"))
    return advice


def _enemy_labels(names):
    counts = {}
    seen = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    labels = []
    for name in names:
        if counts.get(name, 0) <= 1:
            labels.append(name)
            continue
        seen[name] = seen.get(name, 0) + 1
        labels.append(f"{name}#{seen[name]}")
    return labels


def _upgrade_mark(name: str, level: int) -> str:
    if level <= 0:
        return name
    return f"{name}+{level}" if level > 1 else f"{name}+"


def _sequence_parts(result):
    labels = _enemy_labels(result.enemy_names)
    cards = {
        card.index: _upgrade_mark(card.name, card.upgrade_level)
        for card in result.modeled
    }
    parts = []
    for play in result.plays:
        text = _upgrade_mark(play.name, play.upgrade_level)
        if play.target_all:
            text += "→全体"
        elif play.target_index is not None and play.target_index < len(labels):
            text += f"→{labels[play.target_index]}"
        if play.discard_index is not None:
            text += f"（弃{cards.get(play.discard_index, '?')}）"
        elif play.discard_drawn:
            text += "（弃抽到的牌）"
        parts.append(text)
    return parts


def _format_sequence(result):
    """Format the advised plays one per line (the UI renders "\\n")."""
    parts = _sequence_parts(result)
    return "".join(f"\n  {index}. {part}" for index, part in enumerate(parts, 1))


def _potion_damage_options(state):
    """Return available direct-damage potions as (name, damage, hits_all)."""
    result = []
    for entry in _potion_entries(state):
        if _potion_role(entry) != "damage":
            continue
        key = _potion_key(entry)
        entity = entry.get("entity") or {}
        if "explosive" in key:
            damage, hits_all = 10, True
        elif "fire" in key:
            damage, hits_all = 20, False
        elif "shaped" in key:
            damage, hits_all = 15, False
        else:
            damage, hits_all = 0, entity.get("target") == "AllEnemies"
            for effect in entity.get("effects") or []:
                if effect.get("kind") not in ("damage", "self_damage"):
                    continue
                for var in entity.get("vars") or []:
                    if var.get("key") == effect.get("amount"):
                        damage = max(damage, int(var.get("base") or 0))
                        break
            if not damage:
                for var in entity.get("vars") or []:
                    if var.get("key") == "Damage":
                        damage = max(damage, int(var.get("base") or 0))
                        break
        if damage > 0:
            result.append((entry["name"], damage, bool(hits_all)))
    return result


def _potion_kill_advice(state, result):
    """Explain a damage potion that can finish before end-of-turn burdens."""
    hp = int(state.get("Hp", 0))
    end_damage = result.outcome.end_turn_damage
    if result.outcome.hp_after > 0 or end_damage < hp:
        return None
    enemies = state.get("Enemies") or []
    enemy_hp = sum(max(0, int(e.get("Hp") or 0)) for e in enemies if int(e.get("Hp") or 0) > 0)
    if enemy_hp <= 0:
        return None
    intangible = any(int((e.get("Powers") or {}).get("IntangiblePower") or 0) > 0 for e in enemies)
    max_attack = 0
    for card in state.get("Hand") or []:
        if int(card.get("Type") or 0) == 1:
            max_attack = max(max_attack, int(card.get("Damage") or 0) * max(1, int(card.get("Hits") or 1)))
    unblockable = result.outcome.end_turn_unblockable
    if unblockable >= end_damage:
        note = "不可格挡"
    elif unblockable > 0:
        note = f"其中 {unblockable} 点不可格挡"
    else:
        note = "可格挡"
    options = _potion_damage_options(state)
    for name, damage, _ in options:
        effective = min(1, damage) if intangible else damage
        if effective + max_attack >= enemy_hp:
            return f"先用{name}（{effective} 伤害）+ 最高伤害牌（约 {max_attack}），本回合先杀，避免回合结束的 {end_damage} 点伤害（{note}）。"
    return None


def _potion_entries(state, reward=False):
    """Return current/reward potions with ids, labels, catalog data and scores."""
    if reward:
        ids = [str(item) for item in (state.get("RewardPotionIds") or [])]
        names = [str(item) for item in (state.get("RewardPotions") or [])]
    else:
        ids = [str(item) for item in (state.get("PotionIds") or [])]
        names = [str(item) for item in (state.get("Potions") or [])]
    entries = []
    count = max(len(ids), len(names))
    for index in range(count):
        potion_id = ids[index] if index < len(ids) else ""
        name = names[index] if index < len(names) else ""
        entity = model_catalog.potion(potion_id) or model_catalog.potion(name)
        label = name or (entity or {}).get("class") or potion_id or "?"
        entries.append({
            "id": potion_id,
            "name": label,
            "entity": entity or {},
            "score": score_potion(potion_id or name),
        })
    return entries


def _potion_key(entry) -> str:
    entity = entry.get("entity") or {}
    values = [str(entity.get("class") or ""), str(entity.get("id") or ""),
              str(entry.get("id") or ""), str(entry.get("name") or "")]
    return " ".join(values).lower().replace(" ", "")


def _potion_role(entry) -> str:
    key = _potion_key(entry)
    if any(word in key for word in ("explosiveampoule", "firepotion", "potionshapedrock")):
        return "damage"
    if "beetlejuice" in key:
        return "shrink"
    if "heartofiron" in key:
        return "plating"
    if "ghostinajar" in key or "intangible" in key:
        return "intangible"
    if "blockpotion" in key or "shipinabottle" in key:
        return "block"
    if "weakpotion" in key or "potionofbinding" in key:
        return "weaken"
    if "poisonpotion" in key:
        return "poison"
    if "bloodpotion" in key or "fruitjuice" in key or "fairyinabottle" in key:
        return "heal"
    effects = {e.get("kind") for e in (entry.get("entity") or {}).get("effects") or []}
    if "damage" in effects:
        return "damage"
    if "block" in effects:
        return "block"
    if "heal" in effects:
        return "heal"
    return "other"


def _potion_inventory(state):
    entries = _potion_entries(state)
    if not entries:
        return []
    ranked = sorted(entries, key=lambda item: -item["score"])
    shown = "、".join(f"{item['name']}（{item['score']:.1f}）" for item in ranked)
    if len(entries) >= 3:
        worst = ranked[-1]
        text = (
            f"药水 {len(entries)}/3：{shown}。药水已满，最差的是 {worst['name']}；"
            f"奖励/商店出现更高分药水时优先丢弃它。"
        )
        severity = "warn"
    else:
        text = f"药水 {len(entries)}/3：{shown}；还有空位，优先保留高分的伤害/保命药水。"
        severity = "info"
    return [_advice("potion.inventory", text, severity)]


def _potion_reward(state):
    rewards = _potion_entries(state, reward=True)
    if not rewards:
        return []
    current = _potion_entries(state)
    ranked = sorted(rewards, key=lambda item: -item["score"])
    best = ranked[0]
    advice = []
    if len(current) < 3:
        advice.append(_advice(
            "potion.reward",
            f"药水奖励：推荐拿 {best['name']}（评分 {best['score']:.1f}）；"
            f"当前 {len(current)}/3，还有空位。",
            "good"))
    else:
        worst = min(current, key=lambda item: item["score"])
        if best["score"] >= worst["score"] + 0.2:
            advice.append(_advice(
                "potion.reward",
                f"药水奖励：推荐丢弃 {worst['name']}（评分 {worst['score']:.1f}），"
                f"换成 {best['name']}（评分 {best['score']:.1f}）；药水栏已满。",
                "warn"))
            advice.append(_advice(
                "potion.discard",
                f"丢弃 {worst['name']}，拿 {best['name']}。",
                "warn"))
        else:
            advice.append(_advice(
                "potion.reward",
                f"药水奖励：{best['name']}（评分 {best['score']:.1f}）不如当前最差 "
                f"{worst['name']}（{worst['score']:.1f}），药水栏已满，建议跳过。",
                "info"))
    return advice


def _potion_combat(state, result):
    """Recommend a potion only when it changes this turn's survival/lethal."""
    entries = _potion_entries(state)
    if not entries:
        return []

    hp = int(state.get("Hp") or 0)
    max_hp = max(1, int(state.get("MaxHp") or 1))
    incoming = result.outcome.incoming
    block = result.block_left
    end_damage = result.outcome.end_turn_damage
    base_after = result.outcome.hp_after
    enemy_hp_left = result.outcome.enemy_hp_left
    encounter = str(state.get("Encounter") or "")
    boss_or_elite = "boss" in encounter.lower() or "elite" in encounter.lower()
    severe = (
        base_after <= 0
        or hp <= max(10, int(max_hp * 0.35))
        or result.outcome.hp_loss >= max(10, int(max_hp * 0.25))
        or (boss_or_elite and result.outcome.hp_loss >= max(6, int(max_hp * 0.15)))
    )
    if not severe:
        return []

    candidates = []
    for entry in entries:
        entity = entry.get("entity") or {}
        if "automatic" in str(entity.get("usage") or "").lower():
            continue
        role = _potion_role(entry)
        name = entry["name"]
        key = _potion_key(entry)
        new_after = None
        detail = ""
        if role == "damage":
            all_enemies = "explosive" in key
            damage = 10 if all_enemies else (20 if "fire" in key else 15)
            if enemy_hp_left > 0 and (all_enemies or len(state.get("Enemies") or []) <= 1):
                if damage >= enemy_hp_left:
                    new_after = max(0, hp - end_damage)
                    detail = f"{damage} 点{'全体' if all_enemies else ''}伤害可收尾，预计 HP {new_after}"
        elif role in ("block", "plating"):
            extra = 12 if role == "block" else 7
            new_after = max(0, hp - end_damage - max(0, incoming - block - extra))
            detail = f"+{extra} 格挡，预计 HP {new_after}"
        elif role == "shrink":
            reduced = int(incoming * 0.3)
            new_after = max(0, hp - end_damage - max(0, incoming - block - reduced))
            detail = f"敌人攻击约 -{reduced}，预计 HP {new_after}"
        elif role == "intangible":
            hits = sum(
                int(attack.get("Hits") or 1)
                for enemy in state.get("Enemies") or []
                if int(enemy.get("Hp") or 0) > 0
                for attack in enemy.get("Attacks") or []
            )
            new_after = max(0, hp - end_damage - max(0, min(incoming, hits) - block))
            detail = f"本回合每次伤害上限 1（约 {hits} 段），预计 HP {new_after}"
        elif role == "weaken":
            reduced = int(incoming * 0.25)
            new_after = max(0, hp - end_damage - max(0, incoming - block - reduced))
            detail = f"敌人攻击约 -{reduced}，预计 HP {new_after}"
        elif role == "heal" and hp <= int(max_hp * 0.4):
            new_after = min(max_hp, hp + (12 if "blood" in key else 10))
            detail = f"回复后 HP {new_after}"

        if new_after is None:
            continue
        saved = new_after - base_after
        if base_after > 0 and saved < 3:
            continue
        if saved <= 0 and new_after <= 0:
            continue
        if saved <= 0 and base_after > 0:
            continue
        candidates.append((saved, new_after, name, detail))

    if not candidates:
        return []
    candidates.sort(key=lambda item: (-item[0], -item[1]))
    saved, new_after, name, detail = candidates[0]
    severity = "danger" if base_after <= 0 else "warn"
    return [_advice(
        "potion.use",
        f"本回合建议用 {name}：{detail}；不用药水预计 HP {base_after}。",
        severity,
    )]



def _combat_solver(state):
    result, error = solve(state)
    if result is None or not result.modeled:
        return None, {
            "version": 1,
            "error": error or "没有可精确模拟的牌",
            "modeled": 0,
            "unmodeled": [],
        }

    advice = []
    used_energy = sum(p.cost for p in result.plays)
    outgoing = result.damage_dealt
    block_gain = max(0, result.block_left - int(state.get("Block", 0)))
    loss = result.outcome.hp_loss
    hp_after = result.outcome.hp_after

    if result.plays:
        # One action per line: the advice box is a TextBlock with TextWrapping,
        # so "\n" renders as a line break and long sequences stay readable.
        head = f"最优顺序：{_format_sequence(result)}\n"
        separator = ""
    else:
        head = "本回合不出牌最优"
        separator = "；"

    if hp_after <= 0:
        severity = "danger"
        if result.outcome.lethal:
            tail = "会致死（即使敌方被击杀，也会同归于尽），必须用药水或改打法"
        else:
            tail = "会致死，必须用药水或改打法"
    elif result.outcome.lethal:
        severity = "good"
        tail = "可斩杀"
    elif loss == 0:
        severity = "good"
        tail = "不掉血"
    else:
        severity = "warn"
        tail = f"预计掉 {loss} 血"

    advice.append(_advice(
        "combat.solver",
        f"{head}{separator}{tail}（能量 {used_energy}/{int(state.get('Energy', 0))}，"
        f"有效伤害 {outgoing}，格挡 +{block_gain}）",
        severity))

    detail = (
        f"敌方受击后剩 {result.outcome.enemy_hp_left} HP；"
        f"敌方总攻击 {result.outcome.incoming}，我方格挡 {result.outcome.block_used}，"
        f"结算后 HP {hp_after}/{int(state.get('MaxHp', 0) or 0)}"
    )
    relic_block = max(0, result.outcome.block_used - result.block_left)
    if relic_block:
        detail += f"（含遗物 {relic_block} 格挡）"
    if result.outcome.poison_kills:
        detail += f"；毒将在敌方回合开始击杀 {result.outcome.poison_kills} 个敌人"
    advice.append(_advice("combat.solver_detail", detail, "info"))
    advice.append(_advice(
        "combat.solver_assumptions",
        "求解只含已建模卡牌/遗物/能力；未计其他遗物、药水使用、抽牌、随机目标与特殊修正，实际结果以游戏为准。",
        "info"))

    if result.unmodeled:
        shown = "、".join(f"{name}（{reason}）" for name, reason in result.unmodeled[:6])
        more = "" if len(result.unmodeled) <= 6 else f" 等 {len(result.unmodeled)} 张"
        advice.append(_advice(
            "combat.solver_unmodeled",
            f"未纳入求解：{shown}{more}；以上结果只含已建模牌。",
            "info"))

    if result.partial:
        shown = "、".join(f"{name}（{note}）" for name, note in result.partial[:6])
        advice.append(_advice(
            "combat.solver_partial",
            f"部分建模：{shown}；这些牌的已知效果计入求解，未列效果未计。",
            "warn"))

    potions = [str(item) for item in (state.get("Potions") or [])]
    potion_ids = {str(item).upper() for item in (state.get("PotionIds") or [])}
    if potions:
        is_block_potion = "BLOCK_POTION" in potion_ids or any("格挡" in name or "block" in name.lower() for name in potions)
        kill_advice = _potion_kill_advice(state, result)
        if kill_advice:
            advice.append(_advice("potion.lethal", kill_advice, "danger"))
        elif result.outcome.hp_after <= 0 and is_block_potion:
            if result.outcome.end_turn_unblockable >= int(state.get("Hp", 0)):
                advice.append(_advice(
                    "potion.lethal",
                    "回合结束手牌伤害不可格挡且已致死；格挡药水无效，必须弃掉对应状态牌或改打法。",
                    "danger"))
            else:
                after = min(int(state.get("MaxHp", 0) or 0), result.outcome.hp_after + 12)
                advice.append(_advice(
                    "potion.lethal",
                    f"本回合会致死；先用格挡药水（+12 格挡）预计可活（HP {after}）。",
                    "danger"))
        elif result.outcome.hp_after <= 0:
            advice.append(_advice(
                "potion.lethal",
                "本回合会致死；药水栏有：" + "、".join(potions) + "，考虑先用保命/斩杀药水。",
                "danger"))
        elif result.outcome.hp_loss >= max(1, int(state.get("MaxHp", 1)) // 3):
            advice.append(_advice(
                "potion.consider",
                f"预计掉 {result.outcome.hp_loss} 血；药水：" + "、".join(potions) + "。",
                "warn"))

    advice.extend(_potion_combat(state, result))

    if result.truncated:
        advice.append(_advice(
            "combat.solver_truncated",
            "搜索达到时间/节点上限，序列是当前最优近似。",
            "warn"))

    payload = {
        "version": 1,
        "sequence": _sequence_parts(result),
        "hpLoss": loss,
        "hpAfter": hp_after,
        "incoming": result.outcome.incoming,
        "block": result.block_left,
        "energyLeft": max(0, int(state.get("Energy", 0)) - used_energy),
        "enemyHpLeft": result.outcome.enemy_hp_left,
        "damageDealt": outgoing,
        "poisonKills": result.outcome.poison_kills,
        "lethal": result.outcome.lethal,
        "truncated": result.truncated,
        "modeled": len(result.modeled),
        "unmodeled": [name for name, _ in result.unmodeled],
        "partial": [name for name, _ in result.partial],
    }
    return advice, payload


def _combat_rough(state):
    advice = []
    enemies = state.get("Enemies") or []
    hand = state.get("Hand") or []
    incoming = sum(int(e.get("Damage", 0)) for e in enemies)
    block = int(state.get("Block", 0))
    loss = max(0, incoming - block)
    enemy_hp = sum(int(e.get("Hp", 0)) + int(e.get("Block", 0)) for e in enemies)
    energy = int(state.get("Energy", 0))

    attacks = [c for c in hand if c.get("Type") == 1 and c.get("Damage", 0) > 0 and not c.get("CostsX") and c.get("Cost", 0) <= energy]
    blocks = [c for c in hand if c.get("Block", 0) > 0 and not c.get("CostsX") and c.get("Cost", 0) <= energy]

    max_damage, lethal_cards = _knapsack(attacks, energy, lambda c: c.get("Damage", 0) * max(1, c.get("Hits", 1)))
    max_block, block_cards = _knapsack(blocks, energy, lambda c: c.get("Block", 0))
    can_lethal = enemy_hp > 0 and max_damage >= enemy_hp

    if incoming <= 0:
        if can_lethal:
            advice.append(_advice("combat.lethal_available", f"可斩杀（粗算 {max_damage} ≥ 敌方 {enemy_hp}）：{_names(lethal_cards)}", "good"))
        else:
            advice.append(_advice("combat.no_attack", "敌方本回合没有攻击意图，可以全力输出。", "good"))
    elif can_lethal:
        advice.append(_advice("combat.lethal_available", f"可斩杀（粗算 {max_damage} ≥ 敌方 {enemy_hp}）：{_names(lethal_cards)}", "good"))
        advice.append(_advice("combat.incoming", f"不斩杀的话预计掉 {loss} 血（受 {incoming} / 挡 {block}）。", "warn"))
    elif loss <= 0:
        advice.append(_advice("combat.blocked", f"格挡足够：受 {incoming} / 挡 {block}，本回合不掉血。", "good"))
    elif block + max_block >= incoming:
        advice.append(_advice("combat.full_block", f"可以全挡：{block} + {max_block} ≥ {incoming}，推荐 {_names(block_cards)}。", "good"))
    elif loss >= int(state.get("Hp", 0)):
        advice.append(_advice("combat.lethal_incoming", f"致死风险：最多再挡 {max_block}，仍会掉 {loss - max_block}（HP {state.get('Hp')}）。", "danger"))
    else:
        advice.append(_advice("combat.incoming", f"预计掉 {loss} 血；最优格挡可挡 {max_block}，剩 {max(0, loss - max_block)}。", "warn"))

    if loss > 0 and not can_lethal and block + max_block < incoming and max_block > 0:
        advice.append(_advice("combat.block_plan", f"优先格挡：{_names(block_cards)}（共 {max_block} 挡）。", "warn"))

    advice.append(_advice("resources.hand", f"手牌 {len(hand)} 张，能量 {energy}/{state.get('MaxEnergy', 0)}。", "info"))
    if energy > 0 and not any(c.get("Playable") for c in hand):
        advice.append(_advice("resources.waste", f"能量 {energy} 点用不出去。", "warn"))
    elif energy == 0:
        free = [c for c in hand if c.get("Playable") and c.get("Cost", 0) == 0]
        if free:
            advice.append(_advice("resources.free_cards", "能量已空，但还有 0 费牌可打：" + _names(free), "good"))
    return advice


def _enemy_power(enemy: dict, *names: str) -> int:
    powers = enemy.get("Powers") or {}
    for name in names:
        raw = powers.get(name)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return 0


def _eruption_warnings(state):
    """SteamEruptionPower: the kill is not the end of the fight."""
    out = []
    hp = int(state.get("Hp") or 0)
    for enemy in state.get("Enemies") or []:
        amount = _enemy_power(enemy, "SteamEruptionPower", "SteamEruption")
        if amount <= 0:
            continue
        name = enemy.get("Name") or "敌人"
        fatal = amount >= hp
        text = (
            f"{name} 击杀后不会死亡：改为进入蒸汽喷发倒计时，下一回合爆炸"
            f"（当前 {amount} 点，可格挡，受虚弱/易伤修正）。"
        )
        if fatal:
            text += f"当前 HP {hp} ≤ 爆炸伤害：击杀会致死，本回合优先格挡/抬血，或这回合不要击杀。"
        else:
            text += "击杀前留够格挡或先抬血。"
        out.append(_advice("combat.eruption", text, "danger" if fatal else "warn"))
    return out


def _combat(state):
    solved, solver = _combat_solver(state)
    rough = _combat_rough(state)
    eruption = _eruption_warnings(state)
    if solved is not None:
        extras = [
            item for item in rough
            if item["ruleId"].startswith("resources.") or item["ruleId"].startswith("potion.")
        ]
        return solved[:1] + eruption + solved[1:] + extras, solver

    error = (solver or {}).get("error")
    advice = []
    if error and error != "手牌为空":
        advice.append(_advice("combat.solver_unavailable", f"未使用求解器：{error}", "info"))
    return advice + eruption + rough, solver


def _overview(state):
    return [_advice("run.overview", f"金币 {state.get('Gold', 0)} · 牌组 {state.get('DeckCount', 0)} 张 · 遗物 {len(state.get('Relics') or [])} 件", "info")]


def advise(state: dict) -> dict:
    if state.get("ValidationError"):
        return {"advice": [_advice("state.invalid", "状态校验失败：" + str(state["ValidationError"]), "danger")], "source": "python"}

    solver = None
    if state.get("CardChoices") or state.get("RewardPotions") or state.get("RewardPotionIds"):
        advice = _reward(state)
    elif state.get("InShop"):
        advice = _shop(state)
    elif state.get("InRestSite"):
        advice = _rest(state)
    elif state.get("InTreasure"):
        advice = _treasure(state)
    elif state.get("InEvent"):
        advice = _event(state)
    elif state.get("InCombat"):
        advice, solver = _combat(state)
    elif state.get("MapChoices"):
        advice = _map(state)
    else:
        advice = _overview(state)

    if not state.get("InCombat") and state.get("Potions"):
        advice.extend(_potion_inventory(state))

    response = {"advice": advice, "source": "python"}
    if solver is not None:
        response["solver"] = solver
    return response

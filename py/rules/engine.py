"""Local rule engine for StS2 Copilot.

Input: the GameState JSON produced by the C# reader (PascalCase keys).
Output: {"advice": [{"ruleId", "text", "severity"}], "source": "python"}
"""

from __future__ import annotations

from combat import solve

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
    return "、".join(c.get("Name", "?") for c in cards) or "（无）"


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
    return score


def _reward(state):
    choices = state.get("CardChoices") or []
    ranked = sorted(((score_card(state, c), c) for c in choices), key=lambda x: -x[0])
    if not ranked:
        return []

    advice = [_advice("reward.recommend", f"推荐：{ranked[0][1].get('Name', '?')}（评分 {ranked[0][0]:.1f}）", "good")]
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
        lines.append(f"{card.get('Name', '?')}（{cost}费）{suffix}  评分 {score:.1f}")

    advice.append(_advice("reward.card_choice", "三选一：\n" + "\n".join(lines), "good"))
    if len(ranked) >= 2 and ranked[0][0] - ranked[1][0] < 0.5:
        advice.append(_advice("reward.close_call", "前两名差距很小，按流派偏好选即可。", "info"))
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


def _map_dp(state):
    """Full DAG DP from the current node to the boss.

    State = (node, hp); value = node rewards + child value - low-hp risk.
    Returns None when the full graph is unavailable.
    """
    nodes_list = state.get("MapNodes") or []
    edges = state.get("MapEdges") or []
    if len(nodes_list) < 3 or not edges:
        return None

    nodes = {(n.get("Col"), n.get("Row")): n for n in nodes_list}
    start = (state.get("MapCol"), state.get("MapRow"))
    boss = next((k for k, n in nodes.items() if n.get("Type") == 7), None)
    if start not in nodes or boss is None:
        return None

    adjacency = {}
    for edge in edges:
        a = (edge.get("FromCol"), edge.get("FromRow"))
        b = (edge.get("ToCol"), edge.get("ToRow"))
        adjacency.setdefault(a, []).append(b)

    max_hp = max(1, int(state.get("MaxHp", 1)))
    start_hp = max(1, int(state.get("Hp", 1)))
    memo = {}

    def solve(node, hp):
        key = (node, hp)
        if key in memo:
            return memo[key]

        info = nodes.get(node)
        if info is None:
            return (-1e9, (), hp)
        if info.get("Type") == 7:
            return (0.0, (node,), hp)

        loss = _node_loss(state, info)
        heal = int(max_hp * 0.3) if info.get("Type") == 4 else 0
        hp_after = min(max_hp, hp - loss + heal)
        if hp_after <= 0:
            return (-1e9, (), hp_after)

        value = _node_reward(state, info) + _risk_penalty(hp_after, max_hp)
        children = adjacency.get(node, [])
        if not children:
            result = (value, (node,), hp_after)
            memo[key] = result
            return result

        best_total = -1e9
        best_path = ()
        best_hp = hp_after
        for child in children:
            child_value, child_path, child_hp = solve(child, hp_after)
            total = value + child_value
            if total > best_total:
                best_total = total
                best_path = child_path
                best_hp = child_hp

        result = (best_total, (node,) + best_path, best_hp)
        memo[key] = result
        return result

    ranked = []
    for child in adjacency.get(start, []):
        value, path, hp_after = solve(child, start_hp)
        ranked.append((value, child, path, hp_after))

    if not ranked:
        return None

    ranked.sort(key=lambda item: -item[0])

    def fmt_path(path):
        return " → ".join(
            f"{TYPE_NAMES.get(nodes[k].get('Type', 0), '?')}({k[0]},{k[1]})"
            for k in path
        )

    advice = []
    best_value, best_child, best_path, best_hp = ranked[0]
    advice.append(_advice(
        "map.recommend",
        f"推荐路线：{fmt_path(best_path)}；预计结束 HP {best_hp}，评分 {best_value:.1f}",
        "good"))

    lines = []
    for value, child, path, hp_after in ranked:
        preview = fmt_path(path[:4])
        lines.append(f"{TYPE_NAMES.get(nodes[child].get('Type', 0), '?')}（{child[0]},{child[1]}）  评分 {value:.1f}  HP→{hp_after}  {preview}")
    advice.append(_advice("map.route", "第一层：\n" + "\n".join(lines), "info"))
    return advice


def _map(state):
    full = _map_dp(state)
    if full is not None:
        return full

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
    labels = []
    for name in names:
        counts[name] = counts.get(name, 0) + 1
        labels.append(name if counts[name] == 1 else f"{name}#{counts[name]}")
    return labels


def _format_sequence(result):
    labels = _enemy_labels(result.enemy_names)
    cards = {card.index: card.name for card in result.modeled}
    parts = []
    for play in result.plays:
        text = play.name
        if play.target_all:
            text += "→全体"
        elif play.target_index is not None and play.target_index < len(labels):
            text += f"→{labels[play.target_index]}"
        if play.discard_index is not None:
            text += f"（弃{cards.get(play.discard_index, '?')}）"
        parts.append(text)
    return " → ".join(parts)


def _combat_solver(state):
    result, error = solve(state)
    if result is None or not result.modeled:
        return None, error or "没有可精确模拟的牌"

    advice = []
    used_energy = sum(p.cost for p in result.plays)
    outgoing = result.damage_dealt
    block_gain = max(0, result.block_left - int(state.get("Block", 0)))
    loss = result.outcome.hp_loss
    hp_after = result.outcome.hp_after

    if result.plays:
        head = f"最优顺序：{_format_sequence(result)}"
    else:
        head = "本回合不出牌最优"

    if result.outcome.lethal:
        severity = "good"
        tail = "可斩杀"
    elif hp_after <= 0:
        severity = "danger"
        tail = "会致死，必须用药水或改打法"
    elif loss == 0:
        severity = "good"
        tail = "不掉血"
    else:
        severity = "warn"
        tail = f"预计掉 {loss} 血"

    advice.append(_advice(
        "combat.solver",
        f"{head}；{tail}（能量 {used_energy}/{int(state.get('Energy', 0))}，"
        f"有效伤害 {outgoing}，格挡 +{block_gain}）",
        severity))

    detail = (
        f"敌方受击后剩 {result.outcome.enemy_hp_left} HP；"
        f"敌方总攻击 {result.outcome.incoming}，我方格挡 {result.block_left}，"
        f"结算后 HP {hp_after}/{int(state.get('MaxHp', 0) or 0)}"
    )
    if result.outcome.poison_kills:
        detail += f"；毒将在敌方回合开始击杀 {result.outcome.poison_kills} 个敌人"
    advice.append(_advice("combat.solver_detail", detail, "info"))
    advice.append(_advice(
        "combat.solver_assumptions",
        "求解只含已建模卡牌；未计遗物、药水、抽牌、随机目标与特殊能力修正，实际结果以游戏为准。",
        "info"))

    if result.unmodeled:
        shown = "、".join(f"{name}（{reason}）" for name, reason in result.unmodeled[:6])
        more = "" if len(result.unmodeled) <= 6 else f" 等 {len(result.unmodeled)} 张"
        advice.append(_advice(
            "combat.solver_unmodeled",
            f"未纳入求解：{shown}{more}；以上结果只含已建模牌。",
            "info"))

    if result.truncated:
        advice.append(_advice(
            "combat.solver_truncated",
            "搜索达到时间/节点上限，序列是当前最优近似。",
            "warn"))

    return advice, None


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


def _combat(state):
    solved, error = _combat_solver(state)
    rough = _combat_rough(state)
    if solved is not None:
        extras = [
            item for item in rough
            if item["ruleId"].startswith("resources.") or item["ruleId"].startswith("potion.")
        ]
        return solved + extras

    advice = []
    if error and error != "手牌为空":
        advice.append(_advice("combat.solver_unavailable", f"未使用求解器：{error}", "info"))
    return advice + rough


def _overview(state):
    return [_advice("run.overview", f"金币 {state.get('Gold', 0)} · 牌组 {state.get('DeckCount', 0)} 张 · 遗物 {len(state.get('Relics') or [])} 件", "info")]


def advise(state: dict) -> dict:
    if state.get("ValidationError"):
        return {"advice": [_advice("state.invalid", "状态校验失败：" + str(state["ValidationError"]), "danger")], "source": "python"}

    if state.get("CardChoices"):
        advice = _reward(state)
    elif state.get("MapChoices"):
        advice = _map(state)
    elif state.get("InCombat"):
        advice = _combat(state)
    else:
        advice = _overview(state)

    return {"advice": advice, "source": "python"}

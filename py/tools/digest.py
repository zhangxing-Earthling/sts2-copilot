# -*- coding: utf-8 -*-
"""Build a run digest from a StS2 Copilot JSONL log.

The digest helps DSH locate high-error turns when optimizing rules: metrics,
top-K decisions and stable event ids. It is fully offline and never calls an
LLM.

Usage:
    python py\\tools\\digest.py --last 1
    python py\\tools\\digest.py path\\to\\run.jsonl --json
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
from collections import Counter
from typing import Iterable, Iterator

RULES_VERSION = "0.1"
SCHEMA_VERSION = 2
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_ROOT = os.environ.get("STS2_COPILOT_LOG_DIR") or os.path.join(REPO_ROOT, "logs")
RULES_NOTES = [
    "攻击伤害 = 向下取整((卡牌 Damage + 力量) × 虚弱0.75 × Shrink0.7 × 易伤1.5)",
    "格挡 = 向下取整((卡牌 Block + 敏捷) × 脆弱0.75)",
    "敌人攻击 = 向下取整((BaseDamage + 力量) × 敌人虚弱0.75 × 玩家易伤1.5)，多段分别计算",
    "ShrinkPower != 0 时玩家攻击伤害 ×0.7；虚弱 ×0.75；易伤 ×1.5；脆弱 ×0.75",
    "毒在敌人行动前结算；求解器不模拟抽牌，未建模牌见 solver.unmodeled",
]


def _get(mapping, *keys, default=None):
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _state(event: dict) -> dict:
    return _get(event, "state", "State") or {}


def _payload(event: dict) -> dict:
    return _get(event, "payload", "Payload") or {}


def _solver(event: dict) -> dict | None:
    solver = _get(event, "solver", "Solver")
    return solver if isinstance(solver, dict) else None


def _advice(event: dict) -> list[dict]:
    advice = _get(event, "advice", "Advice") or []
    return [item for item in advice if isinstance(item, dict)]


def _advice_text(event: dict, prefer: str | None = None) -> str:
    items = _advice(event)
    if prefer:
        for item in items:
            if _get(item, "RuleId", "ruleId") == prefer:
                return str(_get(item, "Text", "text") or "")
    return str(_get(items[0], "Text", "text") or "") if items else ""


def _event_id(event: dict, index: int) -> str:
    seq = _as_int(_get(event, "seq", "Seq"), index)
    return f"evt_{seq:04d}"


def _card_name(card) -> str:
    if isinstance(card, dict):
        return str(_get(card, "Name", "name", "Id", "id") or "?")
    return str(card or "?")


def _hand_names(state: dict) -> str:
    cards = [_card_name(c) for c in _get(state, "Hand", "hand") or []]
    return "、".join(cards) if cards else "（无）"


def _enemy_summary(state: dict) -> str:
    parts = []
    for enemy in _get(state, "Enemies", "enemies") or []:
        if not isinstance(enemy, dict):
            continue
        parts.append(
            "%s %s/%s"
            % (
                _card_name(enemy),
                _as_int(_get(enemy, "Hp", "hp")),
                _as_int(_get(enemy, "MaxHp", "maxHp")),
            )
        )
    return "、".join(parts) if parts else "（无）"


def _powers_summary(state: dict) -> str:
    powers = _get(state, "PlayerPowers", "playerPowers") or {}
    if not isinstance(powers, dict) or not powers:
        return ""
    return "；玩家能力：" + "、".join("%s=%s" % (key, value) for key, value in powers.items())


def _card_detail(card) -> dict:
    if not isinstance(card, dict):
        return {"name": str(card or "?")}
    detail = {
        "name": _card_name(card),
        "cost": _as_int(_get(card, "Cost", "cost")),
        "damage": _as_int(_get(card, "Damage", "damage")),
        "block": _as_int(_get(card, "Block", "block")),
        "hits": _as_int(_get(card, "Hits", "hits"), 1),
    }
    poison = _as_int(_get(card, "Poison", "poison"))
    if poison:
        detail["poison"] = poison
    variables = _get(card, "Vars", "vars")
    if isinstance(variables, dict) and variables:
        detail["vars"] = variables
    return detail


def _enemy_detail(enemy) -> dict:
    if not isinstance(enemy, dict):
        return {"name": str(enemy or "?")}
    detail = {
        "name": _card_name(enemy),
        "hp": _as_int(_get(enemy, "Hp", "hp")),
        "max_hp": _as_int(_get(enemy, "MaxHp", "maxHp")),
        "block": _as_int(_get(enemy, "Block", "block")),
    }
    powers = _get(enemy, "Powers", "powers")
    if isinstance(powers, dict) and powers:
        detail["powers"] = powers
    attacks = _get(enemy, "Attacks", "attacks")
    if isinstance(attacks, list) and attacks:
        detail["attacks"] = [
            {
                "base_damage": _as_int(_get(attack, "BaseDamage", "baseDamage")),
                "hits": max(1, _as_int(_get(attack, "Hits", "hits"), 1)),
            }
            for attack in attacks
            if isinstance(attack, dict)
        ]
    return detail


def _solver_detail(solver: dict) -> dict:
    detail = {
        "sequence": list(_get(solver, "sequence", "Sequence") or []),
        "hp_loss": _as_int(_get(solver, "hpLoss", "HpLoss")),
        "hp_after": _as_int(_get(solver, "hpAfter", "HpAfter")),
        "incoming": _as_int(_get(solver, "incoming", "Incoming")),
        "block": _as_int(_get(solver, "block", "Block")),
        "lethal": bool(_get(solver, "lethal", "Lethal")),
        "unmodeled": list(_get(solver, "unmodeled", "Unmodeled") or []),
    }
    truncated = _get(solver, "truncated", "Truncated")
    if truncated:
        detail["truncated"] = True
    return detail


def _decision_notes(outcome: dict) -> list[str]:
    solver = outcome["solver"]
    notes = []
    unmodeled = [str(x) for x in (_get(solver, "unmodeled", "Unmodeled") or [])]
    if unmodeled:
        notes.append(
            "求解器未建模：%s；抽牌/随机效果可能改变结果，偏差不能单独归因于排序。"
            % "、".join(unmodeled)
        )

    plays = outcome.get("plays") or []
    played_unmodeled = [play["name"] for play in plays if play.get("name") in unmodeled]
    if played_unmodeled:
        notes.append(
            "实际打出了未建模牌：%s；求解器无法预知这些牌，不能用实际结果反推排序错误。"
            % "、".join(dict.fromkeys(played_unmodeled))
        )

    energy_spent = sum(_as_int(play.get("energy")) for play in plays)
    start_energy = _as_int(_get(outcome["state"], "Energy", "energy"))
    if energy_spent > start_energy + 1:
        notes.append(
            "实际记录的能量消耗 %d 超过回合开始能量 %d，日志可能含旧构建重复事件，actual_plays 仅作参考。"
            % (energy_spent, start_energy)
        )

    error = outcome.get("error")
    if error:
        notes.append(
            "预测偏差 %+d；先检查未建模牌、遗物和抽牌，再判断决策好坏。"
            % error
        )
    return notes


def _iteration(events: Iterable[dict]) -> Iterator[tuple[int, dict]]:
    for index, event in enumerate(events, 1):
        if isinstance(event, dict):
            yield index, event


def _turn_outcomes(events: list[dict]) -> list[dict]:
    """Pair each turn prediction with the next turn/combat_end HP."""
    outcomes: list[dict] = []
    pending: dict | None = None

    for index, event in _iteration(events):
        kind = _get(event, "type", "Type")
        if kind == "turn":
            state = _state(event)
            if pending is not None:
                same_encounter = (
                    not pending["encounter"]
                    or not _get(state, "Encounter", "encounter")
                    or pending["encounter"] == _get(state, "Encounter", "encounter")
                )
                pending["actual_hp"] = _as_int(_get(state, "Hp", "hp"))
                pending["next_turn"] = same_encounter
                pending["error"] = pending["actual_hp"] - pending["predicted_hp"]
                outcomes.append(pending)
                pending = None

            solver = _solver(event)
            if not solver or _get(solver, "hpAfter", "HpAfter") is None:
                continue
            pending = {
                "event_id": _event_id(event, index),
                "seq": _as_int(_get(event, "seq", "Seq"), index),
                "event": event,
                "state": state,
                "solver": solver,
                "turn": _as_int(_get(state, "Turn", "turn")),
                "floor": _as_int(_get(state, "Floor", "floor")),
                "act": _as_int(_get(state, "Act", "act"), 1),
                "state_hp": _as_int(_get(state, "Hp", "hp")),
                "predicted_hp": _as_int(_get(solver, "hpAfter", "HpAfter")),
                "encounter": str(_get(state, "Encounter", "encounter") or ""),
                "actual_hp": None,
                "next_turn": False,
                "error": None,
                "plays": [],
            }
        elif kind == "card_play" and pending is not None:
            payload = _payload(event)
            pending["plays"].append(
                {
                    "name": _card_name(payload),
                    "target": _get(payload, "Target", "target"),
                    "energy": _as_int(_get(payload, "EnergySpent", "energySpent")),
                    "auto": bool(_get(payload, "AutoPlay", "autoPlay")),
                    "play_index": _as_int(_get(payload, "PlayIndex", "playIndex")),
                }
            )
        elif kind == "potion_use" and pending is not None:
            payload = _payload(event)
            pending["plays"].append(
                {
                    "name": "药水:" + _card_name(payload),
                    "target": _get(payload, "Target", "target"),
                    "energy": 0,
                    "auto": False,
                    "play_index": 0,
                }
            )
        elif kind == "combat_end" and pending is not None:
            pending["actual_hp"] = _as_int(_get(_payload(event), "Hp", "hp"))
            pending["next_turn"] = False
            pending["error"] = pending["actual_hp"] - pending["predicted_hp"]
            outcomes.append(pending)
            pending = None
        elif kind in ("combat_start", "run_end", "seed_changed"):
            pending = None

    return outcomes


def _hp_loss_by_act(events: list[dict]) -> list[int]:
    observations: list[tuple[int, int]] = []
    last_act = 0
    for _, event in _iteration(events):
        kind = _get(event, "type", "Type")
        if kind == "run_start":
            state = _payload(event)
        elif kind in ("turn", "combat_end"):
            state = _state(event) if kind == "turn" else _payload(event)
        else:
            continue
        act = _as_int(_get(state, "Act", "act"), last_act)
        hp = _get(state, "Hp", "hp")
        if act and hp is not None:
            last_act = act
            observations.append((act, _as_int(hp)))

    if not observations:
        return []

    losses: dict[int, int] = {}
    prev_act, prev_hp = observations[0]
    for act, hp in observations[1:]:
        if act == prev_act and hp < prev_hp:
            losses[act] = losses.get(act, 0) + (prev_hp - hp)
        prev_act, prev_hp = act, hp

    max_act = max(losses) if losses else observations[-1][0]
    return [int(losses.get(act, 0)) for act in range(1, max_act + 1)]


def _run_summary(events: list[dict], path: str) -> dict:
    run: dict = {
        "seed": "",
        "character": "",
        "ascension": 0,
        "act_start": 1,
        "floor_start": 0,
        "floor_reached": 0,
        "result": "unknown",
        "killed_by": None,
        "end_reason": None,
        "game_version": "",
        "log": os.path.basename(path) if path else "",
    }
    last_encounter = ""
    last_hp = None

    for _, event in _iteration(events):
        kind = _get(event, "type", "Type")
        if kind == "run_start":
            state = _payload(event)
            run.update(
                seed=str(_get(state, "Seed", "seed") or ""),
                character=str(_get(state, "Character", "character") or ""),
                ascension=_as_int(_get(state, "Ascension", "ascension")),
                act_start=_as_int(_get(state, "Act", "act"), 1),
                floor_start=_as_int(_get(state, "Floor", "floor")),
                game_version=str(_get(state, "GameVersion", "gameVersion") or ""),
            )
            last_hp = _as_int(_get(state, "Hp", "hp"))
            run["floor_reached"] = max(run["floor_reached"], run["floor_start"])
        elif kind == "turn":
            state = _state(event)
            run["floor_reached"] = max(run["floor_reached"], _as_int(_get(state, "Floor", "floor")))
            last_hp = _as_int(_get(state, "Hp", "hp"), last_hp or 0)
            last_encounter = str(_get(state, "Encounter", "encounter") or last_encounter)
        elif kind == "combat_start":
            payload = _payload(event)
            run["floor_reached"] = max(run["floor_reached"], _as_int(_get(payload, "Floor", "floor")))
            last_encounter = str(_get(payload, "Encounter", "encounter") or last_encounter)
            last_hp = _as_int(_get(payload, "Hp", "hp"), last_hp or 0)
        elif kind == "combat_end":
            payload = _payload(event)
            last_hp = _as_int(_get(payload, "Hp", "hp"), last_hp or 0)
            if last_hp <= 0:
                run["result"] = "loss"
                run["killed_by"] = last_encounter or None
        elif kind in ("map_pick", "reward_pick"):
            run["floor_reached"] = max(run["floor_reached"], _as_int(_get(event, "floor", "Floor")))
        elif kind == "run_end":
            run["end_reason"] = str(_get(_payload(event), "reason", "Reason") or "")

    if run["result"] == "unknown":
        reason = (run["end_reason"] or "").lower()
        if "abandon" in reason or "give_up" in reason:
            run["result"] = "abandon"
    return run


def _metrics(events: list[dict], outcomes: list[dict]) -> dict:
    kinds = Counter(_get(event, "type", "Type") for _, event in _iteration(events))
    errors = [o["error"] for o in outcomes if o["error"] is not None]
    mae = sum(abs(e) for e in errors) / len(errors) if errors else 0.0
    within_one = sum(1 for e in errors if abs(e) <= 1) / len(errors) if errors else 0.0
    lethal_false = sum(
        1
        for o in outcomes
        if o["next_turn"] and _get(o["solver"], "lethal", "Lethal")
    )
    unmodeled = Counter()
    for o in outcomes:
        for name in _get(o["solver"], "unmodeled", "Unmodeled") or []:
            unmodeled[str(name)] += 1

    last_turn_state = {}
    for _, event in _iteration(events):
        if _get(event, "type", "Type") == "turn":
            last_turn_state = _state(event)

    return {
        "turns": kinds.get("turn", 0),
        "combats": kinds.get("combat_start", 0),
        "turns_evaluated": len(outcomes),
        "low_sample": kinds.get("combat_start", 0) < 5 or kinds.get("turn", 0) < 10,
        "mae": round(mae, 2),
        "within_one": round(within_one, 3),
        "lethal_false": lethal_false,
        "card_plays": kinds.get("card_play", 0),
        "potion_uses": kinds.get("potion_use", 0),
        "reward_picks": sum(
            1
            for _, event in _iteration(events)
            if _get(event, "type", "Type") == "reward_pick"
            and not _get(event, "skipped", "Skipped")
        ),
        "reward_skips": sum(
            1
            for _, event in _iteration(events)
            if _get(event, "type", "Type") == "reward_pick"
            and _get(event, "skipped", "Skipped")
        ),
        "map_picks": kinds.get("map_pick", 0),
        "deck_size": _as_int(_get(last_turn_state, "DeckCount", "deckCount")),
        "hp_loss_by_act": _hp_loss_by_act(events),
        "unmodeled": dict(unmodeled.most_common(12)),
    }


def _combat_decisions(outcomes: list[dict], limit: int = 6) -> list[dict]:
    ranked = sorted(
        outcomes,
        key=lambda o: (abs(o["error"]) if o["error"] is not None else 0, o["seq"]),
        reverse=True,
    )
    decisions = []
    for outcome in ranked:
        solver = outcome["solver"]
        predicted = outcome["predicted_hp"]
        actual = outcome["actual_hp"]
        if actual is None:
            continue
        state = outcome["state"]
        predictions = _get(solver, "sequence", "Sequence") or []
        decisions.append(
            {
                "event_id": outcome["event_id"],
                "floor": outcome["floor"],
                "kind": "combat",
                "state_summary": "第%d回合 HP %d/%d 能量 %d，手牌：%s；敌人：%s%s"
                % (
                    outcome["turn"],
                    outcome["state_hp"],
                    _as_int(_get(state, "MaxHp", "maxHp")),
                    _as_int(_get(state, "Energy", "energy")),
                    _hand_names(state),
                    _enemy_summary(state),
                    _powers_summary(state),
                ),
                "player_powers": _get(state, "PlayerPowers", "playerPowers") or {},
                "hand": [_card_detail(card) for card in _get(state, "Hand", "hand") or []],
                "enemies": [_enemy_detail(enemy) for enemy in _get(state, "Enemies", "enemies") or []],
                "solver": _solver_detail(solver),
                "solver_verdict": "模拟：预计掉血 %d，HP %d，incoming %d，block %d，lethal=%s"
                % (
                    _as_int(_get(solver, "hpLoss", "HpLoss")),
                    predicted,
                    _as_int(_get(solver, "incoming", "Incoming")),
                    _as_int(_get(solver, "block", "Block")),
                    bool(_get(solver, "lethal", "Lethal")),
                ),
                "notes": _decision_notes(outcome),
                "actual_plays": outcome.get("plays") or [],
                "chosen": " → ".join(str(x) for x in predictions) or "（不出牌）",
                "advice": _advice_text(outcome["event"], "combat.solver")[:300],
                "outcome": "预测 HP %d / 实际 %d（偏差 %+d），预测掉血 %d / 实际掉血 %d"
                % (
                    predicted,
                    actual,
                    outcome["error"] or 0,
                    _as_int(_get(solver, "hpLoss", "HpLoss"), outcome["state_hp"] - predicted),
                    outcome["state_hp"] - actual,
                ),
                "loss_hp": outcome["state_hp"] - actual,
                "error": outcome["error"] or 0,
            }
        )
        if len(decisions) >= limit:
            break
    return decisions


def _reward_decisions(events: list[dict], limit: int = 3) -> list[dict]:
    advice_by_floor: dict[int, str] = {}
    decisions = []
    for index, event in _iteration(events):
        kind = _get(event, "type", "Type")
        if kind == "reward":
            floor = _as_int(_get(event, "floor", "Floor"))
            advice_by_floor[floor] = _advice_text(event, "reward.recommend") or _advice_text(event)
        elif kind == "reward_pick":
            options = [_card_name(c) for c in _get(event, "options", "Options") or []]
            picked = [_card_name(c) for c in _get(event, "picked", "Picked") or []]
            skipped = bool(_get(event, "skipped", "Skipped"))
            floor = _as_int(_get(event, "floor", "Floor"))
            decisions.append(
                {
                    "event_id": _event_id(event, index),
                    "floor": floor,
                    "kind": "reward",
                    "state_summary": "三选一：%s" % "、".join(options),
                    "chosen": "跳过" if skipped else "、".join(picked),
                    "advice": advice_by_floor.get(floor, ""),
                    "outcome": "跳过" if skipped else "加入牌组：%s" % "、".join(picked),
                    "loss_hp": None,
                }
            )
    return decisions[-limit:]


def _map_node(node: dict) -> str:
    return str(_get(node, "type", "Type", "TypeName", "typeName") or "?")


def _map_decisions(events: list[dict], limit: int = 3) -> list[dict]:
    decisions = []
    for index, event in _iteration(events):
        if _get(event, "type", "Type") != "map_pick":
            continue
        before = _get(event, "from", "From") or {}
        after = _get(event, "to", "To") or {}
        decisions.append(
            {
                "event_id": _event_id(event, index),
                "floor": _as_int(_get(event, "floor", "Floor")),
                "kind": "map",
                "state_summary": "地图移动：%s → %s"
                % (
                    "%s(%s,%s)" % (_map_node(before), _get(before, "col"), _get(before, "row")),
                    "%s(%s,%s)" % (_map_node(after), _get(after, "col"), _get(after, "row")),
                ),
                "chosen": "%s(%s,%s)" % (_map_node(after), _get(after, "col"), _get(after, "row")),
                "advice": "",
                "outcome": "到达第 %d 层" % _as_int(_get(event, "floor", "Floor")),
                "loss_hp": None,
            }
        )
    return decisions[-limit:]


def _potion_decisions(events: list[dict], limit: int = 2) -> list[dict]:
    decisions = []
    for index, event in _iteration(events):
        if _get(event, "type", "Type") != "potion_use":
            continue
        payload = _payload(event)
        decisions.append(
            {
                "event_id": _event_id(event, index),
                "floor": _as_int(_get(event, "floor", "Floor")),
                "kind": "potion",
                "state_summary": "使用药水",
                "chosen": "%s → %s" % (_card_name(payload), _get(payload, "Target", "target") or "无目标"),
                "advice": "",
                "outcome": "",
                "loss_hp": None,
            }
        )
    return decisions[-limit:]


def build_digest(events: list[dict], path: str = "") -> dict:
    outcomes = _turn_outcomes(events)
    run = _run_summary(events, path)
    metrics = _metrics(events, outcomes)
    decisions = (
        _combat_decisions(outcomes)
        + _reward_decisions(events)
        + _map_decisions(events)
        + _potion_decisions(events)
    )
    # A decision id must be stable and unique.
    seen: set[str] = set()
    unique = []
    for decision in decisions:
        if decision["event_id"] in seen:
            continue
        seen.add(decision["event_id"])
        unique.append(decision)
    return {
        "schema": SCHEMA_VERSION,
        "rules_version": RULES_VERSION,
        "rules_notes": RULES_NOTES,
        "run": run,
        "metrics": metrics,
        "decisions": unique[:12],
    }


def iter_events(path: str) -> Iterator[dict]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event


def load_events(path: str) -> list[dict]:
    return list(iter_events(path))


def find_logs(runs_dir: str, last: int | None = None) -> list[str]:
    paths = glob.glob(os.path.join(runs_dir, "*.jsonl"))
    paths.sort(key=os.path.getmtime, reverse=True)
    return paths[:last] if last is not None else paths


def default_runs_dir() -> str:
    return os.path.join(LOG_ROOT, "runs")


def render_markdown(digest: dict) -> str:
    run = digest.get("run") or {}
    metrics = digest.get("metrics") or {}
    lines = [
        "# 局末复盘输入",
        "",
        "种子 %s · %s · 难度 %s · 第 %s 层 · 结果 %s"
        % (
            run.get("seed", "?"),
            run.get("character", "?"),
            run.get("ascension", "?"),
            run.get("floor_reached", "?"),
            run.get("result", "?"),
        ),
        "",
        "## 指标",
        "",
        "- 回合 %s / 战斗 %s / 可评估 %s"
        % (metrics.get("turns"), metrics.get("combats"), metrics.get("turns_evaluated")),
        "- MAE %s，误差 ≤1 %s，斩杀误报 %s"
        % (metrics.get("mae"), metrics.get("within_one"), metrics.get("lethal_false")),
        "- 出牌 %s，药水 %s，选牌 %s，跳过 %s，地图 %s"
        % (
            metrics.get("card_plays"),
            metrics.get("potion_uses"),
            metrics.get("reward_picks"),
            metrics.get("reward_skips"),
            metrics.get("map_picks"),
        ),
        "- 每幕掉血 %s，未建模 %s"
        % (metrics.get("hp_loss_by_act"), metrics.get("unmodeled")),
        "",
        "## 决策点",
        "",
    ]
    for decision in digest.get("decisions") or []:
        lines.append(
            "- `%s` 第 %s 层 [%s] %s → %s"
            % (
                decision.get("event_id"),
                decision.get("floor"),
                decision.get("kind"),
                decision.get("state_summary"),
                decision.get("chosen"),
            )
        )
        if decision.get("advice"):
            lines.append("  建议：%s" % decision["advice"])
        if decision.get("outcome"):
            lines.append("  结果：%s" % decision["outcome"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a StS2 run digest from JSONL.")
    parser.add_argument("files", nargs="*", help="explicit JSONL files")
    parser.add_argument("--runs", default=default_runs_dir(), help="run log directory")
    parser.add_argument("--last", type=int, default=1, help="use the newest N logs")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("--out", help="write UTF-8 output to this file")
    args = parser.parse_args()

    paths = args.files or find_logs(args.runs, args.last)
    if not paths:
        raise SystemExit("no .jsonl logs found")
    digests = []
    for path in paths:
        digests.append(build_digest(load_events(path), path))
    payload = digests[0] if len(digests) == 1 else digests
    text = (
        json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json
        else render_markdown(payload)
    )
    if args.out:
        with io.open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print("written " + args.out)
    else:
        print(text)


if __name__ == "__main__":
    main()

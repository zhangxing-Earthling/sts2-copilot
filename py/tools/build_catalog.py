# -*- coding: utf-8 -*-
"""Build a source-derived model catalog for StS2 0.107.1.

The decompiled source is only an input to this local generator; the generated
catalog contains class/effect metadata, not game source or assets.

Usage:
    python py/tools/build_catalog.py
    python py/tools/build_catalog.py --root ref/sts2 --out py/rules/data/catalog.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

DEFAULT_ROOT = Path("ref/sts2/MegaCrit/sts2/Core/Models")
DEFAULT_OUT = Path("py/rules/data/catalog.json")
GAME_VERSION = "0.107.1"

TARGETS = {
    "Self": "self",
    "AnyEnemy": "any_enemy",
    "AllEnemies": "all_enemies",
    "RandomEnemy": "random_enemy",
    "AnyAlly": "any_ally",
    "AllAllies": "all_allies",
    "None": "none",
}
CARD_TYPES = {"Attack", "Skill", "Power", "Status", "Curse", "Quest"}
KNOWN_IMMEDIATE_POWERS = {
    "WeakPower", "VulnerablePower", "FrailPower", "StrengthPower",
    "DexterityPower", "PoisonPower", "ThornsPower", "StranglePower",
    "ShrinkPower", "RavenousPower",
}
VAR_NAMES = {
    "DamageVar": "Damage", "CalculatedDamageVar": "CalculatedDamage",
    "ExtraDamageVar": "ExtraDamage", "BlockVar": "Block",
    "CalculatedBlockVar": "CalculatedBlock", "CardsVar": "Cards",
    "EnergyVar": "Energy", "StarsVar": "Stars", "RepeatVar": "Repeat",
    "HealVar": "Heal", "MaxHpVar": "MaxHp", "HpLossVar": "HpLoss",
    "GoldVar": "Gold", "SummonVar": "Summon", "ForgeVar": "Forge",
    "CalculationBaseVar": "CalculationBase", "CalculationExtraVar": "CalculationExtra",
}
IGNORE_COMMANDS = {
    "TriggerAnim", "Wait", "CustomScaledWait", "Preview", "PreviewCardPileAdd",
    "Flash", "SetAnimation", "PlaySfx", "PlayVfx", "AddChildSafely",
}


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def snake(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return value.upper()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def matching(text: str, start: int, open_ch: str = "(", close_ch: str = ")") -> str:
    depth = 0
    quote = None
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if ch == quote and text[i - 1] != "\\":
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    return text[start + 1:]


def method_body(text: str, name: str) -> str:
    pattern = re.compile(
        r"(?:protected|public|private)\s+override\s+(?:async\s+)?[^\n{;]+\s+"
        + re.escape(name) + r"\s*\([^)]*\)\s*\{",
        re.S,
    )
    m = pattern.search(text)
    if not m:
        return ""
    brace = text.find("{", m.start())
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1:i]
    return text[brace + 1:]


def body_for(text: str, name: str) -> str:
    body = method_body(text, name)
    if body:
        return body
    # Expression-bodied property/method, e.g. Rarity => RelicRarity.Rare;
    m = re.search(re.escape(name) + r"\s*=>\s*(.*?);", text, re.S)
    return m.group(1) if m else ""


def base_args(text: str) -> str:
    m = re.search(r":\s*base\s*\(", text)
    if not m:
        return ""
    return matching(text, m.end() - 1)


def constructor_info(text: str) -> dict:
    args = base_args(text)
    result = {"cost": None, "type": None, "rarity": None, "target": None}
    if not args:
        return result
    parts = [p.strip() for p in args.split(",")]
    if parts and re.fullmatch(r"-?\d+", parts[0]):
        result["cost"] = int(parts[0])
    for part in parts:
        m = re.search(r"CardType\.(\w+)", part)
        if m and m.group(1) in CARD_TYPES:
            result["type"] = m.group(1)
        m = re.search(r"CardRarity\.(\w+)", part)
        if m:
            result["rarity"] = m.group(1)
        m = re.search(r"TargetType\.(\w+)", part)
        if m:
            result["target"] = TARGETS.get(m.group(1), m.group(1))
    return result


def parse_vars(text: str) -> list[dict]:
    out = []
    seen = set()
    for m in re.finditer(r"new\s+([A-Za-z0-9_]+Var|DynamicVar)\s*(?:<([^>]+)>)?\s*\(", text):
        var_type = m.group(1)
        generic = (m.group(2) or "").strip()
        args = matching(text, m.end() - 1)
        if var_type == "DynamicVar":
            key_match = re.search(r'"([^"]+)"', args)
            key = key_match.group(1) if key_match else ""
        elif generic:
            key = generic.split(".")[-1]
        else:
            key = VAR_NAMES.get(var_type, var_type.removesuffix("Var"))
        if not key or key in seen:
            continue
        seen.add(key)
        number = re.search(r"-?\d+(?:\.\d+)?", args)
        base = float(number.group(0)) if number else None
        out.append({
            "key": key,
            "var": var_type,
            "generic": generic or None,
            "base": base,
            "upgrade": None,
        })
    # UpgradeValueBy: DynamicVars.X.UpgradeValueBy(N) / DynamicVars["X"]...
    for m in re.finditer(
        r"DynamicVars\s*(?:\.([A-Za-z0-9_]+)|\[\s*\"([^\"]+)\"\s*\])"
        r"\s*\.UpgradeValueBy\s*\(\s*(-?\d+(?:\.\d+)?)", text):
        key = m.group(1) or m.group(2)
        for item in out:
            if item["key"] == key and item["upgrade"] is None:
                item["upgrade"] = float(m.group(3))
    return out


def parse_name_sets(text: str) -> tuple[list[str], list[str]]:
    tags = []
    keywords = []
    for region, marker in (("tags", "CanonicalTags"), ("keywords", "CanonicalKeywords")):
        body = body_for(text, marker)
        if not body:
            continue
        tags.extend(re.findall(r"CardTag\.([A-Za-z0-9_]+)", body))
        keywords.extend(re.findall(r"CardKeyword\.([A-Za-z0-9_]+)", body))
    return sorted(set(tags)), sorted(set(keywords))


def parse_commands(text: str) -> list[dict]:
    out = []
    pattern = re.compile(
        r"\b(DamageCmd|CreatureCmd|PowerCmd|CardPileCmd|CardCmd|CardSelectCmd|"
        r"PlayerCmd|RelicCmd|PotionCmd|OstyCmd|OrbCmd|SummonCmd|ForgeCmd|Shiv|Cmd)"
        r"\s*\.\s*([A-Za-z0-9_]+)\s*(?:<([^>]+)>)?\s*\(")
    for m in pattern.finditer(text):
        namespace, command, generic = m.group(1), m.group(2), (m.group(3) or "").strip()
        if command in IGNORE_COMMANDS:
            continue
        args = matching(text, m.end() - 1)
        tail = text[m.end():m.end() + 450]
        call = text[m.start():m.end()] + args + tail
        if namespace == "DamageCmd" and command == "Attack":
            kind = "damage"
        elif namespace == "DamageCmd":
            kind = "damage"
        elif namespace == "CreatureCmd" and command == "GainBlock":
            kind = "block"
        elif namespace == "CreatureCmd" and command in ("Damage", "LoseHp", "LoseMaxHp"):
            kind = "self_damage" if "Owner.Creature" in args else "damage"
        elif namespace == "CreatureCmd" and command == "Heal":
            kind = "heal"
        elif namespace == "PowerCmd" and command in ("Apply", "ApplyInternal"):
            kind = "power"
        elif namespace == "CardPileCmd" and command.startswith("Draw"):
            kind = "draw"
        elif namespace == "PlayerCmd" and command in ("GainEnergy", "GainStars"):
            kind = "energy" if "Energy" in command else "stars"
        elif namespace == "CardCmd" and command in ("Exhaust", "ExhaustAnd"):
            kind = "exhaust"
        elif namespace == "CardCmd" and command in ("Discard", "DiscardAndDraw"):
            kind = "discard"
        elif namespace == "CardCmd" and command == "Upgrade":
            kind = "upgrade"
        elif namespace in ("CardPileCmd",) and "AddGenerated" in command:
            kind = "generated"
        elif namespace == "CardSelectCmd":
            kind = "choice"
        elif namespace == "CardCmd" and command in ("TransformTo", "AutoPlay"):
            kind = "transform"
        elif namespace == "PotionCmd":
            kind = "potion"
        elif namespace == "CardCmd" and command == "Enchant":
            kind = "enchant"
        elif namespace == "OstyCmd" and command in ("Summon", "SummonOsty"):
            kind = "summon"
        elif namespace == "OrbCmd":
            kind = "orb"
        elif namespace == "Shiv" and command in ("CreateInHand", "Create"):
            kind = "generated"
        elif namespace in ("SummonCmd", "ForgeCmd"):
            kind = "summon"
        else:
            kind = command[:1].lower() + command[1:]
        amount = None
        vm = re.search(r"DynamicVars\s*(?:\.([A-Za-z0-9_]+)|\[\s*\"([^\"]+)\"\s*\])", args)
        if vm:
            amount = vm.group(1) or vm.group(2)
        if not amount:
            num = re.search(r"(?<![\w.])-?\d+(?:\.\d+)?m?", args)
            if num:
                amount = num.group(0).rstrip("m")
        target = None
        if "TargetingAllOpponents" in call or "HittableEnemies" in args:
            target = "all_enemies"
        elif "TargetingRandom" in call:
            target = "random_enemy"
        elif "cardPlay.Target" in args or "Targeting(" in call:
            target = "any_enemy"
        elif "base.Owner.Creature" in args or "base.Owner" in args:
            target = "self"
        power = generic.split(".")[-1] if generic else None
        entry = {
            "kind": kind,
            "command": f"{namespace}.{command}",
            "amount": amount,
            "target": target,
        }
        if power:
            entry["power"] = power
        if not args.strip() and not tail.strip():
            continue
        out.append(entry)
    return out


def model_level(entity: dict) -> tuple[str, list[str]]:
    """Classify precision available to the current Python solver."""
    effects = entity.get("effects", [])
    turn_end = entity.get("turn_end_effects", [])
    kinds = {e.get("kind") for e in effects}
    reasons = []
    if not effects and not turn_end:
        if entity.get("type") in ("Status", "Curse", "Quest"):
            return "catalog_only", ["不可打出的状态/诅咒/任务牌"]
        return "catalog_only", ["没有可识别的即时效果"]
    if turn_end:
        reasons.append("回合结束手牌效果")
    if any(e.get("target") == "random_enemy" for e in effects):
        reasons.append("随机目标")
    if any(e.get("kind") in ("draw", "discard", "exhaust", "energy", "stars",
                             "generated", "transform", "choice", "potion",
                             "enchant", "upgrade", "summon", "orb") for e in effects):
        reasons.append("派生/牌堆/资源/召唤/充能效果未逐项计")
    for e in effects:
        if e.get("kind") != "power":
            continue
        power = e.get("power")
        target = e.get("target")
        if target == "self" and power not in ("StrengthPower", "DexterityPower"):
            reasons.append(f"自身能力 {power or '?'} 未建模")
        elif target != "self" and power not in (
            "WeakPower", "VulnerablePower", "FrailPower", "PoisonPower",
            "StranglePower", "StrengthPower", "DexterityPower",
        ):
            reasons.append(f"敌方能力 {power or '?'} 未建模")
    if not (kinds & {"damage", "block", "power"}):
        reasons.append("无即时伤害/格挡/能力")
    if entity.get("conditional"):
        reasons.append("条件分支")
    if reasons:
        return "partial", sorted(set(reasons))
    return "exact", []


def parse_card(path: Path, root: Path) -> dict:
    text = read(path)
    class_name = path.stem
    info = constructor_info(text)
    tags, keywords = parse_name_sets(text)
    on_play = body_for(text, "OnPlay")
    effects = parse_commands(on_play)
    turn_end_effects = parse_commands(body_for(text, "OnTurnEndInHand"))
    entity = {
        "class": class_name,
        "id": class_name,
        "id_snake": snake(class_name),
        "file": str(path.relative_to(root)).replace("\\", "/"),
        "cost": info["cost"],
        "type": info["type"],
        "rarity": info["rarity"],
        "target": info["target"],
        "tags": tags,
        "keywords": keywords,
        "vars": parse_vars(text),
        "effects": effects,
        "turn_end_effects": turn_end_effects,
        "hooks": sorted(set(re.findall(
            r"public\s+override\s+(?:async\s+)?[^\n{;]+\s+([A-Za-z0-9_]+)\s*\(",
            text))),
        "conditional": bool(re.search(r"\bif\s*\(", on_play)),
        "upgrade": body_for(text, "OnUpgrade")[:500],
    }
    level, reasons = model_level(entity)
    entity["model"] = {"level": level, "reasons": reasons}
    return entity


def parse_relic(path: Path, root: Path) -> dict:
    text = read(path)
    vars_ = parse_vars(text)
    effects = parse_commands(text)
    rarity = body_for(text, "Rarity")
    rm = re.search(r"RelicRarity\.(\w+)", rarity)
    hooks = sorted(set(re.findall(
        r"public\s+override\s+(?:async\s+)?[^\n{;]+\s+([A-Za-z0-9_]+)\s*\(",
        text)))
    entity = {
        "class": path.stem,
        "id": path.stem,
        "id_snake": snake(path.stem),
        "file": str(path.relative_to(root)).replace("\\", "/"),
        "rarity": rm.group(1) if rm else None,
        "vars": vars_,
        "effects": effects,
        "hooks": hooks,
        "conditional": bool(re.search(r"\bif\s*\(", text)),
    }
    level, reasons = model_level(entity)
    if path.stem == "StrikeDummy":
        # StrikeDummy's effect is a damage hook, not an OnPlay command.
        entity["effects"] = [{
            "kind": "strike_damage_bonus", "command": "ModifyDamageAdditive",
            "amount": "ExtraDamage", "target": "self", "value": 3,
        }]
        level, reasons = "exact", []
    elif hooks and level == "exact":
        # A relic hook changes the model even when OnPlay-like commands are absent.
        level, reasons = "partial", ["遗物 hook 未逐项建模"]
    entity["model"] = {"level": level, "reasons": reasons}
    return entity


def parse_power(path: Path, root: Path) -> dict:
    text = read(path)
    power_type = body_for(text, "Type")
    stack = body_for(text, "StackType")
    hooks = sorted(set(re.findall(
        r"public\s+override\s+(?:async\s+)?[^\n{;]+\s+([A-Za-z0-9_]+)\s*\(",
        text)))
    entity = {
        "class": path.stem,
        "id": path.stem,
        "file": str(path.relative_to(root)).replace("\\", "/"),
        "type": next(iter(re.findall(r"PowerType\.(\w+)", power_type)), None),
        "stack": next(iter(re.findall(r"PowerStackType\.(\w+)", stack)), None),
        "hooks": hooks,
        "effects": parse_commands(text),
        "vars": parse_vars(text),
    }
    entity["model"] = {
        "level": "exact" if path.stem in KNOWN_IMMEDIATE_POWERS else ("partial" if hooks else "catalog_only"),
        "reasons": [] if path.stem in KNOWN_IMMEDIATE_POWERS else (
            ["通用 Power hook 未逐项建模"] if hooks else ["没有可识别的通用 hook"]
        ),
    }
    return entity


def parse_potion(path: Path, root: Path) -> dict:
    text = read(path)
    effects = parse_commands(body_for(text, "OnUse"))
    rarity = body_for(text, "Rarity")
    usage = body_for(text, "Usage")
    target = body_for(text, "TargetType")
    entity = {
        "class": path.stem,
        "id": path.stem,
        "file": str(path.relative_to(root)).replace("\\", "/"),
        "rarity": next(iter(re.findall(r"PotionRarity\.(\w+)", rarity)), None),
        "usage": next(iter(re.findall(r"PotionUsage\.(\w+)", usage)), None),
        "target": next(iter(re.findall(r"TargetType\.(\w+)", target)), None),
        "vars": parse_vars(text),
        "effects": effects,
    }
    level, reasons = model_level(entity)
    entity["model"] = {"level": level, "reasons": reasons}
    return entity


def parse_event(path: Path, root: Path) -> dict:
    text = read(path)
    layout = body_for(text, "LayoutType")
    return {
        "class": path.stem,
        "id": path.stem,
        "file": str(path.relative_to(root)).replace("\\", "/"),
        "layout": next(iter(re.findall(r"EventLayoutType\.(\w+)", layout)), None),
        "options": sorted(set(re.findall(r"new\s+EventOption\s*\(", text))),
        "hooks": sorted(set(re.findall(
            r"protected\s+override\s+(?:async\s+)?[^\n{;]+\s+([A-Za-z0-9_]+)\s*\(",
            text))),
        "model": {"level": "catalog_only", "reasons": ["事件后续结果/条件未逐项建模"]},
    }


def parse_encounter(path: Path, root: Path) -> dict:
    text = read(path)
    room = body_for(text, "RoomType")
    return {
        "class": path.stem,
        "id": path.stem,
        "file": str(path.relative_to(root)).replace("\\", "/"),
        "room_type": next(iter(re.findall(r"RoomType\.(\w+)", room)), None),
        "monsters": sorted(set(re.findall(r"ModelDb\.Monster<([A-Za-z0-9_]+)>", text))),
        "model": {"level": "catalog_only", "reasons": ["遭遇 AI/多回合机制未逐项建模"]},
    }


def parse_dir(root: Path, sub: str, parser) -> list[dict]:
    path = root / sub
    if not path.exists():
        return []
    return [parser(p, root) for p in sorted(path.glob("*.cs"))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    root = Path(args.root)
    out = Path(args.out)
    cards = parse_dir(root, "Cards", parse_card)
    relics = parse_dir(root, "Relics", parse_relic)
    powers = parse_dir(root, "Powers", parse_power)
    potions = parse_dir(root, "Potions", parse_potion)
    events = parse_dir(root, "Events", parse_event)
    encounters = parse_dir(root, "Encounters", parse_encounter)
    for collection in (cards, relics, powers, potions, events, encounters):
        for entity in collection:
            entity.setdefault("model", {"level": "catalog_only", "reasons": []})
    coverage = {
        "cards": dict(Counter(c["model"]["level"] for c in cards)),
        "relics": dict(Counter(r["model"]["level"] for r in relics)),
        "powers": dict(Counter(p["model"]["level"] for p in powers)),
        "potions": dict(Counter(p["model"]["level"] for p in potions)),
        "events": dict(Counter(e["model"]["level"] for e in events)),
        "encounters": dict(Counter(e["model"]["level"] for e in encounters)),
    }
    catalog = {
        "schema": 1,
        "game_version": GAME_VERSION,
        "source": "ref/sts2/MegaCrit/sts2/Core/Models",
        "counts": {
            "cards": len(cards), "relics": len(relics), "powers": len(powers),
            "potions": len(potions), "events": len(events), "encounters": len(encounters),
        },
        "coverage": coverage,
        "cards": cards,
        "relics": relics,
        "powers": powers,
        "potions": potions,
        "events": events,
        "encounters": encounters,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(json.dumps(coverage, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

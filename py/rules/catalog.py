# -*- coding: utf-8 -*-
"""Lazy access to the generated, source-derived model catalog.

The catalog covers every real model class in the 0.107.1 decompiled source.
Solver precision is recorded per entity (`exact` / `partial` / `catalog_only`)
so callers never have to guess whether an effect is modeled.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "data" / "catalog.json"
_EMPTY = {
    "schema": 0, "game_version": "", "counts": {}, "coverage": {},
    "cards": [], "relics": [], "powers": [], "potions": [], "events": [], "encounters": [],
}


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


@lru_cache(maxsize=1)
def load() -> dict:
    if not _PATH.exists():
        return _EMPTY
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _EMPTY


@lru_cache(maxsize=1)
def _indexes() -> dict[str, dict[str, dict]]:
    data = load()
    result: dict[str, dict[str, dict]] = {}
    for collection in ("cards", "relics", "powers", "potions", "events", "encounters"):
        index: dict[str, dict] = {}
        for entity in data.get(collection, []):
            for key in (entity.get("id"), entity.get("class"), entity.get("id_snake")):
                normalized = _norm(key)
                if normalized:
                    index.setdefault(normalized, entity)
        result[collection] = index
    return result


def get(collection: str, value) -> dict | None:
    if isinstance(value, dict):
        value = value.get("Id") or value.get("id") or value.get("Class") or value.get("class")
    return _indexes().get(collection, {}).get(_norm(value))


def card(value) -> dict | None:
    return get("cards", value)


def relic(value) -> dict | None:
    return get("relics", value)


def power(value) -> dict | None:
    return get("powers", value)


def potion(value) -> dict | None:
    return get("potions", value)


def card_tags(value) -> set[str]:
    entity = card(value)
    return set(entity.get("tags", []) if entity else [])


def card_keywords(value) -> set[str]:
    entity = card(value)
    return set(entity.get("keywords", []) if entity else [])


def card_model_level(value) -> str:
    entity = card(value)
    return entity.get("model", {}).get("level", "catalog_only") if entity else "catalog_only"


def coverage() -> dict:
    return load().get("coverage", {})


def counts() -> dict:
    return load().get("counts", {})


def effect_kinds(value, collection: str = "cards") -> set[str]:
    entity = get(collection, value)
    return {item.get("kind") for item in (entity or {}).get("effects", []) if item.get("kind")}


def relic_ids_from_state(state: dict) -> set[str]:
    """Return normalized relic ids, falling back to localized relic names.

    Chinese/localized names normalize to an empty string; never put that empty
    value into the set, otherwise ``has_relic(state, ...)`` matches every
    localized name and falsely enables relics such as StrikeDummy.
    """
    values = list(state.get("RelicIds") or []) + list(state.get("Relics") or [])
    return {normalized for value in values if (normalized := _norm(value))}


def has_relic(state: dict, *ids: str) -> bool:
    present = relic_ids_from_state(state)
    targets = {_norm(value) for value in ids if _norm(value)}
    return bool(present & targets)


def normalized(value) -> str:
    return _norm(value)

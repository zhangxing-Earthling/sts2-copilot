"""P1.5 calibration: compare logged solver HP predictions with actual HP.

Usage:
    python py\\tools\\calibrate.py
    python py\\tools\\calibrate.py --last 10
    python py\\tools\\calibrate.py --json
    python py\\tools\\calibrate.py path\\to\\run.jsonl

A prediction is evaluated against the next turn's starting HP, or against
combat_end.Hp when the combat ends before another turn. Old logs without a
`solver` field are counted as "missing", not treated as zero error.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Iterator


@dataclass
class TurnSample:
    path: str
    turn: int
    predicted_hp: int
    actual_hp: int
    predicted_loss: int
    actual_loss: int
    error: int
    lethal: bool
    followed: bool | None
    sequence: list[str] = field(default_factory=list)
    unmodeled: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass
class Calibration:
    samples: list[TurnSample] = field(default_factory=list)
    missing: int = 0
    errors: int = 0
    lethal_false: int = 0
    unmodeled: Counter = field(default_factory=Counter)

    @property
    def evaluated(self) -> int:
        return len(self.samples)

    @property
    def mae(self) -> float:
        return statistics.mean(abs(s.error) for s in self.samples) if self.samples else 0.0

    @property
    def bias(self) -> float:
        return statistics.mean(s.error for s in self.samples) if self.samples else 0.0

    @property
    def within_one(self) -> float:
        if not self.samples:
            return 0.0
        return sum(1 for s in self.samples if abs(s.error) <= 1) / len(self.samples)

    @property
    def exact(self) -> float:
        if not self.samples:
            return 0.0
        return sum(1 for s in self.samples if s.error == 0) / len(self.samples)

    @property
    def followed_samples(self) -> list[TurnSample]:
        return [s for s in self.samples if s.followed is True]

    @property
    def followed(self) -> int:
        return len(self.followed_samples)

    @property
    def followed_mae(self) -> float:
        samples = self.followed_samples
        return statistics.mean(abs(s.error) for s in samples) if samples else 0.0


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


def _solver(event: dict) -> dict | None:
    solver = _get(event, "solver", "Solver")
    return solver if isinstance(solver, dict) else None


def _solver_error(solver: dict | None) -> str | None:
    if not solver:
        return None
    error = _get(solver, "error", "Error")
    return str(error) if error else None


def _card_name(entry) -> str:
    """Turn '打击+→虫' / '生存者（弃防御）' into '打击' / '生存者'."""
    text = str(entry or "").strip()
    for separator in ("→", "（"):
        text = text.split(separator, 1)[0].strip()
    return re.sub(r"\+\d*$", "", text).strip()


def _action_names(event: dict) -> list[str]:
    played = _get(event, "played", "Played")
    if played is None:
        payload = _get(event, "payload", "Payload") or {}
        played = _get(payload, "played", "Played") or []
    names = []
    for card in played or []:
        if isinstance(card, dict):
            name = _get(card, "name", "Name")
            if name:
                names.append(str(name))
        elif card:
            names.append(str(card))
    return names


def _finalize(pending: dict | None, actual_hp: int | None, path: str, out: Calibration) -> None:
    if pending is None:
        return
    if actual_hp is None:
        return

    predicted = _as_int(pending["hpAfter"])
    actual = _as_int(actual_hp)
    solver = pending["solver"]
    if _get(solver, "lethal", "Lethal") and pending["next_turn"]:
        out.lethal_false += 1

    expected = [_card_name(x) for x in (_get(solver, "sequence", "Sequence") or [])]
    actual_cards = pending["actions"]
    if expected and not pending["action_seen"]:
        followed = None
    elif expected or actual_cards or pending["action_seen"]:
        followed = Counter(expected) == Counter(actual_cards)
    else:
        followed = None

    predicted_loss = _as_int(_get(solver, "hpLoss", "HpLoss"), pending["state_hp"] - predicted)
    actual_loss = pending["state_hp"] - actual
    out.samples.append(
        TurnSample(
            path=path,
            turn=pending["turn"],
            predicted_hp=predicted,
            actual_hp=actual,
            predicted_loss=predicted_loss,
            actual_loss=actual_loss,
            error=actual - predicted,
            lethal=bool(_get(solver, "lethal", "Lethal")),
            followed=followed,
            sequence=list(_get(solver, "sequence", "Sequence") or []),
            unmodeled=[str(x) for x in (_get(solver, "unmodeled", "Unmodeled") or [])],
            truncated=bool(_get(solver, "truncated", "Truncated")),
        )
    )


def analyze_events(events: Iterable[dict], path: str = "") -> Calibration:
    out = Calibration()
    pending: dict | None = None

    for event in events:
        if not isinstance(event, dict):
            continue
        kind = _get(event, "type", "Type")
        payload = _get(event, "payload", "Payload") or {}

        if kind == "turn":
            state = _get(event, "state", "State") or {}
            hp = _get(state, "Hp", "hp")
            encounter = _get(state, "Encounter", "encounter")
            # The HP at the start of the next turn is the actual result of the
            # previous turn's enemy action.
            if pending is not None:
                # Old logs may miss combat_end when CombatState stays non-null
                # between fights. An encounter change is a new combat, so the
                # previous prediction must not be counted as a false lethal.
                same_combat = (
                    not pending["encounter"]
                    or not encounter
                    or pending["encounter"] == encounter
                )
                pending["next_turn"] = same_combat
                _finalize(pending, hp, path, out)
                pending = None

            solver = _solver(event)
            if solver is None:
                out.missing += 1
                continue
            if _solver_error(solver):
                out.errors += 1
                continue
            if _get(solver, "hpAfter", "HpAfter") is None:
                out.errors += 1
                continue

            pending = {
                "turn": _as_int(_get(state, "Turn", "turn")),
                "state_hp": _as_int(hp),
                "hpAfter": _as_int(_get(solver, "hpAfter", "HpAfter")),
                "solver": solver,
                "encounter": str(encounter or ""),
                "next_turn": False,
                "actions": [],
                "action_seen": False,
                "history_seen": False,
            }
            for name in _get(solver, "unmodeled", "Unmodeled") or []:
                out.unmodeled[str(name)] += 1

        elif kind == "card_play" and pending is not None:
            payload = _get(event, "payload", "Payload") or {}
            name = _get(payload, "Name", "name")
            auto = bool(_get(payload, "AutoPlay", "autoPlay"))
            play_index = _as_int(_get(payload, "PlayIndex", "playIndex"), 0)
            if name:
                pending["action_seen"] = True
                pending["history_seen"] = True
                if not auto and play_index == 0:
                    pending["actions"].append(str(name))

        elif kind == "potion_use" and pending is not None:
            # Potions are not part of the card sequence, but they explain why
            # the HP result may differ from the solver's card-only prediction.
            pending["action_seen"] = True

        elif kind == "action" and pending is not None and not pending["history_seen"]:
            pending["action_seen"] = True
            if _get(event, "kind", "Kind") == "card_play":
                pending["actions"].extend(_action_names(event))

        elif kind == "combat_end":
            if pending is not None:
                _finalize(pending, _get(payload, "Hp", "hp"), path, out)
                pending = None

        elif kind in ("combat_start", "run_end", "seed_changed"):
            pending = None

    return out


def iter_events(path: str) -> Iterator[dict]:
    with open(path, encoding="utf-8") as handle:
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


def find_logs(runs_dir: str, last: int | None = None) -> list[str]:
    paths = glob.glob(os.path.join(runs_dir, "*.jsonl"))
    paths.sort(key=os.path.getmtime, reverse=True)
    if last is not None:
        paths = paths[:last]
    return paths


def analyze_files(paths: Iterable[str]) -> Calibration:
    total = Calibration()
    for path in paths:
        part = analyze_events(iter_events(path), path)
        total.samples.extend(part.samples)
        total.missing += part.missing
        total.errors += part.errors
        total.lethal_false += part.lethal_false
        total.unmodeled.update(part.unmodeled)
    return total


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def print_report(result: Calibration, paths: list[str], top: int = 10) -> None:
    print("StS2 Copilot - P1.5 校准")
    print(f"日志文件: {len(paths)}")
    print(f"可评估回合: {result.evaluated}")
    print(f"缺少 solver（旧日志/本地回退）: {result.missing}")
    print(f"solver error: {result.errors}")
    print(f"斩杀误报（预测可杀但还有下一回合）: {result.lethal_false}")
    if result.evaluated:
        followed = result.followed
        print(f"按建议出牌: {followed} / {result.evaluated}")
        print(f"MAE: {result.mae:.2f} HP")
        if followed:
            print(f"跟随建议 MAE: {result.followed_mae:.2f} HP")
        print(f"偏差: {result.bias:+.2f} HP（正数=实际 HP 更高，掉血更少）")
        print(f"误差 <=1: {_pct(result.within_one)}")
        print(f"完全一致: {_pct(result.exact)}")

    if result.samples:
        print("\n最差回合:")
        for sample in sorted(result.samples, key=lambda s: abs(s.error), reverse=True)[:top]:
            sequence = " → ".join(sample.sequence) if sample.sequence else "（不出牌）"
            followed = {True: "跟随", False: "未跟随", None: "无法判断"}[sample.followed]
            print(
                f"  [{os.path.basename(sample.path)}] turn {sample.turn}: "
                f"预测 {sample.predicted_hp} / 实际 {sample.actual_hp} "
                f"(误差 {sample.error:+d}, 预测掉 {sample.predicted_loss}, "
                f"实际掉 {sample.actual_loss}, {followed})  {sequence}"
            )

    if result.unmodeled:
        print("\n未建模牌:")
        for name, count in result.unmodeled.most_common(15):
            print(f"  {name}: {count}")


def to_json(result: Calibration) -> dict:
    return {
        "evaluated": result.evaluated,
        "missing": result.missing,
        "errors": result.errors,
        "lethal_false": result.lethal_false,
        "mae": round(result.mae, 3),
        "bias": round(result.bias, 3),
        "within_one": round(result.within_one, 3),
        "exact": round(result.exact, 3),
        "followed": len(result.followed_samples),
        "followed_mae": round(result.followed_mae, 3),
        "unmodeled": dict(result.unmodeled.most_common()),
        "samples": [
            {
                "path": sample.path,
                "turn": sample.turn,
                "predicted_hp": sample.predicted_hp,
                "actual_hp": sample.actual_hp,
                "predicted_loss": sample.predicted_loss,
                "actual_loss": sample.actual_loss,
                "error": sample.error,
                "lethal": sample.lethal,
                "followed": sample.followed,
                "sequence": sample.sequence,
                "unmodeled": sample.unmodeled,
                "truncated": sample.truncated,
            }
            for sample in result.samples
        ],
    }


def main() -> None:
    default_runs = os.path.join(
        os.environ.get("STS2_COPILOT_LOG_DIR")
        or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "logs",
        ),
        "runs",
    )
    parser = argparse.ArgumentParser(description="Compare StS2 Copilot solver predictions with actual HP.")
    parser.add_argument("files", nargs="*", help="explicit JSONL files (default: newest run logs)")
    parser.add_argument("--runs", default=default_runs, help=f"run log directory (default: {default_runs})")
    parser.add_argument("--last", type=int, default=None, help="only analyze the newest N log files")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--top", type=int, default=10, help="number of worst turns to print")
    args = parser.parse_args()

    paths = args.files or find_logs(args.runs, args.last)
    if not paths:
        raise SystemExit(f"no .jsonl logs found under {args.runs}")
    result = analyze_files(paths)
    if args.json:
        print(json.dumps(to_json(result), ensure_ascii=False, indent=2))
    else:
        print_report(result, paths, args.top)


if __name__ == "__main__":
    main()

# Copilot Instructions

This repository is an external, read-only Slay the Spire 2 assistant.

Before editing, read [`.agent.md`](../.agent.md).

Key rules:

- Do not add mods, DLL injection, memory writes, or synthetic input.
- Keep game-version access behind the `0.107.1` version lock.
- Put rule/math logic in `py/rules/engine.py`; C# `Advisor.cs` is only a fallback.
- Never commit API keys, `dist/`, `ref/`, or game assets.
- After publishing, verify the exit code and the DLL timestamp in `dist/Sts2Copilot`.

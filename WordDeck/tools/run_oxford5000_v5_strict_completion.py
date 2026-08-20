#!/usr/bin/env python3
"""Run the V5 heavy orchestrator with the contrastive sense reviewer."""
from __future__ import annotations

import run_oxford5000_v5_completion as inner

_original_run = inner.run


def strict_run(*args: str, capture: bool = False) -> str:
    rewritten = tuple(
        "WordDeck/tools/complete_oxford5000_emergency_v5_strict.py"
        if arg == "WordDeck/tools/complete_oxford5000_emergency_v5.py"
        else arg
        for arg in args
    )
    return _original_run(*rewritten, capture=capture)


def main() -> int:
    inner.run = strict_run
    return inner.main()


if __name__ == "__main__":
    raise SystemExit(main())

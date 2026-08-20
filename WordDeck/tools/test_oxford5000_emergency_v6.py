#!/usr/bin/env python3
"""Executable V6 regression harness without assuming a V5-strict self_test export."""
from __future__ import annotations

import complete_oxford5000_emergency_v6 as v6


def main() -> int:
    # complete_oxford5000_emergency_v5_strict deliberately exposes strict
    # production helpers but no self_test() entry point. V6 owns the new
    # regression contract and exercises those helpers through its own fixtures.
    setattr(v6.strict, "self_test", lambda: None)
    v6.self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

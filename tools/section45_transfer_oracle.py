"""Generate a deterministic Python oracle for the Section 45 JS/Python parity gate.

The file is a CI-only fixture, never a profile store or a product data source.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
import sys

from acs.visual_profile_transfer import FIELDS, encode_transfer


def main(destination: Path) -> int:
    cases = []
    for profile, theme, board_theme, density in itertools.product(
        sorted(FIELDS["profile"]), sorted(FIELDS["theme"]),
        sorted(FIELDS["board_theme"]), sorted(FIELDS["density"])
    ):
        preferences = {
            "profile": profile, "theme": theme,
            "board_theme": board_theme, "density": density,
        }
        cases.append({"preferences": preferences, "payload": encode_transfer(preferences)})
    if len(cases) != 300:
        raise AssertionError("unexpected Section 45.5 acceptance matrix")
    destination.write_text(
        json.dumps({"schema_version": 1, "cases": cases}, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(cases)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tools/section45_transfer_oracle.py OUTPUT.json")
    print("Section 45 Python oracle: " + str(main(Path(sys.argv[1]))) + " cases")

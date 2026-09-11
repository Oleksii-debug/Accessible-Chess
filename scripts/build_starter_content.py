"""Build Accessible Chess P0-F offline starter content."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acs.starter_content import (
    STARTER_GAME_COUNT,
    STRESS_GAME_COUNT,
    build_starter_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build deterministic project-authored Accessible Chess starter assets."
    )
    parser.add_argument("destination", type=Path)
    parser.add_argument("--starter-games", type=int, default=STARTER_GAME_COUNT)
    parser.add_argument("--stress-games", type=int, default=STRESS_GAME_COUNT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace only the known generated starter-content files.",
    )
    args = parser.parse_args()

    manifest = build_starter_bundle(
        args.destination,
        overwrite=args.force,
        starter_count=args.starter_games,
        stress_count=args.stress_games,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

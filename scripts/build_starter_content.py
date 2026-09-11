"""Build Accessible Chess P0-F offline starter content."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Make direct execution reliable on Windows/Linux even when the repository has
# not been installed as a package: `python scripts/build_starter_content.py ...`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acs.starter_content import (  # noqa: E402
    STARTER_GAME_COUNT,
    STRESS_GAME_COUNT,
    build_starter_bundle,
)


def _configure_stdout_utf8() -> None:
    """Keep the CLI's Ukrainian manifest portable across Windows code pages."""

    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="strict")


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
    _configure_stdout_utf8()
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Section-55 independent local-only provisional bundle verification utility."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acs.chess_braille_bundle import verify_provisional_bundle
from acs.chess_braille_factory import BrailleFactoryError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-verify local PEF/BRF bytes; cannot certify print readiness"
    )
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--original-source", type=Path, required=True,
                        help="Same original input file passed to the provisional generator")
    args = parser.parse_args()
    try:
        report = verify_provisional_bundle(args.folder, args.original_source)
    except (BrailleFactoryError, OSError, ValueError, TypeError):
        # Stable failure without exposing private paths, source text or tables.
        print("SECTION 55: FAIL — provisional package did not pass local consistency",
              file=sys.stderr)
        return 2
    print("SECTION 55: PASS — local provisional package consistency only")
    print("Pages:", report.pages)
    print("Status: UNVERIFIED_REQUIRES_DECISION; qualified print readiness: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

"""Generate deterministic unsigned SLSA Provenance v1 for a qualified release."""

import argparse
import sys

from acs.slsa_provenance import ProvenanceError, generate_provenance_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="qualified provenance manifest JSON")
    parser.add_argument("--output", required=True, help="destination in-toto statement JSON")
    args = parser.parse_args(argv)
    try:
        generate_provenance_file(args.input, args.output)
    except ProvenanceError as exc:
        print(f"Provenance generation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

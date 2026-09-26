from __future__ import annotations

import argparse
import sys

from acs.spdx_sbom import SbomError, generate_spdx_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic SPDX 2.3 release SBOM"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        generate_spdx_file(args.input, args.output)
    except SbomError as exc:
        print(f"SBOM generation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

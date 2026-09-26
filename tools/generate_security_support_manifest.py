from __future__ import annotations

"""Generate the canonical Accessible Chess security support manifest."""

import argparse
import sys

from acs.security_support_policy import (
    SecuritySupportError,
    generate_security_support_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        generate_security_support_manifest(args.input, args.output)
    except SecuritySupportError as exc:
        print(f"Security support manifest failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

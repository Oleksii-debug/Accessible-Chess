from __future__ import annotations

"""Generate the canonical Accessible Chess security support manifest."""

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acs.security_support_policy import (
    SecuritySupportError,
    generate_security_support_manifest,
)


_SECURITY_URI_FIELDS = (
    "vulnerability_contact",
    "disclosure_policy_url",
    "security_update_url",
)


def _reject_security_uri_controls(input_path: str) -> None:
    """Fail closed on decoded URI controls before URL parsing can normalize them."""

    try:
        raw = Path(input_path).read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        # The canonical core loader owns file/UTF-8/JSON diagnostics, including
        # duplicate-key rejection. This preflight only closes URI normalization.
        return
    if type(value) is not dict:
        return
    for field in _SECURITY_URI_FIELDS:
        item = value.get(field)
        if type(item) is not str:
            continue
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in item):
            raise SecuritySupportError(
                f"{field} must not contain ASCII control characters"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        _reject_security_uri_controls(args.input)
        generate_security_support_manifest(args.input, args.output)
    except SecuritySupportError as exc:
        print(f"Security support manifest failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

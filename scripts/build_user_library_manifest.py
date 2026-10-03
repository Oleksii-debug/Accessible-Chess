from __future__ import annotations

"""Build an owner-private packaged Library manifest beside supplied PGNs.

This script never copies, uploads, converts or redistributes book bytes. It
records exact local file identities so the final private package can stage the
same files and the runtime can verify them before canonical import.
"""

import argparse
import json
import os
from pathlib import Path
import tempfile

from acs.import_contract import fingerprint
from acs.user_library_payload import (
    MAX_USER_LIBRARY_SOURCE_BYTES,
    MAX_USER_LIBRARY_SOURCES,
    USER_LIBRARY_SCHEMA_VERSION,
    USER_LIBRARY_SCOPE,
)


def build_manifest(root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise ValueError("source directory must exist")
    files = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix.casefold() == ".pgn"
        ),
        key=lambda path: path.name.casefold(),
    )
    if not 1 <= len(files) <= MAX_USER_LIBRARY_SOURCES:
        raise ValueError("PGN source count is outside the supported bound")
    sources = []
    seen: set[str] = set()
    for path in files:
        key = path.name.casefold()
        if key in seen:
            raise ValueError("PGN filenames collide case-insensitively")
        seen.add(key)
        evidence = fingerprint(path)
        if not 1 <= evidence.size <= MAX_USER_LIBRARY_SOURCE_BYTES:
            raise ValueError(f"PGN source size is unsupported: {path.name}")
        sources.append(
            {
                "name": path.name,
                "format": "pgn",
                "bytes": evidence.size,
                "sha256": evidence.sha256,
            }
        )
    return {
        "schema_version": USER_LIBRARY_SCHEMA_VERSION,
        "scope": USER_LIBRARY_SCOPE,
        "sources": sources,
    }


def write_manifest(root: Path, manifest: dict[str, object]) -> Path:
    destination = root / "manifest.json"
    payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    fd, raw = tempfile.mkstemp(prefix=".user-library.", suffix=".tmp", dir=str(root))
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the owner-private Accessible Chess Library manifest."
    )
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.directory)
    destination = write_manifest(args.directory, manifest)
    print(
        json.dumps(
            {
                "manifest": destination.name,
                "sources": len(manifest["sources"]),
                "scope": USER_LIBRARY_SCOPE,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

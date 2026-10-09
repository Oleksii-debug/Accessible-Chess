"""Bounded, fail-closed single-member extraction for external Section-38 QA ZIPs.

No archive contents are published to the product. The independent source-byte
SHA-256 and semantic oracle must still pass after extraction.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import os
import stat
import tempfile
import zipfile


MAX_ARCHIVE_BYTES = 128 * 1024 * 1024


def extract_member(archive: Path, member: str, destination: Path, *, max_bytes: int) -> str:
    """Extract one expected regular member atomically, without overwrite."""
    if (
        not isinstance(max_bytes, int) or isinstance(max_bytes, bool)
        or not 0 < max_bytes <= MAX_ARCHIVE_BYTES
    ):
        raise ValueError("invalid Section-38 member byte budget")
    if (
        not member or member in (".", "..") or "/" in member or "\\" in member
        or member.startswith(".") or PurePosixPath(member).name != member
    ):
        raise ValueError("expected archive member must be one regular filename")
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("source ZIP is missing or indirect")
    if not 0 < archive.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise ValueError("source ZIP exceeds archive byte budget")
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination already exists")
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("destination parent is missing or indirect")
    temporary = None
    try:
        with zipfile.ZipFile(archive, "r", allowZip64=True) as zf:
            entries = zf.infolist()
            if not 1 <= len(entries) <= 4096:
                raise ValueError("unsafe ZIP member count")
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                if (
                    not name or name.startswith(("/", "\\"))
                    or "\\" in name or ":" in name or "\x00" in name
                    or any(part in (".", "..") for part in name.split("/"))
                    or path.is_absolute()
                ):
                    raise ValueError("unsafe ZIP member name")
            matching = [entry for entry in entries if entry.filename == member]
            if len(matching) != 1:
                raise ValueError("expected ZIP member missing or duplicated")
            entry = matching[0]
            mode = entry.external_attr >> 16
            if (
                entry.is_dir() or entry.flag_bits & 1
                or stat.S_ISLNK(mode)
                or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                or not 0 < entry.file_size <= max_bytes
            ):
                raise ValueError("expected ZIP member is unsafe or exceeds budget")
            digest = hashlib.sha256()
            written = 0
            fd, temp_name = tempfile.mkstemp(prefix=".section38-", suffix=".partial", dir=parent)
            temporary = Path(temp_name)
            with os.fdopen(fd, "wb") as sink, zf.open(entry, "r") as source:
                while True:
                    chunk = source.read(min(1024 * 1024, max_bytes - written + 1))
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise ValueError("decompressed ZIP member exceeded budget")
                    sink.write(chunk)
                    digest.update(chunk)
                sink.flush()
                os.fsync(sink.fileno())
            if written != entry.file_size:
                raise ValueError("ZIP member size mismatch")
        if destination.exists() or destination.is_symlink():
            raise ValueError("destination appeared during extraction")
        os.replace(temporary, destination)
        temporary = None
        return digest.hexdigest()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("member")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--max-bytes", type=int, required=True)
    opts = parser.parse_args()
    print(extract_member(opts.archive, opts.member, opts.destination, max_bytes=opts.max_bytes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

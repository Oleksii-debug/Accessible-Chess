from __future__ import annotations

"""Accessible offline command-line entry point for qualified Section54 previews.

Explicit local-only user invocation, no network/API calls, no public release.
Outputs are private and created without silently replacing existing artifacts.
A complete product UI/Windows/NVDA acceptance remains outside this adapter.
"""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Sequence

from .format_factory_conversion import FactoryConversionError, convert_factory_book_private
from .format_factory_intake import MAX_FACTORY_SOURCE_BYTES
from .format_factory_policy import FactoryJobPolicy, FactoryPolicyError, FactorySelection


def _read_input(path_text: str) -> tuple[bytes, str]:
    path = Path(path_text)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Source path must be an explicit absolute non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        # Compare pathname identity with the actual opened descriptor, not only
        # the descriptor with itself. On Windows O_NOFOLLOW is unavailable;
        # a path may be replaced after the initial non-symlink check.
        pathname_before = os.lstat(path)
        if not stat.S_ISREG(pathname_before.st_mode):
            raise ValueError("Source is not a regular file")
        fd = os.open(path, flags)
        try:
            meta = os.fstat(fd)
            def identity(item: os.stat_result) -> tuple[int, int, int, int]:
                return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
            if identity(pathname_before) != identity(meta):
                raise ValueError("Source pathname changed before opening")
            if not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= MAX_FACTORY_SOURCE_BYTES:
                raise ValueError("Source file is empty, too large, or not a regular file")
            with os.fdopen(fd, "rb", closefd=False) as source:
                content = source.read(MAX_FACTORY_SOURCE_BYTES + 1)
                if not content or len(content) > MAX_FACTORY_SOURCE_BYTES:
                    raise ValueError("Source changed or exceeded the supported byte limit")
                if source.read(1):
                    raise ValueError("Source file grew during read")
            after = os.fstat(fd)
            if identity(meta) != identity(after):
                raise ValueError("Source changed during read")
            # Revalidate the pathname after reading, including a path swap
            # which would not change fstat() on the still-open descriptor.
            pathname_after = os.lstat(path)
            if identity(after) != identity(pathname_after):
                raise ValueError("Source pathname changed during read")
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValueError("Source file cannot be read privately") from exc
    return content, path.name


def _private_directory(path_text: str) -> Path:
    out = Path(path_text)
    if not out.is_absolute() or out.is_symlink() or not out.is_dir():
        raise ValueError("Output directory must already exist and must not be a symlink")
    return out


def _write_atomic_new(directory: Path, name: str, payload: bytes) -> Path:
    """Publish one complete verified file, refusing any existing target.

    Temp and target are on the same filesystem. A hardlink publishes a complete
    fsynced file atomically only when the final name does not already exist.
    """
    destination = directory / name
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError("Invalid generated output filename")
    fd, temporary = tempfile.mkstemp(prefix=".section54-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as result:
            result.write(payload)
            result.flush()
            os.fsync(result.fileno())
        os.link(temporary, destination)
        return destination
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def run_offline_private_factory(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m acs.format_factory_cli",
        description="Section 54: private source-verified, no-network book preview (PARTIAL).",
    )
    parser.add_argument("--source", required=True, help="Absolute path to your own book")
    parser.add_argument("--output-dir", required=True, help="Existing private absolute directory")
    parser.add_argument("--language", required=True, help="Explicit original language: uk/en/etc.")
    parser.add_argument("--format", action="append", choices=("html", "txt", "epub3", "docx"),
                        required=True, dest="formats", help="Repeat for multiple output formats")
    parser.add_argument("--scope", choices=("all", "chapters"), default="all")
    parser.add_argument("--ranges", default="", help="For chapters: 1-3,5,8-12")
    parser.add_argument("--chapter-heading-level", type=int)
    parser.add_argument("--modified-utc", help="Required for EPUB3/DOCX: YYYY-MM-DDTHH:MM:SSZ")
    parser.add_argument("--allow-semantic-loss", action="store_true",
                        help="Acknowledge explicit lossy formats, such as TXT headings/diagram art")
    options = parser.parse_args(argv)
    written: list[Path] = []
    try:
        directory = _private_directory(options.output_dir)
        source, filename = _read_input(options.source)
        selection = FactorySelection.from_text(options.scope, options.ranges)
        digest = sha256(source).hexdigest()
        policy = FactoryJobPolicy(
            source_sha256=digest, source_id="offline-" + digest[:20],
            selection=selection, output_formats=tuple(options.formats),
            output_language=options.language,
        )
        result = convert_factory_book_private(
            source, source_name=filename, policy=policy,
            source_language=options.language,
            chapter_heading_level=options.chapter_heading_level,
            epub_modified_utc=options.modified_utc,
            docx_modified_utc=options.modified_utc,
            allow_semantic_loss=options.allow_semantic_loss,
        )
        base = "section54-" + digest[:20] + "-" + result.policy_sha256[:20]
        extension = {"html": "html", "txt": "txt", "epub3": "epub", "docx": "docx"}
        requested = [base + "." + extension[x.output_format] for x in result.outputs]
        requested.append(base + ".manifest.json")
        if len(set(requested)) != len(requested) or any((directory / name).exists() for name in requested):
            raise ValueError("Identical private output already exists; choose an empty output directory")
        manifest = {
            "schema": "section54-private-preview-v1",
            "status": "PARTIAL_PREVIEW_ONLY",
            "public_release_approved": False,
            "source_sha256": result.source_sha256,
            "policy_sha256": result.policy_sha256,
            "import_format": result.import_format,
            "selected_block_count": result.selected_block_count,
            "outputs": [
                {"file": name, "format": item.output_format,
                 "sha256": item.output_sha256, "bytes": len(item.output_bytes),
                 "losses": list(item.losses)}
                for name, item in zip(requested, result.outputs)
            ],
        }
        entries = [(name, item.output_bytes) for name, item in zip(requested, result.outputs)]
        entries.append((requested[-1], (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))
        for name, data in entries:
            written.append(_write_atomic_new(directory, name, data))
    except (ValueError, OSError, FactoryPolicyError, FactoryConversionError) as exc:
        for path in reversed(written):
            try:
                path.unlink()
            except OSError:
                pass
        print("SECTION 54 ERROR: private preview refused; no completed output reported.", file=sys.stderr)
        return 2
    print("SECTION 54 PRIVATE PREVIEW: " + str(len(result.outputs)) + " format(s) saved.")
    for item in result.outputs:
        print("  " + item.output_format + ": " + str(len(item.output_bytes)) + " bytes, SHA256 " + item.output_sha256)
    print("  Manifest: " + requested[-1])
    print("  Status: PARTIAL PREVIEW. Public release NOT authorized.")
    return 0


def main() -> None:
    raise SystemExit(run_offline_private_factory())


if __name__ == "__main__":
    main()

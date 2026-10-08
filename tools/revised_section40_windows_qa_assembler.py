"""Compose a disposable Section 40 Windows TEST_BUILD via canonical release assembler.

This is source/fixture QA engineering: NOT an owner-approved EXE or LIVE release.
Preserve existing owner PGN seeds byte-for-byte; all outputs are separately named.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from acs.acsdb import AcsDatabase
from acs.user_library_seed import (
    BUNDLE_KIND, MANIFEST_NAME, SCHEMA_VERSION,
    import_user_library_seed, load_user_library_seed,
)
from acs.version2_package_assembler import (
    _copy_tree, assemble_version2_package_tree, write_version2_package_zip,
)
from .revised_section40_offline_test_library import OfflineCollectionError
from .revised_section40_user_library_seed_bridge import build_owner_test_seed

_SOURCE_MEMBERS = (
    "section40-lichess-4-annotated-games.pgn",
    "section40-stockfish-512-real-games.pgn",
)
_ARCHIVE_ROOT = "release-content/user-library-seed/"


def build_section40_windows_test_package(
    prepared_product: Path,
    third_party_notices: Path,
    verified_collection_zip: Path,
    output_zip: Path,
    *,
    exact_source_sha: str,
) -> dict:
    """Add 516 actual games to prebuilt prepared product, then invoke V2 core.

    Reuses the canonical package checker/writer and canonical startup importer.
    This deliberately creates an independent QA ZIP, not a replacement for
    the public release or an overwrite of an owner's installed application.
    """
    output_zip = Path(output_zip)
    if output_zip.exists() or output_zip.is_symlink():
        raise OfflineCollectionError("Section 40 owner test ZIP already exists")
    if (type(exact_source_sha) is not str or len(exact_source_sha) != 40
        or any(c not in "0123456789abcdef" for c in exact_source_sha)):
        raise OfflineCollectionError("exact source commit SHA required")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="section40-windows-qa-", dir=output_zip.parent
    ) as scratch:
        work = Path(scratch)
        prepared = work / "prepared-product"
        _copy_tree(Path(prepared_product), prepared, label="existing prepared EXE product")
        imported_zip = work / "reviewed-owner-seed.zip"
        isolated = build_owner_test_seed(Path(verified_collection_zip), imported_zip)
        if isolated["game_count"] != 516 or isolated["source_count"] != 2:
            raise OfflineCollectionError("Section 40 corpus source identity changed")
        seed = prepared / "release-content" / "user-library-seed"
        baseline_rows: list[dict] = []
        if seed.exists() or seed.is_symlink():
            baseline = load_user_library_seed(seed)
            baseline_rows = [
                {
                    "file": item.file_name,
                    "display_name": item.display_name,
                    "bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in baseline.entries
            ]
        else:
            seed.parent.mkdir(parents=True, exist_ok=True)
            seed.mkdir()
        known = {item["file"].casefold() for item in baseline_rows}
        with zipfile.ZipFile(imported_zip) as archive:
            expected = {
                _ARCHIVE_ROOT + MANIFEST_NAME,
                *(_ARCHIVE_ROOT + name for name in _SOURCE_MEMBERS),
            }
            if set(archive.namelist()) != expected:
                raise OfflineCollectionError("canonical seed ZIP identity mismatches")
            new = json.loads(archive.read(_ARCHIVE_ROOT + MANIFEST_NAME))
            if (new.get("schema_version") != SCHEMA_VERSION
                or new.get("bundle_kind") != BUNDLE_KIND
                or new.get("runtime_network_required") is not False
                or new.get("ai_required") is not False
                or len(new.get("files", [])) != 2):
                raise OfflineCollectionError("canonical owner seed manifest invalid")
            if {item.get("file") for item in new["files"]} != set(_SOURCE_MEMBERS):
                raise OfflineCollectionError("unverified Section 40 PGN source member")
            for item in new["files"]:
                name = item["file"]
                if name.casefold() in known:
                    raise OfflineCollectionError("Section 40 would overwrite existing seed")
                known.add(name.casefold())
                body = archive.read(_ARCHIVE_ROOT + name)
                if (len(body) != item["bytes"]
                    or hashlib.sha256(body).hexdigest() != item["sha256"]):
                    raise OfflineCollectionError("Section 40 PGN seed bytes changed")
                with (seed / name).open("xb") as handle:
                    handle.write(body)
        merged = {
            "schema_version": SCHEMA_VERSION,
            "bundle_kind": BUNDLE_KIND,
            "runtime_network_required": False,
            "ai_required": False,
            "files": [*baseline_rows, *new["files"]],
        }
        (seed / MANIFEST_NAME).write_text(
            json.dumps(merged, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        ready = load_user_library_seed(seed)
        probe = work / "library-restart-test.acsdb"
        with AcsDatabase(probe) as db:
            first = import_user_library_seed(db, ready)
            db.verify_integrity()
        with AcsDatabase(probe) as reopened:
            second = import_user_library_seed(reopened, ready)
            reopened.verify_integrity()
        if (first.source_count != len(merged["files"])
            or first.reused_source_count != 0
            or first.game_count < 516
            or second.game_count != first.game_count
            or second.reused_source_count != first.source_count):
            raise OfflineCollectionError("merged real Library startup/restart failed")
        assembled = assemble_version2_package_tree(
            prepared, Path(third_party_notices), work / "canonical-qa-package",
            integration_sha=exact_source_sha,
        )
        archived = write_version2_package_zip(
            assembled.package_root,
            output_zip,
            expected_integration_sha=exact_source_sha,
        )
        if not output_zip.is_file() or output_zip.stat().st_size < 1:
            raise OfflineCollectionError("canonical Section 40 Windows test ZIP missing")
        return {
            "schema": "acs-section40-owner-windows-test-package-v1",
            "profile": "TEST_BUILD_ONLY_NOT_PUBLIC_RELEASE",
            "source_sha": exact_source_sha,
            "seed_sources": first.source_count,
            "seed_games": first.game_count,
            "original_seed_files_untouched": len(baseline_rows),
            "section40_added_sources": 2,
            "section40_added_games": 516,
            "restart_reused_sources": second.reused_source_count,
            "zip_sha256": hashlib.sha256(output_zip.read_bytes()).hexdigest(),
            "canonical_version2_package_readback": True,
            "compiled_real_exe_attested": False,
            "owner_nvda_pass": False,
            "section40_done": False,
        }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared-product", type=Path, required=True)
    parser.add_argument("--notices", type=Path, required=True)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    print(json.dumps(build_section40_windows_test_package(
        args.prepared_product, args.notices, args.collection, args.zip,
        exact_source_sha=args.sha), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

"""Connect the genuine Section-40 offline TEST_BUILD collection to the existing
runtime user-Library-seed seam, without installing a second Library importer.

This prepares a *test-only drop-in*, not a public Windows release. It validates
the entire original collection receipt before producing any output, then uses
the real runtime seed validator and atomic canonical ACSDB importer.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile

from acs.acsdb import AcsDatabase
from acs.gametree import serialize_game
from acs.pgn_roundtrip import parse_pgn_text
from acs.user_library_seed import (
    BUNDLE_KIND, MANIFEST_NAME, SCHEMA_VERSION,
    import_user_library_seed, load_user_library_seed,
)
from .revised_section40_offline_test_library import OfflineCollectionError

_MAX_COLLECTION_BYTES = 80 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
_MAX_MEMBERS = 120
_LIBRARY_PGN = "library/real-stockfish-first-512.pgn"
_SEED_PGN = "section40-stockfish-512-real-games.pgn"
_SEED_ROOT = "release-content/user-library-seed/"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_qualified_collection(source: Path) -> bytes:
    """Fail closed on changed/unsafe ZIPs, metadata, rights, or corpus identity."""
    try:
        before = source.lstat()
        if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
            or getattr(before, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            or not 1 <= before.st_size <= _MAX_COLLECTION_BYTES):
            raise OfflineCollectionError("unsafe Section 40 input ZIP")
        with source.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not os.path.samestat(before, opened) or opened.st_size != before.st_size:
                raise OfflineCollectionError("Section 40 source identity changed")
            with zipfile.ZipFile(stream) as archive:
                entries = archive.infolist()
                if not 1 <= len(entries) <= _MAX_MEMBERS:
                    raise OfflineCollectionError("Section 40 ZIP member count invalid")
                names = set()
                total = 0
                for info in entries:
                    name = info.filename
                    parts = PurePosixPath(name).parts
                    if (not name or name.startswith("/") or "\\" in name
                        or any(part in {"", ".", ".."} for part in parts)
                        or ":" in name or name.casefold() in names
                        or info.is_dir()
                        or (info.external_attr >> 16) & 0o170000
                           not in (0, stat.S_IFREG)
                        or info.compress_type != zipfile.ZIP_DEFLATED
                        or info.file_size > _MAX_UNCOMPRESSED_BYTES):
                        raise OfflineCollectionError("unsafe Section 40 ZIP member")
                    names.add(name.casefold())
                    total += info.file_size
                    if total > _MAX_UNCOMPRESSED_BYTES:
                        raise OfflineCollectionError("Section 40 expanded budget exceeded")
                if "catalog/checksums.json" not in archive.namelist():
                    raise OfflineCollectionError("Section 40 receipts absent")
                receipts = json.loads(archive.read("catalog/checksums.json"))
                if (type(receipts) is not list
                    or len(receipts) != len(entries) - 1):
                    raise OfflineCollectionError("Section 40 receipts malformed")
                receipt_names = set()
                for row in receipts:
                    if (type(row) is not dict
                        or set(row) != {"path", "sha256", "bytes"}
                        or type(row["path"]) is not str
                        or row["path"] == "catalog/checksums.json"
                        or row["path"] in receipt_names
                        or type(row["sha256"]) is not str
                        or len(row["sha256"]) != 64
                        or type(row["bytes"]) is not int
                        or row["bytes"] < 0):
                        raise OfflineCollectionError("Section 40 receipt identity invalid")
                    receipt_names.add(row["path"])
                    content = archive.read(row["path"])
                    if len(content) != row["bytes"] or _sha(content) != row["sha256"]:
                        raise OfflineCollectionError("Section 40 archive content changed")
                if receipt_names != set(archive.namelist()) - {"catalog/checksums.json"}:
                    raise OfflineCollectionError("Section 40 receipt inventory mismatch")
                report = json.loads(archive.read("catalog/materials.json"))
                if (type(report) is not dict
                    or report.get("profile") != "TEST_BUILD"
                    or report.get("schema") != "acs-revised-section40-offline-collection-v1"
                    or report.get("real_import_readback", {}).get("game_count") != 512):
                    raise OfflineCollectionError("only verified 512-game TEST_BUILD is seedable")
                sources = [
                    x for x in report["materials"]
                    if x.get("id") == "stockfish_2moves_v2_pgn_zip"
                ]
                if (len(sources) != 1
                    or not str(sources[0].get("license", "")).startswith("CC0")
                    or sources[0].get("redistribution") != "permitted"):
                    raise OfflineCollectionError("Section 40 source rights unverified")
                raw = archive.read(_LIBRARY_PGN)
                if _sha(raw) != report["real_import_readback"]["derivative_pgn_sha256"]:
                    raise OfflineCollectionError("Section 40 game corpus identity invalid")
            after_open = os.fstat(stream.fileno())
        after = source.lstat()
        if (not os.path.samestat(before, after_open)
            or not os.path.samestat(before, after)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns):
            raise OfflineCollectionError("Section 40 input mutated during audit")
        return raw
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        if isinstance(exc, OfflineCollectionError):
            raise
        raise OfflineCollectionError("Section 40 input collection cannot be trusted") from exc


def build_owner_test_seed(collection_zip: Path, output_zip: Path) -> dict:
    """Publish validated runtime-ready QA seed as a separate no-overwrite ZIP.

    Its release-content folder is copied *beside* the application executable by
    a packaging integrator. Never replaces the owner's existing Library seed.
    """
    output_zip = Path(output_zip)
    if output_zip.exists() or output_zip.is_symlink():
        raise OfflineCollectionError("Section 40 seed output already exists")
    original = _read_qualified_collection(Path(collection_zip))
    try:
        original_games = parse_pgn_text(original.decode("utf-8"), strict=False)
        if len(original_games) != 512 or any(not game.line.moves for game in original_games):
            raise OfflineCollectionError("original corpus lost canonical games")
        # This exact normalization is required by the existing startup seed
        # contract. The original 512-game PGN may parse in recovery mode but
        # fail strict; reuse the canonical serializer instead of hand-repairing.
        canonical = ("\\n\\n".join(serialize_game(game).rstrip()
                                     for game in original_games) + "\\n").encode("utf-8")
        checked = parse_pgn_text(canonical.decode("utf-8"), strict=True)
        if len(checked) != 512 or any(not game.line.moves for game in checked):
            raise OfflineCollectionError("normalized owner Library seed is not strict PGN")
    except (UnicodeError, ValueError) as exc:
        raise OfflineCollectionError("canonical Library seed normalization failed") from exc
    pgn = canonical
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="section40-seed-", dir=output_zip.parent) as scratch:
        work = Path(scratch)
        seed = work / "release-content" / "user-library-seed"
        seed.mkdir(parents=True)
        (seed / _SEED_PGN).write_bytes(pgn)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "bundle_kind": BUNDLE_KIND,
            "runtime_network_required": False,
            "ai_required": False,
            "files": [{
                "file": _SEED_PGN,
                "display_name": "Accessible Chess Section 40: 512 verified Stockfish CC0 games",
                "bytes": len(pgn),
                "sha256": _sha(pgn),
            }],
        }
        (seed / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        validated = load_user_library_seed(seed)
        with AcsDatabase(work / "qa-import.acsdb") as db:
            first = import_user_library_seed(db, validated)
            db.verify_integrity()
        # Actual SQLite process-boundary readback, not same-handle reimport.
        with AcsDatabase(work / "qa-import.acsdb") as reopened:
            again = import_user_library_seed(reopened, validated)
            reopened.verify_integrity()
        if (first.source_count != 1 or first.game_count != 512
            or first.reused_source_count != 0
            or again.reused_source_count != 1
            or again.game_count != 512):
            raise OfflineCollectionError("runtime seed import/restart/reuse failed")
        temp_zip = work / "seed.zip"
        with zipfile.ZipFile(temp_zip, "x", compression=zipfile.ZIP_DEFLATED) as out:
            for path in (seed / MANIFEST_NAME, seed / _SEED_PGN):
                name = _SEED_ROOT + path.name
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                out.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(temp_zip) as check:
            if set(check.namelist()) != {
                _SEED_ROOT + MANIFEST_NAME, _SEED_ROOT + _SEED_PGN
            } or check.read(_SEED_ROOT + _SEED_PGN) != pgn:
                raise OfflineCollectionError("runtime seed output ZIP readback failed")
        try:
            os.link(temp_zip, output_zip)
        except OSError as exc:
            raise OfflineCollectionError("runtime seed atomic publish failed") from exc
    return {
        "profile": "OWNER_TEST_LIBRARY_SEED",
        "game_count": 512, "source_count": 1,
        "readback": "CANONICAL_RUNTIME_SEED_ACSDB_RESTART_AND_REUSE_PASS",
        "archive_sha256": _sha(output_zip.read_bytes()),
        "source_pgn_sha256": _sha(original),
        "normalized_strict_pgn_sha256": _sha(pgn),
        "owner_accepted": False, "section40_done": False,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Prepare actual runtime Library seed from Section 40 QA ZIP")
    parser.add_argument("collection_zip", type=Path)
    parser.add_argument("output_zip", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_owner_test_seed(args.collection_zip, args.output_zip),
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

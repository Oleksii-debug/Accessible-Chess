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
from acs.gametree import serialize_game
from acs.pgn_roundtrip import parse_pgn_text
from acs.lawful_corpus_registry import load_catalog, read_verified_source_snapshot
from acs.user_library_seed import (
    BUNDLE_KIND, MANIFEST_NAME, SCHEMA_VERSION,
    import_user_library_seed, load_user_library_seed,
)
from acs.version2_package_assembler import (
    _copy_file, _copy_tree, assemble_version2_package_tree, write_version2_package_zip,
)
from .revised_section40_offline_test_library import OfflineCollectionError, ROOT
from .revised_section40_user_library_seed_bridge import (
    _read_qualified_collection, build_owner_test_seed,
)

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
        # The owner QA corpus additionally carries one genuinely authored
        # historical Réti endgame study. It is NOT a modern copyrighted
        # composed-study collection or a fabricated puzzle rating.
        original_study_id = "historical_reti_1921_original_bilingual_study_pgn"
        originals = load_catalog(ROOT / "docs/corpus/revised_sections37_40_sources.json")
        matches = [row for row in originals if row.get("id") == original_study_id]
        if len(matches) != 1:
            raise OfflineCollectionError("verified historical endgame study absent")
        historical = matches[0]
        if (historical.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
            or historical.get("public_release") != "INCLUDED_OWN_TEXT_HISTORICAL_COMPOSITION"
            or not str(historical.get("redistribution", "")).startswith("permitted")):
            raise OfflineCollectionError("historical study source rights not qualified")
        study = read_verified_source_snapshot(
            ROOT / historical["local_source"], historical)
        with zipfile.ZipFile(verified_collection_zip) as collected:
            if collected.read("library/original-reti-1921-uk-en-study.pgn") != study:
                raise OfflineCollectionError("historical study corpus/source bytes differ")
        studies = parse_pgn_text(study.decode("utf-8"), strict=False)
        if (len(studies) != 1
            or studies[0].tags.get("FEN") != "7K/8/k1P5/7p/8/8/8/8 w - - 0 1"
            or studies[0].tags.get("SetUp") != "1"
            or len(studies[0].line.moves) != 11):
            raise OfflineCollectionError("historical study semantics have changed")
        study_wire = (serialize_game(studies[0]).rstrip() + "\n").encode("utf-8")
        if len(parse_pgn_text(study_wire.decode("utf-8"), strict=True)) != 1:
            raise OfflineCollectionError("historical study strict PGN export failed")
        study_name = "section40-original-reti-1921-uk-en-study.pgn"
        if study_name.casefold() in known:
            raise OfflineCollectionError("historical endgame study would overwrite owner data")
        (seed / study_name).write_bytes(study_wire)
        historical_entry = {
            "file": study_name,
            "display_name": "Original Réti 1921 endgame study (UK and EN)",
            "bytes": len(study_wire),
            "sha256": hashlib.sha256(study_wire).hexdigest(),
        }
        merged = {
            "schema_version": SCHEMA_VERSION,
            "bundle_kind": BUNDLE_KIND,
            "runtime_network_required": False,
            "ai_required": False,
            "files": [*baseline_rows, *new["files"], historical_entry],
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
            or first.game_count < 517
            or second.game_count != first.game_count
            or second.reused_source_count != first.source_count):
            raise OfflineCollectionError("merged real Library startup/restart failed")
        # Keep the rich TEST_COLLECTION physically beside the Windows program
        # (rather than silently leaving Books/Training/FEN/corpus files elsewhere).
        # The application consumes canonical PGN seed automatically; the separate
        # original ZIP remains available for lawful offline format testing.
        materials = prepared / "release-content" / "section40"
        if materials.exists() or materials.is_symlink():
            raise OfflineCollectionError("Section 40 test content destination exists")
        materials.mkdir()
        copied = materials / "TEST_COLLECTION.zip"
        _copy_file(
            Path(verified_collection_zip), copied,
            label="prequalified licensed Section 40 test collection",
        )
        # Re-verify complete member receipts, bounded ZIP, real source identities,
        # and rights on the COPIED bytes before the package is published.
        if (_read_qualified_collection(copied)
            != _read_qualified_collection(Path(verified_collection_zip))):
            raise OfflineCollectionError("qualified Section 40 source archive changed")
        original_checksum = hashlib.sha256(
            Path(verified_collection_zip).read_bytes()
        ).hexdigest()
        copied_checksum = hashlib.sha256(copied.read_bytes()).hexdigest()
        if original_checksum != copied_checksum:
            raise OfflineCollectionError("copied offline corpus ZIP checksum differs")
        (materials / "READ_FIRST_UK.txt").write_text(
            "Accessible Chess — тимчасова перевірочна колекція Section 40.\n"
            "Ця Windows-комплектація тільки для тестів. НЕ є публічним релізом.\n"
            "Вбудована штатна Library має імпортувати 512 реальних партій Stockfish, "
            "4 оригінальні анотовані партії Lichess і 1 історичний етюд Réti "
            "(усього 517 нових партій/позицій; за наявності старих джерел вони зберігаються).\n"
            "Файл TEST_COLLECTION.zip містить каталог, українські й англійські "
            "BookDocument, вправи, PGN, додаткові формати й ліцензії для тестування.\n"
            "Для NVDA: запускайте AccessibleChess.exe з папки AccessibleChess, "
            "перейдіть до Бібліотеки, Книг або Тренування штатною навігацією. "
            "Тести необхідно підтвердити на реальному Windows EXE.\n"
            "НЕ очищайте тестові дані до власного підтвердження приймання.\n",
            encoding="utf-8",
        )
        (materials / "READ_FIRST_EN.txt").write_text(
            "Accessible Chess — temporary Section 40 offline TEST collection.\n"
            "This Windows package is FOR TESTING ONLY, not a public release.\n"
            "The canonical Library startup seed contains 512 real Stockfish mini-games, "
            "four genuine annotated Lichess games and one historical Reti study "
            "(517 additional games/positions); existing owner PGN sources are preserved.\n"
            "TEST_COLLECTION.zip includes a licensed catalogue, Ukrainian/English "
            "BookDocuments, training cases, PGN and other qualified test formats.\n"
            "For screen-reader testing use AccessibleChess.exe in AccessibleChess "
            "and the product's existing Library, Books and Training navigation.\n"
            "Actual Windows EXE/NVDA tests remain required before claiming DONE.\n"
            "Do not delete test materials until the owner has accepted them.\n",
            encoding="utf-8",
        )
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
            "section40_added_sources": 3,
            "section40_added_games": 517,
            "restart_reused_sources": second.reused_source_count,
            "zip_sha256": hashlib.sha256(output_zip.read_bytes()).hexdigest(),
            "bundled_offline_collection_sha256": copied_checksum,
            "bilingual_test_instructions": True,
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

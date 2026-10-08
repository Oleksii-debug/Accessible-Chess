"""Section 39 -> 40 integration qualification of actually built offline archives.

Reopen TEST_BUILD, PUBLIC_RELEASE and runtime user Library seed bytes from
independent files, using canonical ACSDB, BookDocument and Library-seed imports.
No owner acceptance, EXE or hosted CI-success claim is inferred from this
machine evidence, and restricted third-party source bytes stay excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import zipfile

from acs.acsdb import AcsDatabase
from acs.bookdocument import BookDocument
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from acs.user_library_seed import MANIFEST_NAME, import_user_library_seed, load_user_library_seed
from tools.revised_section40_user_library_seed_bridge import _read_qualified_collection
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head

REPORT = ROOT / "section39-section40-real-packaged-integration.json"
MAX_ZIP = 80 * 1024 * 1024
MAX_MEMBERS = 180
OWNER_FILES = (
    "release-content/user-library-seed/manifest.json",
    "release-content/user-library-seed/section40-stockfish-512-real-games.pgn",
    "release-content/user-library-seed/section40-lichess-4-annotated-games.pgn",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inspect_zip(path: Path) -> tuple[dict[str, bytes], str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ZIP:
        raise LawfulCorpusError("unsafe or oversized packaged corpus")
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_MEMBERS:
            raise LawfulCorpusError("packaged corpus member count invalid")
        expanded = 0
        folded: set[str] = set()
        for info in infos:
            name = info.filename
            if (
                not name or name.startswith("/") or "\\" in name or ":" in name
                or any(p in ("", ".", "..") for p in name.split("/"))
                or name.casefold() in folded or info.is_dir()
                or (info.external_attr >> 16) & 0o170000 not in (0, stat.S_IFREG)
                or info.file_size > MAX_ZIP
            ):
                raise LawfulCorpusError("unsafe packaged chess member path, type or size")
            folded.add(name.casefold())
            expanded += info.file_size
            if expanded > MAX_ZIP:
                raise LawfulCorpusError("oversized decompressed chess package")
            raw = archive.read(info)
            if len(raw) != info.file_size:
                raise LawfulCorpusError("package decompression was incomplete")
            entries[name] = raw
    return entries, _sha(path.read_bytes())


def _catalog_data(files: dict[str, bytes], expected_profile: str) -> dict:
    if "catalog/materials.json" not in files or "catalog/checksums.json" not in files:
        raise LawfulCorpusError("offline chess package lacks complete source manifest")
    meta = json.loads(files["catalog/materials.json"])
    if (meta.get("profile") != expected_profile
        or meta.get("schema") != "acs-revised-section40-offline-collection-v1"
        or meta.get("owner_accepted") is not False
        or meta.get("section40_done") is not False):
        raise LawfulCorpusError("test/public rights profile or acceptance status forged")
    receipts = json.loads(files["catalog/checksums.json"])
    if not isinstance(receipts, list) or len(receipts) != len(files) - 1:
        raise LawfulCorpusError("archive checksum ledger count differs from files")
    seen: set[str] = set()
    for item in receipts:
        if (
            type(item) is not dict
            or set(item) != {"path", "sha256", "bytes"}
            or item["path"] not in files or item["path"] in seen
            or item["path"] == "catalog/checksums.json"
            or type(item["bytes"]) is not int or type(item["sha256"]) is not str
            or item["bytes"] != len(files[item["path"]])
            or item["sha256"] != _sha(files[item["path"]])
        ):
            raise LawfulCorpusError("archive source checksum ledger is invalid")
        seen.add(item["path"])
    if seen != (set(files) - {"catalog/checksums.json"}):
        raise LawfulCorpusError("archive receipt inventory differs from actual ZIP")
    return meta


def qualify_built_delivery(test_path: Path, public_path: Path,
                           owner_path: Path) -> dict:
    """All three distinct real zip files must reopen and preserve semantics."""
    # The owner seam authenticates original PGN bytes independently, including
    # catalog/profile, before this function reads the packaged output.
    original_stockfish, original_annotated = _read_qualified_collection(test_path)
    tests, test_hash = _inspect_zip(test_path)
    public, public_hash = _inspect_zip(public_path)
    owner, owner_hash = _inspect_zip(owner_path)
    if len({test_hash, public_hash, owner_hash}) != 3:
        raise LawfulCorpusError("test, public and runtime seed packages are not distinct")
    trial = _catalog_data(tests, "TEST_BUILD")
    publish = _catalog_data(public, "PUBLIC_RELEASE")
    if set(owner) != set(OWNER_FILES):
        raise LawfulCorpusError("owner seed artifact has extra or missing runtime files")
    if (
        "library/real-stockfish-first-512.acsdb" not in tests
        or "library/real-lichess-four-annotated-original-games.pgn" not in tests
        or tests["library/real-lichess-four-annotated-original-games.pgn"] != original_annotated
        or "library/real-stockfish-first-512.pgn" not in tests
        or tests["library/real-stockfish-first-512.pgn"] != original_stockfish
        or any(k.startswith("library/") for k in public)
        or trial["real_import_readback"].get("total_database_games") != 516
        or publish.get("real_import_readback") is not None
    ):
        raise LawfulCorpusError("real 516-game TEST_BUILD / restricted PUBLIC_RELEASE diverge")
    catalogue = {row["id"]: row for row in load_catalog()}
    for profile, files, meta in (("TEST_BUILD", tests, trial),
                                 ("PUBLIC_RELEASE", public, publish)):
        for item in meta["materials"]:
            origin = catalogue.get(item["id"])
            if origin is not None:
                if (
                    item.get("license") != origin.get("license")
                    or item.get("redistribution") != origin.get("redistribution")
                    or item.get("size_bytes") != len(files[item["source_path"]])
                    or item.get("sha256") != _sha(files[item["source_path"]])
                    or (profile == "PUBLIC_RELEASE"
                        and origin.get("redistribution") != "permitted")
                ):
                    raise LawfulCorpusError("package changed original rights or material SHA")
    # Contents authored by this project are materialized in BookDocument form,
    # never conflated with the restricted original Gutenberg TXT.
    starter = BookDocument.from_dict(json.loads(tests["books/accessible-chess-starter-course.json"]))
    pub_starter = BookDocument.from_dict(json.loads(public["books/accessible-chess-starter-course.json"]))
    if starter.as_dict() != pub_starter.as_dict() or not starter.blocks:
        raise LawfulCorpusError("canonical BookDocument lost content between archive profiles")
    for key, minimum in (
        ("training/advanced-lichess-16-middlegame-endgame.json", 16),
        ("training/extreme-lichess-4-original-puzzles.json", 4),
    ):
        tasks = json.loads(tests[key])["tasks"]
        same = json.loads(public[key])["tasks"]
        if len(tasks) != minimum or tasks != same:
            raise LawfulCorpusError("genuine Section37 advanced source did not enter both packages")
    uncleared_ids = {e["id"] for e in catalogue.values()
                     if e.get("redistribution") != "permitted"
                     or e.get("public_release") in ("EXCLUDED", "EXCLUDED_PENDING_QUALIFICATION")}
    public_source_ids = {row["id"] for row in publish["materials"]}
    if public_source_ids & uncleared_ids:
        raise LawfulCorpusError("uncleared original source entered public offline package")
    if any("gitenberg_" in name or "chessbase_" in name for name in public):
        raise LawfulCorpusError("uncleared original copyrighted binary included in public package")
    # A self-consistent checksums.json is not an authorization to smuggle
    # unknown files into the public distribution. Every payload needs a
    # published catalog material record or one explicitly approved metadata/
    # attribution path; a raw extra chess book is always a failure.
    allowed_public_payloads = {
        "catalog/materials.json", "catalog/checksums.json",
        "catalog/external-links.json", "README_UK.txt", "README_EN.txt",
        "licenses/ACCESSIBLE_CHESS_STARTER_UK.txt",
    }
    allowed_public_payloads.update(row["source_path"] for row in publish["materials"])
    allowed_public_payloads.update(
        row["license_path"] for row in publish["materials"]
        if "license_path" in row
    )
    if set(public) != allowed_public_payloads:
        raise LawfulCorpusError("unauthorized unregistered file entered public chess archive")

    external_links = json.loads(public["catalog/external-links.json"])
    if not any(x.get("id") == "gitenberg_capablanca_33870_original_txt" for x in external_links):
        raise LawfulCorpusError("legal external-only library catalog missing")
    # Reopen ACSDB archive bytes on a fresh connection, inspect source count,
    # and reopen the runtime seed through existing canonical production loader.
    with tempfile.TemporaryDirectory(prefix="acs39-section40-integration-") as temp:
        root = Path(temp)
        dbfile = root / "real-516-games.acsdb"
        dbfile.write_bytes(tests["library/real-stockfish-first-512.acsdb"])
        with AcsDatabase(dbfile) as db:
            db.verify_integrity()
            n = int(db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
            if n != 516:
                raise LawfulCorpusError("archived genuine Library database does not contain 516 games")
        seed_dir = root / "release-content" / "user-library-seed"
        seed_dir.mkdir(parents=True)
        for path, raw in owner.items():
            (seed_dir / path.rsplit("/", 1)[-1]).write_bytes(raw)
        seed = load_user_library_seed(seed_dir)
        for i in range(2):
            with AcsDatabase(root / "owner-seed-startup.acsdb") as db:
                imported = import_user_library_seed(db, seed)
                db.verify_integrity()
                if (imported.game_count != 516 or imported.source_count != 2
                    or imported.reused_source_count != (2 if i else 0)):
                    raise LawfulCorpusError("actual owner runtime seed failed canonical startup/restart")
    return {
        "schema": "acs-section39-40-actual-three-package-integration-v1",
        "archive_sha256": {"TEST_BUILD": test_hash,
                            "PUBLIC_RELEASE": public_hash, "OWNER_RUNTIME_SEED": owner_hash},
        "original_annotated_source_sha256": _sha(original_annotated),
        "real_stockfish_sample_sha256": _sha(original_stockfish),
        "real_library_games": 516,
        "original_annotated_games": 4,
        "advanced_training_original_tasks": 16,
        "extreme_training_original_tasks": 4,
        "book_document_reopen": "PASS",
        "runtime_user_library_restart": "PASS",
        "public_rights_separation": "PASS",
        "owner_nvda_verified": False,
        "windows_exe_packaged_verified": False,
        "section39_terminal_done": False,
        "section40_terminal_done": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    args = parser.parse_args()
    REPORT.unlink(missing_ok=True)
    sha = _source_head()
    result = qualify_built_delivery(args.test, args.public, args.seed)
    result["source_commit_sha"] = sha
    staged = REPORT.with_suffix(".tmp")
    try:
        staged.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
        os.replace(staged, REPORT)
    finally:
        staged.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": sha,
        "real_library_games": result["real_library_games"],
        "original_annotated_games": result["original_annotated_games"],
        "owner_runtime_reimport": result["runtime_user_library_restart"],
        "section39_done": False, "section40_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

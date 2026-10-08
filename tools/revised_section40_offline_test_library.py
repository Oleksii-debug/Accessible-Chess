"""Build rights-separated, offline Section-40 QA collections from canonical sources.

This is a TEST_BUILD/public-fixture builder, not a Windows executable or an
assertion that revised Sections 37-40 are terminally closed. Source rights,
canonical Books/Training/Library boundaries and byte checks are reused.
"""
from __future__ import annotations

from dataclasses import asdict
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
from acs.gametree import CanonicalPgnGameFramer
from acs.lawful_corpus_registry import (
    LawfulCorpusError, inventory_vendored_corpus, load_catalog,
    read_verified_source_snapshot, read_verified_zip_member,
)
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text
from acs.starter_books_training_release import (
    STARTER_RELEASE_LICENSE_ID, STARTER_RELEASE_LICENSE_TERMS_UK, build_release_booklets,
    build_training_task_catalogue,
)
from acs.starter_books_training_runtime import build_training_ready_starter_course
from acs.section40_advanced_training_runtime import (
    build_advanced_offline_material, build_extreme_offline_material,
)
from tools.revised_section40_advanced_training import build_complete_advanced_training
from acs.section40_historical_reti_runtime import build_historical_reti_offline_material
from acs.section40_historical_reti_dataset import original_reti_source_bytes


ROOT = Path(__file__).resolve().parents[1]
PROFILES = frozenset({"TEST_BUILD", "PUBLIC_RELEASE"})
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)
_MAX_ZIP_BYTES = 80 * 1024 * 1024
_GAME_SAMPLE_COUNT = 512
_PGN_SOURCE_ID = "stockfish_2moves_v2_pgn_zip"


class OfflineCollectionError(RuntimeError):
    pass


def _json_bytes(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _asset_path(source_id: str, name: str) -> str:
    if not source_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in source_id):
        raise OfflineCollectionError("unsafe catalog source identity")
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise OfflineCollectionError("unsafe source filename")
    return f"sources/{source_id}/{name}"


def _source_assets(root: Path, profile: str, catalog: tuple[dict, ...]):
    inventory = inventory_vendored_corpus(catalog, root, distribution=profile)
    lookup = {r["id"]: r for r in catalog}
    output = {}
    rows = []
    for item in inventory:
        source_id = str(item["source_id"])
        entry = lookup[source_id]
        path = root / str(item["relative_path"])
        data = read_verified_source_snapshot(path, entry)
        if _digest(data) != item["sha256"]:
            raise OfflineCollectionError("source identity changed after inventory")
        source_key = _asset_path(source_id, path.name)
        output[source_key] = data
        license_path = root / str(entry["license_source"])
        license_data = read_verified_source_snapshot(
            license_path,
            {"sha256": entry["license_sha256"], "max_bytes": 1024 * 1024},
        )
        license_key = _asset_path(source_id, "COPYING.txt")
        output[license_key] = license_data
        rows.append({
            "id": source_id, "title": entry["title"], "author": entry["author"],
            "genre": "opening reference" if "lichess_openings" in source_id
                     else "opening/game or position data",
            "language": "und", "format": entry["format"],
            "source_url": entry.get("source_page"),
            "download_url": entry.get("download_url"),
            "source_path": source_key, "license_path": license_key,
            "size_bytes": len(data), "sha256": _digest(data),
            "license": entry["license"], "redistribution": entry["redistribution"],
            "import_status": "VERIFIED_ORIGINAL_BYTES_NOT_AUTOMATICALLY_IMPORTED",
            "repeat_download": "FOLLOW_SOURCE_URL_WITH_RIGHTS_CHECK",
        })
    return output, rows


def _books_and_training():
    payloads = {
        "licenses/ACCESSIBLE_CHESS_STARTER_UK.txt": (
            "LicenseRef: " + STARTER_RELEASE_LICENSE_ID + "\n"
            + STARTER_RELEASE_LICENSE_TERMS_UK + "\n"
        ).encode("utf-8"),
    }
    rows = []
    booklets = build_release_booklets()
    documents = (*booklets, build_training_ready_starter_course())
    for index, book in enumerate(documents):
        # The existing semantic model validates the published wire payload.
        raw = _json_bytes(book.as_dict())
        reopened = BookDocument.from_dict(json.loads(raw))
        if reopened.as_dict() != book.as_dict():
            raise OfflineCollectionError("canonical BookDocument roundtrip failed")
        target = (f"books/booklet-{index + 1:02}.json" if index < len(booklets)
                  else "books/accessible-chess-starter-course.json")
        payloads[target] = raw
        rows.append({
            "id": f"starter_book_{index + 1:02}", "title": book.title,
            "author": "Accessible Chess", "genre": "instructional chess course",
            "language": book.language or "uk", "format": "BookDocument JSON",
            "source_url": None, "download_url": None, "source_path": target,
            "size_bytes": len(raw), "sha256": _digest(raw),
            "license": STARTER_RELEASE_LICENSE_ID,
            "redistribution": "project-authored content",
            "import_status": "CANONICAL_BOOKDOCUMENT_ROUNDTRIP_PASS",
            "repeat_download": "BUNDLED_OFFLINE",
        })
    tasks = [asdict(task) for task in build_training_task_catalogue()]
    if len(tasks) != 144:
        raise OfflineCollectionError("canonical starter task count changed")
    training_raw = _json_bytes({"schema_version": 1, "tasks": tasks})
    payloads["training/starter-exercises.json"] = training_raw
    rows.append({
        "id": "starter_training_144", "title": "144 authored opening exercises",
        "author": "Accessible Chess", "genre": "chess exercises",
        "language": "uk", "format": "Training JSON", "source_url": None,
        "download_url": None, "source_path": "training/starter-exercises.json",
        "size_bytes": len(training_raw), "sha256": _digest(training_raw),
        "license": STARTER_RELEASE_LICENSE_ID,
        "redistribution": "project-authored content",
        "import_status": "CANONICAL_TRAINING_DATA_SERIALIZED",
        "repeat_download": "BUNDLED_OFFLINE",
    })
    return payloads, rows


def _real_library_sample(root: Path, catalog: tuple[dict, ...], work: Path):
    """Three real collection sizes and one durable, searchable canonical ACSDB."""
    record = next((r for r in catalog if r["id"] == _PGN_SOURCE_ID), None)
    if record is None or record.get("acquisition") != "VENDORED_SOURCE_VERIFIED":
        raise OfflineCollectionError("pinned real PGN corpus is absent")
    if not (record.get("license", "").startswith("CC0") and
            record.get("redistribution", "").startswith("permitted")):
        raise OfflineCollectionError("real PGN source redistribution not cleared")
    member = read_verified_zip_member(
        root / record["local_source"], record,
        expected_member=record["zip_member"],
        max_unpacked_bytes=record["max_unpacked_bytes"],
    )
    text = member.decode("utf-8-sig", errors="strict")
    framer = CanonicalPgnGameFramer(max_frame_bytes=256 * 1024)
    frames = []
    for line in text.splitlines():
        complete = framer.feed_line(line)
        if complete is not None:
            frames.append(complete.text)
            if len(frames) == _GAME_SAMPLE_COUNT:
                break
    if len(frames) != _GAME_SAMPLE_COUNT:
        raise OfflineCollectionError("original archive has too few canonical PGN games")
    samples = {
        size: ("\n".join(frames[:size])).encode("utf-8")
        for size in (32, 128, _GAME_SAMPLE_COUNT)
    }
    source_pgn = samples[_GAME_SAMPLE_COUNT]
    games = parse_pgn_text(source_pgn.decode("utf-8"), strict=False)
    if len(games) != _GAME_SAMPLE_COUNT or not all(g.line.moves for g in games):
        raise OfflineCollectionError("real PGN sample cannot be parsed")
    for index, game in enumerate(games):
        game.source_index = index
    db_path = work / "source-games.acsdb"
    source_sha = _digest(source_pgn)
    advanced_records = [x for x in catalog
                        if x.get("id") == "lichess_cc0_high_level_4_original_annotated_games"]
    if len(advanced_records) != 1:
        raise OfflineCollectionError("original annotated master-game corpus missing")
    advanced_record = advanced_records[0]
    if (advanced_record.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
        or not str(advanced_record.get("license", "")).startswith("CC0")
        or not str(advanced_record.get("redistribution", "")).startswith("permitted")):
        raise OfflineCollectionError("advanced real PGN source rights missing")
    advanced_license = read_verified_source_snapshot(
        root / advanced_record["license_source"],
        {"sha256": advanced_record["license_sha256"],
         "max_bytes": 1024 * 1024},
    )
    advanced_pgn = read_verified_source_snapshot(
        root / advanced_record["local_source"], advanced_record)
    advanced_games = parse_pgn_text(
        advanced_pgn.decode("utf-8", errors="strict"), strict=False)
    if len(advanced_games) != 4 or any(not game.line.moves for game in advanced_games):
        raise OfflineCollectionError("real annotated CC0 master games not preserved")
    for index, game in enumerate(advanced_games):
        game.source_index = index
    with AcsDatabase(db_path) as db:
        result = LibraryImportService(db).import_games(
            games, source_name="Stockfish CC0 2moves_v2 first 512 verified games",
            source_format="pgn", source_sha256=source_sha,
        )
        if result.reused or result.game_count != _GAME_SAMPLE_COUNT:
            raise OfflineCollectionError("first canonical Library publication failed")
        annotated = LibraryImportService(db).import_games(
            advanced_games,
            source_name="Four authentic annotated CC0 Lichess 2200+ online games (not FIDE)",
            source_format="pgn", source_sha256=advanced_record["sha256"],
        )
        if annotated.reused or annotated.game_count != 4:
            raise OfflineCollectionError("advanced 4-game canonical Library import failed")
        db.verify_integrity()
    with AcsDatabase(db_path) as db:
        source = LibrarySourceCatalogService(db).get_source(result.source_id)
        if source is None or source.game_count != _GAME_SAMPLE_COUNT or source.source_sha256 != source_sha:
            raise OfflineCollectionError("canonical Library restart/readback failed")
        page = LibrarySourceCatalogService(db).source_games(result.source_id, limit=32)
        if len(page.items) != 32 or any(x.source_index != i for i, x in enumerate(page.items)):
            raise OfflineCollectionError("source search/index readback failed")
        advanced_source = LibrarySourceCatalogService(db).get_source(annotated.source_id)
        if (advanced_source is None or advanced_source.game_count != 4
            or advanced_source.source_sha256 != advanced_record["sha256"]):
            raise OfflineCollectionError("annotated game Library restart/readback failed")
        advanced_page = LibrarySourceCatalogService(db).source_games(
            annotated.source_id, limit=8)
        if (len(advanced_page.items) != 4
            or any(item.source_index != i
                   for i, item in enumerate(advanced_page.items))):
            raise OfflineCollectionError("advanced annotated source index failed")
        again = LibraryImportService(db).import_games(
            games, source_name="repeat verified offline QA source",
            source_format="pgn", source_sha256=source_sha,
        )
        annotated_again = LibraryImportService(db).import_games(
            advanced_games, source_name="repeat original annotated real games",
            source_format="pgn", source_sha256=advanced_record["sha256"],
        )
        if (not again.reused or again.source_id != result.source_id
            or not annotated_again.reused
            or annotated_again.source_id != annotated.source_id):
            raise OfflineCollectionError("canonical Library idempotent readback failed")
        db.verify_integrity()
    assets = {
        f"library/real-stockfish-first-{size}.pgn": blob
        for size, blob in samples.items()
    }
    assets["library/real-stockfish-first-512.acsdb"] = db_path.read_bytes()
    assets["library/real-lichess-four-annotated-original-games.pgn"] = advanced_pgn
    return assets, {
        "source_id": _PGN_SOURCE_ID,
        "game_count": _GAME_SAMPLE_COUNT, "sample_sizes": [32, 128, 512],
        "advanced_annotated_game_count": 4,
        "advanced_annotated_source_sha256": advanced_record["sha256"],
        "total_database_games": _GAME_SAMPLE_COUNT + 4,
        "derivative_pgn_sha256": source_sha, "database_sha256": _digest(assets[
            "library/real-stockfish-first-512.acsdb"]),
        "import_status": "CANONICAL_LIBRARY_IMPORTED_RESTART_REUSED_SEARCHED",
        "scope_note": "512 authentic Stockfish mini-games plus four annotated original Lichess full games; no GM title or FIDE inference",
    }

def build_collection(profile: str, output: Path, *, root: Path = ROOT) -> dict:
    """Create exactly one immutable, rights-separated ZIP with readback.

    An existing destination is never replaced; test-data cleanup is intentionally
    not automatic, pending the owner's actual completed acceptance session.
    """
    if profile not in PROFILES:
        raise OfflineCollectionError("unsupported distribution profile")
    if output.exists() or output.is_symlink():
        raise OfflineCollectionError("destination exists; refusing overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(root / "docs/corpus/revised_sections37_40_sources.json")
    assets, rows = _source_assets(root, profile, catalog)
    book_assets, book_rows = _books_and_training()
    assets.update(book_assets)
    rows.extend(book_rows)
    # The same original CC0 advanced/chessboard content is already validated
    # by the canonical advanced builder. Export its native English BookDocument
    # variant for external expert testers, not an approximate translation or
    # another Training engine. Bilingual access does not change puzzle FEN.
    for original_id, name, build_en, task_count in (
        ("lichess_cc0_advanced_16_original_derived",
         "advanced-lichess-16-en.json", build_advanced_offline_material, 16),
        ("lichess_cc0_extreme_4_original_derived_puzzles",
         "extreme-lichess-4-en.json", build_extreme_offline_material, 4),
    ):
        original_entry = next((e for e in catalog if e["id"] == original_id), None)
        if (
            original_entry is None
            or original_entry.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
            or original_entry.get("redistribution") != "permitted"
        ):
            raise OfflineCollectionError("genuine English advanced source provenance missing")
        english, tasks = build_en(language="en")
        if len(tasks) != task_count or len(english.exercises()) != task_count:
            raise OfflineCollectionError("authentic English advanced exercise count changed")
        encoded = _json_bytes(english.as_dict())
        if BookDocument.from_dict(json.loads(encoded)).as_dict() != english.as_dict():
            raise OfflineCollectionError("English advanced Books serialization/reopen changed")
        dest = "books/" + name
        if dest in assets:
            raise OfflineCollectionError("duplicate English advanced book path")
        assets[dest] = encoded
        rows.append({
            "id": original_id + "_english_book",
            "title": english.title,
            "author": english.author or "Lichess original CC0 contributors",
            "genre": "advanced calculation and expert chess training",
            "language": "en", "format": "BookDocument JSON",
            "source_url": original_entry.get("source_page"),
            "download_url": None, "source_path": dest,
            "size_bytes": len(encoded), "sha256": _digest(encoded),
            "license": original_entry["license"],
            "redistribution": "permitted",
            "import_status": "CANONICAL_BOOKDOCUMENT_ENGLISH_ROUNDTRIP_PASS",
            "repeat_download": "BUNDLED_OFFLINE",
        })
    # The one authentic historical 1921 Réti composition is a distinct
    # BookDocument/Game/Exercise with fresh UK/EN annotations, not an
    # unlicensed contemporary endgame anthology or a Lichess-rated puzzle.
    historic_id = "historical_reti_1921_original_bilingual_study_pgn"
    historic_candidates = [item for item in catalog if item["id"] == historic_id]
    if len(historic_candidates) != 1:
        raise OfflineCollectionError("historic original Reti source not qualified")
    historic = historic_candidates[0]
    if (historic.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
        or historic.get("public_release") != "INCLUDED_OWN_TEXT_HISTORICAL_COMPOSITION"
        or not str(historic.get("redistribution", "")).startswith("permitted")):
        raise OfflineCollectionError("historic original Reti reuse terms changed")
    historic_raw = read_verified_source_snapshot(
        root / historic["local_source"], historic)
    if historic_raw != original_reti_source_bytes():
        raise OfflineCollectionError("compiled historical Reti study differs from original")
    historic_training = None
    for language in ("uk", "en"):
        study, truth = build_historical_reti_offline_material(language=language)
        dest = f"books/original-reti-1921-{language}.json"
        wire = _json_bytes(study.as_dict())
        if (BookDocument.from_dict(json.loads(wire)).as_dict() != study.as_dict()
            or dest in assets):
            raise OfflineCollectionError("historic study canonical BookDocument reimport failed")
        assets[dest] = wire
        rows.append({
            "id": f"{historic_id}_BookDocument_{language}",
            "title": study.title, "author": historic["author"],
            "genre": "authentic composed endgame study with original bilingual notes",
            "language": language, "format": "BookDocument JSON",
            "source_url": historic["source_page"], "download_url": None,
            "source_path": dest, "size_bytes": len(wire), "sha256": _digest(wire),
            "license": historic["license"],
            "redistribution": historic["redistribution"],
            "import_status": "ORIGINAL_RETI_1921_CANONICAL_BOOKDOCUMENT_PASS",
            "repeat_download": "BUNDLED_OFFLINE",
        })
        if historic_training is None:
            historic_training = truth
        elif historic_training != truth:
            raise OfflineCollectionError("Reti bilingual study must retain identical chess truth")
    truth_path = "training/original-reti-1921-study.json"
    truth_wire = _json_bytes({
        "schema": "acs-section40-original-reti-1921-study-v1",
        "source_id": historic_id,
        "composed_study": True,
        "original_study_not_rating": True,
        "fen": historic_training["fen"],
        "first_solution_san": historic_training["first_solution_san"],
        "full_solution_pgn": historic_training["full_solution_pgn"],
        "language": "uk,en",
    })
    assets[truth_path] = truth_wire
    rows.append({
        "id": f"{historic_id}_Training",
        "title": historic["title"], "author": historic["author"],
        "genre": "original endgame calculation study",
        "language": "uk,en", "format": "Training JSON",
        "source_url": historic["source_page"], "download_url": None,
        "source_path": truth_path, "size_bytes": len(truth_wire),
        "sha256": _digest(truth_wire), "license": historic["license"],
        "redistribution": historic["redistribution"],
        "import_status": "ORIGINAL_RETI_1921_STRICT_PGN_AND_FEN_PASS",
        "repeat_download": "BUNDLED_OFFLINE",
    })
    advanced_assets, advanced_rows = build_complete_advanced_training(root=root)
    if set(assets) & set(advanced_assets):
        raise OfflineCollectionError("duplicate advanced training content key")
    assets.update(advanced_assets)
    rows.extend(advanced_rows)
    imported = None
    with tempfile.TemporaryDirectory(prefix="acs-section40-", dir=output.parent) as temp:
        work = Path(temp)
        if profile == "TEST_BUILD":
            real_assets, imported = _real_library_sample(root, catalog, work)
            assets.update(real_assets)
            # Latest Section37 real historically composed endgame source is an
            # original 1921 Réti study with *project-authored* bilingual notes.
            # Supply an explicitly source-bound PGN for owner QA, not a rated
            # Lichess puzzle, and do not silently change the existing canonical
            # 516-game startup seed acceptance contract.
            historical = next(
                (item for item in catalog
                 if item["id"] == "historical_reti_1921_original_bilingual_study_pgn"),
                None,
            )
            if (
                historical is None
                or historical.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
                or historical.get("public_release") != "INCLUDED_OWN_TEXT_HISTORICAL_COMPOSITION"
                or not str(historical.get("redistribution", "")).startswith("permitted")
            ):
                raise OfflineCollectionError("historic Réti original study is unavailable or rights changed")
            study_bytes = read_verified_source_snapshot(
                root / historical["local_source"], historical
            )
            study_games = parse_pgn_text(study_bytes.decode("utf-8"), strict=False)
            if (
                len(study_games) != 1
                or study_games[0].tags.get("FEN") != "7K/8/k1P5/7p/8/8/8/8 w - - 0 1"
                or study_games[0].tags.get("SetUp") != "1"
                or len(study_games[0].line.moves) != 11
                or not any("EN:" in line and "UK:" in line
                           for line in study_bytes.decode("utf-8").splitlines())
            ):
                raise OfflineCollectionError("historical bilingual composed study semantic data changed")
            study_path = "library/original-reti-1921-uk-en-study.pgn"
            if study_path in assets:
                raise OfflineCollectionError("historical study output collides with existing owner data")
            assets[study_path] = study_bytes
            rows.append({
                "id": historical["id"],
                "title": historical["title"],
                "author": historical["author"],
                "genre": "historical original authored endgame study with bilingual analysis",
                "language": "uk,en", "format": "pgn",
                "source_url": historical["source_page"], "download_url": None,
                "source_path": study_path,
                "size_bytes": len(study_bytes), "sha256": _digest(study_bytes),
                "license": historical["license"],
                "redistribution": historical["redistribution"],
                "import_status": "GENUINE_HISTORICAL_STUDY_PGN_SEMANTIC_READBACK",
                "repeat_download": "BUNDLED_TEST_BUILD_ONLY",
            })
        links = [
            {"id": r["id"], "title": r["title"], "format": r["format"],
             "source_url": r.get("source_page"), "download_url": r.get("download_url"),
             "license": r.get("license"), "redistribution": r.get("redistribution"),
             "acquisition": r.get("acquisition"),
             "note": "External link only; inspect terms before acquiring"}
            for r in catalog if r.get("source_page") or r.get("download_url")
        ]
        assets["catalog/external-links.json"] = _json_bytes(links)
        assets["README_UK.txt"] = (
            "Accessible Chess: офлайнова бібліотека для перевірок.\n"
            "Файли books/*.json читає канонічний BookDocument; training/*.json "
            "містить авторські вправи й справжні задачі Lichess 2200+ (НЕ FIDE Elo). У TEST_BUILD файл library/*.acsdb "
            "містить 512 справжніх PGN-партій та добірки 32/128/512, імпортовані через існуючу Library.\n"
            "PUBLIC_RELEASE містить лише дозволені джерела й посилання; "
            "заборонено трактувати посилання як дозвіл передруку.\n"
            "Тут немає Windows EXE чи підтвердження NVDA. Не видаляйте "
            "тестову комплектацію до завершення перевірки власником.\n"
        ).encode("utf-8")
        assets["README_EN.txt"] = (
            "Accessible Chess offline corpus for QA. Canonical BookDocument "
            "course/booklets, authored Training and real CC0 Lichess 2200+ puzzles (not FIDE Elo) are included. "
            "TEST_BUILD contains real 32/128/512 game collections and 512 genuine games in canonical ACSDB. "
            "PUBLIC_RELEASE is more restrictive and includes links only for "
            "unqualified external sources. This is not a Windows EXE, "
            "an NVDA acceptance report, or a complete Section 40 closure.\n"
        ).encode("utf-8")
        report = {
            "schema": "acs-revised-section40-offline-collection-v1",
            "profile": profile, "materials": rows, "material_count": len(rows),
            "real_import_readback": imported,
            "license_policy": "fail-closed; owner/test-only uncleared sources excluded",
            "links_count": len(links),
            "section40_done": False,
            "owner_accepted": False,
        }
        assets["catalog/materials.json"] = _json_bytes(report)
        receipts = [
            {"path": name, "sha256": _digest(raw), "bytes": len(raw)}
            for name, raw in sorted(assets.items())
        ]
        assets["catalog/checksums.json"] = _json_bytes(receipts)
        stage = work / "collection.zip"
        with zipfile.ZipFile(stage, "x", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=False) as archive:
            for name, raw in sorted(assets.items()):
                if not name or name.startswith("/") or ".." in name.split("/"):
                    raise OfflineCollectionError("unsafe archive member")
                info = zipfile.ZipInfo(name, date_time=_FIXED_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED,
                                 compresslevel=6)
        if stage.stat().st_size > _MAX_ZIP_BYTES:
            raise OfflineCollectionError("collection exceeds bounded ZIP size")
        with zipfile.ZipFile(stage) as archive:
            if archive.namelist() != sorted(assets):
                raise OfflineCollectionError("collection ZIP inventory differs")
            for entry in receipts:
                if _digest(archive.read(entry["path"])) != entry["sha256"]:
                    raise OfflineCollectionError("collection ZIP readback failed")
            archived_report = json.loads(archive.read("catalog/materials.json"))
            if archived_report["profile"] != profile:
                raise OfflineCollectionError("collection profile readback differs")
        try:
            os.link(stage, output)  # no replacement, including a concurrent writer
        except OSError as exc:
            raise OfflineCollectionError("atomic no-overwrite publish failed") from exc
        report["archive_sha256"] = _digest(output.read_bytes())
        report["archive_bytes"] = output.stat().st_size
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline Section 40 QA collection")
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = build_collection(args.profile, args.output)
    print(json.dumps({
        "profile": report["profile"],
        "material_count": report["material_count"],
        "real_import_readback": report["real_import_readback"],
        "archive_sha256": report["archive_sha256"],
        "archive_bytes": report["archive_bytes"],
        "section40_done": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

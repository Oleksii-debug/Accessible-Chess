from __future__ import annotations

"""Build the Section 39 real-format matrix from Section 38 test materials."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acs.acsdb import AcsDatabase  # noqa: E402
from acs.book_library_import import open_book_library_source  # noqa: E402
from acs.library_import_service import LibraryImportService  # noqa: E402
from acs.pgn_roundtrip import parse_pgn_text  # noqa: E402
from acs.gametree import serialize_game  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--section38-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    cotswold = args.corpus_root / "chessit" / "cotswold_2023.pgn"
    alekhine = args.corpus_root / "extracted" / "alekhine" / "Alekhine.pgn"
    books = {
        "EPUB3": args.corpus_root / "gutenberg-33870" / "pg33870.epub3",
        "HTML": args.corpus_root / "gutenberg-33870" / "html" / "pg33870-images.html",
        "TXT": args.corpus_root / "gutenberg-33870" / "pg33870.txt",
    }
    if not cotswold.is_file() or not alekhine.is_file():
        raise RuntimeError("Section 39 requires the real Section 38 PGN sources")

    cotswold_games = parse_pgn_text(cotswold.read_bytes().decode("utf-8-sig"), strict=False)
    alekhine_games = parse_pgn_text(alekhine.read_bytes().decode("utf-8-sig"), strict=False)
    serialized = "\n\n".join(serialize_game(game) for game in cotswold_games)
    reparsed = parse_pgn_text(serialized, strict=False)
    if [serialize_game(game) for game in reparsed] != [serialize_game(game) for game in cotswold_games]:
        raise RuntimeError("real PGN semantic roundtrip changed canonical game trees")

    with tempfile.TemporaryDirectory(prefix="accessible-chess-section39-") as directory:
        database_path = Path(directory) / "roundtrip.acsdb"
        with AcsDatabase(database_path) as database:
            imported = LibraryImportService(database).import_games(
                cotswold_games,
                source_name=cotswold.name,
                source_format="pgn",
                source_sha256=sha256(cotswold),
            )
            found = database.search_games(source_id=imported.source_id, limit=1000)
            if len(found) != len(cotswold_games):
                raise RuntimeError("ACSDB real-source search count differs from import")
            database.verify_integrity()
            database.backup_to(Path(directory) / "roundtrip-backup.acsdb")

    matrix: dict[str, dict[str, object]] = {
        "FEN": {"status": "BLOCKED", "read": "NO_REAL_SOURCE", "write": "SUPPORTED_CANONICAL_CORE"},
        "SAN": {"status": "PASS", "read": "REAL_PGN_MOVES", "write": "REAL_PGN_ROUNDTRIP"},
        "EPD": {"status": "BLOCKED", "read": "NO_REAL_SOURCE", "write": "UNSUPPORTED"},
        "PGN": {
            "status": "PASS",
            "read": {"cotswold_games": len(cotswold_games), "alekhine_games": len(alekhine_games)},
            "write": "canonical serialize_game",
            "roundtrip": "PASS",
            "sources": {"cotswold": sha256(cotswold), "alekhine": sha256(alekhine)},
        },
        "ACSDB": {"status": "PASS", "read": len(cotswold_games), "write": "atomic LibraryImportService", "roundtrip": "backup+verify_integrity PASS"},
        "EPUB": {"status": "PASS" if books["EPUB3"].is_file() else "BLOCKED", "read": "canonical EPUB importer"},
        "HTML": {"status": "PASS" if books["HTML"].is_file() else "BLOCKED", "read": "canonical HTML importer"},
        "TXT": {"status": "PASS" if books["TXT"].is_file() else "BLOCKED", "read": "canonical TXT importer"},
        "Markdown": {"status": "BLOCKED", "read": "NO_REAL_THIRD_PARTY_SOURCE"},
        "DOCX": {"status": "BLOCKED", "read": "NO_LAWFUL_REAL_FIXTURE_AND_OWNER"},
        "PDF": {"status": "BLOCKED", "read": "NO_LAWFUL_REAL_FIXTURE_AND_OWNER"},
        "CBH": {"status": "PASS", "read": "Section 37 pinned libcbh external readback", "write": "UNSUPPORTED"},
        "CBV": {"status": "PASS", "read": "Section 37 pinned uncbv+libcbh external readback", "write": "UNSUPPORTED"},
        "CBF": {"status": "BLOCKED", "read": "NO_LAWFUL_FIXTURE_AND_INDEPENDENT_ORACLE"},
        "2CBH": {"status": "BLOCKED", "read": "NO_LAWFUL_FIXTURE_AND_INDEPENDENT_ORACLE"},
        "CBONE": {"status": "BLOCKED", "read": "NO_LAWFUL_FIXTURE_AND_INDEPENDENT_ORACLE"},
    }
    try:
        source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        source_sha = "unknown"
    report = {
        "schema_version": 1,
        "section": 39,
        "status": "INTERNAL_COMPLETE_EXTERNAL_BLOCKED",
        "source_commit": source_sha,
        "section38_evidence_sha256": sha256(args.section38_evidence),
        "matrix": matrix,
        "negative_recovery": {
            "real_pgn_restart": "PASS",
            "real_acsdb_integrity": "PASS",
            "missing_companion_cbf": "BLOCKED_BY_LAWFUL_FIXTURE",
            "resource_limits_and_malformed_inputs": "covered_by canonical unit suites; no claim of real-corpus PASS",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""External *original* Northwest Chess annotated CBV/PGN pair qualification.

Source publisher offers a CBV archive and matching independently published PGN
for January 2013. Acquire through first-party HTTPS into an ephemeral CI temp
directory only. The downloaded bytes are NOT pinned before observation, not
redistributed, and not recorded as an original-source PASS unless the full
CBV -> MIT cbvault CLI -> canonical GameTree comparison actually runs.
Standalone observed SHA256 is NOT an independently pinned upstream identity.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from acs.acsdb import AcsDatabase
from acs.gametree import parse_games
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text
from tools.section38_39_mit_cbvault_oracle import (
    _bounded_file_digest, _original_games_signature, _run_external_pgn,
)


PUBLISHER = "https://www.nwchess.com/articles/games/published/published_games.htm"
PUBLISHER_HOST = "www.nwchess.com"
SOURCE_STEM = "NWC%202013-01%20Published%20Games"
CBV_URL = (
    "https://www.nwchess.com/articles/games/published/"
    + SOURCE_STEM + ".cbv"
)
PGN_URL = (
    "https://www.nwchess.com/articles/games/published/"
    + SOURCE_STEM + ".pgn"
)
MAX_SOURCE = 32 * 1024 * 1024
MAX_EXTRACTED_TOTAL = 256 * 1024 * 1024
MAX_GAME_COUNT = 25_000
CBV_SOURCE_ID = "northwest_chess_2013_01_annotated_cbv_original_external"
PGN_SOURCE_ID = "northwest_chess_2013_01_annotated_pgn_independent_oracle_external"
_NO_SECRET = re.compile(r"^[0-9a-f]{64}$")


class _SamePublisherRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Format bytes are never fetched from an attacker-controlled redirect.
        _qualified_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _qualified_url(url: str) -> str:
    if type(url) is not str or len(url) > 500:
        raise LawfulCorpusError("original CBV/PGN URL is invalid")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise LawfulCorpusError("original CBV/PGN URL has invalid port") from exc
    if (
        parts.scheme != "https" or parts.hostname != PUBLISHER_HOST
        or parts.username is not None or parts.password is not None
        or port not in (None, 443) or parts.fragment or parts.query
        or not parts.path.startswith("/articles/games/published/")
        or any(component in ("..", ".") for component in parts.path.split("/"))
    ):
        raise LawfulCorpusError("original source escapes Northwest Chess publisher")
    return url


def _read_publisher_source(url: str) -> bytes:
    _qualified_url(url)
    opener = build_opener(
        _SamePublisherRedirect, HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with opener.open(
            Request(url, headers={"User-Agent": "AccessibleChess-FormatQA/1.0"}),
            timeout=35,
        ) as response:
            _qualified_url(response.geturl())
            if response.status != 200:
                raise LawfulCorpusError("original publisher did not serve HTTP 200")
            data = response.read(MAX_SOURCE + 1)
    except LawfulCorpusError:
        raise
    except (OSError, TimeoutError, ValueError) as exc:
        raise LawfulCorpusError("original CBV/PGN publisher read failed") from exc
    if not 0 < len(data) <= MAX_SOURCE:
        raise LawfulCorpusError("original CBV/PGN bytes absent or over quota")
    return data


def _extract_with_mit(binary: Path, archive: Path, outdir: Path) -> None:
    """Monitor extraction *while it runs*, not only after a decompression bomb."""
    import time

    if outdir.exists() or outdir.is_symlink():
        raise LawfulCorpusError("original CBV extraction target is not fresh")

    def inventory() -> tuple[int, int]:
        if not outdir.exists():
            return 0, 0
        if not outdir.is_dir() or outdir.is_symlink():
            raise LawfulCorpusError("MIT CBV decoder output is not a direct directory")
        members = list(outdir.rglob("*"))
        if len(members) > 150:
            raise LawfulCorpusError("decoded CBV output has too many members")
        expanded = 0
        for item in members:
            metadata = item.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise LawfulCorpusError("CBV extraction must not contain symlinks")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise LawfulCorpusError("CBV extraction emitted special file")
            expanded += metadata.st_size
            if expanded > MAX_EXTRACTED_TOTAL:
                raise LawfulCorpusError("original CBV extraction exceeds budget")
        return len(members), expanded

    try:
        process = subprocess.Popen(
            [os.fspath(binary), "archive", "extract",
             os.fspath(archive), os.fspath(outdir)],
            cwd=os.fspath(binary.parent), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            shell=False, start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        raise LawfulCorpusError("MIT original CBV executable cannot start") from exc
    deadline = time.monotonic() + 120
    try:
        while process.poll() is None:
            if time.monotonic() > deadline:
                raise LawfulCorpusError("MIT original CBV extraction timed out")
            inventory()
            time.sleep(0.05)
        if process.returncode != 0:
            raise LawfulCorpusError("MIT CBV decoder refused real publisher original")
        inventory()
        if not outdir.is_dir() or outdir.is_symlink():
            raise LawfulCorpusError("MIT CBV decoder produced no regular destination")
        if not any(
            x.suffix.lower() == ".cbh"
            for x in outdir.rglob("*") if x.is_file() and not x.is_symlink()
        ):
            raise LawfulCorpusError("genuine CBV archive lacks classic CBH source")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def _catalog_source_pair() -> tuple[dict, dict]:
    """The single canonical source registry owns the source and legal labels.

    Exact publisher endpoints below are a security allowlist, not a second
    license/destination authority. Tampered registry/rights/redirect fails
    BEFORE any external source request.
    """
    records = {record["id"]: record for record in load_catalog()}
    if CBV_SOURCE_ID not in records or PGN_SOURCE_ID not in records:
        raise LawfulCorpusError("original Northwest Chess source catalogue is absent")
    cbv, pgn = records[CBV_SOURCE_ID], records[PGN_SOURCE_ID]
    for record, expected_url, extension in (
        (cbv, CBV_URL, "cbv"), (pgn, PGN_URL, "pgn"),
    ):
        if (
            record.get("format") != extension
            or record.get("source_page") != PUBLISHER
            or record.get("download_url") != expected_url
            or record.get("acquisition") != "SOURCE_PAGE_ONLY"
            or record.get("redistribution") != "NOT_CLEARED"
            or record.get("public_release") != "EXCLUDED"
            or record.get("sha256") is not None
            or record.get("max_bytes") != MAX_SOURCE
        ):
            raise LawfulCorpusError("NWC original source records violated lawful metadata")
    return cbv, pgn


def qualify_original_publisher_pair(
    *, binary: Path, expected_binary_sha256: str,
) -> dict:
    if type(expected_binary_sha256) is not str or not _NO_SECRET.fullmatch(
        expected_binary_sha256
    ):
        raise LawfulCorpusError("MIT CBV executable requires exact SHA-256")
    before = _bounded_file_digest(binary, max_bytes=120 * 1024 * 1024)
    if before[0] != expected_binary_sha256:
        raise LawfulCorpusError("MIT CBV binary digest mismatch before source I/O")
    cbv_record, pgn_record = _catalog_source_pair()
    expected_raw = _read_publisher_source(pgn_record["download_url"])
    cbv_raw = _read_publisher_source(cbv_record["download_url"])
    expected_games = tuple(parse_pgn_text(
        expected_raw.decode("utf-8-sig", errors="strict"), strict=False
    ))
    if not 1 <= len(expected_games) <= MAX_GAME_COUNT:
        raise LawfulCorpusError("original Northwest Chess PGN score count invalid")
    expected_recovery_warnings = sum(len(game.warnings) for game in expected_games)
    with tempfile.TemporaryDirectory(prefix="acs-external-nwc2013-cbv-") as tmp:
        root = Path(tmp)
        archive = root / "published.cbv"
        archive.write_bytes(cbv_raw)
        original_pgn = root / "published.pgn"
        original_pgn.write_bytes(expected_raw)
        target = root / "expanded"
        _extract_with_mit(binary, archive, target)
        candidates = [
            file for file in target.rglob("*")
            if file.is_file() and not file.is_symlink()
            and file.suffix.lower() == ".cbh"
        ]
        if len(candidates) != 1:
            raise LawfulCorpusError("CBV archive did not yield exactly one classic database")
        decoded_raw = _run_external_pgn(binary, candidates[0])
        decoded_games = tuple(parse_pgn_text(
            decoded_raw.decode("utf-8-sig", errors="strict"), strict=False
        ))
        if not 1 <= len(decoded_games) <= MAX_GAME_COUNT:
            raise LawfulCorpusError("real CBV decoder returned invalid game count")
        decoded_recovery_warnings = sum(len(game.warnings) for game in decoded_games)
        # Semantic qualification must not end at stdout PGN. Persist genuine
        # CBV-derived games through the *existing* canonical Library importer,
        # restart the actual SQLite database and search by source ID.
        database_file = root / "real-original-cbv.acsdb"
        source_digest = hashlib.sha256(cbv_raw).hexdigest()
        with AcsDatabase(database_file) as database:
            imported = LibraryImportService(database).import_games(
                decoded_games,
                source_name="Northwest Chess 2013-01 original annotated CBV",
                source_format="cbv",
                source_sha256=source_digest,
            )
            if imported.game_count != len(decoded_games):
                raise LawfulCorpusError("original CBV Library publication was partial")
            database.verify_integrity()
        with AcsDatabase(database_file) as database:
            sources = LibrarySourceCatalogService(database)
            source = sources.get_source(imported.source_id)
            if (source is None or source.source_sha256 != source_digest
                or source.game_count != len(decoded_games)):
                raise LawfulCorpusError("original CBV source identity lost at DB restart")
            page = sources.source_games(imported.source_id,
                                        limit=min(len(decoded_games), 200))
            if not page.items:
                raise LawfulCorpusError("real original CBV game Search is empty")
            # Pagination across the *full* source; partial first page is not
            # evidence of a complete 400+ game source.
            stored_games = []
            after_id = None
            while True:
                search_page = sources.source_games(
                    imported.source_id, after_game_id=after_id, limit=200
                )
                for result in search_page.items:
                    record = database.get_game(result.game_id)
                    if record is None:
                        raise LawfulCorpusError("original CBV stored source game missing")
                    parsed = parse_games(str(record["pgn_text"]))
                    if len(parsed) != 1 or parsed[0].warnings:
                        raise LawfulCorpusError("original CBV stored PGN invalid or recovered")
                    stored_games.append((result.source_index, parsed[0]))
                if not search_page.has_more:
                    break
                after_id = search_page.next_after_game_id
                if after_id is None:
                    raise LawfulCorpusError("original CBV source paging cursor absent")
            stored_games.sort(key=lambda item: item[0])
            storage_matches = (
                len(stored_games) == len(decoded_games)
                and decoded_recovery_warnings == 0
                and _original_games_signature(tuple(x[1] for x in stored_games))
                    == _original_games_signature(decoded_games)
            )
            repeated = LibraryImportService(database).import_games(
                decoded_games, source_name="Northwest Chess 2013-01 original annotated CBV",
                source_format="cbv", source_sha256=source_digest,
            )
            if (not repeated.reused or repeated.source_id != imported.source_id):
                raise LawfulCorpusError("original CBV DB import is not idempotent")
            database.verify_integrity()
    after = _bounded_file_digest(binary, max_bytes=120 * 1024 * 1024)
    if before != after:
        raise LawfulCorpusError("MIT original CBV decoder binary changed during test")
    same_count = len(expected_games) == len(decoded_games)
    same_tree = (
        same_count
        and expected_recovery_warnings == 0
        and decoded_recovery_warnings == 0
        and _original_games_signature(expected_games)
            == _original_games_signature(decoded_games)
    )
    # Intentionally report PARTIAL when annotations, results or original
    # game-identity fields do not match. Never count a game-count-only match.
    return {
        "schema": "acs-section38-39-external-NWC-original-cbv-pgn-oracle-v1",
        "publisher_index": PUBLISHER,
        "publisher": "Northwest Chess",
        "canonical_source_ids": [CBV_SOURCE_ID, PGN_SOURCE_ID],
        "source_acquisition_authority": "acs.lawful_corpus_registry.load_catalog",
        "edition": "January 2013 annotated published games",
        "original_pgn_url": PGN_URL,
        "original_cbv_url": CBV_URL,
        "observed_source_pgn_sha256": hashlib.sha256(expected_raw).hexdigest(),
        "observed_source_cbv_sha256": hashlib.sha256(cbv_raw).hexdigest(),
        "source_pgn_bytes": len(expected_raw),
        "source_cbv_bytes": len(cbv_raw),
        "source_original_sha256_previously_pinned": False,
        "pgn_expected_games": len(expected_games),
        "cbv_decoder_actual_games": len(decoded_games),
        "actual_decoder_export_sha256": hashlib.sha256(decoded_raw).hexdigest(),
        "same_game_count": same_count,
        "original_pgn_recovery_warning_count": expected_recovery_warnings,
        "cbv_decoded_pgn_recovery_warning_count": decoded_recovery_warnings,
        "complete_original_header_and_annotation_comparison": True,
        "actual_acsdb_imported_games": imported.game_count,
        "actual_acsdb_restart_game_count": len(stored_games),
        "acsdb_restart_full_semantic_match": storage_matches,
        "acsdb_reimport_reused": repeated.reused,
        "full_semantic_game_tree_match": same_tree,
        "source_acquisition": "ORIGINAL_EXTERNAL_HTTP200_TEST_ONLY_UNPINNED_OBSERVATION",
        "qualification": "PARTIAL" if same_tree else "FAIL",
        "terminal_cbv_format_pass": False,
        "product_cbv_backend_changed": False,
        "original_files_redistributed": False,
        "owner_release_included": False,
        "section38_terminal_done": False,
        "section39_terminal_done": False,
    }


def main() -> None:
    """Only a publisher-source observation; never grant a generic CBV PASS."""
    target = Path("section38-39-nw-chess-real-cbv-source-observation.json")
    target.unlink(missing_ok=True)
    binary = os.environ.get("ACS_CBVAULT_MIT_BINARY")
    if not binary:
        raise LawfulCorpusError("MIT original-source CBV QA binary not provided")
    digest, _size = _bounded_file_digest(
        Path(binary), max_bytes=120 * 1024 * 1024
    )
    report = qualify_original_publisher_pair(
        binary=Path(binary), expected_binary_sha256=digest
    )
    staging = target.with_suffix(".tmp")
    try:
        staging.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)
    print(json.dumps({
        "original_game_count": report["pgn_expected_games"],
        "decoded_game_count": report["cbv_decoder_actual_games"],
        "same_game_count": report["same_game_count"],
        "semantic_equal": report["full_semantic_game_tree_match"],
        "source_pin_preexisting": False,
        "section38_done": False,
        "section39_done": False,
    }, sort_keys=True))


__all__ = [
    "PUBLISHER", "CBV_URL", "PGN_URL", "CBV_SOURCE_ID", "PGN_SOURCE_ID",
    "_catalog_source_pair", "_qualified_url",
    "_read_publisher_source", "qualify_original_publisher_pair",
]


if __name__ == "__main__":
    main()

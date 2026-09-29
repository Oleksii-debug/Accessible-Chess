from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import sys
import tempfile
import zipfile

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from acs.acsdb import AcsDatabase, ACSDB_SCHEMA_VERSION
from acs.gametree import serialize_game
from acs.pgn_roundtrip import PgnRoundTripError, parse_pgn_text


HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_OUTER_BYTES = 300 * 1024 * 1024
MAX_INNER_BYTES = 250 * 1024 * 1024
MAX_OUTER_UNCOMPRESSED_BYTES = 280 * 1024 * 1024
MAX_EVIDENCE_BYTES = 1024 * 1024
MAX_CANDIDATE_METADATA_BYTES = 4 * 1024 * 1024
MAX_CANDIDATE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
MAX_PE_HEADER_OFFSET = 16 * 1024 * 1024
RUN_METADATA_PATH = "p0-evidence/w4-run-metadata.json"
RUN_METADATA_KEYS = {
    "schema_version",
    "product_sha",
    "workflow_sha",
    "winforms_accessibility_config_sha256",
    "pre_upload_product_freshness",
    "pre_upload_workflow_freshness",
    "human_tested",
    "nvda_verified",
}

STARTER_ROOT = "AccessibleChess/release-content/w2-starter"
STARTER_REAL_GAME_COUNT = 240
STARTER_STRESS_GAME_COUNT = 1200
STARTER_CORPUS_NAME = "lichess-standard-rated-2013-01"
STARTER_CORPUS_URL = (
    "https://database.lichess.org/standard/"
    "lichess_db_standard_rated_2013-01.pgn.zst"
)
STARTER_CORPUS_SHA256 = (
    "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
)
STARTER_CORPUS_LICENSE_ID = "CC0-1.0"
STARTER_CORPUS_LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
STARTER_CORPUS_PUBLISHED_GAMES = 121_332
STARTER_CURATION_POLICY_ID = "accessible-chess-p0f-real-sample-v1"
STARTER_PROJECT_LICENSE_ID = "LicenseRef-Accessible-Chess-Starter-Content-1.0"
STARTER_ACSDB_SCHEMA_VERSION = ACSDB_SCHEMA_VERSION
STARTER_EXPECTED_FILES = {
    "starter_uk.pgn": STARTER_CORPUS_LICENSE_ID,
    "stress_uk.pgn": STARTER_PROJECT_LICENSE_ID,
    "sample_library.acsdb": STARTER_CORPUS_LICENSE_ID,
}
STARTER_EXPECTED_CRITERIA = {
    "minimum_plies": 20,
    "valid_results": ["0-1", "1-0", "1/2-1/2"],
    "required_metadata": ["Event", "White", "Black"],
    "result_minimums": {"1-0": 20, "0-1": 20, "1/2-1/2": 8},
    "length_band_minimums": {"20-59": 20, "60-99": 20, "100+": 8},
    "minimum_distinct_opening_prefixes": 12,
    "opening_prefix_plies": 4,
    "maximum_scanned_games": 5000,
}


class CandidateArtifactError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_member(archive: zipfile.ZipFile, name: str) -> str:
    info = archive.getinfo(name)
    digest = hashlib.sha256()
    total = 0
    with archive.open(info, "r") as source:
        while True:
            chunk = source.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
    if total != info.file_size:
        raise CandidateArtifactError(f"candidate member size changed while hashing: {name}")
    return digest.hexdigest()


def _normalize_sha256(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized[7:]
    if not HEX64.fullmatch(normalized):
        raise CandidateArtifactError(f"{label} must be one SHA-256 digest")
    return normalized


def _load_json(data: bytes, label: str) -> dict[str, object]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise CandidateArtifactError(f"{label} is not UTF-8") from exc

    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CandidateArtifactError(f"{label} has duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=no_duplicates)
    except CandidateArtifactError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise CandidateArtifactError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise CandidateArtifactError(f"{label} root must be an object")
    return value


def _safe_members(archive: zipfile.ZipFile, label: str) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    casefold: set[str] = set()
    for info in archive.infolist():
        raw = info.filename.replace("\\", "/")
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise CandidateArtifactError(f"{label} contains unsafe path: {raw}")
        canonical = path.as_posix()
        unix_mode = info.external_attr >> 16
        file_type = stat.S_IFMT(unix_mode)
        if file_type == stat.S_IFLNK:
            raise CandidateArtifactError(f"{label} contains symbolic link entry: {canonical}")
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise CandidateArtifactError(f"{label} contains unsupported special file entry: {canonical}")
        folded = canonical.casefold()
        if folded in casefold:
            raise CandidateArtifactError(f"{label} contains case-insensitive duplicate: {canonical}")
        casefold.add(folded)
        members[canonical] = info
    return members



def _dict_field(value: dict[str, object], key: str, label: str) -> dict[str, object]:
    nested = value.get(key)
    if not isinstance(nested, dict):
        raise CandidateArtifactError(f"{label} required object is missing: {key}")
    return nested


def _exact_int(value: object, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise CandidateArtifactError(f"{label} must equal {expected}")


def _positive_int(value: object, label: str, maximum: int | None = None) -> int:
    if type(value) is not int or value < 1:
        raise CandidateArtifactError(f"{label} must be a positive integer")
    if maximum is not None and value > maximum:
        raise CandidateArtifactError(f"{label} exceeds accepted bound")
    return value


def _read_semantic_member(
    archive: zipfile.ZipFile,
    name: str,
    label: str,
) -> bytes:
    info = archive.getinfo(name)
    if info.file_size <= 0 or info.file_size > MAX_CANDIDATE_METADATA_BYTES:
        raise CandidateArtifactError(f"{label} size is outside accepted semantic bound")
    data = archive.read(info)
    if len(data) != info.file_size:
        raise CandidateArtifactError(f"{label} changed while being read")
    return data


def _require_pe_executable(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    name: str,
    label: str,
) -> None:
    info = members[name]
    if info.is_dir() or info.file_size < 68:
        raise CandidateArtifactError(f"{label} is too small to be a Windows PE executable")
    try:
        with archive.open(info, "r") as source:
            dos_header = source.read(64)
            if len(dos_header) != 64 or dos_header[:2] != b"MZ":
                raise CandidateArtifactError(f"{label} is missing Windows MZ executable signature")
            pe_offset = int.from_bytes(dos_header[60:64], "little")
            if (
                pe_offset < 64
                or pe_offset > MAX_PE_HEADER_OFFSET
                or pe_offset + 4 > info.file_size
            ):
                raise CandidateArtifactError(f"{label} has invalid Windows PE header offset")
            remaining = pe_offset - 64
            while remaining:
                block = source.read(min(HASH_CHUNK_BYTES, remaining))
                if not block:
                    raise CandidateArtifactError(f"{label} Windows PE header is truncated")
                remaining -= len(block)
            signature = source.read(4)
    except CandidateArtifactError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise CandidateArtifactError(f"{label} executable signature read failed") from exc
    if signature != b"PE\x00\x00":
        raise CandidateArtifactError(f"{label} is missing Windows PE executable signature")


def _scan_comment_state(line: str, inside_brace: bool) -> bool:
    for character in line:
        if inside_brace:
            if character == "}":
                inside_brace = False
            continue
        if character == ";":
            break
        if character == "{":
            inside_brace = True
    return inside_brace


def _complete_pgn_records(payload: bytes, label: str) -> list[str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise CandidateArtifactError(f"{label} is not UTF-8") from exc

    current: list[str] = []
    inside_brace = False
    records: list[str] = []
    for line in text.splitlines(keepends=True):
        if not inside_brace and line.startswith('[Event "') and current:
            record = "".join(current).strip()
            if record:
                records.append(record)
            current = [line]
            inside_brace = _scan_comment_state(line, False)
            continue
        current.append(line)
        inside_brace = _scan_comment_state(line, inside_brace)

    if current:
        record = "".join(current).strip()
        if record:
            records.append(record)
    return records


def _strict_starter_record_evidence(
    payload: bytes,
    label: str,
) -> tuple[list[str], list[dict[str, object]], list[str]]:
    records = _complete_pgn_records(payload, label)
    hashes: list[str] = []
    evidence: list[dict[str, object]] = []
    canonical_pgn: list[str] = []
    for index, record in enumerate(records, start=1):
        try:
            games = parse_pgn_text(record, strict=True)
        except PgnRoundTripError as exc:
            raise CandidateArtifactError(
                f"{label} record {index} fails canonical strict PGN parsing"
            ) from exc
        if len(games) != 1:
            raise CandidateArtifactError(f"{label} record {index} is not exactly one game")
        game = games[0]
        event = game.tags.get("Event", "").strip()
        white = game.tags.get("White", "").strip()
        black = game.tags.get("Black", "").strip()
        tag_result = game.tags.get("Result", "*").strip()
        line_result = game.line.result or "*"
        if not event or not white or not black:
            raise CandidateArtifactError(
                f"{label} record {index} is missing required metadata"
            )
        if tag_result not in {"1-0", "0-1", "1/2-1/2"} or line_result != tag_result:
            raise CandidateArtifactError(
                f"{label} record {index} has inconsistent or unfinished result"
            )
        plies = len(game.line.moves)
        if plies < STARTER_EXPECTED_CRITERIA["minimum_plies"]:
            raise CandidateArtifactError(f"{label} record {index} is below the ply floor")
        opening = [node.san for node in game.line.moves[:4]]
        if len(opening) != STARTER_EXPECTED_CRITERIA["opening_prefix_plies"]:
            raise CandidateArtifactError(
                f"{label} record {index} lacks the required opening prefix"
            )
        hashes.append(_sha256(record.encode("utf-8")))
        evidence.append(
            {
                "event": event,
                "white": white,
                "black": black,
                "result": tag_result,
                "plies": plies,
                "length_band": _starter_length_band(plies),
                "opening_prefix": opening,
            }
        )
        canonical_pgn.append(serialize_game(game))
    return hashes, evidence, canonical_pgn


def _complete_pgn_record_hashes(payload: bytes, label: str) -> list[str]:
    hashes, _evidence, _canonical_pgn = _strict_starter_record_evidence(payload, label)
    return hashes


def _starter_length_band(plies: int) -> str:
    if plies < 60:
        return "20-59"
    if plies < 100:
        return "60-99"
    return "100+"


def _verify_starter_curation(
    source: dict[str, object],
    actual_record_hashes: list[str],
    actual_record_evidence: list[dict[str, object]],
) -> None:
    curation = source.get("curation")
    if not isinstance(curation, dict):
        raise CandidateArtifactError("starter curation evidence is missing")
    if (
        curation.get("policy_id") != STARTER_CURATION_POLICY_ID
        or curation.get("parser") != "acs.pgn_roundtrip.parse_pgn_text(strict=True)"
    ):
        raise CandidateArtifactError("starter curation authority mismatch")
    if curation.get("criteria") != STARTER_EXPECTED_CRITERIA:
        raise CandidateArtifactError("starter curation criteria mismatch")

    scanned = _positive_int(
        curation.get("scanned_records"),
        "starter curation scanned_records",
        maximum=5000,
    )
    eligible = _positive_int(curation.get("eligible_records"), "starter curation eligible_records")
    if eligible < STARTER_REAL_GAME_COUNT or eligible > scanned:
        raise CandidateArtifactError("starter curation eligible_records is inconsistent")
    rejected = curation.get("rejected_records")
    if not isinstance(rejected, dict):
        raise CandidateArtifactError("starter curation rejected_records is missing")
    rejected_total = 0
    for reason, count in rejected.items():
        if not isinstance(reason, str) or not reason or type(count) is not int or count < 0:
            raise CandidateArtifactError("starter curation rejected_records is malformed")
        rejected_total += count
    if eligible + rejected_total != scanned:
        raise CandidateArtifactError("starter curation scan accounting mismatch")

    selected = curation.get("selected_games")
    if not isinstance(selected, list) or len(selected) != STARTER_REAL_GAME_COUNT:
        raise CandidateArtifactError("starter curation selected_games count mismatch")

    source_indices: list[int] = []
    result_counts: Counter[str] = Counter()
    length_counts: Counter[str] = Counter()
    openings: set[tuple[str, ...]] = set()
    for item in selected:
        if not isinstance(item, dict):
            raise CandidateArtifactError("starter curation selected game evidence is malformed")
        source_index = item.get("source_index")
        if type(source_index) is not int or source_index < 1 or source_index > scanned:
            raise CandidateArtifactError("starter curation source_index is invalid")
        source_indices.append(source_index)
        for field in ("event", "white", "black"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise CandidateArtifactError(f"starter curation {field} evidence is invalid")
        result = item.get("result")
        if result not in {"1-0", "0-1", "1/2-1/2"}:
            raise CandidateArtifactError("starter curation result evidence is invalid")
        plies = item.get("plies")
        if type(plies) is not int or plies < 20:
            raise CandidateArtifactError("starter curation plies evidence is invalid")
        band = item.get("length_band")
        if band != _starter_length_band(plies):
            raise CandidateArtifactError("starter curation length-band evidence is invalid")
        opening = item.get("opening_prefix")
        if (
            not isinstance(opening, list)
            or len(opening) != 4
            or any(not isinstance(move, str) or not move for move in opening)
        ):
            raise CandidateArtifactError("starter curation opening-prefix evidence is invalid")
        record_sha = item.get("record_sha256")
        if not isinstance(record_sha, str) or not HEX64.fullmatch(record_sha.lower()):
            raise CandidateArtifactError("starter curation record SHA-256 is invalid")
        result_counts[str(result)] += 1
        length_counts[str(band)] += 1
        openings.add(tuple(opening))

    if source_indices != sorted(source_indices) or len(set(source_indices)) != len(source_indices):
        raise CandidateArtifactError("starter curation source indices are not strictly ordered")
    expected_record_hashes = [
        str(item["record_sha256"]).lower()
        for item in selected
        if isinstance(item, dict)
    ]
    if expected_record_hashes != actual_record_hashes:
        raise CandidateArtifactError(
            "starter curation selected record hashes do not match packaged starter PGN"
        )
    if len(actual_record_evidence) != len(selected):
        raise CandidateArtifactError("starter PGN semantic evidence count mismatch")
    semantic_fields = (
        "event",
        "white",
        "black",
        "result",
        "plies",
        "length_band",
        "opening_prefix",
    )
    for index, (declared, actual) in enumerate(
        zip(selected, actual_record_evidence, strict=True),
        start=1,
    ):
        declared_semantics = {field: declared.get(field) for field in semantic_fields}
        if declared_semantics != actual:
            raise CandidateArtifactError(
                f"starter curation semantic evidence mismatch at packaged game {index}"
            )
    for result, minimum in STARTER_EXPECTED_CRITERIA["result_minimums"].items():
        if result_counts[result] < minimum:
            raise CandidateArtifactError("starter curation result representation floor is not met")
    for band, minimum in STARTER_EXPECTED_CRITERIA["length_band_minimums"].items():
        if length_counts[band] < minimum:
            raise CandidateArtifactError("starter curation length representation floor is not met")
    if len(openings) < STARTER_EXPECTED_CRITERIA["minimum_distinct_opening_prefixes"]:
        raise CandidateArtifactError("starter curation opening diversity floor is not met")

    expected_results = dict(sorted(result_counts.items()))
    expected_lengths = dict(sorted(length_counts.items()))
    if curation.get("selected_result_counts") != expected_results:
        raise CandidateArtifactError("starter curation selected_result_counts mismatch")
    if curation.get("selected_length_band_counts") != expected_lengths:
        raise CandidateArtifactError("starter curation selected_length_band_counts mismatch")
    if curation.get("distinct_opening_prefixes") != len(openings):
        raise CandidateArtifactError("starter curation opening-prefix aggregate mismatch")


def _verify_starter_database(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    expected: dict[str, int],
    selected_games: list[dict[str, object]],
    canonical_pgn: list[str],
    starter_sha256: str,
) -> None:
    if info.file_size <= 0 or info.file_size > MAX_CANDIDATE_METADATA_BYTES:
        raise CandidateArtifactError("starter ACSDB size is outside accepted semantic bound")

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="accessible-chess-w4-starter-",
            suffix=".acsdb",
            delete=False,
        ) as output:
            temporary_name = output.name
            total = 0
            try:
                with archive.open(info, "r") as source:
                    while True:
                        block = source.read(HASH_CHUNK_BYTES)
                        if not block:
                            break
                        total += len(block)
                        if total > info.file_size or total > MAX_CANDIDATE_METADATA_BYTES:
                            raise CandidateArtifactError(
                                "starter ACSDB expanded beyond declared semantic bound"
                            )
                        output.write(block)
            except CandidateArtifactError:
                raise
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise CandidateArtifactError("starter ACSDB readback failed") from exc
        if total != info.file_size:
            raise CandidateArtifactError("starter ACSDB readback size mismatch")

        try:
            connection = sqlite3.connect(
                f"file:{Path(temporary_name).as_posix()}?mode=ro",
                uri=True,
                timeout=5.0,
            )
        except sqlite3.Error as exc:
            raise CandidateArtifactError("starter ACSDB cannot be opened read-only") from exc
        try:
            version_row = connection.execute("PRAGMA user_version").fetchone()
            if version_row != (STARTER_ACSDB_SCHEMA_VERSION,):
                raise CandidateArtifactError("starter ACSDB schema version mismatch")
            version = AcsDatabase._check_sqlite_integrity(connection)
            if version != STARTER_ACSDB_SCHEMA_VERSION:
                raise CandidateArtifactError("starter ACSDB schema version mismatch")
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                raise CandidateArtifactError("starter ACSDB foreign_key_check failed")
            row = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT pgn_text), "
                "COUNT(DISTINCT white || char(0) || black), "
                "COUNT(DISTINCT event) FROM games"
            ).fetchone()
            database_game_metadata = connection.execute(
                "SELECT source_index, event, white, black, result, pgn_text "
                "FROM games ORDER BY id"
            ).fetchall()
            source_rows = connection.execute(
                "SELECT source_name, source_format, sha256 FROM sources ORDER BY id"
            ).fetchall()
        except CandidateArtifactError:
            raise
        except (sqlite3.Error, RuntimeError) as exc:
            raise CandidateArtifactError(
                "starter ACSDB integrity/schema/readback validation failed"
            ) from exc
        finally:
            connection.close()
        if not isinstance(row, tuple) or len(row) != 4:
            raise CandidateArtifactError("starter ACSDB evidence row is malformed")
        actual = {
            "games": int(row[0]),
            "distinct_games": int(row[1]),
            "distinct_player_pairs": int(row[2]),
            "distinct_events": int(row[3]),
        }
        if actual != expected:
            raise CandidateArtifactError(
                f"starter ACSDB semantic evidence mismatch: actual={actual} expected={expected}"
            )
        if len(canonical_pgn) != len(selected_games):
            raise CandidateArtifactError("starter ACSDB canonical PGN evidence count mismatch")
        expected_game_metadata = [
            (
                index,
                item["event"],
                item["white"],
                item["black"],
                item["result"],
                canonical_pgn[index],
            )
            for index, item in enumerate(selected_games)
        ]
        if database_game_metadata != expected_game_metadata:
            raise CandidateArtifactError(
                "starter ACSDB game metadata does not match curated starter evidence"
            )
        if source_rows != [
            ("accessible-chess-starter-uk.pgn", "pgn", starter_sha256)
        ]:
            raise CandidateArtifactError(
                "starter ACSDB source provenance does not bind packaged starter PGN"
            )
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _verify_starter_bundle(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
) -> None:
    manifest_name = f"{STARTER_ROOT}/manifest.json"
    manifest = _load_json(archive.read(manifest_name), "starter manifest")
    _exact_int(manifest.get("schema_version"), 3, "starter manifest schema_version")
    if manifest.get("bundle_kind") != "lawful-curated-real-game-starter":
        raise CandidateArtifactError("starter manifest bundle_kind mismatch")
    if manifest.get("runtime_network_required") is not False:
        raise CandidateArtifactError("starter bundle must not require runtime network")

    source = _dict_field(manifest, "starter_source", "starter manifest")
    expected_source = {
        "name": STARTER_CORPUS_NAME,
        "url": STARTER_CORPUS_URL,
        "license_id": STARTER_CORPUS_LICENSE_ID,
        "published_games": STARTER_CORPUS_PUBLISHED_GAMES,
        "compressed_sha256": STARTER_CORPUS_SHA256,
        "selection": STARTER_CURATION_POLICY_ID,
        "selected_games": STARTER_REAL_GAME_COUNT,
    }
    for key, expected_value in expected_source.items():
        if source.get(key) != expected_value:
            raise CandidateArtifactError(f"starter source authority mismatch: {key}")
    _positive_int(
        source.get("compressed_bytes"),
        "starter source compressed_bytes",
        maximum=32 * 1024 * 1024,
    )
    subset_sha = source.get("subset_sha256")
    if not isinstance(subset_sha, str) or not HEX64.fullmatch(subset_sha.lower()):
        raise CandidateArtifactError("starter source subset_sha256 is invalid")

    counts = _dict_field(manifest, "counts", "starter manifest")
    _exact_int(counts.get("starter_games"), STARTER_REAL_GAME_COUNT, "starter_games")
    _exact_int(counts.get("stress_games"), STARTER_STRESS_GAME_COUNT, "stress_games")

    licenses = _dict_field(manifest, "licenses", "starter manifest")
    cc0 = licenses.get(STARTER_CORPUS_LICENSE_ID)
    if not isinstance(cc0, dict) or (
        cc0.get("type") != "public-domain-dedication"
        or cc0.get("url") != STARTER_CORPUS_LICENSE_URL
        or cc0.get("source") != "Lichess standard database publication"
    ):
        raise CandidateArtifactError("starter CC0 license authority mismatch")
    project_license = licenses.get(STARTER_PROJECT_LICENSE_ID)
    terms = project_license.get("terms_uk") if isinstance(project_license, dict) else None
    if (
        not isinstance(project_license, dict)
        or project_license.get("type") != "project-owned-redistribution-grant"
        or not isinstance(terms, str)
        or not terms.strip()
        or len(terms) > 4096
    ):
        raise CandidateArtifactError("starter project license authority mismatch")

    file_manifest = _dict_field(manifest, "files", "starter manifest")
    if set(file_manifest) != set(STARTER_EXPECTED_FILES):
        raise CandidateArtifactError("starter manifest file inventory mismatch")
    for short_name, expected_license in STARTER_EXPECTED_FILES.items():
        metadata = file_manifest.get(short_name)
        if not isinstance(metadata, dict):
            raise CandidateArtifactError(f"starter file metadata missing: {short_name}")
        member_name = f"{STARTER_ROOT}/{short_name}"
        info = members[member_name]
        if type(metadata.get("bytes")) is not int or metadata.get("bytes") != info.file_size:
            raise CandidateArtifactError(f"starter file byte count mismatch: {short_name}")
        digest = metadata.get("sha256")
        if (
            not isinstance(digest, str)
            or not HEX64.fullmatch(digest.lower())
            or digest.lower() != _sha256_member(archive, member_name)
        ):
            raise CandidateArtifactError(f"starter file SHA-256 mismatch: {short_name}")
        if metadata.get("license_id") != expected_license:
            raise CandidateArtifactError(f"starter file license mismatch: {short_name}")

    starter_metadata = file_manifest["starter_uk.pgn"]
    if source.get("subset_sha256") != starter_metadata.get("sha256"):
        raise CandidateArtifactError("starter source subset_sha256 does not bind starter PGN")

    starter_payload = _read_semantic_member(
        archive,
        f"{STARTER_ROOT}/starter_uk.pgn",
        "starter PGN",
    )
    (
        starter_record_hashes,
        starter_record_evidence,
        starter_canonical_pgn,
    ) = _strict_starter_record_evidence(starter_payload, "starter PGN")
    if len(starter_record_hashes) != STARTER_REAL_GAME_COUNT:
        raise CandidateArtifactError("starter PGN complete-record count mismatch")

    stress_payload = _read_semantic_member(
        archive,
        f"{STARTER_ROOT}/stress_uk.pgn",
        "stress PGN",
    )
    if len(_complete_pgn_record_hashes(stress_payload, "stress PGN")) != STARTER_STRESS_GAME_COUNT:
        raise CandidateArtifactError("stress PGN complete-record count mismatch")

    _verify_starter_curation(
        source,
        starter_record_hashes,
        starter_record_evidence,
    )

    sample = _dict_field(manifest, "sample_library", "starter manifest")
    expected_sample: dict[str, int] = {}
    for key in ("games", "distinct_games", "distinct_player_pairs", "distinct_events"):
        value = sample.get(key)
        if type(value) is not int or value < 0:
            raise CandidateArtifactError(f"starter sample_library evidence invalid: {key}")
        expected_sample[key] = value
    if (
        expected_sample["games"] != STARTER_REAL_GAME_COUNT
        or expected_sample["distinct_games"] != STARTER_REAL_GAME_COUNT
        or expected_sample["distinct_player_pairs"] < 20
        or expected_sample["distinct_events"] < 1
    ):
        raise CandidateArtifactError("starter sample_library manifest evidence is insufficient")
    selected_games = source["curation"]["selected_games"]
    if not isinstance(selected_games, list) or any(
        not isinstance(item, dict) for item in selected_games
    ):
        raise CandidateArtifactError("starter curation selected_games is unavailable for ACSDB binding")
    _verify_starter_database(
        archive,
        members[f"{STARTER_ROOT}/sample_library.acsdb"],
        expected_sample,
        selected_games,
        starter_canonical_pgn,
        str(starter_metadata["sha256"]).lower(),
    )


def _parse_checksums(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise CandidateArtifactError("SHA256SUMS.txt is not UTF-8") from exc
    checksums: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        if "  " not in line:
            raise CandidateArtifactError("malformed SHA256SUMS.txt line")
        digest, path = line.split("  ", 1)
        digest = digest.lower()
        if not HEX64.fullmatch(digest):
            raise CandidateArtifactError("malformed SHA256 digest")
        if path in checksums:
            raise CandidateArtifactError(f"duplicate checksum path: {path}")
        checksums[path] = digest
    if not checksums:
        raise CandidateArtifactError("SHA256SUMS.txt is empty")
    return checksums


def _require_true(value: dict[str, object], key: str, label: str) -> None:
    if value.get(key) is not True:
        raise CandidateArtifactError(f"{label} required evidence flag is not true: {key}")


def _require_false(value: dict[str, object], key: str, label: str) -> None:
    if value.get(key) is not False:
        raise CandidateArtifactError(f"{label} required evidence flag is not false: {key}")


def _verify_p0_evidence(
    value: dict[str, object],
    expected_sha: str,
    label: str,
    *,
    required_true: tuple[str, ...],
    required_false: tuple[str, ...] = ("human_tested", "nvda_verified"),
) -> None:
    product_sha = value.get("product_sha")
    if not isinstance(product_sha, str) or product_sha.lower() != expected_sha:
        raise CandidateArtifactError(f"{label} product_sha mismatch")
    for key in required_true:
        _require_true(value, key, label)
    for key in required_false:
        _require_false(value, key, label)



def _bounded_evidence_text(value: dict[str, object], key: str, label: str, maximum: int = 4096) -> str:
    text = value.get(key)
    if not isinstance(text, str) or not text.strip() or len(text) > maximum:
        raise CandidateArtifactError(f"{label} required bounded text is missing or invalid: {key}")
    return text.strip()


def _verify_copy_payload(value: dict[str, object]) -> None:
    _bounded_evidence_text(value, "static_document_text", "copy evidence")
    if (
        value.get("textpattern_selection_equality")
        != "UIA exact range endpoints and case-sensitive text equality"
    ):
        raise CandidateArtifactError("copy evidence TextPattern selection equality contract is not exact")
    if value.get("clipboard_equality") != "case-sensitive exact string equality":
        raise CandidateArtifactError("copy evidence clipboard equality contract is not exact")


def _verify_p0g_payload(value: dict[str, object]) -> None:
    pre1 = _bounded_evidence_text(value, "alt_1_precondition_selected_state", "P0-G evidence")
    selected1 = _bounded_evidence_text(value, "alt_1_selected_state", "P0-G evidence")
    result1 = _bounded_evidence_text(value, "alt_1_result", "P0-G evidence")
    pre2 = _bounded_evidence_text(value, "alt_2_precondition_selected_state", "P0-G evidence")
    selected2 = _bounded_evidence_text(value, "alt_2_selected_state", "P0-G evidence")
    result2 = _bounded_evidence_text(value, "alt_2_result", "P0-G evidence")
    if pre1 == selected1 or pre2 == selected2:
        raise CandidateArtifactError("P0-G evidence does not prove causal selected-state transitions")
    if selected1 == selected2:
        raise CandidateArtifactError("P0-G selected-state evidence is not distinct")
    if result1 == result2:
        raise CandidateArtifactError("P0-G accessible results are not distinct")
    for index, text in ((1, result1), (2, result2)):
        lower = text.casefold()
        if f"variant {index}" not in lower and f"варіант {index}" not in lower:
            raise CandidateArtifactError(f"P0-G Alt+{index} result does not identify selected variation")
        if "depth" not in lower and "глибин" not in lower:
            raise CandidateArtifactError(f"P0-G Alt+{index} result omits analysis depth")
        if "eval" not in lower and "оцін" not in lower:
            raise CandidateArtifactError(f"P0-G Alt+{index} result omits evaluation")
        if "uci" in lower or "debug" in lower or "traceback" in lower:
            raise CandidateArtifactError(f"P0-G Alt+{index} result exposes raw provider/debug text")


COPY_REQUIRED_TRUE = (
    "static_document_outside_edit",
    "static_text_visible_rectangle",
    "native_copy_focus_verified",
    "foreground_product_verified",
    "manifest_product_sha_verified",
    "executable_checksum_verified",
    "textpattern_selection_supported",
    "textpattern_target_selected",
    "ctrl_c_exact_clipboard",
    "move_input_focus_verified",
    "move_input_native_ctrl_a_ctrl_c",
)

P0G_REQUIRED_TRUE = (
    "native_keyboard_dispatch",
    "foreground_product_verified",
    "manifest_product_sha_verified",
    "executable_checksum_verified",
    "alt_1_action_occurred",
    "alt_1_accessible_result_exposed",
    "alt_2_action_occurred",
    "alt_2_accessible_result_exposed",
)


def _verify_strict_uia_evidence(value: dict[str, object], expected_sha: str) -> None:
    product_sha = value.get("product_sha")
    if not isinstance(product_sha, str) or product_sha.lower() != expected_sha:
        raise CandidateArtifactError("strict UIA evidence product_sha mismatch")
    if value.get("classification") != "A":
        raise CandidateArtifactError("strict UIA evidence classification must be A")
    _require_true(value, "evidence_complete", "strict UIA evidence")
    _require_true(value, "invalid_e9_fen_unchanged", "strict UIA evidence")
    _require_true(value, "board_focus_continuity", "strict UIA evidence")
    _require_false(value, "raw_exception_noise", "strict UIA evidence")
    for key in ("human_tested", "nvda_verified"):
        _require_false(value, key, "strict UIA evidence")
    if value.get("semantic_square_count") != 64:
        raise CandidateArtifactError("strict UIA evidence must prove exactly 64 semantic squares")
    if value.get("clipboard") != "e9":
        raise CandidateArtifactError("strict UIA evidence native clipboard proof mismatch")
    if value.get("e4_fen") != "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1":
        raise CandidateArtifactError("strict UIA evidence canonical e4 FEN mismatch")
    if value.get("black_e5_fen") != "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2":
        raise CandidateArtifactError("strict UIA evidence canonical e5 FEN mismatch")
    _bounded_evidence_text(value, "move_runtime_id", "strict UIA evidence", maximum=1024)


def _verify_run_metadata(
    value: dict[str, object],
    expected_sha: str,
    expected_workflow_sha: str | None,
) -> str:
    if set(value) != RUN_METADATA_KEYS:
        missing = sorted(RUN_METADATA_KEYS - set(value))
        unexpected = sorted(set(value) - RUN_METADATA_KEYS)
        raise CandidateArtifactError(
            f"run metadata key mismatch; missing={missing} unexpected={unexpected}"
        )
    if type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
        raise CandidateArtifactError("run metadata schema_version must equal 1")
    product_sha = value.get("product_sha")
    if not isinstance(product_sha, str) or not HEX40.fullmatch(product_sha):
        raise CandidateArtifactError("run metadata product_sha must be lowercase exact 40-hex")
    if product_sha != expected_sha:
        raise CandidateArtifactError("run metadata product_sha mismatch")
    workflow_sha = value.get("workflow_sha")
    if not isinstance(workflow_sha, str) or not HEX40.fullmatch(workflow_sha):
        raise CandidateArtifactError("run metadata workflow_sha must be lowercase exact 40-hex")
    if expected_workflow_sha is not None and workflow_sha != expected_workflow_sha:
        raise CandidateArtifactError("run metadata workflow_sha mismatch")
    config_sha = value.get("winforms_accessibility_config_sha256")
    if not isinstance(config_sha, str) or not HEX64.fullmatch(config_sha):
        raise CandidateArtifactError(
            "run metadata winforms_accessibility_config_sha256 must be lowercase exact 64-hex"
        )
    _require_true(value, "pre_upload_product_freshness", "run metadata")
    _require_true(value, "pre_upload_workflow_freshness", "run metadata")
    _require_false(value, "human_tested", "run metadata")
    _require_false(value, "nvda_verified", "run metadata")
    return config_sha


def verify(
    outer_path: Path,
    expected_sha: str,
    expected_outer_sha256: str | None = None,
    expected_workflow_sha: str | None = None,
) -> None:
    expected_sha = expected_sha.strip().lower()
    if not HEX40.fullmatch(expected_sha):
        raise CandidateArtifactError("expected product SHA must be exact lowercase 40-hex")
    if expected_workflow_sha is not None:
        expected_workflow_sha = expected_workflow_sha.strip().lower()
        if not HEX40.fullmatch(expected_workflow_sha):
            raise CandidateArtifactError("expected workflow SHA must be exact 40-hex")
    if not outer_path.is_file() or outer_path.is_symlink():
        raise CandidateArtifactError("outer artifact must be a direct regular file")
    try:
        outer_size = outer_path.stat().st_size
    except OSError as exc:
        raise CandidateArtifactError("outer artifact size is unavailable") from exc
    if outer_size <= 0 or outer_size > MAX_OUTER_BYTES:
        raise CandidateArtifactError("outer artifact size is outside accepted bounds")
    outer_digest_builder = hashlib.sha256()
    hashed_size = 0
    try:
        with outer_path.open("rb") as source:
            while True:
                block = source.read(HASH_CHUNK_BYTES)
                if not block:
                    break
                hashed_size += len(block)
                if hashed_size > outer_size or hashed_size > MAX_OUTER_BYTES:
                    raise CandidateArtifactError("outer artifact changed while being hashed")
                outer_digest_builder.update(block)
    except CandidateArtifactError:
        raise
    except OSError as exc:
        raise CandidateArtifactError("outer artifact read failed") from exc
    if hashed_size != outer_size:
        raise CandidateArtifactError("outer artifact changed while being hashed")
    outer_digest = outer_digest_builder.hexdigest()
    if expected_outer_sha256 is not None:
        wanted = _normalize_sha256(expected_outer_sha256, "outer artifact SHA-256")
        if wanted != outer_digest:
            raise CandidateArtifactError("outer artifact SHA-256 mismatch")

    try:
        outer = zipfile.ZipFile(outer_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateArtifactError("outer artifact is not a valid ZIP") from exc
    with outer:
        outer_members = _safe_members(outer, "outer artifact")
        outer_uncompressed_size = sum(
            info.file_size for info in outer_members.values() if not info.is_dir()
        )
        if (
            outer_uncompressed_size <= 0
            or outer_uncompressed_size > MAX_OUTER_UNCOMPRESSED_BYTES
        ):
            raise CandidateArtifactError(
                "outer artifact uncompressed size is outside accepted bounds"
            )
        files = [name for name, info in outer_members.items() if not info.is_dir()]
        expected_name = f"Accessible-Chess-V2-{expected_sha[:7]}-NVDA-test-candidate.zip"
        copy_name = "p0-evidence/packaged-v2-document-copy-summary.json"
        p0g_name = "p0-evidence/packaged-p0g-hotkey-result-summary.json"
        uia_name = "p0-evidence/packaged-uia-strict-summary.json"
        expected_outer_files = {
            expected_name,
            copy_name,
            p0g_name,
            uia_name,
            RUN_METADATA_PATH,
        }
        if set(files) != expected_outer_files:
            missing = sorted(expected_outer_files - set(files))
            unexpected = sorted(set(files) - expected_outer_files)
            raise CandidateArtifactError(
                f"outer artifact layout mismatch; missing={missing} unexpected={unexpected}"
            )

        for evidence_name in (copy_name, p0g_name, uia_name, RUN_METADATA_PATH):
            evidence_size = outer_members[evidence_name].file_size
            if evidence_size <= 0 or evidence_size > MAX_EVIDENCE_BYTES:
                raise CandidateArtifactError(
                    f"outer evidence JSON size is outside accepted bounds: {evidence_name}"
                )
        copy_evidence = _load_json(outer.read(copy_name), "copy evidence")
        p0g_evidence = _load_json(outer.read(p0g_name), "P0-G evidence")
        uia_evidence = _load_json(outer.read(uia_name), "strict UIA evidence")
        run_metadata = _load_json(outer.read(RUN_METADATA_PATH), "run metadata")
        expected_config_sha = _verify_run_metadata(
            run_metadata,
            expected_sha,
            expected_workflow_sha,
        )
        _verify_strict_uia_evidence(uia_evidence, expected_sha)
        _verify_p0_evidence(
            copy_evidence,
            expected_sha,
            "copy evidence",
            required_true=COPY_REQUIRED_TRUE,
        )
        _verify_p0_evidence(
            p0g_evidence,
            expected_sha,
            "P0-G evidence",
            required_true=P0G_REQUIRED_TRUE,
            required_false=(
                "board_application_entered",
                "raw_uci_or_debug_exposed",
                "human_tested",
                "nvda_verified",
            ),
        )
        _verify_copy_payload(copy_evidence)
        _verify_p0g_payload(p0g_evidence)

        candidate_info = outer_members[expected_name]
        if candidate_info.file_size <= 0 or candidate_info.file_size > MAX_INNER_BYTES:
            raise CandidateArtifactError("candidate ZIP size is outside accepted bounds")
        candidate_bytes = outer.read(expected_name)
        if len(candidate_bytes) != candidate_info.file_size:
            raise CandidateArtifactError("candidate ZIP changed while being read")

    try:
        candidate = zipfile.ZipFile(io.BytesIO(candidate_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise CandidateArtifactError("candidate payload is not a valid ZIP") from exc
    with candidate:
        members = _safe_members(candidate, "candidate ZIP")
        uncompressed_size = sum(
            info.file_size for info in members.values() if not info.is_dir()
        )
        if (
            uncompressed_size <= 0
            or uncompressed_size > MAX_CANDIDATE_UNCOMPRESSED_BYTES
        ):
            raise CandidateArtifactError(
                "candidate ZIP uncompressed size is outside accepted bounds"
            )
        required = {
            "RELEASE_MANIFEST.json",
            "SHA256SUMS.txt",
            "AccessibleChess/AccessibleChess.exe",
            "AccessibleChess/AccessibleChess.exe.config",
            "AccessibleChess/engines/stockfish/stockfish.exe",
            "AccessibleChess/release-content/w2-starter/manifest.json",
            "AccessibleChess/release-content/w2-starter/starter_uk.pgn",
            "AccessibleChess/release-content/w2-starter/stress_uk.pgn",
            "AccessibleChess/release-content/w2-starter/sample_library.acsdb",
        }
        missing = sorted(required - set(members))
        if missing:
            raise CandidateArtifactError("candidate ZIP is missing release-critical files: " + ", ".join(missing))

        _require_pe_executable(
            candidate,
            members,
            "AccessibleChess/AccessibleChess.exe",
            "application executable",
        )
        _require_pe_executable(
            candidate,
            members,
            "AccessibleChess/engines/stockfish/stockfish.exe",
            "Stockfish executable",
        )
        for metadata_name in (
            "RELEASE_MANIFEST.json",
            "SHA256SUMS.txt",
            f"{STARTER_ROOT}/manifest.json",
        ):
            metadata_size = members[metadata_name].file_size
            if metadata_size <= 0 or metadata_size > MAX_CANDIDATE_METADATA_BYTES:
                raise CandidateArtifactError(
                    f"candidate metadata size is outside accepted bounds: {metadata_name}"
                )

        config_name = "AccessibleChess/AccessibleChess.exe.config"
        config_info = members[config_name]
        if config_info.is_dir() or config_info.file_size <= 0 or config_info.file_size > MAX_CANDIDATE_METADATA_BYTES:
            raise CandidateArtifactError(
                "WinForms accessibility app-config size is outside accepted bounds"
            )

        manifest = _load_json(candidate.read("RELEASE_MANIFEST.json"), "release manifest")
        integration_sha = manifest.get("integration_sha")
        if not isinstance(integration_sha, str) or integration_sha.lower() != expected_sha:
            raise CandidateArtifactError("release manifest integration_sha mismatch")
        _require_false(manifest, "human_tested", "release manifest")
        _require_false(manifest, "nvda_verified", "release manifest")

        checksums = _parse_checksums(candidate.read("SHA256SUMS.txt"))
        # Canonical Version 2 assembler hashes every regular package file that
        # exists before SHA256SUMS.txt is written.  That includes the already
        # materialized RELEASE_MANIFEST.json and excludes only SHA256SUMS.txt.
        inventory_files = {
            name
            for name, info in members.items()
            if not info.is_dir() and name != "SHA256SUMS.txt"
        }
        if set(checksums) != inventory_files:
            missing_checksums = sorted(inventory_files - set(checksums))
            stale_checksums = sorted(set(checksums) - inventory_files)
            raise CandidateArtifactError(
                f"checksum inventory mismatch; missing={missing_checksums} stale={stale_checksums}"
            )
        for name, expected in checksums.items():
            actual = _sha256_member(candidate, name)
            if actual != expected:
                raise CandidateArtifactError(f"candidate checksum mismatch: {name}")
        if checksums.get(config_name) != expected_config_sha:
            raise CandidateArtifactError(
                "WinForms accessibility app-config SHA-256 mismatch against run metadata"
            )

        _verify_starter_bundle(candidate, members)


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify a W4 Accessible Chess candidate artifact")
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--outer-sha256")
    parser.add_argument("--workflow-sha", required=True)
    args = parser.parse_args()
    try:
        verify(args.artifact, args.product_sha, args.outer_sha256, args.workflow_sha)
    except CandidateArtifactError as exc:
        print(f"W4 CANDIDATE ARTIFACT READBACK FAIL: {exc}")
        return 1
    print("W4 CANDIDATE ARTIFACT READBACK VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

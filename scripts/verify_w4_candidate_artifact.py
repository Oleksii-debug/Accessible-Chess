from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
import zipfile


HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_OUTER_BYTES = 300 * 1024 * 1024
MAX_INNER_BYTES = 250 * 1024 * 1024

# Keep independent readback aligned with the canonical package preflight's
# archive resource policy.  The outer Actions artifact is intentionally
# tighter, but the inner release ZIP must still fail closed before expansion.
MAX_INNER_FILES = 50_000
MAX_INNER_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024
MAX_INNER_MEMBER_BYTES = 2 * 1024 * 1024 * 1024
MAX_INNER_COMPRESSION_RATIO = 200
MAX_RELEASE_MANIFEST_BYTES = 256 * 1024
MAX_CHECKSUMS_BYTES = 32 * 1024 * 1024
MAX_STARTER_TEXT_BYTES = 2 * 1024 * 1024
MAX_STARTER_DATABASE_BYTES = 64 * 1024 * 1024

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
STARTER_EXPECTED_FILES = {
    "starter_uk.pgn": STARTER_CORPUS_LICENSE_ID,
    "stress_uk.pgn": STARTER_PROJECT_LICENSE_ID,
    "sample_library.acsdb": STARTER_CORPUS_LICENSE_ID,
}


class CandidateArtifactError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        folded = canonical.casefold()
        if folded in casefold:
            raise CandidateArtifactError(f"{label} contains case-insensitive duplicate: {canonical}")
        casefold.add(folded)
        members[canonical] = info
    return members



def _validate_candidate_zip_bounds(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
) -> tuple[str, ...]:
    files = tuple(name for name, info in members.items() if not info.is_dir())
    if len(files) > MAX_INNER_FILES:
        raise CandidateArtifactError("candidate ZIP exceeds file-count limit")

    total = 0
    for name in files:
        info = members[name]
        if info.file_size < 0 or info.file_size > MAX_INNER_MEMBER_BYTES:
            raise CandidateArtifactError(f"candidate ZIP member exceeds size limit: {name}")
        total += int(info.file_size)
        if total > MAX_INNER_UNCOMPRESSED_BYTES:
            raise CandidateArtifactError("candidate ZIP exceeds total uncompressed byte limit")
        if info.file_size:
            if info.compress_size <= 0:
                raise CandidateArtifactError(
                    f"candidate ZIP member has invalid compressed size: {name}"
                )
            if info.file_size > info.compress_size * MAX_INNER_COMPRESSION_RATIO:
                raise CandidateArtifactError(
                    f"candidate ZIP member exceeds compression-ratio limit: {name}"
                )
    return files


def _read_zip_member_bounded(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    maximum: int,
    label: str,
) -> bytes:
    if info.file_size < 0 or info.file_size > maximum:
        raise CandidateArtifactError(f"{label} exceeds accepted size bound")
    chunks: list[bytes] = []
    total = 0
    try:
        with archive.open(info, "r") as stream:
            while True:
                block = stream.read(min(1024 * 1024, maximum + 1))
                if not block:
                    break
                total += len(block)
                if total > info.file_size or total > maximum:
                    raise CandidateArtifactError(f"{label} expanded beyond declared bounds")
                chunks.append(block)
    except CandidateArtifactError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise CandidateArtifactError(f"{label} readback failed") from exc
    if total != info.file_size:
        raise CandidateArtifactError(f"{label} readback size mismatch")
    return b"".join(chunks)


def _sha256_zip_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    label: str,
) -> str:
    digest = hashlib.sha256()
    total = 0
    try:
        with archive.open(info, "r") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > info.file_size or total > MAX_INNER_MEMBER_BYTES:
                    raise CandidateArtifactError(f"{label} expanded beyond declared bounds")
                digest.update(block)
    except CandidateArtifactError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise CandidateArtifactError(f"{label} checksum readback failed") from exc
    if total != info.file_size:
        raise CandidateArtifactError(f"{label} checksum readback size mismatch")
    return digest.hexdigest()


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


def _decode_starter_text(payload: bytes, label: str) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeError as exc:
        raise CandidateArtifactError(f"{label} is not UTF-8") from exc


def _verify_starter_database(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    expected: dict[str, object],
) -> None:
    if info.file_size <= 0 or info.file_size > MAX_STARTER_DATABASE_BYTES:
        raise CandidateArtifactError("starter ACSDB size is outside accepted bounds")

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
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        total += len(block)
                        if total > info.file_size or total > MAX_STARTER_DATABASE_BYTES:
                            raise CandidateArtifactError(
                                "starter ACSDB expanded beyond declared bounds"
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
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise CandidateArtifactError("starter ACSDB integrity_check failed")
            row = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT pgn_text), "
                "COUNT(DISTINCT white || char(0) || black), "
                "COUNT(DISTINCT event) FROM games"
            ).fetchone()
        except sqlite3.Error as exc:
            raise CandidateArtifactError("starter ACSDB schema/readback query failed") from exc
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
    manifest = _load_json(
        _read_zip_member_bounded(
            archive,
            members[manifest_name],
            MAX_STARTER_TEXT_BYTES,
            "starter manifest",
        ),
        "starter manifest",
    )
    _exact_int(manifest.get("schema_version"), 3, "starter manifest schema_version")
    if manifest.get("bundle_kind") != "lawful-curated-real-game-starter":
        raise CandidateArtifactError("starter manifest bundle_kind mismatch")
    if manifest.get("runtime_network_required") is not False:
        raise CandidateArtifactError("starter bundle must not require runtime network")

    source = _dict_field(manifest, "starter_source", "starter manifest")
    expected_source_scalars = {
        "name": STARTER_CORPUS_NAME,
        "url": STARTER_CORPUS_URL,
        "license_id": STARTER_CORPUS_LICENSE_ID,
        "published_games": STARTER_CORPUS_PUBLISHED_GAMES,
        "compressed_sha256": STARTER_CORPUS_SHA256,
        "selection": STARTER_CURATION_POLICY_ID,
        "selected_games": STARTER_REAL_GAME_COUNT,
    }
    for key, expected_value in expected_source_scalars.items():
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
    if not isinstance(cc0, dict):
        raise CandidateArtifactError("starter CC0 license authority is missing")
    if (
        cc0.get("type") != "public-domain-dedication"
        or cc0.get("url") != STARTER_CORPUS_LICENSE_URL
        or cc0.get("source") != "Lichess standard database publication"
    ):
        raise CandidateArtifactError("starter CC0 license authority mismatch")
    project_license = licenses.get(STARTER_PROJECT_LICENSE_ID)
    if not isinstance(project_license, dict):
        raise CandidateArtifactError("starter project license authority is missing")
    terms = project_license.get("terms_uk")
    if (
        project_license.get("type") != "project-owned-redistribution-grant"
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
            or digest.lower() != _sha256_zip_member(archive, info, f"starter {short_name}")
        ):
            raise CandidateArtifactError(f"starter file SHA-256 mismatch: {short_name}")
        if metadata.get("license_id") != expected_license:
            raise CandidateArtifactError(f"starter file license mismatch: {short_name}")

    starter_info = members[f"{STARTER_ROOT}/starter_uk.pgn"]
    stress_info = members[f"{STARTER_ROOT}/stress_uk.pgn"]
    starter_bytes = _read_zip_member_bounded(
        archive, starter_info, MAX_STARTER_TEXT_BYTES, "starter PGN"
    )
    stress_bytes = _read_zip_member_bounded(
        archive, stress_info, MAX_STARTER_TEXT_BYTES, "stress PGN"
    )
    starter_text = _decode_starter_text(starter_bytes, "starter PGN")
    stress_text = _decode_starter_text(stress_bytes, "stress PGN")
    if starter_text.count('[Event "') != STARTER_REAL_GAME_COUNT:
        raise CandidateArtifactError("starter PGN complete-record count mismatch")
    if stress_text.count('[Event "') != STARTER_STRESS_GAME_COUNT:
        raise CandidateArtifactError("stress PGN complete-record count mismatch")
    if subset_sha.lower() != _sha256(starter_bytes):
        raise CandidateArtifactError("starter source subset_sha256 does not bind starter PGN")

    curation = source.get("curation")
    if not isinstance(curation, dict):
        raise CandidateArtifactError("starter curation evidence is missing")
    if (
        curation.get("policy_id") != STARTER_CURATION_POLICY_ID
        or curation.get("parser") != "acs.pgn_roundtrip.parse_pgn_text(strict=True)"
    ):
        raise CandidateArtifactError("starter curation authority mismatch")
    selected = curation.get("selected_games")
    if not isinstance(selected, list) or len(selected) != STARTER_REAL_GAME_COUNT:
        raise CandidateArtifactError("starter curation selected_games count mismatch")
    for item in selected:
        if not isinstance(item, dict):
            raise CandidateArtifactError("starter curation selected game evidence is malformed")
        record_sha = item.get("record_sha256")
        if not isinstance(record_sha, str) or not HEX64.fullmatch(record_sha.lower()):
            raise CandidateArtifactError("starter curation record SHA-256 is invalid")
    criteria = curation.get("criteria")
    expected_criteria = {
        "minimum_plies": 20,
        "valid_results": ["0-1", "1-0", "1/2-1/2"],
        "required_metadata": ["Event", "White", "Black"],
        "result_minimums": {"1-0": 20, "0-1": 20, "1/2-1/2": 8},
        "length_band_minimums": {"20-59": 20, "60-99": 20, "100+": 8},
        "minimum_distinct_opening_prefixes": 12,
        "opening_prefix_plies": 4,
        "maximum_scanned_games": 5000,
    }
    if criteria != expected_criteria:
        raise CandidateArtifactError("starter curation criteria mismatch")

    sample = _dict_field(manifest, "sample_library", "starter manifest")
    expected_sample = {}
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
    _verify_starter_database(
        archive,
        members[f"{STARTER_ROOT}/sample_library.acsdb"],
        expected_sample,
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
    "native_copy_focus_verified",
    "foreground_product_verified",
    "manifest_product_sha_verified",
    "executable_checksum_verified",
    "textpattern_selection_supported",
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


def verify(outer_path: Path, expected_sha: str, expected_outer_sha256: str | None = None) -> None:
    expected_sha = expected_sha.strip().lower()
    if not HEX40.fullmatch(expected_sha):
        raise CandidateArtifactError("expected product SHA must be exact 40-hex")
    if not outer_path.is_file() or outer_path.is_symlink():
        raise CandidateArtifactError("outer artifact must be a direct regular file")
    try:
        outer_size = outer_path.stat().st_size
    except OSError as exc:
        raise CandidateArtifactError("outer artifact size is unavailable") from exc
    if outer_size <= 0 or outer_size > MAX_OUTER_BYTES:
        raise CandidateArtifactError("outer artifact size is outside accepted bounds")
    outer_bytes = outer_path.read_bytes()
    if len(outer_bytes) != outer_size:
        raise CandidateArtifactError("outer artifact changed while being read")
    outer_digest = _sha256(outer_bytes)
    if expected_outer_sha256 is not None:
        wanted = _normalize_sha256(expected_outer_sha256, "outer artifact SHA-256")
        if wanted != outer_digest:
            raise CandidateArtifactError("outer artifact SHA-256 mismatch")

    try:
        outer = zipfile.ZipFile(io.BytesIO(outer_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise CandidateArtifactError("outer artifact is not a valid ZIP") from exc
    with outer:
        outer_members = _safe_members(outer, "outer artifact")
        files = [name for name, info in outer_members.items() if not info.is_dir()]
        candidate_names = [name for name in files if name.endswith("-NVDA-test-candidate.zip")]
        copy_names = [name for name in files if name.endswith("packaged-v2-document-copy-summary.json")]
        p0g_names = [name for name in files if name.endswith("packaged-p0g-hotkey-result-summary.json")]
        if len(candidate_names) != 1:
            raise CandidateArtifactError("outer artifact must contain exactly one candidate ZIP")
        candidate_name = PurePosixPath(candidate_names[0]).name
        expected_name = f"Accessible-Chess-V2-{expected_sha[:7]}-NVDA-test-candidate.zip"
        if candidate_name.lower() != expected_name.lower():
            raise CandidateArtifactError("candidate ZIP filename Product prefix mismatch")
        if len(copy_names) != 1 or len(p0g_names) != 1:
            raise CandidateArtifactError("outer artifact must contain both exact P0 evidence JSON files")
        expected_outer_files = {candidate_names[0], copy_names[0], p0g_names[0]}
        if set(files) != expected_outer_files:
            unexpected = sorted(set(files) - expected_outer_files)
            raise CandidateArtifactError(f"outer artifact contains unexpected files: {unexpected}")

        copy_evidence = _load_json(outer.read(copy_names[0]), "copy evidence")
        p0g_evidence = _load_json(outer.read(p0g_names[0]), "P0-G evidence")
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

        candidate_info = outer_members[candidate_names[0]]
        if candidate_info.file_size <= 0 or candidate_info.file_size > MAX_INNER_BYTES:
            raise CandidateArtifactError("candidate ZIP size is outside accepted bounds")
        candidate_bytes = outer.read(candidate_names[0])
        if len(candidate_bytes) != candidate_info.file_size:
            raise CandidateArtifactError("candidate ZIP changed while being read")

    try:
        candidate = zipfile.ZipFile(io.BytesIO(candidate_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise CandidateArtifactError("candidate payload is not a valid ZIP") from exc
    with candidate:
        members = _safe_members(candidate, "candidate ZIP")
        inner_files = _validate_candidate_zip_bounds(candidate, members)
        required = {
            "RELEASE_MANIFEST.json",
            "SHA256SUMS.txt",
            "AccessibleChess/AccessibleChess.exe",
            "AccessibleChess/engines/stockfish/stockfish.exe",
            "AccessibleChess/release-content/w2-starter/manifest.json",
            "AccessibleChess/release-content/w2-starter/starter_uk.pgn",
            "AccessibleChess/release-content/w2-starter/stress_uk.pgn",
            "AccessibleChess/release-content/w2-starter/sample_library.acsdb",
        }
        missing = sorted(required - set(members))
        if missing:
            raise CandidateArtifactError("candidate ZIP is missing release-critical files: " + ", ".join(missing))

        manifest = _load_json(
            _read_zip_member_bounded(
                candidate,
                members["RELEASE_MANIFEST.json"],
                MAX_RELEASE_MANIFEST_BYTES,
                "release manifest",
            ),
            "release manifest",
        )
        integration_sha = manifest.get("integration_sha")
        if not isinstance(integration_sha, str) or integration_sha.lower() != expected_sha:
            raise CandidateArtifactError("release manifest integration_sha mismatch")
        if manifest.get("human_tested") is True or manifest.get("nvda_verified") is True:
            raise CandidateArtifactError(
                "release manifest makes forbidden human/NVDA acceptance claim"
            )

        checksums = _parse_checksums(
            _read_zip_member_bounded(
                candidate,
                members["SHA256SUMS.txt"],
                MAX_CHECKSUMS_BYTES,
                "SHA256SUMS.txt",
            )
        )
        # Canonical Version 2 assembler hashes every regular package file that
        # exists before SHA256SUMS.txt is written.  That includes the already
        # materialized RELEASE_MANIFEST.json and excludes only SHA256SUMS.txt.
        inventory_files = set(inner_files) - {"SHA256SUMS.txt"}
        if set(checksums) != inventory_files:
            missing_checksums = sorted(inventory_files - set(checksums))
            stale_checksums = sorted(set(checksums) - inventory_files)
            raise CandidateArtifactError(
                f"checksum inventory mismatch; missing={missing_checksums} stale={stale_checksums}"
            )
        for name, expected in checksums.items():
            actual = _sha256_zip_member(
                candidate,
                members[name],
                f"candidate member {name}",
            )
            if actual != expected:
                raise CandidateArtifactError(f"candidate checksum mismatch: {name}")

        _verify_starter_bundle(candidate, members)


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify a W4 Accessible Chess candidate artifact")
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--outer-sha256")
    args = parser.parse_args()
    try:
        verify(args.artifact, args.product_sha, args.outer_sha256)
    except CandidateArtifactError as exc:
        print(f"W4 CANDIDATE ARTIFACT READBACK FAIL: {exc}")
        return 1
    print("W4 CANDIDATE ARTIFACT READBACK VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

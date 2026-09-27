from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_OUTER_BYTES = 300 * 1024 * 1024
MAX_INNER_BYTES = 250 * 1024 * 1024
MAX_OUTER_UNCOMPRESSED_BYTES = 280 * 1024 * 1024
MAX_EVIDENCE_BYTES = 1024 * 1024
MAX_CANDIDATE_METADATA_BYTES = 4 * 1024 * 1024
MAX_CANDIDATE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024


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
        folded = canonical.casefold()
        if folded in casefold:
            raise CandidateArtifactError(f"{label} contains case-insensitive duplicate: {canonical}")
        casefold.add(folded)
        members[canonical] = info
    return members


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
    if value.get("semantic_square_count") != 64:
        raise CandidateArtifactError("strict UIA evidence must prove exactly 64 semantic squares")
    if value.get("clipboard") != "e9":
        raise CandidateArtifactError("strict UIA evidence native clipboard proof mismatch")
    if value.get("e4_fen") != "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1":
        raise CandidateArtifactError("strict UIA evidence canonical e4 FEN mismatch")
    if value.get("black_e5_fen") != "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2":
        raise CandidateArtifactError("strict UIA evidence canonical e5 FEN mismatch")
    _bounded_evidence_text(value, "move_runtime_id", "strict UIA evidence", maximum=1024)


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
        candidate_names = [name for name in files if name.endswith("-NVDA-test-candidate.zip")]
        copy_names = [name for name in files if name.endswith("packaged-v2-document-copy-summary.json")]
        p0g_names = [name for name in files if name.endswith("packaged-p0g-hotkey-result-summary.json")]
        uia_names = [name for name in files if name.endswith("packaged-uia-strict-summary.json")]
        if len(candidate_names) != 1:
            raise CandidateArtifactError("outer artifact must contain exactly one candidate ZIP")
        candidate_name = PurePosixPath(candidate_names[0]).name
        expected_name = f"Accessible-Chess-V2-{expected_sha[:7]}-NVDA-test-candidate.zip"
        if candidate_name.lower() != expected_name.lower():
            raise CandidateArtifactError("candidate ZIP filename Product prefix mismatch")
        if len(copy_names) != 1 or len(p0g_names) != 1 or len(uia_names) != 1:
            raise CandidateArtifactError(
                "outer artifact must contain exact strict UIA, copy and P0-G evidence JSON files"
            )
        expected_outer_files = {
            candidate_names[0],
            copy_names[0],
            p0g_names[0],
            uia_names[0],
        }
        if set(files) != expected_outer_files:
            unexpected = sorted(set(files) - expected_outer_files)
            raise CandidateArtifactError(f"outer artifact contains unexpected files: {unexpected}")

        for evidence_name in (copy_names[0], p0g_names[0], uia_names[0]):
            evidence_size = outer_members[evidence_name].file_size
            if evidence_size <= 0 or evidence_size > MAX_EVIDENCE_BYTES:
                raise CandidateArtifactError(
                    f"outer evidence JSON size is outside accepted bounds: {evidence_name}"
                )
        copy_evidence = _load_json(outer.read(copy_names[0]), "copy evidence")
        p0g_evidence = _load_json(outer.read(p0g_names[0]), "P0-G evidence")
        uia_evidence = _load_json(outer.read(uia_names[0]), "strict UIA evidence")
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
            "AccessibleChess/engines/stockfish/stockfish.exe",
            "AccessibleChess/release-content/w2-starter/manifest.json",
            "AccessibleChess/release-content/w2-starter/starter_uk.pgn",
            "AccessibleChess/release-content/w2-starter/stress_uk.pgn",
            "AccessibleChess/release-content/w2-starter/sample_library.acsdb",
        }
        missing = sorted(required - set(members))
        if missing:
            raise CandidateArtifactError("candidate ZIP is missing release-critical files: " + ", ".join(missing))

        for metadata_name in ("RELEASE_MANIFEST.json", "SHA256SUMS.txt"):
            metadata_size = members[metadata_name].file_size
            if metadata_size <= 0 or metadata_size > MAX_CANDIDATE_METADATA_BYTES:
                raise CandidateArtifactError(
                    f"candidate metadata size is outside accepted bounds: {metadata_name}"
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

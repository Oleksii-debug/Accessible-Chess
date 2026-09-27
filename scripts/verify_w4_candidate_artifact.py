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


def _verify_p0_evidence(value: dict[str, object], expected_sha: str, label: str) -> None:
    product_sha = value.get("product_sha")
    if not isinstance(product_sha, str) or product_sha.lower() != expected_sha:
        raise CandidateArtifactError(f"{label} product_sha mismatch")
    if value.get("human_tested") is True or value.get("nvda_verified") is True:
        raise CandidateArtifactError(f"{label} makes forbidden human/NVDA claim")


def verify(outer_path: Path, expected_sha: str, expected_outer_sha256: str | None = None) -> None:
    expected_sha = expected_sha.strip().lower()
    if not HEX40.fullmatch(expected_sha):
        raise CandidateArtifactError("expected product SHA must be exact 40-hex")
    if not outer_path.is_file() or outer_path.is_symlink():
        raise CandidateArtifactError("outer artifact must be a direct regular file")
    outer_bytes = outer_path.read_bytes()
    if not outer_bytes or len(outer_bytes) > MAX_OUTER_BYTES:
        raise CandidateArtifactError("outer artifact size is outside accepted bounds")
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

        copy_evidence = _load_json(outer.read(copy_names[0]), "copy evidence")
        p0g_evidence = _load_json(outer.read(p0g_names[0]), "P0-G evidence")
        _verify_p0_evidence(copy_evidence, expected_sha, "copy evidence")
        _verify_p0_evidence(p0g_evidence, expected_sha, "P0-G evidence")

        candidate_bytes = outer.read(candidate_names[0])
        if not candidate_bytes or len(candidate_bytes) > MAX_INNER_BYTES:
            raise CandidateArtifactError("candidate ZIP size is outside accepted bounds")

    try:
        candidate = zipfile.ZipFile(io.BytesIO(candidate_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise CandidateArtifactError("candidate payload is not a valid ZIP") from exc
    with candidate:
        members = _safe_members(candidate, "candidate ZIP")
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

        manifest = _load_json(candidate.read("RELEASE_MANIFEST.json"), "release manifest")
        integration_sha = manifest.get("integration_sha")
        if not isinstance(integration_sha, str) or integration_sha.lower() != expected_sha:
            raise CandidateArtifactError("release manifest integration_sha mismatch")
        if manifest.get("nvda_verified") is True:
            raise CandidateArtifactError("release manifest makes forbidden NVDA verified claim")

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
            actual = _sha256(candidate.read(name))
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

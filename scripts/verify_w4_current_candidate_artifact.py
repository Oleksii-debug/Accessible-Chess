from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from acs.version2_package_preflight import (
    Version2PackagePreflightError,
    validate_version2_package_zip,
)
from scripts.verify_w4_candidate_artifact import (
    CandidateArtifactError,
    HASH_CHUNK_BYTES,
    MAX_EVIDENCE_BYTES,
    MAX_INNER_BYTES,
    MAX_OUTER_BYTES,
    RUN_METADATA_PATH,
    _load_json,
    _normalize_sha256,
    _safe_members,
    verify as verify_legacy_contract,
)


HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CURRENT_RUN_METADATA_KEYS = {
    "schema_version",
    "product_sha",
    "workflow_sha",
    "pre_upload_product_freshness",
    "pre_upload_workflow_freshness",
    "user_sound_pack_zip_sha256",
    "user_sound_inventory_sha256",
    "user_sound_wav_count",
    "human_tested",
    "nvda_verified",
}
SOUND_WAV_COUNT = 330
SOUND_ROOT = "AccessibleChess/assets/sounds"
SOUND_INVENTORY_PATH = f"{SOUND_ROOT}/inventory.json"
SOUND_REQUIRED_METADATA = {
    SOUND_INVENTORY_PATH,
    f"{SOUND_ROOT}/manifest.json",
    f"{SOUND_ROOT}/variants.json",
    f"{SOUND_ROOT}/layers.json",
    f"{SOUND_ROOT}/newgame_impacts.json",
}


def _require_exact_bool(value: dict[str, object], key: str, expected: bool) -> None:
    if value.get(key) is not expected:
        raise CandidateArtifactError(f"current run metadata {key} must be {expected}")


def validate_current_run_metadata(
    value: dict[str, object],
    expected_sha: str,
    expected_workflow_sha: str,
) -> dict[str, object]:
    if set(value) != CURRENT_RUN_METADATA_KEYS:
        missing = sorted(CURRENT_RUN_METADATA_KEYS - set(value))
        unexpected = sorted(set(value) - CURRENT_RUN_METADATA_KEYS)
        raise CandidateArtifactError(
            f"current run metadata key mismatch; missing={missing} unexpected={unexpected}"
        )
    if type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
        raise CandidateArtifactError("current run metadata schema_version must equal 1")

    product_sha = value.get("product_sha")
    workflow_sha = value.get("workflow_sha")
    if not isinstance(product_sha, str) or not HEX40.fullmatch(product_sha):
        raise CandidateArtifactError("current run metadata product_sha must be lowercase exact 40-hex")
    if product_sha != expected_sha:
        raise CandidateArtifactError("current run metadata product_sha mismatch")
    if not isinstance(workflow_sha, str) or not HEX40.fullmatch(workflow_sha):
        raise CandidateArtifactError("current run metadata workflow_sha must be lowercase exact 40-hex")
    if workflow_sha != expected_workflow_sha:
        raise CandidateArtifactError("current run metadata workflow_sha mismatch")

    sound_zip_sha = value.get("user_sound_pack_zip_sha256")
    sound_inventory_sha = value.get("user_sound_inventory_sha256")
    sound_wav_count = value.get("user_sound_wav_count")
    if not isinstance(sound_zip_sha, str) or not HEX64.fullmatch(sound_zip_sha):
        raise CandidateArtifactError(
            "current run metadata user_sound_pack_zip_sha256 must be lowercase exact 64-hex"
        )
    if not isinstance(sound_inventory_sha, str) or not HEX64.fullmatch(sound_inventory_sha):
        raise CandidateArtifactError(
            "current run metadata user_sound_inventory_sha256 must be lowercase exact 64-hex"
        )
    if type(sound_wav_count) is not int or sound_wav_count != SOUND_WAV_COUNT:
        raise CandidateArtifactError(
            f"current run metadata user_sound_wav_count must equal {SOUND_WAV_COUNT}"
        )

    _require_exact_bool(value, "pre_upload_product_freshness", True)
    _require_exact_bool(value, "pre_upload_workflow_freshness", True)
    _require_exact_bool(value, "human_tested", False)
    _require_exact_bool(value, "nvda_verified", False)
    return value


def _read_current_run_metadata(
    outer_path: Path,
    expected_sha: str,
    expected_workflow_sha: str,
) -> dict[str, object]:
    try:
        outer = zipfile.ZipFile(outer_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateArtifactError("outer artifact is not a valid ZIP") from exc
    with outer:
        members = _safe_members(outer, "outer artifact")
        info = members.get(RUN_METADATA_PATH)
        if info is None or info.is_dir():
            raise CandidateArtifactError("current run metadata is missing")
        if info.file_size <= 0 or info.file_size > MAX_EVIDENCE_BYTES:
            raise CandidateArtifactError("current run metadata size is outside accepted bounds")
        value = _load_json(outer.read(info), "current run metadata")
    return validate_current_run_metadata(value, expected_sha, expected_workflow_sha)


def _verify_current_sound_binding(
    outer_path: Path,
    expected_sha: str,
    metadata: dict[str, object],
) -> None:
    candidate_name = f"Accessible-Chess-V2-{expected_sha[:7]}-NVDA-test-candidate.zip"
    try:
        outer = zipfile.ZipFile(outer_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateArtifactError("outer artifact is not a valid ZIP") from exc
    with outer:
        outer_members = _safe_members(outer, "outer artifact")
        candidate_info = outer_members.get(candidate_name)
        if candidate_info is None or candidate_info.is_dir():
            raise CandidateArtifactError("current candidate ZIP is missing")
        if candidate_info.file_size <= 0 or candidate_info.file_size > MAX_INNER_BYTES:
            raise CandidateArtifactError("current candidate ZIP size is outside accepted bounds")
        with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as nested:
            with outer.open(candidate_info, "r") as source:
                shutil.copyfileobj(source, nested, length=HASH_CHUNK_BYTES)
            nested.seek(0)
            try:
                candidate = zipfile.ZipFile(nested, "r")
            except zipfile.BadZipFile as exc:
                raise CandidateArtifactError("current candidate payload is not a valid ZIP") from exc
            with candidate:
                members = _safe_members(candidate, "current candidate ZIP")
                missing = sorted(SOUND_REQUIRED_METADATA - set(members))
                if missing:
                    raise CandidateArtifactError(
                        "current candidate sound metadata missing: " + ", ".join(missing)
                    )
                inventory_info = members[SOUND_INVENTORY_PATH]
                if (
                    inventory_info.is_dir()
                    or inventory_info.file_size <= 0
                    or inventory_info.file_size > MAX_EVIDENCE_BYTES
                ):
                    raise CandidateArtifactError(
                        "current candidate sound inventory size is outside accepted bounds"
                    )
                inventory = _load_json(
                    candidate.read(inventory_info),
                    "current candidate sound inventory",
                )

                if inventory.get("file_count") != metadata["user_sound_wav_count"]:
                    raise CandidateArtifactError(
                        "current candidate sound WAV count does not match run metadata"
                    )
                if inventory.get("source_inventory_sha256") != metadata["user_sound_inventory_sha256"]:
                    raise CandidateArtifactError(
                        "current candidate sound inventory SHA-256 does not match run metadata"
                    )
                if inventory.get("source_archive_sha256") != metadata["user_sound_pack_zip_sha256"]:
                    raise CandidateArtifactError(
                        "current candidate sound source archive SHA-256 does not match run metadata"
                    )
                source_archive_bytes = inventory.get("source_archive_bytes")
                if type(source_archive_bytes) is not int or source_archive_bytes <= 0:
                    raise CandidateArtifactError(
                        "current candidate sound source archive byte count is invalid"
                    )

                wav_prefix = f"{SOUND_ROOT}/library/"
                wavs = [
                    name
                    for name, info in members.items()
                    if not info.is_dir()
                    and name.startswith(wav_prefix)
                    and name.casefold().endswith(".wav")
                ]
                if len(wavs) != metadata["user_sound_wav_count"]:
                    raise CandidateArtifactError(
                        "current candidate sound library WAV inventory mismatch"
                    )


def _verify_exact_product_package_preflight(
    outer_path: Path,
    expected_sha: str,
) -> None:
    candidate_name = f"Accessible-Chess-V2-{expected_sha[:7]}-NVDA-test-candidate.zip"
    try:
        outer = zipfile.ZipFile(outer_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateArtifactError("outer artifact is not a valid ZIP") from exc

    with outer:
        outer_members = _safe_members(outer, "outer artifact")
        candidate_info = outer_members.get(candidate_name)
        if candidate_info is None or candidate_info.is_dir():
            raise CandidateArtifactError("current candidate ZIP is missing")
        if candidate_info.file_size <= 0 or candidate_info.file_size > MAX_INNER_BYTES:
            raise CandidateArtifactError(
                "current candidate ZIP size is outside accepted bounds"
            )

        with tempfile.TemporaryDirectory() as directory:
            candidate_path = Path(directory) / "candidate.zip"
            written = 0
            try:
                with outer.open(candidate_info, "r") as source, candidate_path.open("xb") as target:
                    while True:
                        block = source.read(HASH_CHUNK_BYTES)
                        if not block:
                            break
                        written += len(block)
                        if written > candidate_info.file_size or written > MAX_INNER_BYTES:
                            raise CandidateArtifactError(
                                "current candidate ZIP expanded beyond accepted bounds"
                            )
                        target.write(block)
            except CandidateArtifactError:
                raise
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise CandidateArtifactError(
                    "current candidate ZIP could not be materialized for exact Product preflight"
                ) from exc
            if written != candidate_info.file_size:
                raise CandidateArtifactError(
                    "current candidate ZIP size changed during exact Product preflight materialization"
                )

            try:
                validate_version2_package_zip(
                    candidate_path,
                    expected_integration_sha=expected_sha,
                )
            except Version2PackagePreflightError as exc:
                raise CandidateArtifactError(
                    f"exact Product package preflight failed: {exc}"
                ) from exc


def _translated_legacy_metadata(
    current: dict[str, object],
    expected_config_sha256: str,
) -> dict[str, object]:
    legacy = {
        key: value
        for key, value in current.items()
        if key
        not in {
            "user_sound_pack_zip_sha256",
            "user_sound_inventory_sha256",
            "user_sound_wav_count",
        }
    }
    legacy["winforms_accessibility_config_sha256"] = expected_config_sha256
    return legacy


def _translate_outer_metadata(
    source_path: Path,
    target_path: Path,
    translated_metadata: dict[str, object],
) -> None:
    try:
        source = zipfile.ZipFile(source_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateArtifactError("outer artifact is not a valid ZIP") from exc
    with source, zipfile.ZipFile(target_path, "w") as target:
        seen_metadata = False
        for info in source.infolist():
            if info.filename == RUN_METADATA_PATH:
                if seen_metadata:
                    raise CandidateArtifactError("duplicate current run metadata member")
                seen_metadata = True
                payload = (
                    json.dumps(translated_metadata, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8")
                target.writestr(info, payload)
                continue
            with source.open(info, "r") as source_member, target.open(info, "w") as target_member:
                shutil.copyfileobj(source_member, target_member, length=HASH_CHUNK_BYTES)
        if not seen_metadata:
            raise CandidateArtifactError("current run metadata is missing")


def _stream_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while True:
            block = source.read(HASH_CHUNK_BYTES)
            if not block:
                break
            total += len(block)
            if total > MAX_OUTER_BYTES:
                raise CandidateArtifactError("outer artifact exceeds accepted size bound while hashing")
            digest.update(block)
    if total != path.stat().st_size:
        raise CandidateArtifactError("outer artifact changed while being hashed")
    return digest.hexdigest()


def verify_current(
    outer_path: Path,
    expected_sha: str,
    expected_workflow_sha: str,
    expected_config_sha256: str,
    expected_outer_sha256: str | None = None,
) -> None:
    expected_sha = expected_sha.strip().lower()
    expected_workflow_sha = expected_workflow_sha.strip().lower()
    if not HEX40.fullmatch(expected_sha):
        raise CandidateArtifactError("expected product SHA must be exact lowercase 40-hex")
    if not HEX40.fullmatch(expected_workflow_sha):
        raise CandidateArtifactError("expected workflow SHA must be exact lowercase 40-hex")
    expected_config_sha256 = _normalize_sha256(
        expected_config_sha256,
        "exact Product WinForms config SHA-256",
    )

    if not outer_path.is_file() or outer_path.is_symlink():
        raise CandidateArtifactError("outer artifact must be a direct regular file")
    size = outer_path.stat().st_size
    if size <= 0 or size > MAX_OUTER_BYTES:
        raise CandidateArtifactError("outer artifact size is outside accepted bounds")
    digest = _stream_sha256(outer_path)
    if expected_outer_sha256 is not None:
        wanted = _normalize_sha256(expected_outer_sha256, "outer artifact SHA-256")
        if digest != wanted:
            raise CandidateArtifactError("outer artifact SHA-256 mismatch")

    metadata = _read_current_run_metadata(
        outer_path,
        expected_sha,
        expected_workflow_sha,
    )
    _verify_current_sound_binding(outer_path, expected_sha, metadata)
    _verify_exact_product_package_preflight(outer_path, expected_sha)
    translated = _translated_legacy_metadata(metadata, expected_config_sha256)

    with tempfile.TemporaryDirectory() as directory:
        legacy_outer = Path(directory) / "legacy-contract-artifact.zip"
        _translate_outer_metadata(outer_path, legacy_outer, translated)
        verify_legacy_contract(
            legacy_outer,
            expected_sha,
            expected_outer_sha256=None,
            expected_workflow_sha=expected_workflow_sha,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a current-schema W4 Accessible Chess candidate artifact"
    )
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--product-config-sha256", required=True)
    parser.add_argument("--outer-sha256")
    args = parser.parse_args()
    try:
        verify_current(
            args.artifact,
            args.product_sha,
            args.workflow_sha,
            args.product_config_sha256,
            args.outer_sha256,
        )
    except CandidateArtifactError as exc:
        print(f"W4 CURRENT CANDIDATE ARTIFACT READBACK FAIL: {exc}")
        return 1
    print("W4 CURRENT CANDIDATE ARTIFACT READBACK VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

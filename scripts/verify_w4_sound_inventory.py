from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile


HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HASH_CHUNK_BYTES = 1024 * 1024
MAX_OUTER_BYTES = 300 * 1024 * 1024
MAX_INNER_BYTES = 250 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
RUN_METADATA_PATH = "p0-evidence/w4-run-metadata.json"
SOUND_ROOT = "AccessibleChess/assets/sounds"
SOUND_INVENTORY_PATH = f"{SOUND_ROOT}/inventory.json"
SOUND_NOTICE_PATH = "THIRD_PARTY_NOTICES/SOUND_INVENTORY.json"
SOUND_WAV_COUNT = 330
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


class SoundInventoryVerificationError(RuntimeError):
    pass


def _load_json(data: bytes, label: str) -> dict[str, object]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise SoundInventoryVerificationError(f"{label} is not UTF-8") from exc

    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise SoundInventoryVerificationError(
                    f"{label} has duplicate JSON key: {key}"
                )
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=no_duplicates)
    except SoundInventoryVerificationError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise SoundInventoryVerificationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SoundInventoryVerificationError(f"{label} root must be an object")
    return value


def _safe_members(
    archive: zipfile.ZipFile,
    label: str,
) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    folded_names: set[str] = set()
    for info in archive.infolist():
        raw = info.filename.replace("\\", "/")
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise SoundInventoryVerificationError(
                f"{label} contains unsafe path: {raw}"
            )
        canonical = path.as_posix()
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type == stat.S_IFLNK:
            raise SoundInventoryVerificationError(
                f"{label} contains symbolic link entry: {canonical}"
            )
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise SoundInventoryVerificationError(
                f"{label} contains unsupported special file entry: {canonical}"
            )
        folded = canonical.casefold()
        if folded in folded_names:
            raise SoundInventoryVerificationError(
                f"{label} contains case-insensitive duplicate: {canonical}"
            )
        folded_names.add(folded)
        members[canonical] = info
    return members


def _member_bytes(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    label: str,
) -> bytes:
    if info.is_dir() or info.file_size <= 0 or info.file_size > MAX_METADATA_BYTES:
        raise SoundInventoryVerificationError(
            f"{label} size is outside accepted bounds"
        )
    try:
        data = archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise SoundInventoryVerificationError(f"{label} could not be read") from exc
    if len(data) != info.file_size:
        raise SoundInventoryVerificationError(f"{label} changed while being read")
    return data


def _sha256_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    total = 0
    try:
        with archive.open(info, "r") as source:
            while True:
                block = source.read(HASH_CHUNK_BYTES)
                if not block:
                    break
                total += len(block)
                digest.update(block)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise SoundInventoryVerificationError(
            f"packaged sound WAV could not be hashed: {info.filename}"
        ) from exc
    if total != info.file_size:
        raise SoundInventoryVerificationError(
            f"packaged sound WAV changed while hashing: {info.filename}"
        )
    return digest.hexdigest()


def _validate_run_metadata(
    value: dict[str, object],
    expected_product_sha: str,
    expected_workflow_sha: str,
) -> dict[str, object]:
    if set(value) != CURRENT_RUN_METADATA_KEYS:
        raise SoundInventoryVerificationError("current run metadata key set mismatch")
    if type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
        raise SoundInventoryVerificationError(
            "current run metadata schema_version must equal 1"
        )
    product_sha = value.get("product_sha")
    workflow_sha = value.get("workflow_sha")
    if product_sha != expected_product_sha:
        raise SoundInventoryVerificationError("current run metadata product_sha mismatch")
    if workflow_sha != expected_workflow_sha:
        raise SoundInventoryVerificationError("current run metadata workflow_sha mismatch")
    if value.get("pre_upload_product_freshness") is not True:
        raise SoundInventoryVerificationError(
            "current run metadata lacks product freshness proof"
        )
    if value.get("pre_upload_workflow_freshness") is not True:
        raise SoundInventoryVerificationError(
            "current run metadata lacks workflow freshness proof"
        )
    if value.get("human_tested") is not False or value.get("nvda_verified") is not False:
        raise SoundInventoryVerificationError(
            "current run metadata overclaims human or NVDA acceptance"
        )
    archive_sha = value.get("user_sound_pack_zip_sha256")
    inventory_sha = value.get("user_sound_inventory_sha256")
    wav_count = value.get("user_sound_wav_count")
    if not isinstance(archive_sha, str) or not HEX64.fullmatch(archive_sha):
        raise SoundInventoryVerificationError(
            "current run metadata sound archive SHA-256 is invalid"
        )
    if not isinstance(inventory_sha, str) or not HEX64.fullmatch(inventory_sha):
        raise SoundInventoryVerificationError(
            "current run metadata sound inventory SHA-256 is invalid"
        )
    if type(wav_count) is not int or wav_count != SOUND_WAV_COUNT:
        raise SoundInventoryVerificationError(
            f"current run metadata sound WAV count must equal {SOUND_WAV_COUNT}"
        )
    return value


def _validate_inventory_file_name(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("library/"):
        raise SoundInventoryVerificationError(
            "sound inventory WAV path must be library-relative"
        )
    if "\\" in value or "\x00" in value:
        raise SoundInventoryVerificationError("sound inventory WAV path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or ".." in path.parts:
        raise SoundInventoryVerificationError("sound inventory WAV path is unsafe")
    relative = value[len("library/") :]
    if not relative or not relative.casefold().endswith(".wav"):
        raise SoundInventoryVerificationError(
            "sound inventory entry is not a WAV path"
        )
    return value


def _verify_candidate_sound_inventory(
    candidate: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    metadata: dict[str, object],
) -> None:
    inventory_info = members.get(SOUND_INVENTORY_PATH)
    notice_info = members.get(SOUND_NOTICE_PATH)
    if inventory_info is None:
        raise SoundInventoryVerificationError("packaged sound inventory is missing")
    if notice_info is None:
        raise SoundInventoryVerificationError("packaged sound audit notice is missing")
    inventory = _load_json(
        _member_bytes(candidate, inventory_info, "packaged sound inventory"),
        "packaged sound inventory",
    )
    notice = _load_json(
        _member_bytes(candidate, notice_info, "packaged sound audit notice"),
        "packaged sound audit notice",
    )
    if notice != inventory:
        raise SoundInventoryVerificationError(
            "packaged sound audit notice does not equal inventory"
        )

    if type(inventory.get("schema_version")) is not int or inventory.get("schema_version") != 1:
        raise SoundInventoryVerificationError("sound inventory schema_version must equal 1")
    if inventory.get("file_count") != SOUND_WAV_COUNT:
        raise SoundInventoryVerificationError(
            f"sound inventory file_count must equal {SOUND_WAV_COUNT}"
        )
    if inventory.get("source_archive_sha256") != metadata["user_sound_pack_zip_sha256"]:
        raise SoundInventoryVerificationError(
            "sound inventory source archive SHA-256 does not match run metadata"
        )
    source_archive_bytes = inventory.get("source_archive_bytes")
    if type(source_archive_bytes) is not int or source_archive_bytes <= 0:
        raise SoundInventoryVerificationError(
            "sound inventory source archive byte count is invalid"
        )
    authorized_inventory_sha = metadata["user_sound_inventory_sha256"]
    if inventory.get("source_inventory_sha256") != authorized_inventory_sha:
        raise SoundInventoryVerificationError(
            "sound inventory authority SHA-256 does not match run metadata"
        )

    rows = inventory.get("files")
    if not isinstance(rows, list) or len(rows) != SOUND_WAV_COUNT:
        raise SoundInventoryVerificationError(
            f"sound inventory files must contain exactly {SOUND_WAV_COUNT} rows"
        )

    listed_members: set[str] = set()
    folded_paths: set[str] = set()
    fingerprint_rows: list[bytes] = []
    previous_sort_key: str | None = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SoundInventoryVerificationError(
                f"sound inventory row {index} must be an object"
            )
        file_name = _validate_inventory_file_name(row.get("file"))
        sort_key = file_name.casefold()
        if previous_sort_key is not None and sort_key <= previous_sort_key:
            raise SoundInventoryVerificationError(
                "sound inventory files are not in canonical casefold order"
            )
        previous_sort_key = sort_key
        if sort_key in folded_paths:
            raise SoundInventoryVerificationError(
                f"sound inventory contains duplicate WAV path: {file_name}"
            )
        folded_paths.add(sort_key)

        digest = row.get("sha256")
        byte_count = row.get("bytes")
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise SoundInventoryVerificationError(
                f"sound inventory row {index} SHA-256 is invalid"
            )
        if type(byte_count) is not int or byte_count <= 0:
            raise SoundInventoryVerificationError(
                f"sound inventory row {index} byte count is invalid"
            )

        member_name = f"{SOUND_ROOT}/{file_name}"
        member = members.get(member_name)
        if member is None or member.is_dir():
            raise SoundInventoryVerificationError(
                f"sound inventory WAV is missing from candidate: {file_name}"
            )
        if member.file_size != byte_count:
            raise SoundInventoryVerificationError(
                f"packaged sound WAV byte count mismatch: {file_name}"
            )
        if _sha256_member(candidate, member) != digest:
            raise SoundInventoryVerificationError(
                f"packaged sound WAV SHA-256 mismatch: {file_name}"
            )
        listed_members.add(member_name)
        relative_source_name = file_name[len("library/") :]
        fingerprint_rows.append(
            f"{relative_source_name}\0{digest}\n".encode("utf-8")
        )

    wav_prefix = f"{SOUND_ROOT}/library/"
    actual_wavs = {
        name
        for name, info in members.items()
        if not info.is_dir()
        and name.startswith(wav_prefix)
        and name.casefold().endswith(".wav")
    }
    if actual_wavs != listed_members:
        missing = sorted(listed_members - actual_wavs)
        untracked = sorted(actual_wavs - listed_members)
        raise SoundInventoryVerificationError(
            f"packaged sound WAV inventory mismatch; missing={missing} untracked={untracked}"
        )
    if len(actual_wavs) != SOUND_WAV_COUNT:
        raise SoundInventoryVerificationError(
            f"packaged sound WAV count must equal {SOUND_WAV_COUNT}"
        )

    recomputed_inventory_sha = hashlib.sha256(b"".join(fingerprint_rows)).hexdigest()
    if recomputed_inventory_sha != authorized_inventory_sha:
        raise SoundInventoryVerificationError(
            "recomputed sound source inventory SHA-256 does not match authorized identity"
        )


def verify(
    outer_path: Path,
    expected_product_sha: str,
    expected_workflow_sha: str,
) -> None:
    expected_product_sha = expected_product_sha.strip().lower()
    expected_workflow_sha = expected_workflow_sha.strip().lower()
    if not HEX40.fullmatch(expected_product_sha):
        raise SoundInventoryVerificationError(
            "expected product SHA must be exact lowercase 40-hex"
        )
    if not HEX40.fullmatch(expected_workflow_sha):
        raise SoundInventoryVerificationError(
            "expected workflow SHA must be exact lowercase 40-hex"
        )
    if not outer_path.is_file() or outer_path.is_symlink():
        raise SoundInventoryVerificationError(
            "outer artifact must be a direct regular file"
        )
    try:
        outer_size = outer_path.stat().st_size
    except OSError as exc:
        raise SoundInventoryVerificationError(
            "outer artifact size is unavailable"
        ) from exc
    if outer_size <= 0 or outer_size > MAX_OUTER_BYTES:
        raise SoundInventoryVerificationError(
            "outer artifact size is outside accepted bounds"
        )

    try:
        outer = zipfile.ZipFile(outer_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise SoundInventoryVerificationError(
            "outer artifact is not a valid ZIP"
        ) from exc
    with outer:
        outer_members = _safe_members(outer, "outer artifact")
        metadata_info = outer_members.get(RUN_METADATA_PATH)
        if metadata_info is None:
            raise SoundInventoryVerificationError("current run metadata is missing")
        metadata = _validate_run_metadata(
            _load_json(
                _member_bytes(outer, metadata_info, "current run metadata"),
                "current run metadata",
            ),
            expected_product_sha,
            expected_workflow_sha,
        )
        candidate_name = (
            f"Accessible-Chess-V2-{expected_product_sha[:7]}-NVDA-test-candidate.zip"
        )
        candidate_info = outer_members.get(candidate_name)
        if candidate_info is None or candidate_info.is_dir():
            raise SoundInventoryVerificationError("current candidate ZIP is missing")
        if candidate_info.file_size <= 0 or candidate_info.file_size > MAX_INNER_BYTES:
            raise SoundInventoryVerificationError(
                "current candidate ZIP size is outside accepted bounds"
            )
        with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as nested:
            with outer.open(candidate_info, "r") as source:
                shutil.copyfileobj(source, nested, length=HASH_CHUNK_BYTES)
            nested.seek(0)
            try:
                candidate = zipfile.ZipFile(nested, "r")
            except zipfile.BadZipFile as exc:
                raise SoundInventoryVerificationError(
                    "current candidate payload is not a valid ZIP"
                ) from exc
            with candidate:
                members = _safe_members(candidate, "current candidate ZIP")
                _verify_candidate_sound_inventory(candidate, members, metadata)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify W4 packaged sound bytes against the authorized user inventory"
    )
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--workflow-sha", required=True)
    args = parser.parse_args()
    try:
        verify(args.artifact, args.product_sha, args.workflow_sha)
    except SoundInventoryVerificationError as exc:
        print(f"W4 SOUND INVENTORY READBACK FAIL: {exc}")
        return 1
    print("W4 SOUND INVENTORY READBACK VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

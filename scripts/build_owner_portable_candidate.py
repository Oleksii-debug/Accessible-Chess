from __future__ import annotations

"""Build and qualify the owner-specific one-click Windows candidate.

This is a release/build seam, not a second chess, PGN, Library or sound engine.
It composes the existing portable-package authority with the canonical private
Library seed importer and exact user-sound-pack identity authority.

The generic portable package may exist without private owner content. The final
owner candidate may not: this module fails closed unless the immutable package
contains the required private seed, exact 330-WAV inventory, and two explicitly
SHA-256-authorized DOCX inputs.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Mapping

from acs.acsdb import AcsDatabase
from acs.user_library_seed import (
    UserLibrarySeedError,
    import_user_library_seed,
    load_user_library_seed,
)
from acs.version2_package_preflight import _passive_path
from acs.version2_portable_package import (
    Version2PortablePackageError,
    _portable_docx_filename,
    _stable_bytes,
    _stable_digest,
    assemble_portable_oneclick_tree,
    validate_portable_oneclick_tree,
    write_portable_oneclick_zip,
)
from scripts.build_user_sound_pack import (
    EXPECTED_SOURCE_INVENTORY_SHA256,
    EXPECTED_SOURCE_WAV_COUNT,
    PROVENANCE_CREATOR,
    PROVENANCE_LICENSE,
    PROVENANCE_SOURCE,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OWNER_JSON_MAX_BYTES = 1024 * 1024
class OwnerPortableCandidateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OwnerPortableCandidateReport:
    package_root: Path
    archive_path: Path
    archive_sha256: str
    integration_sha: str
    document_sha256: tuple[str, str]
    sound_archive_sha256: str
    sound_inventory_sha256: str
    package_checksum_sha256: str
    sound_wav_count: int
    seed_source_count: int
    seed_game_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "package_root": str(self.package_root),
            "archive_path": str(self.archive_path),
            "archive_sha256": self.archive_sha256,
            "integration_sha": self.integration_sha,
            "document_sha256": list(self.document_sha256),
            "sound_archive_sha256": self.sound_archive_sha256,
            "sound_inventory_sha256": self.sound_inventory_sha256,
            "package_checksum_sha256": self.package_checksum_sha256,
            "sound_wav_count": self.sound_wav_count,
            "seed_source_count": self.seed_source_count,
            "seed_game_count": self.seed_game_count,
            "human_tested": False,
            "nvda_verified": False,
            "result": "PASS",
        }


def _fail(message: str) -> None:
    raise OwnerPortableCandidateError(message)


def _owner_docx_filename(name: str) -> str:
    """Validate an external DOCX filename before constructing a Path."""

    if type(name) is not str:
        _fail("owner Word document filename is not Win32-portable")
    try:
        return _portable_docx_filename(name)
    except Version2PortablePackageError as exc:
        # Preserve the more diagnostic owner-facing Unicode error while keeping
        # every actual Win32 filename rule in the generic portable authority.
        try:
            name.encode("utf-16-le", errors="strict")
        except UnicodeEncodeError as unicode_exc:
            raise OwnerPortableCandidateError(
                "owner Word document filename is not valid Unicode for Win32"
            ) from unicode_exc
        raise OwnerPortableCandidateError(
            "owner Word document filename is not Win32-portable"
        ) from exc


def _owner_docx_name(path: Path) -> str:
    """Validate the basename of an already-materialized owner DOCX path."""

    return _owner_docx_filename(path.name)


def _sha256_value(value: object, *, label: str) -> str:
    if type(value) is not str:
        _fail(f"{label} SHA-256 is invalid")
    normalized = value.strip().casefold()
    if _SHA256_RE.fullmatch(normalized) is None:
        _fail(f"{label} SHA-256 is invalid")
    return normalized


def _file_sha256(path: Path) -> str:
    try:
        return _stable_digest(path, label=f"owner candidate file {path.name}")
    except Version2PortablePackageError as exc:
        raise OwnerPortableCandidateError(
            f"candidate file cannot be hashed safely: {path.name}"
        ) from exc


def _strict_json_object(path: Path, *, label: str) -> dict[str, object]:
    def unique_pairs(items):
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail(f"{label} contains duplicate keys")
            result[key] = value
        return result

    try:
        payload = _stable_bytes(
            path,
            label=label,
            maximum=_OWNER_JSON_MAX_BYTES,
        )
        text = payload.decode("utf-8-sig", errors="strict")
        value = json.loads(text, object_pairs_hook=unique_pairs)
    except OwnerPortableCandidateError:
        raise
    except Version2PortablePackageError as exc:
        raise OwnerPortableCandidateError(f"{label} cannot be read safely") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OwnerPortableCandidateError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    return value


def _portable_inventory_name(value: object) -> str:
    if type(value) is not str:
        _fail("owner sound inventory filename is invalid")
    pure = PurePosixPath(value)
    if (
        not value
        or pure.is_absolute()
        or pure.as_posix() != value
        or len(pure.parts) < 2
        or pure.parts[0] != "library"
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in value
        or "\x00" in value
        or not value.casefold().endswith(".wav")
    ):
        _fail("owner sound inventory filename is invalid")
    return value


def _validate_owner_sound_pack(
    sound_root: Path,
    *,
    expected_archive_sha256: str,
) -> tuple[int, str, str]:
    expected_archive = _sha256_value(
        expected_archive_sha256,
        label="owner sound archive",
    )
    inventory = _strict_json_object(
        sound_root / "inventory.json",
        label="owner sound inventory",
    )
    if set(inventory) != {
        "schema_version",
        "source",
        "license_id",
        "creator",
        "file_count",
        "source_inventory_sha256",
        "source_archive_sha256",
        "source_archive_bytes",
        "files",
    }:
        _fail("owner sound inventory contract is invalid")
    if (
        type(inventory["schema_version"]) is not int
        or inventory["schema_version"] != 1
        or inventory["source"] != PROVENANCE_SOURCE
        or inventory["license_id"] != PROVENANCE_LICENSE
        or inventory["creator"] != PROVENANCE_CREATOR
        or type(inventory["file_count"]) is not int
        or inventory["file_count"] != EXPECTED_SOURCE_WAV_COUNT
        or type(inventory["source_archive_bytes"]) is not int
        or inventory["source_archive_bytes"] <= 0
    ):
        _fail("owner sound inventory identity is invalid")

    declared_archive = _sha256_value(
        inventory["source_archive_sha256"],
        label="declared owner sound archive",
    )
    if declared_archive != expected_archive:
        _fail("owner sound archive SHA-256 does not match the authorized input")

    files = inventory["files"]
    if not isinstance(files, list) or len(files) != EXPECTED_SOURCE_WAV_COUNT:
        _fail("owner sound inventory file count is invalid")

    declared: dict[str, tuple[str, str, int]] = {}
    fingerprint_rows: list[tuple[str, bytes]] = []
    for item in files:
        if not isinstance(item, Mapping) or not {"file", "sha256", "bytes"}.issubset(item):
            _fail("owner sound inventory file metadata is invalid")
        name = _portable_inventory_name(item["file"])
        folded = name.casefold()
        if folded in declared:
            _fail("owner sound inventory contains duplicate filenames")
        digest = _sha256_value(item["sha256"], label="owner sound file")
        size = item["bytes"]
        if type(size) is not int or size <= 0:
            _fail("owner sound inventory file byte size is invalid")
        declared[folded] = (name, digest, size)
        source_relative = name[len("library/") :]
        fingerprint_rows.append(
            (
                source_relative.casefold(),
                f"{source_relative}\0{digest}\n".encode("utf-8"),
            )
        )

    library = sound_root / "library"
    try:
        actual_paths = tuple(
            path
            for path in library.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".wav"
        )
        all_sound_wavs = tuple(
            path
            for path in sound_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".wav"
        )
    except OSError as exc:
        raise OwnerPortableCandidateError("owner sound tree cannot be enumerated") from exc
    if (
        len(actual_paths) != EXPECTED_SOURCE_WAV_COUNT
        or len(all_sound_wavs) != EXPECTED_SOURCE_WAV_COUNT
    ):
        _fail("owner sound tree does not contain exactly the authorized 330 WAV files")

    actual_names: set[str] = set()
    for path in actual_paths:
        try:
            relative = PurePosixPath(*path.relative_to(sound_root).parts).as_posix()
        except ValueError as exc:
            raise OwnerPortableCandidateError("owner sound path escaped its root") from exc
        folded = relative.casefold()
        if folded in actual_names:
            _fail("owner sound tree contains case-colliding WAV paths")
        actual_names.add(folded)
        metadata = declared.get(folded)
        if metadata is None:
            _fail("owner sound tree contains a WAV not declared by inventory")
        _name, expected_digest, expected_size = metadata
        try:
            payload = _stable_bytes(
                path,
                label="owner sound WAV",
                maximum=expected_size,
            )
        except Version2PortablePackageError as exc:
            raise OwnerPortableCandidateError(
                "owner sound WAV cannot be read safely"
            ) from exc
        if (
            len(payload) != expected_size
            or hashlib.sha256(payload).hexdigest() != expected_digest
        ):
            _fail("owner sound WAV bytes do not match inventory")

    if actual_names != set(declared):
        _fail("owner sound inventory does not match the packaged WAV tree")

    computed_inventory = hashlib.sha256(
        b"".join(row for _folded, row in sorted(fingerprint_rows, key=lambda item: item[0]))
    ).hexdigest()
    declared_inventory = _sha256_value(
        inventory["source_inventory_sha256"],
        label="owner sound inventory",
    )
    if (
        computed_inventory != EXPECTED_SOURCE_INVENTORY_SHA256
        or declared_inventory != EXPECTED_SOURCE_INVENTORY_SHA256
    ):
        _fail("owner sound inventory does not match the exact authorized 330-WAV identity")

    return len(actual_paths), declared_inventory, declared_archive


def _validate_owner_seed(
    seed_root: Path,
    *,
    expected_source_count: int,
    expected_game_count: int,
) -> tuple[int, int]:
    if type(expected_source_count) is not int or expected_source_count <= 0:
        _fail("expected owner Library source count is invalid")
    if type(expected_game_count) is not int or expected_game_count <= 0:
        _fail("expected owner Library game count is invalid")
    try:
        manifest = load_user_library_seed(seed_root)
    except UserLibrarySeedError as exc:
        raise OwnerPortableCandidateError(
            "owner Library seed failed canonical validation"
        ) from exc
    try:
        with AcsDatabase(":memory:") as database:
            summary = import_user_library_seed(database, manifest)
    except UserLibrarySeedError as exc:
        raise OwnerPortableCandidateError(
            "owner Library seed failed canonical import qualification"
        ) from exc
    except Exception as exc:
        raise OwnerPortableCandidateError(
            "owner Library seed import qualification failed unexpectedly"
        ) from exc

    if summary.source_count != expected_source_count:
        _fail(
            "owner Library seed source count mismatch: "
            f"actual={summary.source_count} expected={expected_source_count}"
        )
    if summary.game_count != expected_game_count:
        _fail(
            "owner Library seed game count mismatch: "
            f"actual={summary.game_count} expected={expected_game_count}"
        )
    if summary.reused_source_count != 0:
        _fail("owner Library seed qualification unexpectedly reused sources")
    return summary.source_count, summary.game_count


def validate_owner_portable_candidate_tree(
    package_root: str | Path,
    *,
    expected_integration_sha: str,
    expected_sound_archive_sha256: str,
    expected_seed_source_count: int = 6,
    expected_seed_game_count: int = 3738,
) -> dict[str, object]:
    if type(expected_seed_source_count) is not int or expected_seed_source_count <= 0:
        _fail("expected owner Library source count is invalid")
    if type(expected_seed_game_count) is not int or expected_seed_game_count <= 0:
        _fail("expected owner Library game count is invalid")
    root = _passive_path(package_root, label="owner portable package root")
    try:
        portable = validate_portable_oneclick_tree(
            root,
            expected_integration_sha=expected_integration_sha,
            require_user_seed=True,
        )
    except Version2PortablePackageError as exc:
        raise OwnerPortableCandidateError(
            "portable package failed canonical one-click validation"
        ) from exc

    package_checksum = _sha256_value(
        portable.checksum_sha256,
        label="portable package checksum snapshot",
    )

    sound_count, sound_inventory, sound_archive = _validate_owner_sound_pack(
        root / "App" / "assets" / "sounds",
        expected_archive_sha256=expected_sound_archive_sha256,
    )
    seed_sources, seed_games = _validate_owner_seed(
        root / "App" / "release-content" / "user-library-seed",
        expected_source_count=expected_seed_source_count,
        expected_game_count=expected_seed_game_count,
    )
    return {
        "integration_sha": portable.integration_sha,
        "inventory_count": len(portable.inventory),
        "total_bytes": portable.total_bytes,
        "sound_wav_count": sound_count,
        "sound_inventory_sha256": sound_inventory,
        "sound_archive_sha256": sound_archive,
        "package_checksum_sha256": package_checksum,
        "seed_source_count": seed_sources,
        "seed_game_count": seed_games,
    }


def assemble_owner_portable_candidate(
    canonical_package_root: str | Path,
    launcher_exe: str | Path,
    word_documents: tuple[str | Path, str | Path],
    output_root: str | Path,
    output_zip: str | Path,
    *,
    integration_sha: str,
    expected_document_sha256: tuple[str, str],
    expected_sound_archive_sha256: str,
    expected_seed_source_count: int = 6,
    expected_seed_game_count: int = 3738,
) -> OwnerPortableCandidateReport:
    # These values are caller-controlled release policy. Reject derived
    # containers/counts before len(), iteration, path coercion or package work
    # can execute caller hooks.
    if type(expected_document_sha256) is not tuple or len(expected_document_sha256) != 2:
        raise TypeError("expected_document_sha256 must be an exact two-item tuple")
    if type(word_documents) is not tuple or len(word_documents) != 2:
        raise TypeError("word_documents must be an exact two-item tuple")
    if type(expected_seed_source_count) is not int or expected_seed_source_count <= 0:
        _fail("expected owner Library source count is invalid")
    if type(expected_seed_game_count) is not int or expected_seed_game_count <= 0:
        _fail("expected owner Library game count is invalid")

    canonical = _passive_path(
        canonical_package_root,
        label="owner canonical package root",
    )
    launcher = _passive_path(launcher_exe, label="owner portable launcher source")
    output = _passive_path(output_root, label="owner portable package output")
    archive_output = _passive_path(output_zip, label="owner portable ZIP output")
    documents = tuple(
        _passive_path(item, label="owner Word document source")
        for item in word_documents
    )
    document_names = tuple(_owner_docx_name(path) for path in documents)
    if len({name.casefold() for name in document_names}) != 2:
        _fail("owner Word documents must have distinct Win32 filenames")
    document_digests = tuple(
        _sha256_value(value, label=f"owner Word document {index + 1}")
        for index, value in enumerate(expected_document_sha256)
    )
    sound_archive = _sha256_value(
        expected_sound_archive_sha256,
        label="owner sound archive",
    )

    assembled = assemble_portable_oneclick_tree(
        canonical,
        launcher,
        documents,
        output,
        integration_sha=integration_sha,
        require_user_seed=True,
    )
    root = assembled.package_root
    for source, expected_digest in zip(documents, document_digests, strict=True):
        if _file_sha256(root / source.name) != expected_digest:
            _fail("packaged owner Word document does not match its authorized SHA-256")

    qualification = validate_owner_portable_candidate_tree(
        root,
        expected_integration_sha=integration_sha,
        expected_sound_archive_sha256=sound_archive,
        expected_seed_source_count=expected_seed_source_count,
        expected_seed_game_count=expected_seed_game_count,
    )

    # Re-bind the owner-authorized document bytes after owner qualification.
    # The early check rejects bad assembly cheaply. This second check closes
    # the document+CHECKSUMS rewrite window before ZIP publication, which is
    # pinned to the qualification checksum snapshot below.
    for source, expected_digest in zip(documents, document_digests, strict=True):
        if _file_sha256(root / source.name) != expected_digest:
            _fail("packaged owner Word document changed after owner qualification")
    archived = write_portable_oneclick_zip(
        root,
        archive_output,
        expected_integration_sha=integration_sha,
        require_user_seed=True,
        expected_checksum_sha256=str(qualification["package_checksum_sha256"]),
    )
    if archived.archive_path is None or archived.archive_sha256 is None:
        _fail("owner portable candidate ZIP publication did not return an archive identity")

    return OwnerPortableCandidateReport(
        package_root=root,
        archive_path=archived.archive_path,
        archive_sha256=archived.archive_sha256,
        integration_sha=archived.integration_sha,
        document_sha256=(document_digests[0], document_digests[1]),
        sound_archive_sha256=str(qualification["sound_archive_sha256"]),
        sound_inventory_sha256=str(qualification["sound_inventory_sha256"]),
        package_checksum_sha256=str(qualification["package_checksum_sha256"]),
        sound_wav_count=int(qualification["sound_wav_count"]),
        seed_source_count=int(qualification["seed_source_count"]),
        seed_game_count=int(qualification["seed_game_count"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the exact owner-specific Accessible Chess portable candidate",
    )
    parser.add_argument("canonical_package_root", type=Path)
    parser.add_argument("launcher_exe", type=Path)
    parser.add_argument("first_docx", type=Path)
    parser.add_argument("second_docx", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("output_zip", type=Path)
    parser.add_argument("--integration-sha", required=True)
    parser.add_argument("--first-docx-sha256", required=True)
    parser.add_argument("--second-docx-sha256", required=True)
    parser.add_argument("--sound-archive-sha256", required=True)
    parser.add_argument("--seed-source-count", type=int, default=6)
    parser.add_argument("--seed-game-count", type=int, default=3738)
    args = parser.parse_args()

    report = assemble_owner_portable_candidate(
        args.canonical_package_root,
        args.launcher_exe,
        (args.first_docx, args.second_docx),
        args.output_root,
        args.output_zip,
        integration_sha=args.integration_sha,
        expected_document_sha256=(args.first_docx_sha256, args.second_docx_sha256),
        expected_sound_archive_sha256=args.sound_archive_sha256,
        expected_seed_source_count=args.seed_source_count,
        expected_seed_game_count=args.seed_game_count,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
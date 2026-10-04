from __future__ import annotations

"""Build and qualify the owner-specific one-click Windows candidate.

This is a release/build seam, not a second chess, PGN, Library or sound engine.
It composes the existing portable-package authority with the existing private
Library seed importer and the exact user-sound-pack identity authority.

The generic portable package intentionally supports products without private
owner content.  The final owner candidate does not: this module fails closed
unless the immutable package contains the explicitly required private Library
seed and exact 330-WAV user sound inventory, and unless both requested DOCX
bytes match caller-supplied SHA-256 identities.
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
from acs.version2_portable_package import (
    Version2PortablePackageError,
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
            "sound_wav_count": self.sound_wav_count,
            "seed_source_count": self.seed_source_count,
            "seed_game_count": self.seed_game_count,
            "human_tested": False,
            "nvda_verified": False,
            "result": "PASS",
        }


def _fail(message: str) -> None:
    raise OwnerPortableCandidateError(message)


def _sha256_value(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        _fail(f"{label} SHA-256 is invalid")
    normalized = value.strip().casefold()
    if _SHA256_RE.fullmatch(normalized) is None:
        _fail(f"{label} SHA-256 is invalid")
    return normalized


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise OwnerPortableCandidateError(
            f"candidate file cannot be hashed: {path.name}"
        ) from exc
    return digest.hexdigest()


def _strict_json_object(path: Path, *, label: str) -> dict[str, object]:
    def pairs(items):
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail(f"{label} contains duplicate keys")
            result[key] = value
        return result

    try:
        payload = path.read_text(encoding="utf-8-sig", errors="strict")
        value = json.loads(payload, object_pairs_hook=pairs)
    except OwnerPortableCandidateError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OwnerPortableCandidateError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    return value


def _portable_inventory_name(value: object) -> str:
    if type(value) is not str:
        _fail("owner sound inventory filename is invalid")
    name = value
    pure = PurePosixPath(name)
    if (
        not name
        or pure.is_absolute()
        or pure.as_posix() != name
        or len(pure.parts) < 2
        or pure.parts[0] != "library"
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in name
        or "\x00" in name
        or not name.casefold().endswith(".wav")
    ):
        _fail("owner sound inventory filename is invalid")
    return name


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
    required = {
        "schema_version",
        "source",
        "license_id",
        "creator",
        "file_count",
        "source_inventory_sha256",
        "source_archive_sha256",
        "source_archive_bytes",
        "files",
    }
    if set(inventory) != required:
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
        str(inventory["source_archive_sha256"]),
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
        if not isinstance(item, Mapping):
            _fail("owner sound inventory file metadata is invalid")
        if not {"file", "sha256", "bytes"}.issubset(item):
            _fail("owner sound inventory file metadata is incomplete")
        name = _portable_inventory_name(item["file"])
        folded = name.casefold()
        if folded in declared:
            _fail("owner sound inventory contains duplicate filenames")
        digest = _sha256_value(str(item["sha256"]), label="owner sound file")
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
        _declared_name, expected_digest, expected_size = metadata
        try:
            actual_size = path.stat().st_size
        except OSError as exc:
            raise OwnerPortableCandidateError("owner sound WAV cannot be inspected") from exc
        if actual_size != expected_size or _file_sha256(path) != expected_digest:
            _fail("owner sound WAV bytes do not match inventory")

    if actual_names != set(declared):
        _fail("owner sound inventory does not match the packaged WAV tree")

    computed_inventory = hashlib.sha256(
        b"".join(row for _folded, row in sorted(fingerprint_rows, key=lambda item: item[0]))
    ).hexdigest()
    declared_inventory = _sha256_value(
        str(inventory["source_inventory_sha256"]),
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
        with AcsDatabase(":memory:") as database:
            summary = import_user_library_seed(database, manifest)
    except UserLibrarySeedError as exc:
        raise OwnerPortableCandidateError(
            "owner Library seed failed canonical validation"
        ) from exc
    except Exception as exc:
        raise OwnerPortableCandidateError(
            "owner Library seed failed canonical import qualification"
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
    root = Path(package_root)
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
    if not isinstance(expected_document_sha256, tuple) or len(expected_document_sha256) != 2:
        raise TypeError("expected_document_sha256 must be an exact two-item tuple")
    document_digests = tuple(
        _sha256_value(value, label=f"owner Word document {index + 1}")
        for index, value in enumerate(expected_document_sha256)
    )
    sound_archive = _sha256_value(
        expected_sound_archive_sha256,
        label="owner sound archive",
    )

    assembled = assemble_portable_oneclick_tree(
        canonical_package_root,
        launcher_exe,
        word_documents,
        output_root,
        integration_sha=integration_sha,
        require_user_seed=True,
    )
    root = assembled.package_root
    for source, expected_digest in zip(word_documents, document_digests, strict=True):
        packaged = root / Path(source).name
        if _file_sha256(packaged) != expected_digest:
            _fail("packaged owner Word document does not match its authorized SHA-256")

    qualification = validate_owner_portable_candidate_tree(
        root,
        expected_integration_sha=integration_sha,
        expected_sound_archive_sha256=sound_archive,
        expected_seed_source_count=expected_seed_source_count,
        expected_seed_game_count=expected_seed_game_count,
    )
    archived = write_portable_oneclick_zip(
        root,
        output_zip,
        expected_integration_sha=integration_sha,
        require_user_seed=True,
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
        expected_document_sha256=(
            args.first_docx_sha256,
            args.second_docx_sha256,
        ),
        expected_sound_archive_sha256=args.sound_archive_sha256,
        expected_seed_source_count=args.seed_source_count,
        expected_seed_game_count=args.seed_game_count,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

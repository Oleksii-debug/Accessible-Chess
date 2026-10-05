from __future__ import annotations

"""Security wrapper for the canonical owner portable candidate builder.

The implementation core is retained byte-for-byte in
``scripts._build_owner_portable_candidate_core``. This seam adds fail-closed DOCX
OOXML validation without forking any chess, Library, sound, packaging or checksum
semantics owned by the existing builder.
"""

import argparse
import json
from pathlib import Path

from acs.portable_docx_integrity import PortableDocxIntegrityError, validate_portable_docx
from scripts import _build_owner_portable_candidate_core as _core


OwnerPortableCandidateError = _core.OwnerPortableCandidateError
OwnerPortableCandidateReport = _core.OwnerPortableCandidateReport
_owner_docx_filename = _core._owner_docx_filename
_owner_docx_name = _core._owner_docx_name
_sha256_value = _core._sha256_value
_file_sha256 = _core._file_sha256
_strict_json_object = _core._strict_json_object
_portable_inventory_name = _core._portable_inventory_name
_validate_owner_sound_pack = _core._validate_owner_sound_pack
_validate_owner_seed = _core._validate_owner_seed


def _validate_docx_or_fail(path: Path, *, label: str) -> None:
    try:
        validate_portable_docx(path)
    except PortableDocxIntegrityError as exc:
        raise OwnerPortableCandidateError(f"{label} is not a valid bounded OOXML Word document") from exc


def validate_owner_portable_candidate_tree(
    package_root: str | Path,
    *,
    expected_integration_sha: str,
    expected_sound_archive_sha256: str,
    expected_seed_source_count: int = 6,
    expected_seed_game_count: int = 3738,
) -> dict[str, object]:
    result = _core.validate_owner_portable_candidate_tree(
        package_root,
        expected_integration_sha=expected_integration_sha,
        expected_sound_archive_sha256=expected_sound_archive_sha256,
        expected_seed_source_count=expected_seed_source_count,
        expected_seed_game_count=expected_seed_game_count,
    )
    root = Path(package_root)
    try:
        documents = tuple(
            path for path in root.iterdir() if path.is_file() and path.suffix.casefold() == ".docx"
        )
    except OSError as exc:
        raise OwnerPortableCandidateError("owner portable root cannot be enumerated") from exc
    if len(documents) != 2:
        raise OwnerPortableCandidateError("owner portable package must contain exactly two root Word documents")
    for index, document in enumerate(sorted(documents, key=lambda path: path.name.casefold()), start=1):
        _validate_docx_or_fail(document, label=f"packaged owner Word document {index}")
    return result


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
    if not isinstance(word_documents, tuple) or len(word_documents) != 2:
        raise TypeError("word_documents must be an exact two-item tuple")
    documents = tuple(Path(item) for item in word_documents)
    for index, document in enumerate(documents, start=1):
        _validate_docx_or_fail(document, label=f"source owner Word document {index}")

    report = _core.assemble_owner_portable_candidate(
        canonical_package_root,
        launcher_exe,
        word_documents,
        output_root,
        output_zip,
        integration_sha=integration_sha,
        expected_document_sha256=expected_document_sha256,
        expected_sound_archive_sha256=expected_sound_archive_sha256,
        expected_seed_source_count=expected_seed_source_count,
        expected_seed_game_count=expected_seed_game_count,
    )

    # The core already binds exact authorized SHA-256 values and the package
    # checksum. Re-parse the copied files so valid source bytes cannot become a
    # structurally invalid published DOCX through a packaging-path regression.
    for index, document in enumerate(documents, start=1):
        _validate_docx_or_fail(
            report.package_root / document.name,
            label=f"packaged owner Word document {index}",
        )
    return report


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

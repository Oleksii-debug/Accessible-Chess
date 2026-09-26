from __future__ import annotations

"""Deterministic SPDX 2.3 inventory for one assembled Version 2 package.

The SBOM is release metadata, not a package builder.  It describes the exact
regular payload files that exist after the product/notices tree and release
manifest have been staged.  The SBOM file itself and SHA256SUMS.txt are omitted
from the SPDX file set to avoid circular hashes; SHA256SUMS covers the SBOM.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable


SBOM_NAME = "SBOM.spdx.json"
CHECKSUMS_NAME = "SHA256SUMS.txt"
SPDX_VERSION = "SPDX-2.3"
DATA_LICENSE = "CC0-1.0"
DOCUMENT_SPDX_ID = "SPDXRef-DOCUMENT"
PRODUCT_SPDX_ID = "SPDXRef-Package-Accessible-Chess"
STOCKFISH_SPDX_ID = "SPDXRef-Package-Stockfish-18"
STOCKFISH_EXECUTABLE = "AccessibleChess/engines/stockfish/stockfish.exe"
STOCKFISH_SOURCE = "THIRD_PARTY_NOTICES/Stockfish-18-source.zip"
STOCKFISH_NOTICE = "THIRD_PARTY_NOTICES/Stockfish-NOTICE.txt"
SOUND_PROVENANCE = "THIRD_PARTY_NOTICES/SOUND_PROVENANCE.json"
SOUND_ROOT = "AccessibleChess/assets/sounds"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_LICENSE_RE = re.compile(r"^[A-Za-z0-9.+-]{1,128}$")


class Version2ReleaseSbomError(RuntimeError):
    """Raised when release SBOM generation or validation fails closed."""


def _fail(message: str) -> None:
    raise Version2ReleaseSbomError(message)


def _sha40(value: object) -> str:
    if not isinstance(value, str) or not _SHA40_RE.fullmatch(value.casefold()):
        _fail("SBOM integration_sha must be a 40-hex commit")
    return value.casefold()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        _fail(f"SBOM payload file cannot be hashed: {type(exc).__name__}")
    return digest.hexdigest()


def _json_object(path: Path, *, label: str) -> dict[str, object]:
    def hook(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail(f"{label} contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=hook)
    except Version2ReleaseSbomError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _fail(f"{label} is invalid: {type(exc).__name__}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _payload_files(root: Path, inventory: Iterable[str] | None = None) -> tuple[str, ...]:
    if inventory is None:
        values: list[str] = []
        try:
            for path in root.rglob("*"):
                if path.is_symlink():
                    _fail("SBOM payload must not contain symlinks")
                if path.is_file():
                    values.append(PurePosixPath(*path.relative_to(root).parts).as_posix())
        except Version2ReleaseSbomError:
            raise
        except (OSError, ValueError) as exc:
            _fail(f"SBOM package inventory failed: {type(exc).__name__}")
    else:
        values = list(inventory)
    excluded = {SBOM_NAME, CHECKSUMS_NAME}
    result = tuple(sorted((value for value in values if value not in excluded), key=str.casefold))
    if len(result) != len(set(value.casefold() for value in result)):
        _fail("SBOM package paths collide under Windows case-folding")
    return result


def _file_spdx_id(relative: str) -> str:
    token = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
    return f"SPDXRef-File-{token}"


def _sound_licenses(root: Path) -> dict[str, str]:
    provenance = _json_object(root / SOUND_PROVENANCE, label="sound provenance")
    events = provenance.get("events")
    if not isinstance(events, dict) or not events:
        _fail("sound provenance events are missing")
    result: dict[str, str] = {}
    for event, raw in events.items():
        if not isinstance(event, str) or not isinstance(raw, dict):
            _fail("sound provenance event contract is invalid")
        file_name = raw.get("file")
        license_id = raw.get("license_id")
        if not isinstance(file_name, str) or not file_name or "/" in file_name or "\\" in file_name:
            _fail("sound provenance file name is invalid")
        if not isinstance(license_id, str) or not _SAFE_LICENSE_RE.fullmatch(license_id):
            _fail("sound provenance SPDX license identity is invalid")
        relative = f"{SOUND_ROOT}/{file_name}"
        previous = result.setdefault(relative, license_id)
        if previous != license_id:
            _fail("sound asset has conflicting license identities")
    return result


def _stockfish_notice_is_present(root: Path) -> None:
    notice = root / STOCKFISH_NOTICE
    source = root / STOCKFISH_SOURCE
    executable = root / STOCKFISH_EXECUTABLE
    for path, label in (
        (notice, "Stockfish notice"),
        (source, "Stockfish corresponding source"),
        (executable, "Stockfish executable"),
    ):
        try:
            if not path.is_file() or path.stat().st_size <= 0:
                _fail(f"{label} is missing from SBOM package")
        except OSError as exc:
            _fail(f"{label} cannot be inspected: {type(exc).__name__}")
    try:
        notice_text = notice.read_text(encoding="utf-8-sig").casefold()
    except (OSError, UnicodeError) as exc:
        _fail(f"Stockfish notice is unreadable: {type(exc).__name__}")
    if "stockfish" not in notice_text or "gpl" not in notice_text:
        _fail("Stockfish notice does not identify GPL licensing")


def build_version2_release_sbom(
    root: str | Path,
    *,
    integration_sha: str,
    inventory: Iterable[str] | None = None,
) -> dict[str, object]:
    package_root = Path(root)
    sha = _sha40(integration_sha)
    files = _payload_files(package_root, inventory)
    if not files:
        _fail("SBOM cannot describe an empty package")
    _stockfish_notice_is_present(package_root)
    sound_licenses = _sound_licenses(package_root)
    missing_sounds = sorted(set(sound_licenses) - set(files), key=str.casefold)
    if missing_sounds:
        _fail("sound provenance references files outside the SBOM payload")

    file_rows: list[dict[str, object]] = []
    relationships: list[dict[str, str]] = [
        {
            "spdxElementId": DOCUMENT_SPDX_ID,
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": PRODUCT_SPDX_ID,
        }
    ]
    for relative in files:
        path = package_root.joinpath(*PurePosixPath(relative).parts)
        try:
            if not path.is_file() or path.is_symlink():
                _fail(f"SBOM payload file is not a regular file: {relative}")
        except OSError as exc:
            _fail(f"SBOM payload file cannot be inspected: {type(exc).__name__}")
        file_id = _file_spdx_id(relative)
        license_id = sound_licenses.get(relative, "NOASSERTION")
        file_rows.append(
            {
                "SPDXID": file_id,
                "fileName": f"./{relative}",
                "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256(path)}],
                "licenseConcluded": license_id,
                "licenseInfoInFiles": [license_id],
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": PRODUCT_SPDX_ID,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": file_id,
            }
        )

    relationships.append(
        {
            "spdxElementId": PRODUCT_SPDX_ID,
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": STOCKFISH_SPDX_ID,
        }
    )
    namespace = f"https://github.com/Oleksii-debug/Accessible-Chess/spdx/{sha}"
    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": DATA_LICENSE,
        "SPDXID": DOCUMENT_SPDX_ID,
        "name": f"Accessible Chess V2 package {sha[:12]}",
        "documentNamespace": namespace,
        "creationInfo": {
            "created": "1980-01-01T00:00:00Z",
            "creators": ["Tool: Accessible-Chess deterministic release SBOM generator"],
        },
        "documentDescribes": [PRODUCT_SPDX_ID],
        "packages": [
            {
                "name": "Accessible Chess",
                "SPDXID": PRODUCT_SPDX_ID,
                "versionInfo": sha,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "comment": "Project license is intentionally not inferred; package files are enumerated and hashed below.",
            },
            {
                "name": "Stockfish",
                "SPDXID": STOCKFISH_SPDX_ID,
                "versionInfo": "18",
                "downloadLocation": "https://github.com/official-stockfish/Stockfish/releases/tag/sf_18",
                "filesAnalyzed": False,
                "licenseConcluded": "GPL-3.0-or-later",
                "licenseDeclared": "GPL-3.0-or-later",
                "copyrightText": "NOASSERTION",
                "comment": f"Packaged binary: {STOCKFISH_EXECUTABLE}; corresponding source: {STOCKFISH_SOURCE}; notice: {STOCKFISH_NOTICE}.",
            },
        ],
        "files": file_rows,
        "relationships": relationships,
        "annotations": [
            {
                "annotationDate": "1980-01-01T00:00:00Z",
                "annotationType": "OTHER",
                "annotator": "Tool: Accessible-Chess deterministic release SBOM generator",
                "comment": f"Release metadata excluded from file inventory to avoid cyclic hashes: {SBOM_NAME}, {CHECKSUMS_NAME}. SHA256SUMS covers {SBOM_NAME}.",
            }
        ],
    }


def write_version2_release_sbom(root: str | Path, *, integration_sha: str) -> Path:
    package_root = Path(root)
    target = package_root / SBOM_NAME
    if target.exists():
        _fail("SBOM output must not already exist")
    document = build_version2_release_sbom(package_root, integration_sha=integration_sha)
    try:
        target.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        _fail(f"SBOM could not be written: {type(exc).__name__}")
    return target


def validate_version2_release_sbom(
    root: str | Path,
    *,
    integration_sha: str,
    inventory: Iterable[str],
) -> dict[str, object]:
    package_root = Path(root)
    expected = build_version2_release_sbom(
        package_root,
        integration_sha=integration_sha,
        inventory=inventory,
    )
    actual = _json_object(package_root / SBOM_NAME, label="release SBOM")
    if actual != expected:
        _fail("release SBOM does not exactly describe the packaged payload")
    files = actual.get("files")
    if not isinstance(files, list):
        _fail("release SBOM files contract is invalid")
    seen: set[str] = set()
    for row in files:
        if not isinstance(row, dict):
            _fail("release SBOM file entry is invalid")
        name = row.get("fileName")
        checksums = row.get("checksums")
        if not isinstance(name, str) or not name.startswith("./"):
            _fail("release SBOM file name is invalid")
        if name.casefold() in seen:
            _fail("release SBOM contains duplicate file names")
        seen.add(name.casefold())
        if not isinstance(checksums, list) or len(checksums) != 1:
            _fail("release SBOM file checksum contract is invalid")
        checksum = checksums[0]
        if (
            not isinstance(checksum, dict)
            or checksum.get("algorithm") != "SHA256"
            or not isinstance(checksum.get("checksumValue"), str)
            or not _SHA256_RE.fullmatch(checksum["checksumValue"])
        ):
            _fail("release SBOM SHA-256 contract is invalid")
    return actual

from __future__ import annotations

"""Deterministic SPDX 2.3 sidecar for an exact validated V2 package tree.

The SBOM is deliberately written *outside* the package tree. That lets it hash
every shipped regular file, including RELEASE_MANIFEST.json and SHA256SUMS.txt,
without creating a self-referential checksum cycle or changing package bytes.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable


SBOM_NAME = "AccessibleChess-SBOM.spdx.json"
SPDX_VERSION = "SPDX-2.3"
DATA_LICENSE = "CC0-1.0"
DOCUMENT_SPDX_ID = "SPDXRef-DOCUMENT"
PRODUCT_SPDX_ID = "SPDXRef-Package-Accessible-Chess"
STOCKFISH_SPDX_ID = "SPDXRef-Package-Stockfish-18"
STOCKFISH_EXECUTABLE = "AccessibleChess/engines/stockfish/stockfish.exe"
STOCKFISH_SOURCE = "THIRD_PARTY_NOTICES/Stockfish-18-source.zip"
STOCKFISH_NOTICE = "THIRD_PARTY_NOTICES/Stockfish-NOTICE.txt"
STOCKFISH_LICENSE = "THIRD_PARTY_NOTICES/Stockfish-COPYING.txt"
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


def _scan_payload_files(root: Path) -> tuple[str, ...]:
    values: list[str] = []
    try:
        for path in root.rglob("*"):
            if path.is_symlink():
                _fail("SBOM package must not contain symlinks")
            if path.is_file():
                values.append(PurePosixPath(*path.relative_to(root).parts).as_posix())
    except Version2ReleaseSbomError:
        raise
    except (OSError, ValueError) as exc:
        _fail(f"SBOM package inventory failed: {type(exc).__name__}")
    result = tuple(sorted(values, key=str.casefold))
    if not result:
        _fail("SBOM cannot describe an empty package")
    if len(result) != len(set(value.casefold() for value in result)):
        _fail("SBOM package paths collide under Windows case-folding")
    return result


def _payload_files(root: Path, inventory: Iterable[str] | None) -> tuple[str, ...]:
    actual = _scan_payload_files(root)
    if inventory is None:
        return actual
    supplied = tuple(sorted(inventory, key=str.casefold))
    if len(supplied) != len(set(value.casefold() for value in supplied)):
        _fail("SBOM supplied inventory collides under Windows case-folding")
    if supplied != actual:
        _fail("SBOM supplied inventory does not exactly match package tree")
    return actual


def _file_spdx_id(relative: str) -> str:
    return "SPDXRef-File-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]


def _sound_licenses(root: Path) -> dict[str, str]:
    provenance = _json_object(root / SOUND_PROVENANCE, label="sound provenance")
    events = provenance.get("events")
    if not isinstance(events, dict) or not events:
        _fail("sound provenance events are missing")
    result: dict[str, str] = {}
    for raw in events.values():
        if not isinstance(raw, dict):
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


def _require_stockfish_compliance(root: Path) -> None:
    for relative, label in (
        (STOCKFISH_EXECUTABLE, "Stockfish executable"),
        (STOCKFISH_SOURCE, "Stockfish corresponding source"),
        (STOCKFISH_NOTICE, "Stockfish notice"),
        (STOCKFISH_LICENSE, "Stockfish license text"),
    ):
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            if not path.is_file() or path.stat().st_size <= 0:
                _fail(f"{label} is missing from SBOM package")
        except OSError as exc:
            _fail(f"{label} cannot be inspected: {type(exc).__name__}")
    try:
        notice_text = root.joinpath(*PurePosixPath(STOCKFISH_NOTICE).parts).read_text(
            encoding="utf-8-sig"
        ).casefold()
        license_text = root.joinpath(*PurePosixPath(STOCKFISH_LICENSE).parts).read_text(
            encoding="utf-8-sig"
        ).casefold()
    except (OSError, UnicodeError) as exc:
        _fail(f"Stockfish licensing evidence is unreadable: {type(exc).__name__}")
    if "stockfish" not in notice_text or "gpl" not in notice_text:
        _fail("Stockfish notice does not identify GPL licensing")
    if not all(
        token in license_text
        for token in ("gnu general public license", "version 3", "any later version")
    ):
        _fail("Stockfish license text does not prove GPL-3.0-or-later")


def build_version2_release_sbom(
    root: str | Path,
    *,
    integration_sha: str,
    inventory: Iterable[str] | None = None,
) -> dict[str, object]:
    package_root = Path(root)
    sha = _sha40(integration_sha)
    files = _payload_files(package_root, inventory)
    _require_stockfish_compliance(package_root)
    sound_licenses = _sound_licenses(package_root)
    file_set = set(files)
    provenance_set = set(sound_licenses)
    if provenance_set - file_set:
        _fail("sound provenance references files outside the SBOM payload")
    packaged_sounds = {
        relative for relative in files if relative.startswith(f"{SOUND_ROOT}/")
    }
    if packaged_sounds - provenance_set:
        _fail("packaged sound asset is missing authoritative provenance")

    file_rows: list[dict[str, object]] = []
    relationships: list[dict[str, str]] = [{
        "spdxElementId": DOCUMENT_SPDX_ID,
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": PRODUCT_SPDX_ID,
    }]
    for relative in files:
        path = package_root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file() or path.is_symlink():
            _fail(f"SBOM payload file is not a regular file: {relative}")
        file_id = _file_spdx_id(relative)
        license_id = sound_licenses.get(relative, "NOASSERTION")
        file_rows.append({
            "SPDXID": file_id,
            "fileName": f"./{relative}",
            "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256(path)}],
            "licenseConcluded": license_id,
            "licenseInfoInFiles": [license_id],
            "copyrightText": "NOASSERTION",
        })
        relationships.append({
            "spdxElementId": PRODUCT_SPDX_ID,
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": file_id,
        })
    relationships.append({
        "spdxElementId": PRODUCT_SPDX_ID,
        "relationshipType": "DEPENDS_ON",
        "relatedSpdxElement": STOCKFISH_SPDX_ID,
    })

    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": DATA_LICENSE,
        "SPDXID": DOCUMENT_SPDX_ID,
        "name": f"Accessible Chess V2 package {sha[:12]}",
        "documentNamespace": f"https://github.com/Oleksii-debug/Accessible-Chess/spdx/{sha}",
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
                "comment": "Project license is not inferred; every packaged regular file is enumerated and hashed.",
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
                "comment": (
                    f"Binary: {STOCKFISH_EXECUTABLE}; corresponding source: {STOCKFISH_SOURCE}; "
                    f"notice: {STOCKFISH_NOTICE}; exact license text: {STOCKFISH_LICENSE}."
                ),
            },
        ],
        "files": file_rows,
        "relationships": relationships,
    }


def write_version2_release_sbom(
    root: str | Path,
    output: str | Path,
    *,
    integration_sha: str,
    inventory: Iterable[str] | None = None,
) -> Path:
    package_root = Path(root)
    target = Path(output)
    try:
        package_resolved = package_root.resolve(strict=True)
        target_parent = target.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        _fail(f"SBOM paths cannot be resolved: {type(exc).__name__}")
    try:
        target_parent.relative_to(package_resolved)
    except ValueError:
        pass
    else:
        _fail("SBOM sidecar output must be outside the package tree")
    if target.exists():
        _fail("SBOM output must not already exist")
    document = build_version2_release_sbom(
        package_root,
        integration_sha=integration_sha,
        inventory=inventory,
    )
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
    sbom_path: str | Path,
    *,
    integration_sha: str,
    inventory: Iterable[str],
) -> dict[str, object]:
    expected = build_version2_release_sbom(
        root,
        integration_sha=integration_sha,
        inventory=inventory,
    )
    actual = _json_object(Path(sbom_path), label="release SBOM")
    if actual != expected:
        _fail("release SBOM does not exactly describe the packaged payload")
    files = actual.get("files")
    if not isinstance(files, list):
        _fail("release SBOM files contract is invalid")
    for row in files:
        if not isinstance(row, dict):
            _fail("release SBOM file entry is invalid")
        checksums = row.get("checksums")
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

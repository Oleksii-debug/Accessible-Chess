from __future__ import annotations

"""Deterministic SPDX 2.3 JSON projection of the runtime dependency notice manifest.

The notice manifest remains the single dependency/version/license authority.  This
module only projects those already-verified facts into SPDX; it never discovers
packages independently and never guesses license identifiers from free text.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote


_SPDX_VERSION = "SPDX-2.3"
_DATA_LICENSE = "CC0-1.0"
_NOTICE_SCHEMA_VERSION = 2
_SAFE_LICENSE_EXPRESSION = re.compile(r"^[A-Za-z0-9.+()\-: ]+$")


class RuntimeDependencySbomError(RuntimeError):
    """Raised when the verified notice manifest cannot be projected safely."""


def _text(value: object, *, label: str, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise RuntimeDependencySbomError(f"{label} must be text")
    text = value.strip()
    if not text or len(text) > max_length or any(ord(ch) < 32 for ch in text):
        raise RuntimeDependencySbomError(f"{label} is invalid")
    return text


def _created(value: str) -> str:
    text = _text(value, label="SPDX creation time", max_length=64)
    if not text.endswith("Z"):
        raise RuntimeDependencySbomError("SPDX creation time must be UTC with Z suffix")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise RuntimeDependencySbomError("SPDX creation time is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise RuntimeDependencySbomError("SPDX creation time must be UTC")
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _spdx_id(prefix: str, value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9.-]+", "-", value).strip("-.")
    if not token:
        raise RuntimeDependencySbomError("cannot form SPDX identifier")
    return f"SPDXRef-{prefix}-{token}"


def _declared_license(row: dict[str, Any]) -> str:
    expression = row.get("license_expression")
    if expression is None or expression == "":
        return "NOASSERTION"
    text = _text(expression, label="license expression", max_length=256)
    if not _SAFE_LICENSE_EXPRESSION.fullmatch(text):
        raise RuntimeDependencySbomError("license expression contains unsupported characters")
    return text


def _load_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RuntimeDependencySbomError("runtime dependency notice manifest is unavailable") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeDependencySbomError("runtime dependency notice manifest is invalid JSON") from exc
    if not isinstance(data, dict) or data.get("schema_version") != _NOTICE_SCHEMA_VERSION:
        raise RuntimeDependencySbomError("runtime dependency notice manifest schema is unsupported")
    if not isinstance(data.get("python"), dict) or not isinstance(data.get("distributions"), list):
        raise RuntimeDependencySbomError("runtime dependency notice manifest shape is invalid")
    return data, raw


def build_runtime_dependency_spdx23(
    notice_manifest_path: str | Path,
    output_path: str | Path,
    *,
    document_name: str,
    created_utc: str,
) -> Path:
    """Project one verified notice manifest into deterministic SPDX 2.3 JSON."""

    source = Path(notice_manifest_path)
    target = Path(output_path)
    if target.exists():
        raise RuntimeDependencySbomError("SBOM output already exists")
    manifest, raw = _load_manifest(source)
    manifest_sha = hashlib.sha256(raw).hexdigest()
    name = _text(document_name, label="SPDX document name", max_length=256)
    created = _created(created_utc)

    python_row = manifest["python"]
    python_version = _text(python_row.get("version"), label="Python version", max_length=128)
    python_id = _spdx_id("Package", f"Python-{python_version}")
    packages: list[dict[str, Any]] = [
        {
            "SPDXID": python_id,
            "name": "Python",
            "versionInfo": python_version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        }
    ]
    relationships: list[dict[str, str]] = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": python_id,
        }
    ]

    seen: set[str] = set()
    distributions = manifest["distributions"]
    for row in sorted(distributions, key=lambda item: str(item.get("distribution", "")).casefold()):
        if not isinstance(row, dict):
            raise RuntimeDependencySbomError("distribution row is invalid")
        distribution = _text(row.get("distribution"), label="distribution name", max_length=256)
        version = _text(row.get("version"), label="distribution version", max_length=128)
        folded = distribution.casefold()
        if folded in seen:
            raise RuntimeDependencySbomError("runtime dependency manifest contains duplicate distributions")
        seen.add(folded)
        notices = row.get("notice_files")
        if not isinstance(notices, list) or not notices:
            raise RuntimeDependencySbomError(f"distribution has no verified notice evidence: {distribution}")
        for notice in notices:
            if not isinstance(notice, dict):
                raise RuntimeDependencySbomError("notice evidence row is invalid")
            digest = _text(notice.get("sha256"), label="notice SHA-256", max_length=64)
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise RuntimeDependencySbomError("notice SHA-256 is invalid")

        package_id = _spdx_id("Package", f"{distribution}-{version}")
        purl = f"pkg:pypi/{quote(distribution, safe='._-').lower()}@{quote(version, safe='._+-')}"
        packages.append(
            {
                "SPDXID": package_id,
                "name": distribution,
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": _declared_license(row),
                "copyrightText": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": purl,
                    }
                ],
            }
        )
        relationships.append(
            {
                "spdxElementId": python_id,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": package_id,
            }
        )

    namespace = f"https://accessible-chess.invalid/spdx/{manifest_sha}"
    document = {
        "spdxVersion": _SPDX_VERSION,
        "dataLicense": _DATA_LICENSE,
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": name,
        "documentNamespace": namespace,
        "creationInfo": {
            "created": created,
            "creators": ["Tool: Accessible-Chess runtime_dependency_sbom"],
        },
        "documentDescribes": [python_id],
        "packages": packages,
        "relationships": relationships,
        "annotations": [
            {
                "annotationType": "OTHER",
                "annotator": "Tool: Accessible-Chess runtime_dependency_sbom",
                "annotationDate": created,
                "comment": f"Source notice manifest SHA-256: {manifest_sha}",
            }
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


__all__ = ["RuntimeDependencySbomError", "build_runtime_dependency_spdx23"]
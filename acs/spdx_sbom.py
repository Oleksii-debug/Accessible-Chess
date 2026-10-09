from __future__ import annotations

"""Deterministic SPDX 2.3 release SBOM construction for Accessible Chess.

The module is intentionally release-tooling focused. It does not discover packages,
inspect the host environment, contact package registries, or infer licenses. Callers
must provide already-qualified component facts for the exact release input tree.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


SPDX_VERSION = "SPDX-2.3"
DATA_LICENSE = "CC0-1.0"
DOCUMENT_SPDX_ID = "SPDXRef-DOCUMENT"
PRODUCT_SPDX_ID = "SPDXRef-Package-AccessibleChess"
_TOOL_CREATOR = "Tool: Accessible Chess deterministic SPDX generator"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9.-]+")
_PURL_RE = re.compile(r"^pkg:[A-Za-z0-9.+-]+/[^\s]+$")


class SbomError(ValueError):
    """Raised when SBOM input or a generated document is unsafe or ambiguous."""


@dataclass(frozen=True, slots=True)
class ComponentRecord:
    name: str
    version: str
    artifact_sha256: str
    license_declared: str
    supplier: str = "NOASSERTION"
    download_location: str = "NOASSERTION"
    purl: str | None = None
    copyright_text: str = "NOASSERTION"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "component name", 240))
        object.__setattr__(self, "version", _text(self.version, "component version", 160))
        object.__setattr__(
            self,
            "artifact_sha256",
            _sha256(self.artifact_sha256, "component artifact sha256"),
        )
        object.__setattr__(
            self,
            "license_declared",
            _license_text(self.license_declared, "component declared license"),
        )
        object.__setattr__(self, "supplier", _supplier(self.supplier))
        object.__setattr__(
            self,
            "download_location",
            _download_location(self.download_location),
        )
        if self.purl is not None:
            object.__setattr__(self, "purl", _purl(self.purl))
        object.__setattr__(
            self,
            "copyright_text",
            _text_or_assertion(self.copyright_text, "component copyright text", 2000),
        )

    @property
    def identity(self) -> tuple[str, str]:
        return (self.name.casefold(), self.version.casefold())


def build_spdx_document(
    *,
    product_version: str,
    source_sha: str,
    product_sha256: str,
    components: Iterable[ComponentRecord],
    created_at: datetime,
    product_name: str = "Accessible Chess",
    product_supplier: str = "NOASSERTION",
    product_license_declared: str = "NOASSERTION",
    product_download_location: str = "NOASSERTION",
) -> dict[str, Any]:
    """Build one canonical SPDX 2.3 JSON document from qualified release facts.

    Component order supplied by the caller is deliberately ignored. Canonical
    ordering means the same qualified input and timestamp produce byte-identical
    JSON through :func:`canonical_spdx_json`.
    """

    product_name = _text(product_name, "product name", 240)
    product_version = _text(product_version, "product version", 160)
    source_sha = _sha40(source_sha, "source sha")
    product_sha256 = _sha256(product_sha256, "product sha256")
    product_supplier = _supplier(product_supplier)
    product_license_declared = _license_text(
        product_license_declared,
        "product declared license",
    )
    product_download_location = _download_location(product_download_location)
    created = _created_timestamp(created_at)

    normalized = _normalize_components(components)
    component_packages = [_component_package(item) for item in normalized]

    namespace_seed = {
        "created": created,
        "product": {
            "name": product_name,
            "version": product_version,
            "source_sha": source_sha,
            "sha256": product_sha256,
        },
        "components": [
            {
                "name": item.name,
                "version": item.version,
                "sha256": item.artifact_sha256,
                "license": item.license_declared,
                "supplier": item.supplier,
                "download": item.download_location,
                "purl": item.purl,
            }
            for item in normalized
        ],
    }
    seed_bytes = json.dumps(
        namespace_seed,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    namespace_digest = hashlib.sha256(seed_bytes).hexdigest()

    product_package: dict[str, Any] = {
        "SPDXID": PRODUCT_SPDX_ID,
        "name": product_name,
        "versionInfo": product_version,
        "downloadLocation": product_download_location,
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": product_license_declared,
        "copyrightText": "NOASSERTION",
        "supplier": product_supplier,
        "checksums": [{"algorithm": "SHA256", "checksumValue": product_sha256}],
        "externalRefs": [
            {
                "referenceCategory": "OTHER",
                "referenceType": "accessible-chess-source-commit",
                "referenceLocator": source_sha,
            }
        ],
        "primaryPackagePurpose": "APPLICATION",
    }

    relationships = [
        {
            "spdxElementId": DOCUMENT_SPDX_ID,
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": PRODUCT_SPDX_ID,
        }
    ]
    relationships.extend(
        {
            "spdxElementId": PRODUCT_SPDX_ID,
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": package["SPDXID"],
        }
        for package in component_packages
    )

    document: dict[str, Any] = {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": DATA_LICENSE,
        "SPDXID": DOCUMENT_SPDX_ID,
        "name": f"{product_name}-{product_version}-release-sbom",
        "documentNamespace": (
            "https://spdx.org/spdxdocs/Accessible-Chess-" + namespace_digest
        ),
        "creationInfo": {
            "created": created,
            "creators": [_TOOL_CREATOR],
        },
        "documentDescribes": [PRODUCT_SPDX_ID],
        "packages": [product_package, *component_packages],
        "relationships": relationships,
    }
    validate_spdx_document(document)
    return document


def canonical_spdx_json(document: Mapping[str, Any]) -> str:
    validate_spdx_document(document)
    return json.dumps(
        document,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n"


def spdx_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_spdx_json(document).encode("utf-8")).hexdigest()


def validate_spdx_document(document: Mapping[str, Any]) -> None:
    if type(document) is not dict:
        raise SbomError("SPDX document must be a plain mapping")
    required = {
        "spdxVersion",
        "dataLicense",
        "SPDXID",
        "name",
        "documentNamespace",
        "creationInfo",
        "documentDescribes",
        "packages",
        "relationships",
    }
    unknown = set(document) - required
    missing = required - set(document)
    if missing or unknown:
        raise SbomError(
            f"SPDX document keys invalid: missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    if document["spdxVersion"] != SPDX_VERSION:
        raise SbomError("unsupported SPDX version")
    if document["dataLicense"] != DATA_LICENSE:
        raise SbomError("SPDX data license must be CC0-1.0")
    if document["SPDXID"] != DOCUMENT_SPDX_ID:
        raise SbomError("invalid SPDX document identifier")
    _text(document["name"], "SPDX document name", 400)
    namespace = _text(document["documentNamespace"], "SPDX document namespace", 600)
    prefix = "https://spdx.org/spdxdocs/Accessible-Chess-"
    if not namespace.startswith(prefix) or not _SHA256_RE.fullmatch(namespace[len(prefix) :]):
        raise SbomError("invalid deterministic SPDX document namespace")

    creation = document["creationInfo"]
    if type(creation) is not dict or set(creation) != {"created", "creators"}:
        raise SbomError("invalid SPDX creationInfo")
    _validate_created_text(creation["created"])
    if creation["creators"] != [_TOOL_CREATOR]:
        raise SbomError("unexpected SPDX creator")

    described = document["documentDescribes"]
    if described != [PRODUCT_SPDX_ID]:
        raise SbomError("document must describe exactly the Accessible Chess package")

    packages = document["packages"]
    if type(packages) is not list or not packages:
        raise SbomError("SPDX document must contain packages")
    ids: list[str] = []
    for package in packages:
        _validate_package(package)
        ids.append(package["SPDXID"])
    if ids[0] != PRODUCT_SPDX_ID:
        raise SbomError("product package must be first")
    if len(set(ids)) != len(ids):
        raise SbomError("duplicate SPDX package identifier")

    relationships = document["relationships"]
    if type(relationships) is not list:
        raise SbomError("SPDX relationships must be a list")
    expected = [
        {
            "spdxElementId": DOCUMENT_SPDX_ID,
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": PRODUCT_SPDX_ID,
        },
        *[
            {
                "spdxElementId": PRODUCT_SPDX_ID,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": package_id,
            }
            for package_id in ids[1:]
        ],
    ]
    if relationships != expected:
        raise SbomError("SPDX relationship graph does not match package inventory")


def _normalize_components(components: Iterable[ComponentRecord]) -> tuple[ComponentRecord, ...]:
    try:
        values = tuple(components)
    except TypeError as exc:
        raise SbomError("components must be iterable") from exc
    if any(type(item) is not ComponentRecord for item in values):
        raise SbomError("components must contain only ComponentRecord values")
    ordered = tuple(
        sorted(
            values,
            key=lambda item: (
                item.name.casefold(),
                item.version.casefold(),
                item.artifact_sha256,
            ),
        )
    )
    identities: set[tuple[str, str]] = set()
    purls: set[str] = set()
    spdx_ids: set[str] = set()
    for item in ordered:
        if item.identity in identities:
            raise SbomError(f"duplicate component identity: {item.name} {item.version}")
        identities.add(item.identity)
        if item.purl is not None:
            key = item.purl.casefold()
            if key in purls:
                raise SbomError(f"duplicate component purl: {item.purl}")
            purls.add(key)
        package_id = _component_spdx_id(item)
        if package_id in spdx_ids:
            raise SbomError("component SPDX identifier collision")
        spdx_ids.add(package_id)
    return ordered


def _component_spdx_id(item: ComponentRecord) -> str:
    slug = _SAFE_ID_RE.sub("-", item.name).strip("-.") or "Component"
    slug = slug[:72]
    digest = hashlib.sha256(
        f"{item.name}\0{item.version}\0{item.artifact_sha256}".encode("utf-8")
    ).hexdigest()[:16]
    return f"SPDXRef-Package-{slug}-{digest}"


def _component_package(item: ComponentRecord) -> dict[str, Any]:
    package: dict[str, Any] = {
        "SPDXID": _component_spdx_id(item),
        "name": item.name,
        "versionInfo": item.version,
        "downloadLocation": item.download_location,
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": item.license_declared,
        "copyrightText": item.copyright_text,
        "supplier": item.supplier,
        "checksums": [
            {"algorithm": "SHA256", "checksumValue": item.artifact_sha256}
        ],
        "primaryPackagePurpose": "LIBRARY",
    }
    if item.purl is not None:
        package["externalRefs"] = [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": item.purl,
            }
        ]
    return package


def _validate_package(package: Any) -> None:
    if type(package) is not dict:
        raise SbomError("SPDX package must be a plain mapping")
    required = {
        "SPDXID",
        "name",
        "versionInfo",
        "downloadLocation",
        "filesAnalyzed",
        "licenseConcluded",
        "licenseDeclared",
        "copyrightText",
        "supplier",
        "checksums",
        "primaryPackagePurpose",
    }
    optional = {"externalRefs"}
    if not required.issubset(package) or set(package) - required - optional:
        raise SbomError("invalid SPDX package keys")
    package_id = _text(package["SPDXID"], "package SPDXID", 180)
    if not package_id.startswith("SPDXRef-Package-"):
        raise SbomError("invalid package SPDXID")
    _text(package["name"], "package name", 240)
    _text(package["versionInfo"], "package version", 160)
    _download_location(package["downloadLocation"])
    if package["filesAnalyzed"] is not False:
        raise SbomError("release SBOM packages must use filesAnalyzed=false")
    if package["licenseConcluded"] != "NOASSERTION":
        raise SbomError("licenseConcluded must remain NOASSERTION")
    _license_text(package["licenseDeclared"], "package declared license")
    _text_or_assertion(package["copyrightText"], "package copyright text", 2000)
    _supplier(package["supplier"])
    checksums = package["checksums"]
    if type(checksums) is not list or len(checksums) != 1:
        raise SbomError("package must contain exactly one SHA256 checksum")
    checksum = checksums[0]
    if type(checksum) is not dict or set(checksum) != {"algorithm", "checksumValue"}:
        raise SbomError("invalid SPDX package checksum")
    if checksum["algorithm"] != "SHA256":
        raise SbomError("only SHA256 package checksums are accepted")
    _sha256(checksum["checksumValue"], "package checksum")
    purpose = package["primaryPackagePurpose"]
    if purpose not in {"APPLICATION", "LIBRARY"}:
        raise SbomError("unexpected package purpose")
    refs = package.get("externalRefs", [])
    if type(refs) is not list:
        raise SbomError("package externalRefs must be a list")
    for ref in refs:
        if type(ref) is not dict or set(ref) != {
            "referenceCategory",
            "referenceType",
            "referenceLocator",
        }:
            raise SbomError("invalid SPDX external reference")
        category = ref["referenceCategory"]
        reference_type = ref["referenceType"]
        locator = ref["referenceLocator"]
        if category == "PACKAGE-MANAGER" and reference_type == "purl":
            _purl(locator)
        elif category == "OTHER" and reference_type == "accessible-chess-source-commit":
            _sha40(locator, "source commit external reference")
        else:
            raise SbomError("unsupported SPDX external reference")


def _created_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SbomError("created_at must be a timezone-aware datetime")
    utc = value.astimezone(timezone.utc)
    if utc.microsecond:
        raise SbomError("created_at must have whole-second precision")
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_created_text(value: Any) -> None:
    if type(value) is not str:
        raise SbomError("SPDX creation timestamp must be text")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise SbomError("invalid SPDX creation timestamp") from exc
    if _created_timestamp(parsed) != value:
        raise SbomError("non-canonical SPDX creation timestamp")


def _text(value: Any, label: str, limit: int) -> str:
    if type(value) is not str:
        raise SbomError(f"{label} must be text")
    if not value or len(value) > limit or value != value.strip():
        raise SbomError(f"{label} is empty, padded, or too long")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise SbomError(f"{label} contains control characters")
    return value


def _text_or_assertion(value: Any, label: str, limit: int) -> str:
    return _text(value, label, limit)


def _sha40(value: Any, label: str) -> str:
    if type(value) is not str or not _SHA40_RE.fullmatch(value):
        raise SbomError(f"{label} must be lowercase 40-hex")
    return value


def _sha256(value: Any, label: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise SbomError(f"{label} must be lowercase 64-hex")
    return value


def _license_text(value: Any, label: str) -> str:
    value = _text(value, label, 512)
    if value == "NONE":
        raise SbomError(f"{label} may not claim NONE")
    return value


def _supplier(value: Any) -> str:
    value = _text(value, "supplier", 512)
    if value == "NOASSERTION":
        return value
    if not (value.startswith("Organization: ") or value.startswith("Person: ")):
        raise SbomError("supplier must be NOASSERTION, Organization:, or Person:")
    return value


def _download_location(value: Any) -> str:
    value = _text(value, "download location", 2048)
    if value in {"NOASSERTION", "NONE"}:
        return value
    if not (value.startswith("https://") or value.startswith("http://")):
        raise SbomError("download location must be HTTP(S), NONE, or NOASSERTION")
    return value


def _purl(value: Any) -> str:
    value = _text(value, "package URL", 1024)
    if not _PURL_RE.fullmatch(value):
        raise SbomError("invalid package URL")
    return value


__all__ = [
    "ComponentRecord",
    "SbomError",
    "build_spdx_document",
    "canonical_spdx_json",
    "spdx_sha256",
    "validate_spdx_document",
]

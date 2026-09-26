from __future__ import annotations

"""Deterministic, fail-closed SPDX 2.3 SBOM tooling for release artifacts."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterable, Mapping

SPDX_VERSION = "SPDX-2.3"
DATA_LICENSE = "CC0-1.0"
DOCUMENT_ID = "SPDXRef-DOCUMENT"
PRODUCT_ID = "SPDXRef-Package-AccessibleChess"
CREATOR = "Tool: Accessible Chess deterministic SPDX generator"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PURL = re.compile(r"^pkg:[A-Za-z0-9.+-]+/[^\s]+$")
_ID_BAD = re.compile(r"[^A-Za-z0-9.-]+")


class SbomError(ValueError):
    pass


class _DuplicateKey(ValueError):
    pass


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
            _sha256(self.artifact_sha256, "component sha256"),
        )
        object.__setattr__(self, "license_declared", _license(self.license_declared))
        object.__setattr__(self, "supplier", _supplier(self.supplier))
        object.__setattr__(
            self,
            "download_location",
            _download(self.download_location),
        )
        if self.purl is not None:
            object.__setattr__(self, "purl", _purl(self.purl))
        object.__setattr__(
            self,
            "copyright_text",
            _text(self.copyright_text, "copyright text", 2000),
        )

    @property
    def identity(self) -> tuple[str, str]:
        return self.name.casefold(), self.version.casefold()


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
    product_name = _text(product_name, "product name", 240)
    product_version = _text(product_version, "product version", 160)
    source_sha = _sha40(source_sha, "source sha")
    product_sha256 = _sha256(product_sha256, "product sha256")
    product_supplier = _supplier(product_supplier)
    product_license_declared = _license(product_license_declared)
    product_download_location = _download(product_download_location)
    created = _created(created_at)
    parts = _components(components)

    seed = json.dumps(
        {
            "created": created,
            "product": [
                product_name,
                product_version,
                source_sha,
                product_sha256,
            ],
            "components": [
                [
                    p.name,
                    p.version,
                    p.artifact_sha256,
                    p.license_declared,
                    p.supplier,
                    p.download_location,
                    p.purl,
                ]
                for p in parts
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    namespace = (
        "https://spdx.org/spdxdocs/Accessible-Chess-"
        + hashlib.sha256(seed).hexdigest()
    )

    product = {
        "SPDXID": PRODUCT_ID,
        "name": product_name,
        "versionInfo": product_version,
        "downloadLocation": product_download_location,
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": product_license_declared,
        "copyrightText": "NOASSERTION",
        "supplier": product_supplier,
        "checksums": [
            {"algorithm": "SHA256", "checksumValue": product_sha256}
        ],
        "externalRefs": [
            {
                "referenceCategory": "PERSISTENT-ID",
                "referenceType": "gitoid",
                "referenceLocator": f"gitoid:commit:sha1:{source_sha}",
            }
        ],
        "primaryPackagePurpose": "APPLICATION",
    }
    packages = [product, *[_component_package(p) for p in parts]]
    relationships = [
        {
            "spdxElementId": DOCUMENT_ID,
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": PRODUCT_ID,
        }
    ]
    relationships += [
        {
            "spdxElementId": PRODUCT_ID,
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": package["SPDXID"],
        }
        for package in packages[1:]
    ]
    document = {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": DATA_LICENSE,
        "SPDXID": DOCUMENT_ID,
        "name": f"{product_name}-{product_version}-release-sbom",
        "documentNamespace": namespace,
        "creationInfo": {"created": created, "creators": [CREATOR]},
        "documentDescribes": [PRODUCT_ID],
        "packages": packages,
        "relationships": relationships,
    }
    validate_spdx_document(document)
    return document


def canonical_spdx_json(document: Mapping[str, Any]) -> str:
    validate_spdx_document(document)
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def spdx_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_spdx_json(document).encode("utf-8")
    ).hexdigest()


def load_release_manifest(path: str | Path) -> dict[str, Any]:
    raw = _regular_text(Path(path), "SBOM manifest")
    if len(raw.encode("utf-8")) > 2 * 1024 * 1024:
        raise SbomError("SBOM manifest exceeds 2 MiB limit")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except _DuplicateKey as exc:
        raise SbomError(f"duplicate JSON key: {exc.args[0]}") from exc
    except json.JSONDecodeError as exc:
        raise SbomError(
            f"invalid SBOM manifest JSON: {exc.msg}"
        ) from exc
    if (
        type(value) is not dict
        or set(value)
        != {"schema_version", "created_at", "product", "components"}
    ):
        raise SbomError("invalid SBOM manifest root")
    if (
        value["schema_version"] != 1
        or type(value["product"]) is not dict
        or type(value["components"]) is not list
    ):
        raise SbomError("invalid SBOM manifest schema")
    return value


def build_from_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict:
        raise SbomError("manifest must be a plain mapping")
    product = value.get("product")
    if type(product) is not dict:
        raise SbomError("manifest product must be an object")
    required = {"version", "source_sha", "sha256"}
    optional = {
        "name",
        "supplier",
        "license_declared",
        "download_location",
    }
    if (
        not required.issubset(product)
        or set(product) - required - optional
    ):
        raise SbomError("invalid manifest product keys")
    created_text = value.get("created_at")
    if type(created_text) is not str:
        raise SbomError("manifest created_at must be text")
    try:
        created = datetime.strptime(
            created_text,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SbomError(
            "manifest created_at must be canonical UTC whole-second text"
        ) from exc

    records: list[ComponentRecord] = []
    required_component = {
        "name",
        "version",
        "artifact_sha256",
        "license_declared",
    }
    optional_component = {
        "supplier",
        "download_location",
        "purl",
        "copyright_text",
    }
    items = value.get("components")
    if type(items) is not list:
        raise SbomError("manifest components must be an array")
    for index, item in enumerate(items):
        if (
            type(item) is not dict
            or not required_component.issubset(item)
            or set(item) - required_component - optional_component
        ):
            raise SbomError(f"invalid component {index}")
        try:
            records.append(
                ComponentRecord(
                    name=item["name"],
                    version=item["version"],
                    artifact_sha256=item["artifact_sha256"],
                    license_declared=item["license_declared"],
                    supplier=item.get("supplier", "NOASSERTION"),
                    download_location=item.get(
                        "download_location",
                        "NOASSERTION",
                    ),
                    purl=item.get("purl"),
                    copyright_text=item.get(
                        "copyright_text",
                        "NOASSERTION",
                    ),
                )
            )
        except SbomError as exc:
            raise SbomError(f"component {index}: {exc}") from exc
    return build_spdx_document(
        product_name=product.get("name", "Accessible Chess"),
        product_version=product["version"],
        source_sha=product["source_sha"],
        product_sha256=product["sha256"],
        product_supplier=product.get("supplier", "NOASSERTION"),
        product_license_declared=product.get(
            "license_declared",
            "NOASSERTION",
        ),
        product_download_location=product.get(
            "download_location",
            "NOASSERTION",
        ),
        components=records,
        created_at=created,
    )


def generate_spdx_file(
    input_path: str | Path,
    output_path: str | Path,
) -> str:
    encoded = canonical_spdx_json(
        build_from_manifest(load_release_manifest(input_path))
    )
    _atomic_text(Path(output_path), encoded)
    return encoded


def validate_spdx_document(document: Mapping[str, Any]) -> None:
    if type(document) is not dict:
        raise SbomError("SPDX document must be a plain mapping")
    keys = {
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
    if set(document) != keys:
        raise SbomError("invalid SPDX document keys")
    if (
        document["spdxVersion"] != SPDX_VERSION
        or document["dataLicense"] != DATA_LICENSE
        or document["SPDXID"] != DOCUMENT_ID
    ):
        raise SbomError("invalid SPDX document header")
    _text(document["name"], "document name", 400)
    namespace = _text(
        document["documentNamespace"],
        "document namespace",
        600,
    )
    prefix = "https://spdx.org/spdxdocs/Accessible-Chess-"
    if (
        not namespace.startswith(prefix)
        or not _SHA256.fullmatch(namespace[len(prefix) :])
    ):
        raise SbomError("invalid document namespace")
    creation = document["creationInfo"]
    if (
        type(creation) is not dict
        or creation.get("creators") != [CREATOR]
        or set(creation) != {"created", "creators"}
    ):
        raise SbomError("invalid creationInfo")
    _parse_created_text(creation["created"])
    if document["documentDescribes"] != [PRODUCT_ID]:
        raise SbomError("document must describe Accessible Chess")
    packages = document["packages"]
    if type(packages) is not list or not packages:
        raise SbomError("missing SPDX packages")
    ids = []
    for package in packages:
        _validate_package(package)
        ids.append(package["SPDXID"])
    if ids[0] != PRODUCT_ID or len(ids) != len(set(ids)):
        raise SbomError("invalid SPDX package identifiers")
    expected = [
        {
            "spdxElementId": DOCUMENT_ID,
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": PRODUCT_ID,
        }
    ]
    expected += [
        {
            "spdxElementId": PRODUCT_ID,
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": item,
        }
        for item in ids[1:]
    ]
    if document["relationships"] != expected:
        raise SbomError(
            "SPDX relationship graph does not match package inventory"
        )


def _components(
    values: Iterable[ComponentRecord],
) -> tuple[ComponentRecord, ...]:
    try:
        items = tuple(values)
    except TypeError as exc:
        raise SbomError("components must be iterable") from exc
    if any(type(item) is not ComponentRecord for item in items):
        raise SbomError(
            "components must contain ComponentRecord values"
        )
    items = tuple(
        sorted(
            items,
            key=lambda p: (
                p.name.casefold(),
                p.version.casefold(),
                p.artifact_sha256,
            ),
        )
    )
    seen_id: set[tuple[str, str]] = set()
    seen_purl: set[str] = set()
    seen_spdx: set[str] = set()
    for item in items:
        if item.identity in seen_id:
            raise SbomError(
                f"duplicate component identity: {item.name} {item.version}"
            )
        seen_id.add(item.identity)
        if item.purl:
            key = item.purl.casefold()
            if key in seen_purl:
                raise SbomError(
                    f"duplicate component purl: {item.purl}"
                )
            seen_purl.add(key)
        spdx_id = _component_id(item)
        if spdx_id in seen_spdx:
            raise SbomError("component SPDX identifier collision")
        seen_spdx.add(spdx_id)
    return items


def _component_id(item: ComponentRecord) -> str:
    slug = (
        _ID_BAD.sub("-", item.name).strip("-.") or "Component"
    )[:72]
    digest = hashlib.sha256(
        f"{item.name}\0{item.version}\0{item.artifact_sha256}".encode()
    ).hexdigest()[:16]
    return f"SPDXRef-Package-{slug}-{digest}"


def _component_package(
    item: ComponentRecord,
) -> dict[str, Any]:
    package = {
        "SPDXID": _component_id(item),
        "name": item.name,
        "versionInfo": item.version,
        "downloadLocation": item.download_location,
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": item.license_declared,
        "copyrightText": item.copyright_text,
        "supplier": item.supplier,
        "checksums": [
            {
                "algorithm": "SHA256",
                "checksumValue": item.artifact_sha256,
            }
        ],
        "primaryPackagePurpose": "LIBRARY",
    }
    if item.purl:
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
        raise SbomError("SPDX package must be an object")
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
    if (
        not required.issubset(package)
        or set(package) - required - {"externalRefs"}
    ):
        raise SbomError("invalid SPDX package keys")
    if not _text(
        package["SPDXID"],
        "package SPDXID",
        180,
    ).startswith("SPDXRef-Package-"):
        raise SbomError("invalid package SPDXID")
    _text(package["name"], "package name", 240)
    _text(package["versionInfo"], "package version", 160)
    _download(package["downloadLocation"])
    if (
        package["filesAnalyzed"] is not False
        or package["licenseConcluded"] != "NOASSERTION"
    ):
        raise SbomError("invalid package analysis/license state")
    _license(package["licenseDeclared"])
    _text(package["copyrightText"], "copyright text", 2000)
    _supplier(package["supplier"])
    checksums = package["checksums"]
    if (
        type(checksums) is not list
        or len(checksums) != 1
        or checksums[0].get("algorithm") != "SHA256"
        or set(checksums[0])
        != {"algorithm", "checksumValue"}
    ):
        raise SbomError("invalid package checksum")
    _sha256(checksums[0]["checksumValue"], "package checksum")
    if package["primaryPackagePurpose"] not in {
        "APPLICATION",
        "LIBRARY",
    }:
        raise SbomError("invalid package purpose")
    for ref in package.get("externalRefs", []):
        if (
            type(ref) is not dict
            or set(ref)
            != {
                "referenceCategory",
                "referenceType",
                "referenceLocator",
            }
        ):
            raise SbomError("invalid external reference")
        category = ref["referenceCategory"]
        kind = ref["referenceType"]
        locator = ref["referenceLocator"]
        if category == "PACKAGE-MANAGER" and kind == "purl":
            _purl(locator)
        elif (
            category == "PERSISTENT-ID"
            and kind == "gitoid"
        ):
            prefix = "gitoid:commit:sha1:"
            if (
                type(locator) is not str
                or not locator.startswith(prefix)
            ):
                raise SbomError("invalid source gitoid")
            _sha40(
                locator[len(prefix) :],
                "source gitoid",
            )
        else:
            raise SbomError("unsupported external reference")


def _unique_object(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    out = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateKey(key)
        out[key] = value
    return out


def _regular_text(path: Path, label: str) -> str:
    try:
        meta = path.lstat()
    except OSError as exc:
        raise SbomError(
            f"cannot inspect {label}: {exc}"
        ) from exc
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(
        meta.st_mode
    ):
        raise SbomError(
            f"{label} must be a regular non-symlink file"
        )
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SbomError(
            f"cannot read {label} as UTF-8: {exc}"
        ) from exc


def _atomic_text(path: Path, content: str) -> None:
    parent = path.parent
    try:
        meta = parent.lstat()
    except OSError as exc:
        raise SbomError(
            f"cannot inspect output directory: {exc}"
        ) from exc
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISDIR(
        meta.st_mode
    ):
        raise SbomError(
            "output parent must be a real directory"
        )
    if path.exists() or path.is_symlink():
        current = path.lstat()
        if stat.S_ISLNK(
            current.st_mode
        ) or not stat.S_ISREG(current.st_mode):
            raise SbomError(
                "existing output must be a regular non-symlink file"
            )
    temp = parent / f".{path.name}.tmp-{os.getpid()}"
    try:
        fd = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(content.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if fd != -1:
                os.close(fd)
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
    except OSError as exc:
        raise SbomError(
            f"cannot publish SBOM atomically: {exc}"
        ) from exc


def _created(value: datetime) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
    ):
        raise SbomError(
            "created_at must be timezone-aware"
        )
    value = value.astimezone(timezone.utc)
    if value.microsecond:
        raise SbomError(
            "created_at must have whole-second precision"
        )
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_created_text(value: Any) -> datetime:
    if type(value) is not str:
        raise SbomError(
            "creation timestamp must be text"
        )
    try:
        return datetime.strptime(
            value,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SbomError(
            "invalid creation timestamp"
        ) from exc


def _text(value: Any, label: str, limit: int) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
    ):
        raise SbomError(f"invalid {label}")
    if any(
        ord(ch) < 0x20 or ord(ch) == 0x7F
        for ch in value
    ):
        raise SbomError(f"invalid {label}")
    return value


def _sha40(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not _SHA40.fullmatch(value)
    ):
        raise SbomError(
            f"{label} must be lowercase 40-hex"
        )
    return value


def _sha256(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not _SHA256.fullmatch(value)
    ):
        raise SbomError(
            f"{label} must be lowercase 64-hex"
        )
    return value


def _license(value: Any) -> str:
    value = _text(value, "declared license", 512)
    if value == "NONE":
        raise SbomError(
            "declared license may not claim NONE"
        )
    return value


def _supplier(value: Any) -> str:
    value = _text(value, "supplier", 512)
    if (
        value != "NOASSERTION"
        and not value.startswith("Organization: ")
        and not value.startswith("Person: ")
    ):
        raise SbomError("invalid supplier")
    return value


def _download(value: Any) -> str:
    value = _text(value, "download location", 2048)
    if (
        value not in {"NONE", "NOASSERTION"}
        and not value.startswith("https://")
        and not value.startswith("http://")
    ):
        raise SbomError("invalid download location")
    return value


def _purl(value: Any) -> str:
    value = _text(value, "purl", 1024)
    if not _PURL.fullmatch(value):
        raise SbomError("invalid purl")
    return value


__all__ = [
    "ComponentRecord",
    "SbomError",
    "build_from_manifest",
    "build_spdx_document",
    "canonical_spdx_json",
    "generate_spdx_file",
    "load_release_manifest",
    "spdx_sha256",
    "validate_spdx_document",
]

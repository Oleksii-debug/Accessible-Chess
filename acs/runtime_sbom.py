from __future__ import annotations

"""Deterministic CycloneDX SBOM derived from qualified runtime notice evidence.

This module deliberately does not scan the Python environment. The qualified
runtime dependency notice manifest is the single dependency inventory authority.
The SBOM builder revalidates that manifest and the exact packaged notice bytes,
then projects the verified inventory into a deterministic CycloneDX document.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
from urllib.parse import quote, urlparse
import uuid


_NOTICE_SCHEMA_VERSION = 2
_NOTICE_SCOPE = "qualified Python build/runtime dependency notice evidence"
_SBOM_SPEC_VERSION = "1.6"
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_NOTICE_BYTES = 2 * 1024 * 1024
_SAFE_DISTRIBUTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}$")
_SAFE_PRODUCT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+()-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class RuntimeSbomError(RuntimeError):
    """Raised when exact runtime SBOM evidence cannot be built fail-closed."""


@dataclass(frozen=True, slots=True)
class RuntimeSbomResult:
    path: Path
    sha256: str
    notice_manifest_sha256: str
    component_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeSbomError("runtime dependency manifest contains duplicate JSON keys")
        result[key] = value
    return result


def _read_manifest(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink():
        raise RuntimeSbomError("runtime dependency manifest must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeSbomError("runtime dependency manifest is unavailable") from exc
    try:
        stat = resolved.stat()
        if (
            not resolved.is_file()
            or resolved.is_symlink()
            or stat.st_size <= 0
            or stat.st_size > _MAX_MANIFEST_BYTES
        ):
            raise RuntimeSbomError("runtime dependency manifest is invalid")
        raw = resolved.read_bytes()
    except RuntimeSbomError:
        raise
    except OSError as exc:
        raise RuntimeSbomError("runtime dependency manifest cannot be read") from exc
    try:
        text = raw.decode("utf-8")
        payload = json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except RuntimeSbomError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeSbomError("runtime dependency manifest is not canonical UTF-8 JSON") from exc
    if type(payload) is not dict:
        raise RuntimeSbomError("runtime dependency manifest root must be an object")
    return payload, hashlib.sha256(raw).hexdigest()


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise RuntimeSbomError(f"{label} fields are invalid")


def _clean_distribution(value: Any) -> str:
    if type(value) is not str:
        raise RuntimeSbomError("distribution name must be text")
    token = value.strip()
    if not _SAFE_DISTRIBUTION.fullmatch(token):
        raise RuntimeSbomError("distribution name is unsafe")
    return token


def _clean_version(value: Any, *, label: str = "version") -> str:
    if type(value) is not str:
        raise RuntimeSbomError(f"{label} must be text")
    token = value.strip()
    if not _SAFE_VERSION.fullmatch(token):
        raise RuntimeSbomError(f"{label} is unsafe")
    return token


def _clean_product_name(value: Any) -> str:
    if type(value) is not str:
        raise RuntimeSbomError("product name must be text")
    token = value.strip()
    if not _SAFE_PRODUCT_NAME.fullmatch(token):
        raise RuntimeSbomError("product name is unsafe")
    return token


def _bounded_text(value: Any, label: str, *, maximum: int = 1024) -> str:
    if type(value) is not str:
        raise RuntimeSbomError(f"{label} must be text")
    token = value.strip()
    if len(token) > maximum or _CONTROL.search(token):
        raise RuntimeSbomError(f"{label} is invalid")
    return token


def _clean_sha256(value: Any, label: str) -> str:
    if type(value) is not str:
        raise RuntimeSbomError(f"{label} must be text")
    token = value.strip().casefold()
    if not _SHA256.fullmatch(token):
        raise RuntimeSbomError(f"{label} is invalid")
    return token


def _safe_flat_filename(value: Any) -> str:
    token = _bounded_text(value, "packaged notice filename", maximum=255)
    path = PurePosixPath(token.replace("\\", "/"))
    if (
        path.is_absolute()
        or len(path.parts) != 1
        or path.name != token
        or token in {"", ".", ".."}
    ):
        raise RuntimeSbomError("packaged notice filename is unsafe")
    return token


def _safe_provenance_path(value: Any) -> str:
    token = _bounded_text(value, "notice provenance path", maximum=1024).replace("\\", "/")
    path = PurePosixPath(token)
    if (
        not token
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != token
    ):
        raise RuntimeSbomError("notice provenance path is unsafe")
    return token


def _https_url(value: Any, label: str) -> str:
    token = _bounded_text(value, label, maximum=2048)
    parsed = urlparse(token)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise RuntimeSbomError(f"{label} is invalid")
    return parsed.geturl()


def _verify_notice_file(root: Path, filename: str, digest: str) -> None:
    candidate = root / filename
    if candidate.is_symlink():
        raise RuntimeSbomError("packaged notice evidence must not be a symlink")
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeSbomError("packaged notice evidence is unavailable") from exc
    try:
        if (
            resolved.parent != resolved_root
            or not resolved.is_file()
            or resolved.is_symlink()
            or resolved.stat().st_size <= 0
            or resolved.stat().st_size > _MAX_NOTICE_BYTES
        ):
            raise RuntimeSbomError("packaged notice evidence is invalid")
    except RuntimeSbomError:
        raise
    except OSError as exc:
        raise RuntimeSbomError("packaged notice evidence cannot be inspected") from exc
    if _sha256(resolved) != digest:
        raise RuntimeSbomError("packaged notice evidence sha256 mismatch")


def _license_name(expression: str, metadata_value: str) -> str:
    if expression:
        return expression
    if metadata_value:
        return metadata_value
    return "SEE-PACKAGED-NOTICE-EVIDENCE"


def _component_ref(name: str, version: str) -> str:
    folded = re.sub(r"[-_.]+", "-", name).strip("-").casefold()
    return f"pkg:pypi/{quote(folded, safe='-._~')}@{quote(version, safe='-._~+!')}"


def _notice_properties(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    properties: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=1):
        prefix = f"accessiblechess:notice:{index:02d}"
        for key in (
            "packaged_file",
            "sha256",
            "source_kind",
            "source_path",
            "source_url",
            "source_artifact_sha256",
        ):
            if key in row:
                properties.append({"name": f"{prefix}:{key}", "value": row[key]})
    return properties


def _parse_notice_rows(root: Path, raw: Any) -> list[dict[str, str]]:
    if type(raw) is not list or not raw:
        raise RuntimeSbomError("distribution notice evidence must be a non-empty list")
    rows: list[dict[str, str]] = []
    seen_files: set[str] = set()
    for item in raw:
        if type(item) is not dict:
            raise RuntimeSbomError("distribution notice evidence item must be an object")
        source_kind = item.get("source_kind")
        if source_kind == "installed_distribution":
            _exact_keys(
                item,
                {"source_kind", "source_path", "packaged_file", "sha256"},
                "installed notice evidence",
            )
        elif source_kind == "verified_source_archive":
            _exact_keys(
                item,
                {
                    "source_kind",
                    "source_path",
                    "source_url",
                    "source_artifact_sha256",
                    "packaged_file",
                    "sha256",
                },
                "external notice evidence",
            )
        else:
            raise RuntimeSbomError("distribution notice source kind is invalid")

        source_path = _safe_provenance_path(item["source_path"])
        packaged_file = _safe_flat_filename(item["packaged_file"])
        digest = _clean_sha256(item["sha256"], "notice sha256")
        folded_file = packaged_file.casefold()
        if folded_file in seen_files:
            raise RuntimeSbomError("distribution notice evidence contains duplicate files")
        seen_files.add(folded_file)

        row = {
            "source_kind": source_kind,
            "source_path": source_path,
            "packaged_file": packaged_file,
            "sha256": digest,
        }
        if source_kind == "verified_source_archive":
            row["source_url"] = _https_url(item["source_url"], "notice source URL")
            row["source_artifact_sha256"] = _clean_sha256(
                item["source_artifact_sha256"],
                "notice source artifact sha256",
            )
        _verify_notice_file(root, packaged_file, digest)
        rows.append(row)
    return rows


def _parse_manifest(
    payload: dict[str, Any],
    root: Path,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    _exact_keys(payload, {"schema_version", "scope", "python", "distributions"}, "manifest")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != _NOTICE_SCHEMA_VERSION:
        raise RuntimeSbomError("runtime dependency manifest schema version is unsupported")
    if payload["scope"] != _NOTICE_SCOPE:
        raise RuntimeSbomError("runtime dependency manifest scope is invalid")

    python = payload["python"]
    if type(python) is not dict:
        raise RuntimeSbomError("Python runtime evidence must be an object")
    _exact_keys(python, {"version", "packaged_file", "sha256"}, "Python runtime evidence")
    python_row = {
        "version": _clean_version(python["version"], label="Python version"),
        "packaged_file": _safe_flat_filename(python["packaged_file"]),
        "sha256": _clean_sha256(python["sha256"], "Python notice sha256"),
    }
    _verify_notice_file(root, python_row["packaged_file"], python_row["sha256"])

    raw_distributions = payload["distributions"]
    if type(raw_distributions) is not list or not raw_distributions:
        raise RuntimeSbomError("runtime dependency distribution inventory must be non-empty")

    distributions: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for item in raw_distributions:
        if type(item) is not dict:
            raise RuntimeSbomError("runtime dependency distribution item must be an object")
        _exact_keys(
            item,
            {
                "distribution",
                "version",
                "license_expression",
                "license_metadata",
                "project_urls",
                "notice_files",
            },
            "runtime dependency distribution",
        )
        name = _clean_distribution(item["distribution"])
        folded = name.casefold()
        if folded in seen_names:
            raise RuntimeSbomError("runtime dependency inventory contains duplicate distributions")
        seen_names.add(folded)
        version = _clean_version(item["version"])
        expression = _bounded_text(item["license_expression"], "license expression", maximum=512)
        license_metadata = _bounded_text(item["license_metadata"], "license metadata", maximum=512)

        raw_urls = item["project_urls"]
        if type(raw_urls) is not list:
            raise RuntimeSbomError("project URLs must be a list")
        urls: list[str] = []
        for value in raw_urls:
            url = _https_url(value, "project URL")
            if url in urls:
                raise RuntimeSbomError("project URLs contain duplicates")
            urls.append(url)

        notices = _parse_notice_rows(root, item["notice_files"])
        distributions.append(
            {
                "distribution": name,
                "version": version,
                "license_expression": expression,
                "license_metadata": license_metadata,
                "project_urls": urls,
                "notice_files": notices,
            }
        )

    distributions.sort(key=lambda row: (row["distribution"].casefold(), row["version"]))
    return python_row, distributions


def _component_from_distribution(row: dict[str, Any]) -> dict[str, Any]:
    name = row["distribution"]
    version = row["version"]
    component: dict[str, Any] = {
        "type": "library",
        "bom-ref": _component_ref(name, version),
        "name": name,
        "version": version,
        "purl": _component_ref(name, version),
        "licenses": [
            {
                "license": {
                    "name": _license_name(
                        row["license_expression"],
                        row["license_metadata"],
                    )
                }
            }
        ],
        "properties": [
            {"name": "accessiblechess:license_expression", "value": row["license_expression"]},
            {"name": "accessiblechess:license_metadata", "value": row["license_metadata"]},
            *_notice_properties(row["notice_files"]),
        ],
    }
    if row["project_urls"]:
        component["externalReferences"] = [
            {"type": "website", "url": url}
            for url in row["project_urls"]
        ]
    return component


def build_runtime_cyclonedx_sbom(
    notice_manifest_path: str | Path,
    output_path: str | Path,
    *,
    product_version: str,
    product_name: str = "Accessible Chess",
) -> RuntimeSbomResult:
    """Build deterministic CycloneDX JSON from exact qualified notice evidence."""

    manifest_path = Path(notice_manifest_path)
    payload, manifest_sha256 = _read_manifest(manifest_path)
    root = manifest_path.resolve(strict=True).parent
    python_row, distributions = _parse_manifest(payload, root)

    clean_product_name = _clean_product_name(product_name)
    clean_product_version = _clean_version(product_version, label="product version")
    product_ref = (
        "urn:accessiblechess:product:"
        + quote(clean_product_name.casefold().replace(" ", "-"), safe="-._~")
        + ":"
        + quote(clean_product_version, safe="-._~+!")
    )
    python_ref = (
        "pkg:generic/python@"
        + quote(python_row["version"], safe="-._~+!")
    )

    components: list[dict[str, Any]] = [
        {
            "type": "framework",
            "bom-ref": python_ref,
            "name": "Python",
            "version": python_row["version"],
            "licenses": [{"license": {"name": "Python Software Foundation License"}}],
            "properties": [
                {
                    "name": "accessiblechess:notice:01:packaged_file",
                    "value": python_row["packaged_file"],
                },
                {
                    "name": "accessiblechess:notice:01:sha256",
                    "value": python_row["sha256"],
                },
            ],
        },
        *[_component_from_distribution(row) for row in distributions],
    ]
    component_refs = [component["bom-ref"] for component in components]
    if len(component_refs) != len(set(component_refs)):
        raise RuntimeSbomError("runtime SBOM component identities collide")

    serial_seed = f"{clean_product_name}\n{clean_product_version}\n{manifest_sha256}"
    serial = uuid.uuid5(uuid.NAMESPACE_URL, serial_seed)

    document = {
        "bomFormat": "CycloneDX",
        "specVersion": _SBOM_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": product_ref,
                "name": clean_product_name,
                "version": clean_product_version,
            },
            "properties": [
                {
                    "name": "accessiblechess:source_notice_manifest",
                    "value": manifest_path.name,
                },
                {
                    "name": "accessiblechess:source_notice_manifest_sha256",
                    "value": manifest_sha256,
                },
            ],
        },
        "components": components,
        "dependencies": [
            {"ref": product_ref, "dependsOn": component_refs},
            *[
                {"ref": component_ref, "dependsOn": []}
                for component_ref in component_refs
            ],
        ],
    }
    serialized = (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")

    destination = Path(output_path)
    if destination.exists():
        raise RuntimeSbomError("runtime SBOM output already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        try:
            os.link(temp_path, destination)
        except FileExistsError as exc:
            raise RuntimeSbomError("runtime SBOM output appeared during publication") from exc
        except OSError as exc:
            raise RuntimeSbomError("runtime SBOM cannot be published atomically") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    return RuntimeSbomResult(
        path=destination,
        sha256=_sha256(destination),
        notice_manifest_sha256=manifest_sha256,
        component_count=len(components),
    )


__all__ = [
    "RuntimeSbomError",
    "RuntimeSbomResult",
    "build_runtime_cyclonedx_sbom",
]

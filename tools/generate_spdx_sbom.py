from __future__ import annotations

"""Generate a deterministic SPDX 2.3 JSON SBOM from qualified release facts."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from acs.spdx_sbom import (
    ComponentRecord,
    SbomError,
    build_spdx_document,
    canonical_spdx_json,
)


class ManifestError(SbomError):
    pass


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _regular_input(path: Path) -> str:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ManifestError(f"cannot inspect SBOM manifest: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ManifestError("SBOM manifest must be a regular non-symlink file")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ManifestError(f"cannot read UTF-8 SBOM manifest: {exc}") from exc


def load_release_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    raw = _regular_input(manifest_path)
    if len(raw.encode("utf-8")) > 2 * 1024 * 1024:
        raise ManifestError("SBOM manifest exceeds 2 MiB limit")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except _DuplicateKeyError as exc:
        raise ManifestError(
            f"duplicate JSON key in SBOM manifest: {exc.args[0]}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid SBOM manifest JSON: {exc.msg}") from exc
    if type(value) is not dict:
        raise ManifestError("SBOM manifest root must be an object")
    if set(value) != {"schema_version", "created_at", "product", "components"}:
        raise ManifestError("SBOM manifest root keys are invalid")
    if value["schema_version"] != 1:
        raise ManifestError("unsupported SBOM manifest schema_version")
    if type(value["product"]) is not dict:
        raise ManifestError("SBOM product must be an object")
    if type(value["components"]) is not list:
        raise ManifestError("SBOM components must be an array")
    return value


def build_from_manifest(value: dict[str, Any]) -> dict[str, Any]:
    product = value["product"]
    required = {"version", "source_sha", "sha256"}
    optional = {"name", "supplier", "license_declared", "download_location"}
    if not required.issubset(product) or set(product) - required - optional:
        raise ManifestError("SBOM product keys are invalid")

    created = value["created_at"]
    if type(created) is not str:
        raise ManifestError("SBOM created_at must be text")
    try:
        created_at = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ManifestError(
            "SBOM created_at must use canonical UTC whole-second form"
        ) from exc

    components: list[ComponentRecord] = []
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
    for index, item in enumerate(value["components"]):
        if type(item) is not dict:
            raise ManifestError(f"component {index} must be an object")
        if (
            not required_component.issubset(item)
            or set(item) - required_component - optional_component
        ):
            raise ManifestError(f"component {index} keys are invalid")
        try:
            components.append(
                ComponentRecord(
                    name=item["name"],
                    version=item["version"],
                    artifact_sha256=item["artifact_sha256"],
                    license_declared=item["license_declared"],
                    supplier=item.get("supplier", "NOASSERTION"),
                    download_location=item.get("download_location", "NOASSERTION"),
                    purl=item.get("purl"),
                    copyright_text=item.get("copyright_text", "NOASSERTION"),
                )
            )
        except SbomError as exc:
            raise ManifestError(f"component {index}: {exc}") from exc

    return build_spdx_document(
        product_name=product.get("name", "Accessible Chess"),
        product_version=product["version"],
        source_sha=product["source_sha"],
        product_sha256=product["sha256"],
        product_supplier=product.get("supplier", "NOASSERTION"),
        product_license_declared=product.get("license_declared", "NOASSERTION"),
        product_download_location=product.get(
            "download_location", "NOASSERTION"
        ),
        components=components,
        created_at=created_at,
    )


def write_atomic(path: str | Path, content: str) -> None:
    output = Path(path)
    parent = output.parent
    try:
        parent_meta = parent.lstat()
    except OSError as exc:
        raise ManifestError(f"cannot inspect SBOM output directory: {exc}") from exc
    if stat.S_ISLNK(parent_meta.st_mode) or not stat.S_ISDIR(parent_meta.st_mode):
        raise ManifestError("SBOM output parent must be a real directory")
    if output.exists() or output.is_symlink():
        try:
            current = output.lstat()
        except OSError as exc:
            raise ManifestError(
                f"cannot inspect existing SBOM output: {exc}"
            ) from exc
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
            raise ManifestError(
                "existing SBOM output must be a regular non-symlink file"
            )

    temp = parent / f".{output.name}.tmp-{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(temp, flags, 0o600)
        try:
            data = content.encode("utf-8")
            with os.fdopen(fd, "wb", closefd=True) as stream:
                fd = -1
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, output)
        finally:
            if fd != -1:
                os.close(fd)
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
    except OSError as exc:
        raise ManifestError(
            f"cannot publish SBOM output atomically: {exc}"
        ) from exc


def generate(input_path: str | Path, output_path: str | Path) -> str:
    manifest = load_release_manifest(input_path)
    document = build_from_manifest(manifest)
    encoded = canonical_spdx_json(document)
    write_atomic(output_path, encoded)
    return encoded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help="qualified release component manifest JSON",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="destination SPDX 2.3 JSON file",
    )
    args = parser.parse_args(argv)
    try:
        generate(args.input, args.output)
    except SbomError as exc:
        print(f"SBOM generation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

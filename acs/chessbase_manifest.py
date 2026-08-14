from __future__ import annotations

"""Immutable provenance manifests for ChessBase-family source bundles.

This module performs evidence collection only. It does not decode proprietary
records and never writes to source files. The manifest is a neutral DTO that can
be attached to import reports or persisted by ACSDB without exposing format
internals to UI code.
"""

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from .chessbase_adapter import ChessBaseSourceProbe, probe_chessbase_source

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ComponentEvidence:
    path: str
    extension: str
    role: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ChessBaseBundleManifest:
    schema_version: int
    primary_path: str
    source_kind: str
    family_name: str
    status: str
    primary: ComponentEvidence | None
    components: tuple[ComponentEvidence, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def all_evidence(self) -> tuple[ComponentEvidence, ...]:
        if self.primary is None:
            return self.components
        return (self.primary,) + self.components

    def as_dict(self) -> dict[str, object]:
        def item(e: ComponentEvidence) -> dict[str, object]:
            return {
                "path": e.path,
                "extension": e.extension,
                "role": e.role,
                "size": e.size,
                "sha256": e.sha256,
            }
        return {
            "schema_version": self.schema_version,
            "primary_path": self.primary_path,
            "source_kind": self.source_kind,
            "family_name": self.family_name,
            "status": self.status,
            "primary": item(self.primary) if self.primary else None,
            "components": [item(e) for e in self.components],
            "warnings": list(self.warnings),
        }


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> ComponentEvidence:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return ComponentEvidence(
        path=str(path.resolve()),
        extension=path.suffix.lower(),
        role="source",
        size=size,
        sha256=digest.hexdigest(),
    )


def _with_role(evidence: ComponentEvidence, role: str, extension: str | None = None) -> ComponentEvidence:
    return ComponentEvidence(
        path=evidence.path,
        extension=extension or evidence.extension,
        role=role,
        size=evidence.size,
        sha256=evidence.sha256,
    )


def build_chessbase_manifest(path: str | Path) -> ChessBaseBundleManifest:
    source = Path(path)
    probe: ChessBaseSourceProbe = probe_chessbase_source(source)
    warnings: list[str] = list(probe.warnings)

    if not probe.recognized:
        warnings.append("Unrecognized source extension; no proprietary decoding attempted.")
        return ChessBaseBundleManifest(
            MANIFEST_SCHEMA_VERSION, str(source.resolve()), probe.source_kind,
            probe.family_name, "unsupported", None, warnings=tuple(warnings)
        )
    if not probe.is_primary_source:
        warnings.append("Component-only path is not a database primary source.")
        return ChessBaseBundleManifest(
            MANIFEST_SCHEMA_VERSION, str(source.resolve()), probe.source_kind,
            probe.family_name, "component_only", None, warnings=tuple(warnings)
        )
    if not source.is_file():
        warnings.append("Primary source file is missing or unavailable.")
        return ChessBaseBundleManifest(
            MANIFEST_SCHEMA_VERSION, str(source.resolve()), probe.source_kind,
            probe.family_name, "damaged", None, warnings=tuple(warnings)
        )

    primary = _with_role(_hash_file(source), "primary database source", probe.extension)
    components: list[ComponentEvidence] = []
    if probe.extension == ".cbh":
        for component in probe.components:
            if component.exists and component.path.is_file():
                components.append(
                    _with_role(_hash_file(component.path), component.role, component.extension)
                )
        if not components:
            warnings.append("No CBH companion components were found; completeness cannot be established.")
            status = "partial"
        else:
            status = "evidence_collected"
    else:
        status = "evidence_collected"

    warnings.append("Manifest records source evidence only; decoder compatibility is not implied.")
    return ChessBaseBundleManifest(
        MANIFEST_SCHEMA_VERSION,
        str(source.resolve()),
        probe.source_kind,
        probe.family_name,
        status,
        primary,
        tuple(components),
        tuple(warnings),
    )


def verify_manifest_unchanged(manifest: ChessBaseBundleManifest) -> tuple[bool, tuple[str, ...]]:
    """Re-hash every recorded file and report exact drift without modifying input."""
    problems: list[str] = []
    for evidence in manifest.all_evidence:
        path = Path(evidence.path)
        if not path.is_file():
            problems.append(f"Missing source evidence: {evidence.path}")
            continue
        current = _hash_file(path)
        if current.size != evidence.size:
            problems.append(
                f"Size changed for {evidence.path}: {evidence.size} -> {current.size}"
            )
        if current.sha256 != evidence.sha256:
            problems.append(f"SHA-256 changed for {evidence.path}")
    return not problems, tuple(problems)


def total_manifest_bytes(manifest: ChessBaseBundleManifest) -> int:
    return sum(item.size for item in manifest.all_evidence)

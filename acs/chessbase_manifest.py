from __future__ import annotations

"""Immutable provenance manifests for ChessBase-family source bundles.

This module performs evidence collection only. It does not decode proprietary
records and never writes to source files. Internal evidence retains a usable
source path for re-verification, while serialized report payloads expose only
report-safe filenames rather than workstation directories.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .chessbase_adapter import ChessBaseSourceProbe, probe_chessbase_source, report_safe_name
from .import_contract import fingerprint

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
                "path": report_safe_name(e.path),
                "extension": e.extension,
                "role": e.role,
                "size": e.size,
                "sha256": e.sha256,
            }
        return {
            "schema_version": self.schema_version,
            "primary_path": report_safe_name(self.primary_path),
            "source_kind": self.source_kind,
            "family_name": self.family_name,
            "status": self.status,
            "primary": item(self.primary) if self.primary else None,
            "components": [item(e) for e in self.components],
            "warnings": list(self.warnings),
        }


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> ComponentEvidence:
    source = fingerprint(path, chunk_size=chunk_size)
    return ComponentEvidence(source.path, path.suffix.lower(), "source", source.size, source.sha256)


def _with_role(evidence: ComponentEvidence, role: str, extension: str | None = None) -> ComponentEvidence:
    return ComponentEvidence(evidence.path, extension or evidence.extension, role, evidence.size, evidence.sha256)


def _empty_manifest(source: Path, probe: ChessBaseSourceProbe, status: str, warnings: list[str]) -> ChessBaseBundleManifest:
    return ChessBaseBundleManifest(
        MANIFEST_SCHEMA_VERSION,
        str(Path(source).absolute()),
        probe.source_kind,
        probe.family_name,
        status,
        None,
        warnings=tuple(warnings),
    )


def build_chessbase_manifest(path: str | Path) -> ChessBaseBundleManifest:
    source = Path(path)
    probe: ChessBaseSourceProbe = probe_chessbase_source(source)
    warnings: list[str] = list(probe.warnings)
    if not probe.recognized:
        warnings.append("Unrecognized source extension; no proprietary decoding attempted.")
        return _empty_manifest(source, probe, "unsupported", warnings)
    if not probe.is_primary_source:
        warnings.append("Component-only path is not a database primary source.")
        return _empty_manifest(source, probe, "component_only", warnings)
    if source.is_symlink():
        warnings.append("Primary source uses filesystem indirection and was rejected.")
        return _empty_manifest(source, probe, "damaged", warnings)
    if not source.is_file():
        warnings.append("Primary source file is missing or unavailable.")
        return _empty_manifest(source, probe, "damaged", warnings)

    try:
        primary = _with_role(_hash_file(source), "primary database source", probe.extension)
    except (OSError, ValueError, RuntimeError):
        warnings.append("Primary source evidence is unavailable or unsafe to inspect.")
        return _empty_manifest(source, probe, "damaged", warnings)

    components: list[ComponentEvidence] = []
    if probe.extension == ".cbh":
        for component in probe.components:
            if not component.exists:
                continue
            if component.path.is_symlink():
                warnings.append(f"Companion {component.extension} uses filesystem indirection and was rejected.")
                continue
            try:
                if component.path.is_file():
                    components.append(
                        _with_role(_hash_file(component.path), component.role, component.extension)
                    )
            except (OSError, ValueError, RuntimeError):
                warnings.append(f"Companion {component.extension} evidence is unavailable or unsafe.")
        if not components:
            warnings.append("No safe CBH companion evidence was collected; completeness cannot be established.")
            status = "partial"
        else:
            status = "evidence_collected"
    else:
        status = "evidence_collected"
    warnings.append("Manifest records source evidence only; decoder compatibility is not implied.")
    return ChessBaseBundleManifest(
        MANIFEST_SCHEMA_VERSION,
        primary.path,
        probe.source_kind,
        probe.family_name,
        status,
        primary,
        tuple(components),
        tuple(warnings),
    )


def verify_manifest_unchanged(manifest: ChessBaseBundleManifest) -> tuple[bool, tuple[str, ...]]:
    problems: list[str] = []
    for evidence in manifest.all_evidence:
        path = Path(evidence.path)
        safe_name = report_safe_name(evidence.path)
        try:
            if not path.is_file() or path.is_symlink():
                problems.append(f"Source evidence unavailable: {safe_name}")
                continue
            current = _hash_file(path)
        except (OSError, ValueError, RuntimeError) as exc:
            problems.append(f"Source evidence unavailable for {safe_name}: {type(exc).__name__}")
            continue
        if current.size != evidence.size:
            problems.append(f"Size changed for {safe_name}: {evidence.size} -> {current.size}")
        if current.sha256 != evidence.sha256:
            problems.append(f"SHA-256 changed for {safe_name}")
    return not problems, tuple(problems)


def total_manifest_bytes(manifest: ChessBaseBundleManifest) -> int:
    return sum(item.size for item in manifest.all_evidence)

from __future__ import annotations

"""Evidence-gated backend seam for future ChessBase 2CBH decoding.

This module deliberately does *not* implement 2CBH semantics and does not make
2CBH import available.  It provides the boundary that a future independently
qualified decoder must satisfy before Product code may observe a multi-file
2CBH family as a complete source bundle.

No component role or required/optional status is inferred from a filename.
Those facts belong to a reviewed :class:`TwoCbhFamilyContract` supplied by a
qualified backend evidence package.  The default registry is empty.
"""

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
from typing import Iterable

from .report_paths import report_safe_name

PRIMARY_EXTENSION = ".2cbh"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BACKEND_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_PROTOCOL_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_SUFFIX_RE = re.compile(r"^\.[a-z0-9][a-z0-9._-]{0,31}$")


class TwoCbhQualificationError(ValueError):
    """Raised when backend/topology evidence is not sufficient to enable use."""


class TwoCbhSourceError(RuntimeError):
    """Raised when a 2CBH source family cannot be observed safely."""


class TwoCbhSourceChangedError(TwoCbhSourceError):
    """Raised when source bytes/topology change after evidence capture."""


class TwoCbhRequirement(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True, slots=True)
class TwoCbhResourceLimits:
    """Hard pre-decode limits for a future external backend invocation."""

    max_members: int = 32
    max_member_bytes: int = 8 * 1024 * 1024 * 1024
    max_total_bytes: int = 32 * 1024 * 1024 * 1024
    hash_chunk_bytes: int = 1024 * 1024
    decoder_timeout_seconds: float = 120.0
    max_decoder_stdout_bytes: int = 64 * 1024 * 1024
    max_decoder_stderr_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for value, label, minimum, maximum in (
            (self.max_members, "max_members", 1, 256),
            (self.max_member_bytes, "max_member_bytes", 1, 64 * 1024**3),
            (self.max_total_bytes, "max_total_bytes", 1, 256 * 1024**3),
            (self.hash_chunk_bytes, "hash_chunk_bytes", 4096, 16 * 1024**2),
            (self.max_decoder_stdout_bytes, "max_decoder_stdout_bytes", 1024, 256 * 1024**2),
            (self.max_decoder_stderr_bytes, "max_decoder_stderr_bytes", 1024, 64 * 1024**2),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{label} is outside the supported bound")
        if self.max_total_bytes < self.max_member_bytes:
            raise ValueError("max_total_bytes must be >= max_member_bytes")
        if type(self.decoder_timeout_seconds) not in (int, float):
            raise ValueError("decoder_timeout_seconds must be numeric")
        timeout = float(self.decoder_timeout_seconds)
        if not 0 < timeout <= 600:
            raise ValueError("decoder_timeout_seconds must be within (0, 600]")


@dataclass(frozen=True, slots=True)
class TwoCbhMemberRule:
    """One evidence-qualified same-root member rule.

    ``suffix`` and ``requirement`` are transport/topology facts only.  There is
    intentionally no semantic-role field here: Product must not invent one.
    """

    suffix: str
    requirement: TwoCbhRequirement

    def __post_init__(self) -> None:
        if type(self.suffix) is not str:
            raise ValueError("member suffix must be text")
        suffix = self.suffix.lower()
        if _SUFFIX_RE.fullmatch(suffix) is None or suffix == PRIMARY_EXTENSION:
            raise ValueError("member suffix is invalid or duplicates the primary extension")
        object.__setattr__(self, "suffix", suffix)
        object.__setattr__(self, "requirement", TwoCbhRequirement(self.requirement))


@dataclass(frozen=True, slots=True)
class TwoCbhFamilyContract:
    """Reviewed topology facts supplied by one qualified decoder evidence set."""

    evidence_id: str
    members: tuple[TwoCbhMemberRule, ...]
    topology_evidence_qualified: bool
    reject_unlisted_same_root_files: bool = False

    def __post_init__(self) -> None:
        if type(self.evidence_id) is not str or not self.evidence_id.strip():
            raise ValueError("evidence_id must be non-empty text")
        if type(self.members) is not tuple:
            object.__setattr__(self, "members", tuple(self.members))
        if type(self.topology_evidence_qualified) is not bool:
            raise ValueError("topology_evidence_qualified must be boolean")
        if type(self.reject_unlisted_same_root_files) is not bool:
            raise ValueError("reject_unlisted_same_root_files must be boolean")
        seen: set[str] = set()
        for rule in self.members:
            if not isinstance(rule, TwoCbhMemberRule):
                raise ValueError("members must contain TwoCbhMemberRule values")
            folded = rule.suffix.casefold()
            if folded in seen:
                raise ValueError("duplicate 2CBH family member suffix")
            seen.add(folded)


@dataclass(frozen=True, slots=True)
class TwoCbhBackendDescriptor:
    """Evidence package required before any future 2CBH backend may register."""

    backend_id: str
    backend_version: str
    executable_sha256: str
    protocol_id: str
    license_name: str
    license_url: str
    automation_interface_evidence: str
    family_contract: TwoCbhFamilyContract
    oracle_id: str
    oracle_lawful_for_testing: bool
    oracle_independent_of_decoder: bool
    oracle_semantic_equivalence_proven: bool
    evidence_references: tuple[str, ...] = field(default_factory=tuple)
    integration_mode: str = "external_executable"
    default_windows_bundle_allowed: bool = False

    def __post_init__(self) -> None:
        if type(self.backend_id) is not str or _BACKEND_ID_RE.fullmatch(self.backend_id) is None:
            raise ValueError("backend_id is invalid")
        for value, label in (
            (self.backend_version, "backend_version"),
            (self.license_name, "license_name"),
            (self.license_url, "license_url"),
            (self.automation_interface_evidence, "automation_interface_evidence"),
            (self.oracle_id, "oracle_id"),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"{label} must be non-empty text")
        if type(self.executable_sha256) is not str or _SHA256_RE.fullmatch(self.executable_sha256) is None:
            raise ValueError("executable_sha256 must be lowercase SHA-256")
        if type(self.protocol_id) is not str or _PROTOCOL_RE.fullmatch(self.protocol_id) is None:
            raise ValueError("protocol_id is invalid")
        if not isinstance(self.family_contract, TwoCbhFamilyContract):
            raise ValueError("family_contract is invalid")
        for value, label in (
            (self.oracle_lawful_for_testing, "oracle_lawful_for_testing"),
            (self.oracle_independent_of_decoder, "oracle_independent_of_decoder"),
            (self.oracle_semantic_equivalence_proven, "oracle_semantic_equivalence_proven"),
            (self.default_windows_bundle_allowed, "default_windows_bundle_allowed"),
        ):
            if type(value) is not bool:
                raise ValueError(f"{label} must be boolean")
        if type(self.evidence_references) is not tuple:
            object.__setattr__(self, "evidence_references", tuple(self.evidence_references))
        if any(type(item) is not str or not item.strip() for item in self.evidence_references):
            raise ValueError("evidence_references must contain non-empty text")
        if self.integration_mode != "external_executable":
            raise ValueError("2CBH backends must remain isolated external executables")
        # Product policy: third-party decoders are never silently added to the
        # default Windows package.  A future packaging decision requires its own
        # explicit release/legal review and a different contract revision.
        if self.default_windows_bundle_allowed:
            raise ValueError("default Windows package must not bundle a 2CBH backend")

    @property
    def qualified(self) -> bool:
        return (
            self.family_contract.topology_evidence_qualified
            and self.oracle_lawful_for_testing
            and self.oracle_independent_of_decoder
            and self.oracle_semantic_equivalence_proven
            and bool(self.evidence_references)
            and not self.default_windows_bundle_allowed
        )


class TwoCbhBackendRegistry:
    """Explicit registry.  There are deliberately no built-in/default backends."""

    def __init__(self) -> None:
        self._items: dict[str, TwoCbhBackendDescriptor] = {}

    def register(self, descriptor: TwoCbhBackendDescriptor) -> None:
        if not isinstance(descriptor, TwoCbhBackendDescriptor):
            raise TypeError("descriptor must be TwoCbhBackendDescriptor")
        if not descriptor.qualified:
            raise TwoCbhQualificationError(
                "2CBH backend lacks qualified topology and independent lawful semantic oracle evidence"
            )
        if descriptor.backend_id in self._items:
            raise TwoCbhQualificationError("2CBH backend id is already registered")
        self._items[descriptor.backend_id] = descriptor

    def get(self, backend_id: str) -> TwoCbhBackendDescriptor | None:
        if type(backend_id) is not str:
            raise TypeError("backend_id must be text")
        return self._items.get(backend_id)

    def descriptors(self) -> tuple[TwoCbhBackendDescriptor, ...]:
        return tuple(self._items[key] for key in sorted(self._items))

    @property
    def decoder_available(self) -> bool:
        return bool(self._items)


def default_twocbh_backend_registry() -> TwoCbhBackendRegistry:
    """Return the shipping registry; support remains unavailable by default."""

    return TwoCbhBackendRegistry()


@dataclass(frozen=True, slots=True)
class TwoCbhMemberEvidence:
    path: Path
    suffix: str
    requirement: TwoCbhRequirement
    size_bytes: int
    sha256: str

    def as_report_fields(self) -> dict[str, object]:
        return {
            "path": report_safe_name(self.path),
            "suffix": self.suffix,
            "requirement": self.requirement.value,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class TwoCbhBundleEvidence:
    primary_path: Path
    backend_id: str
    topology_evidence_id: str
    files: tuple[TwoCbhMemberEvidence, ...]
    total_bytes: int

    def as_report_fields(self) -> dict[str, object]:
        return {
            "primary_path": report_safe_name(self.primary_path),
            "backend_id": self.backend_id,
            "topology_evidence_id": self.topology_evidence_id,
            "files": [item.as_report_fields() for item in self.files],
            "total_bytes": self.total_bytes,
        }


def _is_reparse_point(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & marker)


def _require_regular(path: Path, label: str) -> os.stat_result:
    try:
        st = path.lstat()
    except OSError as exc:
        raise TwoCbhSourceError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st) or not stat.S_ISREG(st.st_mode):
        raise TwoCbhSourceError(f"{label} must be a regular non-indirected file")
    return st


def _hash_bounded(
    path: Path,
    *,
    suffix: str,
    requirement: TwoCbhRequirement,
    limits: TwoCbhResourceLimits,
) -> TwoCbhMemberEvidence:
    before = _require_regular(path, "2CBH source member")
    if before.st_size > limits.max_member_bytes:
        raise TwoCbhSourceError("2CBH source member exceeds the configured size limit")
    digest = sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(limits.hash_chunk_bytes)
                if not chunk:
                    break
                size += len(chunk)
                if size > limits.max_member_bytes:
                    raise TwoCbhSourceError("2CBH source member exceeds the configured size limit")
                digest.update(chunk)
    except TwoCbhSourceError:
        raise
    except OSError as exc:
        raise TwoCbhSourceError("2CBH source member could not be read safely") from exc
    after = _require_regular(path, "2CBH source member")
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise TwoCbhSourceChangedError("2CBH source member changed while hashing")
    return TwoCbhMemberEvidence(
        path=Path(os.path.abspath(os.fspath(path))),
        suffix=suffix,
        requirement=requirement,
        size_bytes=size,
        sha256=digest.hexdigest(),
    )


def _directory_index(directory: Path, watched_names: Iterable[str]) -> dict[str, Path]:
    watched = {item.casefold() for item in watched_names}
    result: dict[str, Path] = {}
    try:
        for entry in directory.iterdir():
            folded = entry.name.casefold()
            if folded not in watched:
                continue
            previous = result.get(folded)
            if previous is not None and previous.name != entry.name:
                raise TwoCbhSourceError("2CBH source family contains a case-colliding member")
            result[folded] = entry
    except TwoCbhSourceError:
        raise
    except OSError as exc:
        raise TwoCbhSourceError("2CBH source directory is unavailable") from exc
    return result


def capture_twocbh_bundle(
    primary: str | Path,
    descriptor: TwoCbhBackendDescriptor,
    *,
    limits: TwoCbhResourceLimits | None = None,
) -> TwoCbhBundleEvidence:
    """Capture a qualified, read-only source family before future decoding.

    This function is intentionally unreachable with the shipping registry:
    callers must supply a descriptor that already passed independent topology,
    license/interface, corpus and semantic-oracle qualification.
    """

    if not isinstance(descriptor, TwoCbhBackendDescriptor) or not descriptor.qualified:
        raise TwoCbhQualificationError("2CBH backend descriptor is not qualified")
    limits = limits or TwoCbhResourceLimits()
    if not isinstance(limits, TwoCbhResourceLimits):
        raise TypeError("limits must be TwoCbhResourceLimits")
    source = Path(primary)
    if source.suffix.lower() != PRIMARY_EXTENSION:
        raise TwoCbhSourceError("2CBH primary source must use the .2cbh extension")
    _require_regular(source, "2CBH primary source")

    contract = descriptor.family_contract
    expected_names = [source.name]
    expected_names.extend(f"{source.stem}{rule.suffix}" for rule in contract.members)
    if len(expected_names) > limits.max_members:
        raise TwoCbhSourceError("2CBH topology exceeds the configured member-count limit")
    index = _directory_index(source.parent, expected_names)

    real_primary = index.get(source.name.casefold(), source)
    files: list[TwoCbhMemberEvidence] = [
        _hash_bounded(
            real_primary,
            suffix=PRIMARY_EXTENSION,
            requirement=TwoCbhRequirement.REQUIRED,
            limits=limits,
        )
    ]

    for rule in contract.members:
        expected_name = f"{source.stem}{rule.suffix}"
        member = index.get(expected_name.casefold())
        if member is None:
            if rule.requirement is TwoCbhRequirement.REQUIRED:
                raise TwoCbhSourceError("2CBH source family is missing a required qualified member")
            continue
        files.append(
            _hash_bounded(
                member,
                suffix=rule.suffix,
                requirement=rule.requirement,
                limits=limits,
            )
        )

    if contract.reject_unlisted_same_root_files:
        allowed = {name.casefold() for name in expected_names}
        try:
            for entry in source.parent.iterdir():
                if not entry.is_file():
                    continue
                if entry.stem.casefold() == source.stem.casefold() and entry.name.casefold() not in allowed:
                    raise TwoCbhSourceError("2CBH source family contains an unqualified same-root member")
        except TwoCbhSourceError:
            raise
        except OSError as exc:
            raise TwoCbhSourceError("2CBH source directory is unavailable") from exc

    total = sum(item.size_bytes for item in files)
    if total > limits.max_total_bytes:
        raise TwoCbhSourceError("2CBH source family exceeds the configured total-size limit")
    return TwoCbhBundleEvidence(
        primary_path=files[0].path,
        backend_id=descriptor.backend_id,
        topology_evidence_id=contract.evidence_id,
        files=tuple(files),
        total_bytes=total,
    )


def verify_twocbh_bundle_unchanged(
    evidence: TwoCbhBundleEvidence,
    descriptor: TwoCbhBackendDescriptor,
    *,
    limits: TwoCbhResourceLimits | None = None,
) -> TwoCbhBundleEvidence:
    """Re-capture a family and reject any byte/topology mutation."""

    if not isinstance(evidence, TwoCbhBundleEvidence):
        raise TypeError("evidence must be TwoCbhBundleEvidence")
    current = capture_twocbh_bundle(evidence.primary_path, descriptor, limits=limits)
    if current != evidence:
        raise TwoCbhSourceChangedError(
            "2CBH source family changed after capture; discard all decoder output"
        )
    return current

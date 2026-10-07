from __future__ import annotations

"""Section 37 cross-domain persistence and user-data portability boundary.

The coordinator deliberately owns no domain state. Existing Settings, Library,
Books/Training, Classroom, Media, Agent/account stores remain authoritative.
This layer only creates bounded, checksummed bundles and coordinates validated
restore/import with rollback across typed adapters.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import base64
import hashlib
import json


BUNDLE_SCHEMA_VERSION = 1
MAX_DOMAIN_ID = 96
MAX_ENTRIES = 128
MAX_ENTRY_BYTES = 128 * 1024 * 1024
MAX_BUNDLE_BYTES = 512 * 1024 * 1024


class UserDataPortabilityError(ValueError):
    """Stable failure at the Section 37 orchestration boundary."""


class BundleKind(StrEnum):
    BACKUP = "backup"
    PORTABLE = "portable"


@dataclass(frozen=True, slots=True)
class DomainSnapshot:
    domain: str
    schema_version: int
    payload: bytes
    revision: str | None = None

    def __post_init__(self) -> None:
        if type(self.domain) is not str or not self.domain or self.domain != self.domain.strip():
            raise UserDataPortabilityError("domain must be canonical text")
        if len(self.domain) > MAX_DOMAIN_ID or any(ch.isspace() for ch in self.domain):
            raise UserDataPortabilityError("domain is invalid")
        if type(self.schema_version) is not int or self.schema_version < 0:
            raise UserDataPortabilityError("schema_version must be a non-negative exact integer")
        if type(self.payload) is not bytes:
            raise UserDataPortabilityError("payload must be immutable bytes")
        if len(self.payload) > MAX_ENTRY_BYTES:
            raise UserDataPortabilityError("domain snapshot exceeds byte limit")
        if self.revision is not None:
            if type(self.revision) is not str or not self.revision or self.revision != self.revision.strip():
                raise UserDataPortabilityError("revision must be canonical text or null")
            if len(self.revision) > 256:
                raise UserDataPortabilityError("revision is too long")


@dataclass(frozen=True, slots=True)
class DomainAdapter:
    """Typed adapter around one existing authoritative durable domain."""

    domain: str
    snapshot: Callable[[], DomainSnapshot]
    prepare_import: Callable[[DomainSnapshot], DomainSnapshot]
    restore: Callable[[DomainSnapshot], None]
    portable: bool = True
    contains_secret_material: bool = False

    def __post_init__(self) -> None:
        DomainSnapshot(self.domain, 0, b"")
        if not callable(self.snapshot) or not callable(self.prepare_import) or not callable(self.restore):
            raise TypeError("domain adapter callables are required")
        if type(self.portable) is not bool or type(self.contains_secret_material) is not bool:
            raise TypeError("adapter flags must be boolean")
        if self.contains_secret_material:
            raise UserDataPortabilityError(
                "secret material must remain with its canonical credential owner"
            )


@dataclass(frozen=True, slots=True)
class BundleReceipt:
    kind: BundleKind
    domains: tuple[str, ...]
    byte_size: int
    sha256: str


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _snapshot_from(adapter: DomainAdapter) -> DomainSnapshot:
    value = adapter.snapshot()
    if type(value) is not DomainSnapshot or value.domain != adapter.domain:
        raise UserDataPortabilityError("domain snapshot identity mismatch")
    return value


def _entry(snapshot: DomainSnapshot) -> dict[str, object]:
    return {
        "domain": snapshot.domain,
        "schema_version": snapshot.schema_version,
        "revision": snapshot.revision,
        "size": len(snapshot.payload),
        "sha256": _sha256(snapshot.payload),
        "payload_b64": base64.b64encode(snapshot.payload).decode("ascii"),
    }


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    try:
        raw = (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise UserDataPortabilityError("bundle cannot be serialized") from exc
    if len(raw) > MAX_BUNDLE_BYTES:
        raise UserDataPortabilityError("bundle exceeds byte limit")
    return raw


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise UserDataPortabilityError("bundle contains duplicate JSON keys")
        value[key] = item
    return value


def _parse(raw: bytes) -> tuple[BundleKind, tuple[DomainSnapshot, ...]]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_BUNDLE_BYTES:
        raise UserDataPortabilityError("bundle bytes are invalid")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                UserDataPortabilityError("bundle contains a non-finite number")
            ),
        )
    except UserDataPortabilityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UserDataPortabilityError("bundle is not valid canonical JSON") from exc
    if type(value) is not dict or set(value) != {"schema_version", "kind", "entries"}:
        raise UserDataPortabilityError("bundle envelope is invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise UserDataPortabilityError("bundle schema is unsupported")
    try:
        kind = BundleKind(value["kind"])
    except (TypeError, ValueError) as exc:
        raise UserDataPortabilityError("bundle kind is invalid") from exc
    entries = value["entries"]
    if type(entries) is not list or len(entries) > MAX_ENTRIES:
        raise UserDataPortabilityError("bundle entry collection is invalid")
    snapshots: list[DomainSnapshot] = []
    seen: set[str] = set()
    total = 0
    expected_fields = {
        "domain", "schema_version", "revision", "size", "sha256", "payload_b64"
    }
    for item in entries:
        if type(item) is not dict or set(item) != expected_fields:
            raise UserDataPortabilityError("bundle entry is invalid")
        domain = item["domain"]
        schema_version = item["schema_version"]
        revision = item["revision"]
        size = item["size"]
        digest = item["sha256"]
        encoded = item["payload_b64"]
        if type(domain) is not str or domain in seen:
            raise UserDataPortabilityError("bundle domain identity is invalid or duplicated")
        if type(size) is not int or size < 0 or size > MAX_ENTRY_BYTES:
            raise UserDataPortabilityError("bundle entry size is invalid")
        if type(digest) is not str or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise UserDataPortabilityError("bundle entry digest is invalid")
        if type(encoded) is not str:
            raise UserDataPortabilityError("bundle entry payload is invalid")
        try:
            payload = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as exc:
            raise UserDataPortabilityError("bundle entry payload is invalid") from exc
        if len(payload) != size or _sha256(payload) != digest:
            raise UserDataPortabilityError("bundle entry checksum mismatch")
        total += len(payload)
        if total > MAX_BUNDLE_BYTES:
            raise UserDataPortabilityError("bundle payload exceeds byte limit")
        snapshot = DomainSnapshot(domain, schema_version, payload, revision)
        snapshots.append(snapshot)
        seen.add(domain)
    if tuple(sorted(seen)) != tuple(s.domain for s in snapshots):
        raise UserDataPortabilityError("bundle domains must be canonical sorted order")
    return kind, tuple(snapshots)


class UserDataPortabilityCoordinator:
    """Compose existing durable owners without becoming another state authority."""

    def __init__(self, adapters: tuple[DomainAdapter, ...]) -> None:
        if type(adapters) is not tuple or len(adapters) > MAX_ENTRIES:
            raise TypeError("adapters must be a bounded tuple")
        by_domain: dict[str, DomainAdapter] = {}
        for adapter in adapters:
            if type(adapter) is not DomainAdapter:
                raise TypeError("adapters must contain exact DomainAdapter values")
            if adapter.domain in by_domain:
                raise UserDataPortabilityError("duplicate domain adapter")
            by_domain[adapter.domain] = adapter
        self._adapters = dict(sorted(by_domain.items()))

    @property
    def domains(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def _build(self, kind: BundleKind) -> tuple[bytes, BundleReceipt]:
        entries: list[dict[str, object]] = []
        domains: list[str] = []
        for domain, adapter in self._adapters.items():
            if kind is BundleKind.PORTABLE and not adapter.portable:
                continue
            snapshot = _snapshot_from(adapter)
            entries.append(_entry(snapshot))
            domains.append(domain)
        raw = _canonical_bytes(
            {
                "schema_version": BUNDLE_SCHEMA_VERSION,
                "kind": kind.value,
                "entries": entries,
            }
        )
        return raw, BundleReceipt(kind, tuple(domains), len(raw), _sha256(raw))

    def create_backup(self) -> tuple[bytes, BundleReceipt]:
        return self._build(BundleKind.BACKUP)

    def export_user_data(self) -> tuple[bytes, BundleReceipt]:
        return self._build(BundleKind.PORTABLE)

    def inspect(self, raw: bytes) -> BundleReceipt:
        kind, snapshots = _parse(raw)
        return BundleReceipt(
            kind,
            tuple(snapshot.domain for snapshot in snapshots),
            len(raw),
            _sha256(raw),
        )

    def restore_backup(self, raw: bytes) -> BundleReceipt:
        return self._restore(raw, expected_kind=BundleKind.BACKUP)

    def import_user_data(self, raw: bytes) -> BundleReceipt:
        return self._restore(raw, expected_kind=BundleKind.PORTABLE)

    def _restore(self, raw: bytes, *, expected_kind: BundleKind) -> BundleReceipt:
        kind, incoming = _parse(raw)
        if kind is not expected_kind:
            raise UserDataPortabilityError("bundle kind does not match the requested operation")
        prepared: list[tuple[DomainAdapter, DomainSnapshot]] = []
        for snapshot in incoming:
            adapter = self._adapters.get(snapshot.domain)
            if adapter is None:
                raise UserDataPortabilityError(
                    f"bundle domain is unavailable in this product: {snapshot.domain}"
                )
            if kind is BundleKind.PORTABLE and not adapter.portable:
                raise UserDataPortabilityError("bundle contains a non-portable domain")
            candidate = adapter.prepare_import(snapshot)
            if type(candidate) is not DomainSnapshot or candidate.domain != adapter.domain:
                raise UserDataPortabilityError("prepared import identity mismatch")
            prepared.append((adapter, candidate))

        # Capture every rollback point before mutating the first owner.
        before = {adapter.domain: _snapshot_from(adapter) for adapter, _ in prepared}
        applied: list[DomainAdapter] = []
        try:
            for adapter, candidate in prepared:
                adapter.restore(candidate)
                applied.append(adapter)
                current = _snapshot_from(adapter)
                if (
                    current.schema_version != candidate.schema_version
                    or current.payload != candidate.payload
                ):
                    raise UserDataPortabilityError(
                        f"domain restore readback mismatch: {adapter.domain}"
                    )
        except BaseException as primary:
            rollback_error: BaseException | None = None
            for adapter in reversed(applied):
                try:
                    adapter.restore(before[adapter.domain])
                    current = _snapshot_from(adapter)
                    previous = before[adapter.domain]
                    if (
                        current.schema_version != previous.schema_version
                        or current.payload != previous.payload
                    ):
                        raise UserDataPortabilityError(
                            f"domain rollback readback mismatch: {adapter.domain}"
                        )
                except BaseException as exc:
                    rollback_error = exc
                    break
            if rollback_error is not None:
                raise UserDataPortabilityError(
                    "user-data restore failed and rollback could not re-establish prior state"
                ) from rollback_error
            raise UserDataPortabilityError(
                "user-data restore failed; prior state was restored"
            ) from primary

        return BundleReceipt(
            kind,
            tuple(snapshot.domain for _, snapshot in prepared),
            len(raw),
            _sha256(raw),
        )

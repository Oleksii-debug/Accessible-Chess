from __future__ import annotations

"""Section 54.1 evidence sidecar over the ONE canonical factory intake.

This is not a second BookDocument, importer, metadata extractor or rights
adjudicator. Unverified claims never become evidence of publication rights.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .format_factory_intake import (
    FactoryImportedBook,
    FactorySourceReceipt,
    import_factory_book,
    inspect_factory_source,
)


class FactoryEvidenceError(ValueError):
    """Stable non-disclosing provenance validation failure."""


_CLAIM_FIELDS = frozenset((
    "title", "author", "edition", "language", "publication_year", "publisher",
))
_CLAIM_ORIGINS = frozenset((
    "USER_ASSERTION", "EMBEDDED_METADATA", "EXTERNAL_CATALOG_CLAIM",
))
_RIGHTS_KINDS = frozenset((
    "UNSPECIFIED", "USER_PRIVATE_CONVERSION_CLAIM",
    "LICENSE_REVIEW_REQUIRED", "PUBLIC_DOMAIN_REVIEW_REQUIRED",
))
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _bounded_text(value: object, label: str, *, maximum: int = 1024) -> str:
    if type(value) is not str or not 1 <= len(value) <= maximum:
        raise FactoryEvidenceError(label + " must be bounded text")
    if not value.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise FactoryEvidenceError(label + " contains invalid characters")
    return value


def _source_sha(value: object) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise FactoryEvidenceError("Original source SHA-256 is required")
    return value


@dataclass(frozen=True, slots=True)
class FactoryMetadataClaim:
    field: str
    value: str
    origin: str
    evidence_reference: str
    source_sha256: str
    proof_status: str = "NOT_PROVEN"

    def __post_init__(self) -> None:
        if type(self.field) is not str or self.field not in _CLAIM_FIELDS:
            raise FactoryEvidenceError("Unsupported metadata field")
        _bounded_text(self.value, "Claim value", maximum=4096)
        if type(self.origin) is not str or self.origin not in _CLAIM_ORIGINS:
            raise FactoryEvidenceError("Unsupported claim provenance")
        _bounded_text(self.evidence_reference, "Evidence reference")
        _source_sha(self.source_sha256)
        if self.proof_status != "NOT_PROVEN" or type(self.proof_status) is not str:
            raise FactoryEvidenceError("Unverified metadata cannot be promoted to proven")


@dataclass(frozen=True, slots=True)
class FactoryRightsClaim:
    kind: str = "UNSPECIFIED"
    evidence_reference: str | None = None
    source_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in _RIGHTS_KINDS:
            raise FactoryEvidenceError("Unknown rights claim type")
        if self.kind == "UNSPECIFIED":
            if self.evidence_reference is not None or self.source_sha256 is not None:
                raise FactoryEvidenceError("Unspecified rights cannot carry approval")
        else:
            _bounded_text(self.evidence_reference, "Rights evidence reference")
            _source_sha(self.source_sha256)


@dataclass(frozen=True, slots=True)
class FactoryPageReference:
    file_page: int
    printed_label: str | None
    source_anchor: str
    source_sha256: str
    proof_status: str = "NOT_PROVEN"

    def __post_init__(self) -> None:
        if type(self.file_page) is not int or not 1 <= self.file_page <= 1_000_000:
            raise FactoryEvidenceError("File page must be an explicit positive index")
        if self.printed_label is not None:
            _bounded_text(self.printed_label, "Printed page label", maximum=128)
        _bounded_text(self.source_anchor, "Page source anchor")
        _source_sha(self.source_sha256)
        if self.proof_status != "NOT_PROVEN" or type(self.proof_status) is not str:
            raise FactoryEvidenceError("Unverified page mapping cannot be promoted to proven")


@dataclass(frozen=True, slots=True)
class FactorySourceEvidence:
    receipt: FactorySourceReceipt
    claims: tuple[FactoryMetadataClaim, ...]
    rights: FactoryRightsClaim
    pages: tuple[FactoryPageReference, ...]
    schema_version: int = 1

    @property
    def publication_approved(self) -> bool:
        # A user assertion, purported license URL, or catalog title does not
        # independently establish the legal right to redistribute a whole book.
        return False

    @property
    def unresolved(self) -> tuple[str, ...]:
        issues = ["RIGHTS_NOT_INDEPENDENTLY_VERIFIED", "EDITION_NOT_SOURCE_VERIFIED"]
        if not self.pages:
            issues.append("PRINTED_TO_FILE_PAGE_MAPPING_NOT_PROVEN")
        elif any(page.proof_status == "NOT_PROVEN" for page in self.pages):
            issues.append("PAGE_MAPPING_NOT_PROVEN")
        if self.receipt.import_status != "SUPPORTED_BOOK_INGRESS":
            issues.append("SOURCE_FORMAT_NOT_FULLY_QUALIFIED")
        return tuple(issues)

    def snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_sha256": self.receipt.sha256,
            "source_byte_count": self.receipt.byte_count,
            "detected_format": self.receipt.detected_format,
            "import_status": self.receipt.import_status,
            "claims": [
                {"field": x.field, "value": x.value, "origin": x.origin,
                 "reference": x.evidence_reference, "source_sha256": x.source_sha256,
                 "proof_status": x.proof_status}
                for x in self.claims
            ],
            "rights": {
                "kind": self.rights.kind, "reference": self.rights.evidence_reference,
                "source_sha256": self.rights.source_sha256,
                "publication_approved": False,
            },
            "pages": [
                {"file_page": x.file_page, "printed_label": x.printed_label,
                 "source_anchor": x.source_anchor, "source_sha256": x.source_sha256,
                 "proof_status": x.proof_status}
                for x in self.pages
            ],
            "unresolved": list(self.unresolved),
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.snapshot(), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return sha256(raw).hexdigest()


def inspect_factory_source_evidence(
    source: bytes, *, source_name: str,
    claims: tuple[FactoryMetadataClaim, ...] = (),
    rights: FactoryRightsClaim | None = None,
    pages: tuple[FactoryPageReference, ...] = (),
) -> FactorySourceEvidence:
    """Tie voluntary claims to original bytes; never infer license or pages."""
    receipt = inspect_factory_source(source, source_name=source_name)
    if type(claims) is not tuple or len(claims) > len(_CLAIM_FIELDS):
        raise FactoryEvidenceError("Metadata claims must be bounded and immutable")
    if type(pages) is not tuple or len(pages) > 100_000:
        raise FactoryEvidenceError("Page mappings must be bounded and immutable")
    if rights is None:
        rights = FactoryRightsClaim()
    if type(rights) is not FactoryRightsClaim:
        raise FactoryEvidenceError("Rights claim must be explicitly typed")
    seen_fields: set[str] = set()
    for claim in claims:
        if type(claim) is not FactoryMetadataClaim or claim.source_sha256 != receipt.sha256:
            raise FactoryEvidenceError("Metadata claim is not tied to original source")
        if claim.field in seen_fields:
            raise FactoryEvidenceError("Duplicate metadata claim")
        seen_fields.add(claim.field)
    if rights.source_sha256 is not None and rights.source_sha256 != receipt.sha256:
        raise FactoryEvidenceError("Rights declaration does not match original source")
    seen_pages: set[int] = set()
    for page in pages:
        if type(page) is not FactoryPageReference or page.source_sha256 != receipt.sha256:
            raise FactoryEvidenceError("Page reference does not match original source")
        if page.file_page in seen_pages:
            raise FactoryEvidenceError("Conflicting file-page references")
        seen_pages.add(page.file_page)
    return FactorySourceEvidence(receipt, claims, rights, pages)


def import_factory_book_with_evidence(
    source: bytes, *, source_name: str,
    claims: tuple[FactoryMetadataClaim, ...] = (),
    rights: FactoryRightsClaim | None = None,
    pages: tuple[FactoryPageReference, ...] = (),
) -> tuple[FactoryImportedBook, FactorySourceEvidence]:
    """Compose the existing canonical import; no alternative parsing or schema."""
    evidence = inspect_factory_source_evidence(
        source, source_name=source_name, claims=claims, rights=rights, pages=pages,
    )
    imported = import_factory_book(source, source_name=source_name)
    if imported.source.sha256 != evidence.receipt.sha256:
        raise FactoryEvidenceError("Canonical import source identity disagrees")
    return imported, evidence

from __future__ import annotations

"""Section 54.1 source-bound, non-authorizing evidence tests."""

from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
import unittest

from acs.format_factory_source_evidence import (
    FactoryEvidenceError,
    FactoryMetadataClaim,
    FactoryPageReference,
    FactoryRightsClaim,
    import_factory_book_with_evidence,
    inspect_factory_source_evidence,
)


_SOURCE = b"# Simple chess chapter\nA quiet test page.\n"
_SHA = sha256(_SOURCE).hexdigest()
_OTHER_SHA = sha256(b"unrelated different book").hexdigest()


class FactoryEvidenceTests(unittest.TestCase):
    def test_unqualified_rights_and_edition_remain_explicitly_unproven(self) -> None:
        evidence = inspect_factory_source_evidence(_SOURCE, source_name="book.md")
        self.assertEqual(evidence.receipt.sha256, _SHA)
        self.assertEqual(evidence.receipt.import_status, "SUPPORTED_BOOK_INGRESS")
        self.assertEqual(evidence.rights.kind, "UNSPECIFIED")
        self.assertFalse(evidence.publication_approved)
        self.assertIn("RIGHTS_NOT_INDEPENDENTLY_VERIFIED", evidence.unresolved)
        self.assertIn("PRINTED_TO_FILE_PAGE_MAPPING_NOT_PROVEN", evidence.unresolved)
        self.assertNotIn("author", evidence.snapshot())

    def test_valid_claims_are_attached_but_not_promoted(self) -> None:
        claim = FactoryMetadataClaim(
            "edition", "Second edition", "USER_ASSERTION", "user-entry:1", _SHA
        )
        rights = FactoryRightsClaim(
            "USER_PRIVATE_CONVERSION_CLAIM", "owner-signed-local-record:1", _SHA
        )
        page = FactoryPageReference(1, "xv", "page-file:1", _SHA)
        evidence = inspect_factory_source_evidence(
            _SOURCE, source_name="book.md",
            claims=(claim,), rights=rights, pages=(page,),
        )
        s = evidence.snapshot()
        self.assertEqual(s["claims"][0]["proof_status"], "NOT_PROVEN")
        self.assertEqual(s["pages"][0]["printed_label"], "xv")
        self.assertEqual(s["rights"]["publication_approved"], False)
        self.assertIn("PAGE_MAPPING_NOT_PROVEN", s["unresolved"])
        self.assertNotIn("PRINTED_TO_FILE_PAGE_MAPPING_NOT_PROVEN", s["unresolved"])
        self.assertFalse(evidence.publication_approved)
        self.assertEqual(len(evidence.fingerprint()), 64)
        self.assertEqual(evidence.fingerprint(), evidence.fingerprint())
        self.assertEqual(s, json.loads(json.dumps(s, ensure_ascii=False)))

    def test_import_reuses_canonical_bookdocument_and_source_receipt(self) -> None:
        imported, evidence = import_factory_book_with_evidence(
            _SOURCE, source_name="book.md"
        )
        from acs.bookdocument import BookDocument
        self.assertIsInstance(imported.document, BookDocument)
        self.assertEqual(imported.source.sha256, evidence.receipt.sha256)
        self.assertEqual(imported.importer, "acs.book_text_import")
        self.assertFalse(evidence.publication_approved)

    def test_claim_for_other_source_rejected_without_reading_private_text(self) -> None:
        claim = FactoryMetadataClaim(
            "title", "Private title", "EMBEDDED_METADATA", "opfpkg:1", _OTHER_SHA
        )
        with self.assertRaisesRegex(
            FactoryEvidenceError, "not tied to original source"
        ) as caught:
            inspect_factory_source_evidence(
                _SOURCE, source_name="book.md", claims=(claim,)
            )
        self.assertNotIn("Private title", str(caught.exception))

    def test_duplicate_metadata_or_page_index_refused(self) -> None:
        c = FactoryMetadataClaim(
            "title", "Chess", "USER_ASSERTION", "user:1", _SHA
        )
        page = FactoryPageReference(1, "1", "filepage:1", _SHA)
        for claims, pages in (((c, c), ()), ((), (page, page))):
            with self.subTest(claims=len(claims), pages=len(pages)):
                with self.assertRaises(FactoryEvidenceError):
                    inspect_factory_source_evidence(
                        _SOURCE, source_name="book.md", claims=claims, pages=pages
                    )

    def test_rights_attestation_cannot_be_reused_for_other_book(self) -> None:
        rights = FactoryRightsClaim(
            "LICENSE_REVIEW_REQUIRED", "license-record:2", _OTHER_SHA
        )
        with self.assertRaises(FactoryEvidenceError):
            inspect_factory_source_evidence(
                _SOURCE, source_name="book.md", rights=rights
            )

    def test_invalid_rights_claim_and_fake_approval_rejected(self) -> None:
        with self.assertRaises(FactoryEvidenceError):
            FactoryRightsClaim("UNSPECIFIED", "license=granted", _SHA)
        with self.assertRaises(FactoryEvidenceError):
            FactoryRightsClaim("LICENSE_REVIEW_REQUIRED", "", _SHA)
        with self.assertRaises(FactoryEvidenceError):
            FactoryRightsClaim("PUBLIC_RELEASE_APPROVED", "lic:1", _SHA)
        with self.assertRaises(FactoryEvidenceError):
            FactoryMetadataClaim(
                "edition", "2026", "USER_ASSERTION", "user:1",
                _SHA, proof_status="PROVEN"
            )
        with self.assertRaises(FactoryEvidenceError):
            FactoryPageReference(1, "1", "page:1", _SHA, proof_status="PROVEN")

    def test_malformed_claims_pages_and_digest_fail_closed(self) -> None:
        with self.assertRaises(FactoryEvidenceError):
            FactoryMetadataClaim("title", "Text", "USER_ASSERTION", "user", "0" * 63)
        with self.assertRaises(FactoryEvidenceError):
            FactoryMetadataClaim("unknown", "Text", "USER_ASSERTION", "user", _SHA)
        with self.assertRaises(FactoryEvidenceError):
            FactoryMetadataClaim("title", "Bad\nInjected", "USER_ASSERTION", "user", _SHA)
        with self.assertRaises(FactoryEvidenceError):
            FactoryPageReference(True, "1", "page:1", _SHA)
        with self.assertRaises(FactoryEvidenceError):
            FactoryPageReference(1, "1", "page:1", _OTHER_SHA)
        with self.assertRaises(FactoryEvidenceError):
            inspect_factory_source_evidence(
                _SOURCE, source_name="book.md", claims=[ ]
            )

    def test_frozen_records_prevent_accidental_mutation(self) -> None:
        rights = FactoryRightsClaim()
        with self.assertRaises(FrozenInstanceError):
            rights.kind = "LICENSE_REVIEW_REQUIRED"

    def test_partial_docx_or_unsupported_file_does_not_gain_publication_rights(self) -> None:
        evidence = inspect_factory_source_evidence(
            b"%PDF-1.7\n", source_name="scan.pdf"
        )
        self.assertEqual(evidence.receipt.import_status, "PARTIAL")
        self.assertIn("SOURCE_FORMAT_NOT_FULLY_QUALIFIED", evidence.unresolved)
        self.assertFalse(evidence.publication_approved)
        with self.assertRaises(ValueError):
            import_factory_book_with_evidence(b"%PDF-1.7\n", source_name="scan.pdf")


if __name__ == "__main__":
    unittest.main()

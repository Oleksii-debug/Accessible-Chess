"""Section39: original-source chess DOCX interoperability cannot impersonate upstream original."""
from __future__ import annotations
import unittest
from unittest.mock import patch
from acs.lawful_corpus_registry import LawfulCorpusError
from tools import section39_real_chess_docx_interoperability as qa

class GenuineChessProseDocxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proof = qa.qualify_source_derived_docx()

    def test_real_chess_prose_is_reopened_in_actual_docx_books_adapter(self):
        proof = self.proof
        self.assertEqual(proof["original_format"], "TXT")
        self.assertEqual(proof["derived_format"], "DOCX")
        self.assertEqual(proof["original_txt_bytes"], 262824)
        self.assertEqual(proof["actual_original_chess_paragraphs"], 32)
        self.assertEqual(proof["actual_semantic_blocks"], 33)
        self.assertTrue(proof["genuine_original_text"])
        self.assertFalse(proof["independent_upstream_docx"])
        self.assertFalse(proof["mocked"])
        self.assertEqual(proof["read"], "PASS")
        self.assertEqual(proof["write"], "UNSUPPORTED")
        self.assertEqual(proof["roundtrip"], "UNSUPPORTED")
        self.assertTrue(proof["qualification"].startswith("PARTIAL_"))
        self.assertFalse(proof["section39_terminal_done"])

    def test_damaged_actual_original_text_is_rejected_without_docx_publication(self):
        original = qa.read_verified_source_snapshot
        def bad(path, record):
            return original(path, record)[:-1]
        with patch.object(qa, "read_verified_source_snapshot", side_effect=bad):
            with self.assertRaisesRegex(LawfulCorpusError, "bytes mismatch"):
                qa.qualify_source_derived_docx()

    def test_source_nonredistribution_cannot_be_overridden_by_generated_docx(self):
        origin = qa.load_catalog
        with patch.object(qa, "load_catalog", return_value=tuple(
            {**r, "redistribution": "permitted"}
            if r["id"] == qa.ID else r for r in origin()
        )):
            with self.assertRaisesRegex(LawfulCorpusError, "rights/provenance"):
                qa.qualify_source_derived_docx()

if __name__ == "__main__":
    unittest.main()

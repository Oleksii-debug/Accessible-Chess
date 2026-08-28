from __future__ import annotations

import json
from pathlib import Path
import unittest


class CbfCbiRealCorpusUnblockQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.manifest_path = (
            cls.root / "docs" / "automation" / "V2_CBF_CBI_REAL_CORPUS_UNBLOCK.json"
        )
        cls.payload = json.loads(cls.manifest_path.read_text(encoding="utf-8"))

    def test_status_remains_blocked_until_every_promotion_requirement_is_true(self) -> None:
        self.assertEqual(self.payload["format_status"], "BLOCKED")
        self.assertFalse(self.payload["support_promotion_allowed"])
        requirements = self.payload["promotion_requirements"]
        self.assertTrue(requirements)
        self.assertIn(False, requirements.values())
        self.assertFalse(all(requirements.values()))

    def test_pitt_candidate_is_not_misrepresented_as_inspected_or_licensed(self) -> None:
        candidate = self.payload["candidate_corpus"]
        self.assertEqual(candidate["chessbase_archive_name"], "95DORTCB.ZIP")
        self.assertEqual(candidate["pgn_archive_name"], "95DORTPG.ZIP")
        self.assertTrue(candidate["same_event_distribution_record"])
        self.assertTrue(candidate["independent_pgn_counterpart_advertised"])
        self.assertFalse(candidate["actual_archive_bytes_inspected"])
        self.assertFalse(candidate["specific_archive_contains_cbf_cbi_confirmed"])
        self.assertFalse(candidate["explicit_modern_redistribution_license_found"])
        self.assertFalse(candidate["ci_reuse_rights_proven"])
        self.assertFalse(candidate["semantic_equivalence_executed"])

    def test_scidb_source_contract_is_pinned_and_read_only(self) -> None:
        scidb = self.payload["decoder_chain"]["scidb"]
        self.assertEqual(scidb["repository"], "foolnotion/scidb")
        self.assertEqual(
            scidb["commit"],
            "7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415",
        )
        self.assertEqual(
            scidb["cbh2si4_source_blob"],
            "1830d059b987e3b9d4b97803d92f33936a69ace1",
        )
        self.assertEqual(
            scidb["cbf_codec_source_blob"],
            "c9608dc93e704070c5ec7f8294d09e6c52374b53",
        )
        self.assertTrue(scidb["cli_source_accepts_cbf"])
        self.assertEqual(scidb["source_database_open_mode"], "ReadOnly")
        self.assertEqual(scidb["output_format"], "SI4")

    def test_scidpgn_source_contract_is_pinned_readonly_and_loss_aware(self) -> None:
        exporter = self.payload["decoder_chain"]["scid_pgn_export"]
        self.assertEqual(exporter["repository"], "lpt/scid")
        self.assertEqual(
            exporter["commit"],
            "5837653efa3975c64cff232006d9f981b36ac56b",
        )
        self.assertEqual(
            exporter["scidpgn_blob"],
            "84273490e8ee6b47bc78ca26a274ab559845e7b5",
        )
        self.assertTrue(exporter["source_opens_database_readonly"])
        self.assertTrue(exporter["source_exports_tags_comments_variations"])

    def test_no_custom_cbf_parser_or_false_support_claim_is_added(self) -> None:
        chain = self.payload["decoder_chain"]
        self.assertFalse(chain["accessible_chess_custom_cbf_parser_added"])
        rendered = json.dumps(self.payload, sort_keys=True).casefold()
        self.assertNotIn('"format_status": "supported"', rendered)
        self.assertNotIn('"format_status": "partial"', rendered)


if __name__ == "__main__":
    unittest.main()

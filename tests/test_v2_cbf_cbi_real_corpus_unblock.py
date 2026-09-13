from __future__ import annotations

import json
from pathlib import Path
import unittest


class CbfCbiRealCorpusUnblockQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.manifest_path = cls.root / "docs" / "automation" / "V2_CBF_CBI_REAL_CORPUS_UNBLOCK.json"
        cls.payload = json.loads(cls.manifest_path.read_text(encoding="utf-8"))

    def test_status_remains_blocked_until_every_acceptance_condition_is_true(self) -> None:
        self.assertEqual(self.payload["schema_version"], 2)
        self.assertEqual(self.payload["format_status"], "BLOCKED")
        self.assertFalse(self.payload["support_promotion_allowed"])
        requirements = self.payload["required_acceptance_conditions"]
        self.assertEqual(len(requirements), 9)
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

    def test_reader_sources_are_exactly_pinned_and_read_only(self) -> None:
        scidb = self.payload["reader_chain"]["scidb"]
        self.assertEqual(scidb["repository"], "foolnotion/scidb")
        self.assertEqual(scidb["commit"], "7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415")
        self.assertEqual(scidb["cbh2si4_source_blob"], "1830d059b987e3b9d4b97803d92f33936a69ace1")
        self.assertEqual(scidb["cbf_codec_source_blob"], "c9608dc93e704070c5ec7f8294d09e6c52374b53")
        self.assertEqual(scidb["source_database_open_mode"], "ReadOnly")
        self.assertTrue(scidb["cli_accepts_cbf"])

        exporter = self.payload["reader_chain"]["scid_pgn_export"]
        self.assertEqual(exporter["repository"], "lpt/scid")
        self.assertEqual(exporter["commit"], "5837653efa3975c64cff232006d9f981b36ac56b")
        self.assertEqual(exporter["scidpgn_blob"], "84273490e8ee6b47bc78ca26a274ab559845e7b5")
        self.assertTrue(exporter["source_opens_database_readonly"])
        self.assertTrue(exporter["source_exports_tags_comments_variations"])

    def test_product_unblock_closes_execution_validation_and_atomicity_seams(self) -> None:
        product = self.payload["reader_chain"]["accessible_chess"]
        requirements = self.payload["required_acceptance_conditions"]
        self.assertFalse(product["custom_cbf_binary_parser_added"])
        self.assertFalse(product["registered_as_user_facing_importer"])
        self.assertTrue(product["binary_sha256_pin_required"])
        self.assertFalse(product["shell_execution"])
        self.assertTrue(product["source_integrity_before_after"])
        self.assertTrue(product["process_timeout_bounded"])
        self.assertTrue(product["stdout_stderr_bounded"])
        self.assertTrue(product["private_temp_bytes_bounded"])
        self.assertTrue(requirements["bounded_execution"])
        self.assertTrue(requirements["canonical_pgn_gametree_validation"])
        self.assertTrue(requirements["atomic_acsdb_import"])
        self.assertTrue(requirements["export_reopen_comparison"])

    def test_support_stays_blocked_on_external_evidence_not_product_seam(self) -> None:
        requirements = self.payload["required_acceptance_conditions"]
        self.assertFalse(requirements["authentic_real_cbf_cbi_family"])
        self.assertFalse(requirements["legal_automated_use_provenance"])
        self.assertFalse(requirements["independent_pgn_or_gametree_oracle"])
        rendered = json.dumps(self.payload, sort_keys=True).casefold()
        self.assertNotIn('"format_status": "supported"', rendered)
        self.assertNotIn('"format_status": "partial"', rendered)


if __name__ == "__main__":
    unittest.main()

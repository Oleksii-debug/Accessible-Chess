"""CBH real-oracle receipt must not turn skipped or fake tests into PASS."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from acs.lawful_corpus_registry import LawfulCorpusError
from tools.section39_real_cbh_oracle_receipt import (
    CASES, build_cbh_real_receipt,
)


class CbhOriginalOracleGateTests(unittest.TestCase):
    def test_real_families_have_independent_annotations_rav_and_unusual_boundaries(self):
        self.assertEqual(len(CASES), 3)
        self.assertEqual([item[3] for item in CASES], ["PASS", "PASS", "PARTIAL"])
        self.assertEqual(len({item[0] for item in CASES}), 3)
        self.assertTrue(all(item[1].startswith("LIBCBH_") for item in CASES))

    def test_unavailable_original_backend_never_produces_receipt(self):
        with patch("tools.section39_real_cbh_oracle_receipt._environment_ready",
                   return_value=False):
            with self.assertRaisesRegex(LawfulCorpusError, "actual pinned CBH bridge"):
                build_cbh_real_receipt()

    def test_skipped_tests_cannot_be_counted_as_completed_original_qualification(self):
        simulated = MagicMock()
        simulated.testsRun = 3
        simulated.wasSuccessful.return_value = True
        simulated.skipped = [(object(), "no real fixture")]
        simulated.expectedFailures = []
        simulated.unexpectedSuccesses = []
        with patch("tools.section39_real_cbh_oracle_receipt._environment_ready",
                   return_value=True):
            with patch("tools.section39_real_cbh_oracle_receipt.unittest.TextTestRunner") as runner:
                runner.return_value.run.return_value = simulated
                with self.assertRaisesRegex(LawfulCorpusError, "all execute and pass"):
                    build_cbh_real_receipt()


if __name__ == "__main__":
    unittest.main()

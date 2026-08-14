import unittest

from acs.chessbase_adapter import (
    probe_chessbase_source,
    probe_many,
    recognized_extensions,
)


class ChessBaseAdapterContractTests(unittest.TestCase):
    def test_known_family_suffixes_are_recognized_but_not_claimed_supported(self):
        for suffix in (".cbh", ".cbv", ".cbf", ".2cbh", ".cbone"):
            with self.subTest(suffix=suffix):
                probe = probe_chessbase_source("sample" + suffix)
                self.assertTrue(probe.recognized)
                self.assertTrue(probe.read_only)
                self.assertFalse(probe.decoder_available)
                self.assertFalse(probe.safe_to_import)
                self.assertEqual(probe.status, "adapter_only")
                self.assertTrue(probe.warnings)

    def test_unknown_suffix_is_explicitly_not_importable(self):
        probe = probe_chessbase_source("sample.zip")
        self.assertFalse(probe.recognized)
        self.assertFalse(probe.safe_to_import)
        self.assertEqual(probe.family_name, "unknown")
        self.assertIn("Unrecognized", probe.warnings[0])

    def test_probe_preserves_source_path_for_provenance(self):
        probe = probe_chessbase_source("incoming/Training Database.CBH")
        report = probe.as_report_fields()
        self.assertEqual(report["source_path"], "incoming/Training Database.CBH")
        self.assertEqual(report["extension"], ".cbh")
        self.assertTrue(report["read_only"])
        self.assertFalse(report["safe_to_import"])

    def test_batch_probe_never_silently_drops_unknown_records(self):
        probes = probe_many(["a.cbh", "b.unknown", "c.cbv"])
        self.assertEqual(len(probes), 3)
        self.assertEqual([item.recognized for item in probes], [True, False, True])

    def test_recognized_extension_list_is_stable_and_sorted(self):
        extensions = recognized_extensions()
        self.assertEqual(extensions, tuple(sorted(extensions)))
        self.assertEqual(set(extensions), {".2cbh", ".cbf", ".cbh", ".cbone", ".cbv"})


if __name__ == "__main__":
    unittest.main()

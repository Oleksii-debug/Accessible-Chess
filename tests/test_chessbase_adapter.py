import tempfile
import unittest
from pathlib import Path

from acs.chessbase_adapter import (
    component_extensions,
    primary_extensions,
    probe_chessbase_source,
    probe_many,
    recognized_extensions,
)


class ChessBaseAdapterContractTests(unittest.TestCase):
    def test_known_primary_family_suffixes_are_recognized_but_not_claimed_supported(self):
        for suffix in (".cbh", ".cbv", ".cbf", ".2cbh", ".cbone"):
            with self.subTest(suffix=suffix):
                probe = probe_chessbase_source("sample" + suffix)
                self.assertTrue(probe.recognized)
                self.assertTrue(probe.is_primary_source)
                self.assertTrue(probe.read_only)
                self.assertFalse(probe.decoder_available)
                self.assertFalse(probe.safe_to_import)
                self.assertEqual(probe.status, "adapter_only")
                self.assertTrue(probe.warnings)

    def test_classic_components_are_recognized_but_never_treated_as_standalone_imports(self):
        for suffix in (".cbg", ".cba", ".cbp", ".cbt", ".cbc", ".cbs"):
            with self.subTest(suffix=suffix):
                probe = probe_chessbase_source("sample" + suffix)
                self.assertTrue(probe.recognized)
                self.assertFalse(probe.is_primary_source)
                self.assertEqual(probe.source_kind, "component")
                self.assertFalse(probe.safe_to_import)

    def test_cbh_probe_discovers_same_stem_companions_case_insensitively(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cbh = root / "My Base.CBH"
            cbh.write_bytes(b"header")
            (root / "My Base.CBG").write_bytes(b"moves")
            (root / "my base.CBP").write_bytes(b"players")
            (root / "Other Base.CBG").write_bytes(b"not-this-db")

            probe = probe_chessbase_source(cbh)
            existing = {item.extension: item for item in probe.existing_components}
            self.assertEqual(set(existing), {".cbg", ".cbp"})
            self.assertEqual(existing[".cbg"].path.name, "My Base.CBG")
            self.assertEqual(existing[".cbp"].path.name, "my base.CBP")
            self.assertFalse(probe.safe_to_import)

    def test_cbv_is_distinguished_from_cbh_component_family(self):
        probe = probe_chessbase_source("archive.cbv")
        self.assertEqual(probe.source_kind, "archive_container")
        self.assertEqual(probe.components, ())
        self.assertTrue(any("archive/container" in warning for warning in probe.warnings))

    def test_batch_probe_never_silently_drops_unknown_or_component_records(self):
        probes = probe_many(["a.cbh", "b.unknown", "c.cbv", "d.cbg"])
        self.assertEqual(len(probes), 4)
        self.assertEqual([item.recognized for item in probes], [True, False, True, True])
        self.assertEqual([item.is_primary_source for item in probes], [True, False, True, False])

    def test_extension_sets_remain_separate(self):
        primaries = set(primary_extensions())
        components = set(component_extensions())
        self.assertFalse(primaries & components)
        self.assertEqual(set(recognized_extensions()), primaries | components)


if __name__ == "__main__":
    unittest.main()

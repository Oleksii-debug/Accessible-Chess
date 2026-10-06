import os
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
        for suffix in (".cbh", ".cbv", ".cbz", ".cbf", ".2cbh", ".2cbz", ".cbone"):
            with self.subTest(suffix=suffix):
                probe = probe_chessbase_source("sample" + suffix)
                self.assertTrue(probe.recognized)
                self.assertTrue(probe.is_primary_source)
                self.assertTrue(probe.read_only)
                self.assertFalse(probe.decoder_available)
                self.assertFalse(probe.safe_to_import)
                self.assertEqual(probe.status, "adapter_only")
                self.assertTrue(probe.warnings)

    def test_known_component_suffixes_are_never_standalone_imports(self):
        for suffix in (".cbg", ".cba", ".cbp", ".cbt", ".cbc", ".cbs", ".cbi"):
            with self.subTest(suffix=suffix):
                probe = probe_chessbase_source("sample" + suffix)
                self.assertTrue(probe.recognized)
                self.assertFalse(probe.is_primary_source)
                self.assertEqual(probe.source_kind, "component")
                self.assertFalse(probe.safe_to_import)
                self.assertIn("component file only", probe.warnings[0])

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
        self.assertEqual(report["source_kind"], "component_set")
        self.assertTrue(report["read_only"])
        self.assertFalse(report["safe_to_import"])

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
            self.assertTrue(
                any(
                    ".cbg" in warning and ".cbp" in warning
                    for warning in probe.warnings
                )
            )
            self.assertFalse(probe.safe_to_import)

    def test_cbh_missing_companions_is_reported_without_guessing_damage(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "lonely.cbh"
            path.write_bytes(b"header")
            probe = probe_chessbase_source(path)
            self.assertEqual(probe.existing_components, ())
            self.assertTrue(
                any(
                    "No classic CBH companion files" in warning
                    for warning in probe.warnings
                )
            )
            self.assertEqual(
                {item.extension for item in probe.components},
                {".cba", ".cbg", ".cbp", ".cbs", ".cbt", ".cbc"},
            )

    def test_cbf_probe_models_same_stem_cbi_as_one_legacy_family(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cbf = root / "Legacy Base.CBF"
            cbi = root / "legacy base.cBi"
            cbf.write_bytes(b"games")
            cbi.write_bytes(b"index")
            (root / "Other Base.cbi").write_bytes(b"wrong index")

            probe = probe_chessbase_source(cbf)

            self.assertEqual(probe.source_kind, "legacy_two_file_database")
            self.assertEqual(len(probe.components), 1)
            self.assertEqual(probe.components[0].extension, ".cbi")
            self.assertTrue(probe.components[0].exists)
            self.assertEqual(probe.components[0].path, cbi)
            self.assertTrue(
                any("CBF/CBI pair detected" in warning for warning in probe.warnings)
            )
            self.assertFalse(probe.decoder_available)
            self.assertFalse(probe.safe_to_import)

    def test_cbf_missing_same_stem_cbi_is_explicit_incomplete_topology(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cbf = root / "Legacy.cbf"
            cbf.write_bytes(b"games")
            (root / "Other.cbi").write_bytes(b"not this database")

            probe = probe_chessbase_source(cbf)

            self.assertEqual(len(probe.components), 1)
            self.assertFalse(probe.components[0].exists)
            self.assertTrue(
                any("incomplete" in warning.casefold() for warning in probe.warnings)
            )
            self.assertFalse(probe.safe_to_import)

    def test_case_colliding_companion_names_fail_closed_where_filesystem_allows_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cbf = root / "Legacy.cbf"
            cbf.write_bytes(b"games")
            first = root / "Legacy.CBI"
            second = root / "legacy.cbi"
            first.write_bytes(b"index-a")
            second.write_bytes(b"index-b")

            try:
                same = os.path.samefile(first, second)
            except OSError:
                same = False
            if same:
                self.skipTest("filesystem is case-insensitive")

            probe = probe_chessbase_source(cbf)
            self.assertEqual(probe.components, ())
            self.assertTrue(
                any(
                    "case-colliding" in warning.casefold()
                    for warning in probe.warnings
                )
            )
            self.assertFalse(probe.safe_to_import)

    def test_cbv_is_distinguished_from_cbh_component_family(self):
        probe = probe_chessbase_source("archive.cbv")
        self.assertEqual(probe.source_kind, "archive_container")
        self.assertEqual(probe.components, ())
        self.assertTrue(
            any("archive/container" in warning for warning in probe.warnings)
        )

    def test_batch_probe_never_silently_drops_unknown_or_component_records(self):
        probes = probe_many(
            ["a.cbh", "b.unknown", "c.cbv", "d.cbg", "e.cbf", "e.cbi"]
        )
        self.assertEqual(len(probes), 6)
        self.assertEqual(
            [item.recognized for item in probes],
            [True, False, True, True, True, True],
        )
        self.assertEqual(
            [item.is_primary_source for item in probes],
            [True, False, True, False, True, False],
        )

    def test_extension_lists_are_stable_sorted_and_separate_primary_from_components(self):
        primaries = primary_extensions()
        components = component_extensions()
        extensions = recognized_extensions()
        self.assertEqual(primaries, tuple(sorted(primaries)))
        self.assertEqual(components, tuple(sorted(components)))
        self.assertEqual(extensions, tuple(sorted(extensions)))
        self.assertEqual(
            set(primaries),
            {".2cbh", ".2cbz", ".cbf", ".cbh", ".cbone", ".cbv", ".cbz"},
        )
        self.assertEqual(
            set(components),
            {".cba", ".cbg", ".cbp", ".cbs", ".cbt", ".cbc", ".cbi"},
        )
        self.assertEqual(set(extensions), set(primaries) | set(components))


if __name__ == "__main__":
    unittest.main()

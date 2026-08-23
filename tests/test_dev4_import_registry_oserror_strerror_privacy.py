from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.import_registry import ImportRegistry


class _OSErrorImporter:
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path):
        private_sidecar = r"C:\Users\PrivateUser\Documents\decoder-cache.bin"
        raise OSError(5, f"decoder failed while reading {private_sidecar}", str(path))


class Dev4ImportRegistryOSErrorStrerrorPrivacyTests(unittest.TestCase):
    def test_batch_oserror_strerror_must_not_republish_private_sidecar_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Users" / "PrivateUser" / "Documents" / "analysis.pgn"
            source.parent.mkdir(parents=True)
            source.write_text('[Event "Privacy"]\n[Result "*"]\n\n*\n', encoding="utf-8")

            registry = ImportRegistry()
            registry.register(_OSErrorImporter())
            batch = registry.inspect_batch((source,))

            self.assertEqual(len(batch.items), 1)
            error = batch.items[0].error
            self.assertTrue(error)
            self.assertIn("analysis.pgn", error)
            self.assertNotIn("PrivateUser", error)
            self.assertNotIn("Documents", error)
            self.assertNotIn("Users", error)
            self.assertNotIn("decoder-cache.bin", error)
            self.assertNotIn(r"C:\Users", error)


if __name__ == "__main__":
    unittest.main()

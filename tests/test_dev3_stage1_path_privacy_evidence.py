from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.gametree import parse_games
from acs.import_contract import ImportReport, SourceFingerprint, fingerprint
from acs.import_registry import ImportRegistry, SourceProvenanceError
from acs.pgn_service import save_pgn_atomic


class _WrongProvenanceImporter:
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        source = fingerprint(path)
        forged = SourceFingerprint(
            path=str(path.parent / "other.pgn"),
            size=source.size,
            sha256=source.sha256,
            suffix=source.suffix,
        )
        return ImportReport(source=forged, format_name=self.format_name)


class Stage1PathPrivacyEvidenceTests(unittest.TestCase):
    def test_existing_destination_error_does_not_expose_private_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            private_dir = Path(root) / "Users" / "PrivateUser" / "Documents"
            private_dir.mkdir(parents=True)
            destination = private_dir / "analysis.pgn"
            destination.write_text("[Event \"Existing\"]\n\n*\n", encoding="utf-8")
            games = parse_games("[Event \"New\"]\n\n*\n")

            with self.assertRaises(FileExistsError) as ctx:
                save_pgn_atomic(destination, games, overwrite=False)

            message = str(ctx.exception)
            self.assertIn("analysis.pgn", message)
            self.assertNotIn("PrivateUser", message)
            self.assertNotIn("Documents", message)
            self.assertNotIn(str(private_dir), message)

    def test_import_registry_provenance_error_does_not_expose_private_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            private_dir = Path(root) / "Users" / "PrivateUser" / "Documents"
            private_dir.mkdir(parents=True)
            source = private_dir / "analysis.pgn"
            source.write_text("[Event \"Source\"]\n\n*\n", encoding="utf-8")

            registry = ImportRegistry()
            registry.register(_WrongProvenanceImporter())
            with self.assertRaises(SourceProvenanceError) as ctx:
                registry.inspect(source)

            message = str(ctx.exception)
            self.assertIn("analysis.pgn", message)
            self.assertNotIn("PrivateUser", message)
            self.assertNotIn("Documents", message)
            self.assertNotIn(str(private_dir), message)

            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.items), 1)
            self.assertFalse(batch.items[0].ok)
            self.assertIn("analysis.pgn", batch.items[0].error)
            self.assertNotIn("PrivateUser", batch.items[0].error)
            self.assertNotIn("Documents", batch.items[0].error)
            self.assertNotIn(str(private_dir), batch.items[0].error)


if __name__ == "__main__":
    unittest.main()

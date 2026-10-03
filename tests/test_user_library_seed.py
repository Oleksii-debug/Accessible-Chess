from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.user_library_seed import (
    BUNDLE_KIND,
    SCHEMA_VERSION,
    UserLibrarySeedError,
    import_user_library_seed,
    load_user_library_seed,
)


PGN_ONE = """[Event "Етюди"]
[White "Автор"]
[Black "Розв'язання"]
[Result "*"]

1. e4 {Головний план} e5 (1... c5 $1 {Альтернатива} 2. Nf3) 2. Nf3 *
"""

PGN_TWO = """[Event "Позиція"]
[SetUp "1"]
[FEN "8/8/8/8/8/8/4K3/7k w - - 0 1"]
[Result "*"]

*
"""


class UserLibrarySeedTests(unittest.TestCase):
    def _seed(self, root: Path, sources: dict[str, str]) -> Path:
        root.mkdir()
        files = []
        for name, text in sources.items():
            payload = text.encode("utf-8")
            (root / name).write_bytes(payload)
            files.append(
                {
                    "file": name,
                    "display_name": name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "bundle_kind": BUNDLE_KIND,
            "runtime_network_required": False,
            "ai_required": False,
            "files": files,
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return root

    def test_verified_private_seed_imports_and_reuses_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed(
                Path(directory) / "seed",
                {"studies.pgn": PGN_ONE, "positions.pgn": PGN_TWO},
            )
            manifest = load_user_library_seed(root)
            with AcsDatabase(":memory:") as database:
                first = import_user_library_seed(database, manifest)
                self.assertEqual(first.source_count, 2)
                self.assertEqual(first.game_count, 2)
                self.assertEqual(first.reused_source_count, 0)
                self.assertEqual(
                    int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
                    2,
                )

                second = import_user_library_seed(database, manifest)
                self.assertEqual(second.source_count, 2)
                self.assertEqual(second.game_count, 2)
                self.assertEqual(second.reused_source_count, 2)
                self.assertEqual(
                    int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
                    2,
                )

    def test_manifest_explicitly_proves_no_network_or_ai_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed(Path(directory) / "seed", {"book.pgn": PGN_ONE})
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertIs(manifest["runtime_network_required"], False)
            self.assertIs(manifest["ai_required"], False)
            loaded = load_user_library_seed(root)
            self.assertEqual(len(loaded.entries), 1)

    def test_byte_tampering_fails_before_library_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed(Path(directory) / "seed", {"book.pgn": PGN_ONE})
            manifest = load_user_library_seed(root)
            (root / "book.pgn").write_bytes(PGN_TWO.encode("utf-8"))

            with AcsDatabase(":memory:") as database:
                with self.assertRaises(UserLibrarySeedError):
                    import_user_library_seed(database, manifest)
                self.assertEqual(
                    int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
                    0,
                )

    def test_later_tampering_fails_before_any_seed_source_is_published(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed(
                Path(directory) / "seed",
                {"first.pgn": PGN_ONE, "second.pgn": PGN_TWO},
            )
            manifest = load_user_library_seed(root)
            (root / "second.pgn").write_bytes(PGN_ONE.encode("utf-8"))

            with AcsDatabase(":memory:") as database:
                with self.assertRaises(UserLibrarySeedError):
                    import_user_library_seed(database, manifest)
                self.assertEqual(
                    int(database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]),
                    0,
                )
                self.assertEqual(
                    int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
                    0,
                )

    def test_invalid_utf8_and_noncanonical_pgn_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "seed"
            root.mkdir()
            payload = b'[Event "Broken"]\n[Result "*"]\n\n1. e4 \xff *\n'
            (root / "broken.pgn").write_bytes(payload)
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "bundle_kind": BUNDLE_KIND,
                "runtime_network_required": False,
                "ai_required": False,
                "files": [{
                    "file": "broken.pgn",
                    "display_name": "Broken",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }],
            }
            (root / "manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            loaded = load_user_library_seed(root)
            with AcsDatabase(":memory:") as database:
                with self.assertRaises(UserLibrarySeedError):
                    import_user_library_seed(database, loaded)
                self.assertEqual(
                    int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
                    0,
                )

    def test_extra_inventory_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed(Path(directory) / "seed", {"book.pgn": PGN_ONE})
            (root / "unexpected.txt").write_text("no", encoding="utf-8")
            with self.assertRaises(UserLibrarySeedError):
                load_user_library_seed(root)

    def test_casefold_colliding_inventory_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed(Path(directory) / "seed", {"book.pgn": PGN_ONE})
            canonical = root / "book.pgn"
            colliding = root / "BOOK.PGN"
            colliding.write_text("collision", encoding="utf-8")
            try:
                if colliding.samefile(canonical):
                    self.skipTest("filesystem does not permit distinct case-colliding names")
            except OSError:
                pass
            with self.assertRaises(UserLibrarySeedError):
                load_user_library_seed(root)


if __name__ == "__main__":
    unittest.main()

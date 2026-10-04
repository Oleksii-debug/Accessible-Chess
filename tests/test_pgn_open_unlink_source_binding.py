from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import acs.pgn_service as pgn_service
from acs.pgn_service import PgnSourceChangedError, open_pgn


_SAMPLE_PGN = """[Event "Unlink"]
[Result "*"]

1. e4 e5 *
"""


class PgnOpenUnlinkSourceBindingTests(unittest.TestCase):
    def test_unlink_after_descriptor_open_never_accepts_orphaned_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pgn"
            source.write_text(_SAMPLE_PGN, encoding="utf-8", newline="")
            real_opened_identity = pgn_service._opened_source_identity
            unlinked = False
            unlink_blocked = False

            def identity_then_unlink(handle):
                nonlocal unlinked, unlink_blocked
                identity = real_opened_identity(handle)
                try:
                    source.unlink()
                except PermissionError:
                    unlink_blocked = True
                else:
                    unlinked = True
                return identity

            caught = None
            opened = None
            with patch.object(
                pgn_service,
                "_opened_source_identity",
                side_effect=identity_then_unlink,
            ):
                try:
                    opened = open_pgn(source)
                except PgnSourceChangedError as exc:
                    caught = exc

            self.assertNotEqual(unlinked, unlink_blocked)
            if unlinked:
                self.assertIsNotNone(caught)
                self.assertIsNone(opened)
                self.assertFalse(source.exists())
            else:
                self.assertTrue(unlink_blocked)
                self.assertIsNone(caught)
                self.assertIsNotNone(opened)
                self.assertEqual(opened.total_games, 1)
                self.assertEqual(opened.games[0].tags["Event"], "Unlink")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.gametree import parse_games
from acs.pgn_service import export_game_atomic, save_pgn_atomic


PGN = '''[Event "Passive overwrite"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 *
'''


class ActiveBool:
    def __bool__(self) -> bool:
        raise AssertionError("active overwrite truthiness executed")


class PgnServicePassiveOverwriteTests(unittest.TestCase):
    def games(self):
        return tuple(parse_games(PGN))

    def test_new_destination_rejects_active_overwrite_before_temp_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "new.pgn"

            with self.assertRaises(TypeError):
                save_pgn_atomic(target, self.games(), overwrite=ActiveBool())  # type: ignore[arg-type]

            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_existing_destination_rejects_active_overwrite_before_read_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing.pgn"
            original = b"preserve exactly\n"
            target.write_bytes(original)

            with self.assertRaises(TypeError):
                save_pgn_atomic(target, self.games(), overwrite=ActiveBool())  # type: ignore[arg-type]

            self.assertEqual(target.read_bytes(), original)

    def test_export_wrapper_inherits_same_passive_overwrite_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "export.pgn"

            with self.assertRaises(TypeError):
                export_game_atomic(target, self.games()[0], overwrite=ActiveBool())  # type: ignore[arg-type]

            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_exact_boolean_controls_retain_normal_save_and_replace_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "normal.pgn"
            first = save_pgn_atomic(target, self.games(), overwrite=False)
            before = target.read_bytes()
            second = save_pgn_atomic(target, self.games(), overwrite=True)

            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

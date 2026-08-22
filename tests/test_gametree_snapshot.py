from __future__ import annotations

import unittest
from dataclasses import replace

from acs.game_identity import identity_for_game
from acs.gametree import parse_games
from acs.gametree_snapshot import (
    GAMETREE_SNAPSHOT_SCHEMA_VERSION,
    GameTreeSnapshot,
    GameTreeSnapshotCode,
    GameTreeSnapshotError,
    MAX_WARNING_CHARS,
    restore_game,
    snapshot_game,
)


PGN = '''[Event "Snapshot"]
[Site "Local"]
[Result "1-0"]

1. e4 $1 {main} e5 (1... c5 {sicilian}) 2. Nf3 Nc6 3. Bb5 a6 1-0
'''


class GameTreeSnapshotTests(unittest.TestCase):
    def game(self):
        game = parse_games(PGN)[0]
        game.source_index = 7
        game.warnings = ["source warning"]
        return game

    def test_round_trip_preserves_semantic_identity_and_metadata(self):
        game = self.game()
        before = identity_for_game(game)
        snapshot = snapshot_game(game)
        restored = restore_game(snapshot)
        self.assertEqual(GAMETREE_SNAPSHOT_SCHEMA_VERSION, snapshot.schema_version)
        self.assertEqual(before, identity_for_game(restored))
        self.assertEqual(7, restored.source_index)
        self.assertEqual(["source warning"], restored.warnings)
        self.assertIsNot(game, restored)
        self.assertIsNot(game.line, restored.line)

    def test_snapshot_does_not_alias_mutable_source_state(self):
        game = self.game()
        snapshot = snapshot_game(game)
        game.tags["Event"] = "mutated"
        game.line.moves[0].san = "d4"
        game.warnings.append("later")
        restored = restore_game(snapshot)
        self.assertEqual("Snapshot", restored.tags["Event"])
        self.assertEqual("e4", restored.line.moves[0].san)
        self.assertEqual(["source warning"], restored.warnings)

    def test_tampered_pgn_fails_identity_check(self):
        snapshot = snapshot_game(self.game())
        tampered = replace(snapshot, pgn_text=snapshot.pgn_text.replace("e4", "d4", 1))
        with self.assertRaises(GameTreeSnapshotError) as caught:
            restore_game(tampered)
        self.assertEqual(GameTreeSnapshotCode.IDENTITY_MISMATCH, caught.exception.code)

    def test_tampered_digest_fails_identity_check(self):
        snapshot = snapshot_game(self.game())
        tampered = replace(snapshot, tree_digest="0" * 64)
        with self.assertRaises(GameTreeSnapshotError) as caught:
            restore_game(tampered)
        self.assertEqual(GameTreeSnapshotCode.IDENTITY_MISMATCH, caught.exception.code)

    def test_multi_game_payload_is_rejected_before_restore(self):
        snapshot = snapshot_game(self.game())
        tampered = replace(snapshot, pgn_text=snapshot.pgn_text + "\n" + snapshot.pgn_text)
        with self.assertRaises(GameTreeSnapshotError) as caught:
            restore_game(tampered)
        self.assertEqual(GameTreeSnapshotCode.PARSE_FAILURE, caught.exception.code)

    def test_schema_and_scalar_boundaries_reject_bool_and_coercion(self):
        snapshot = snapshot_game(self.game())
        cases = (
            {"schema_version": True},
            {"schema_version": 2},
            {"source_index": True},
            {"source_index": "7"},
            {"warnings": ["not a tuple"]},
            {"tree_digest": snapshot.tree_digest.upper()},
        )
        for patch in cases:
            with self.subTest(patch=patch):
                with self.assertRaises(GameTreeSnapshotError):
                    replace(snapshot, **patch)

    def test_warning_resource_limit_is_fail_closed(self):
        snapshot = snapshot_game(self.game())
        with self.assertRaises(GameTreeSnapshotError) as caught:
            replace(snapshot, warnings=("x" * (MAX_WARNING_CHARS + 1),))
        self.assertEqual(GameTreeSnapshotCode.RESOURCE_LIMIT, caught.exception.code)

    def test_invalid_restore_input_type_is_rejected(self):
        with self.assertRaises(TypeError):
            restore_game({})
        with self.assertRaises(TypeError):
            snapshot_game({})


if __name__ == "__main__":
    unittest.main()

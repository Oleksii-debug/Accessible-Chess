from __future__ import annotations

import hashlib
import unittest

from acs.game_identity import identity_for_game
from acs.gametree import parse_games
from acs.gametree_snapshot import (
    GAMETREE_SNAPSHOT_SCHEMA_VERSION,
    GameTreeSnapshot,
    GameTreeSnapshotCode,
    GameTreeSnapshotError,
    restore_game,
    snapshot_from_record,
    snapshot_game,
    snapshot_to_record,
)
from acs.pgn_roundtrip import parse_pgn_text


ATTACHED_NAG_PGN = '''[Event "Snapshot NAG convergence"]
[Site "QA"]
[Result "*"]

1. e4?! *
'''

CANONICAL_NAG_PGN = '''[Event "Snapshot canonical"]
[Site "QA"]
[Result "*"]

1. e4 $5 *
'''


class D06SnapshotCanonicalRestoreTests(unittest.TestCase):
    def _external_noncanonical_snapshot(self) -> GameTreeSnapshot:
        game = parse_games(ATTACHED_NAG_PGN)[0]
        game.source_index = 11
        identity = identity_for_game(game)
        return GameTreeSnapshot(
            schema_version=GAMETREE_SNAPSHOT_SCHEMA_VERSION,
            pgn_text=ATTACHED_NAG_PGN,
            pgn_digest=hashlib.sha256(ATTACHED_NAG_PGN.encode("utf-8")).hexdigest(),
            tree_digest=identity.tree_digest,
            record_digest=identity.record_digest,
            source_index=game.source_index,
            warnings=("external provenance warning",),
        )

    def test_snapshot_game_rejects_noncanonical_structural_model(self) -> None:
        """Outgoing snapshots must never label non-D06 GameTrees canonical exchange."""

        game = parse_games(ATTACHED_NAG_PGN)[0]
        self.assertEqual("e4?!", game.line.moves[0].san)
        self.assertEqual([], game.line.moves[0].nags)

        with self.assertRaises(GameTreeSnapshotError) as caught:
            snapshot_game(game)

        self.assertEqual(GameTreeSnapshotCode.INVALID_SNAPSHOT, caught.exception.code)

    def test_external_noncanonical_snapshot_fails_identity_after_canonical_normalization(self) -> None:
        """A digest-consistent external record cannot restore a non-strict GameTree."""

        external = self._external_noncanonical_snapshot()
        rebuilt = snapshot_from_record(snapshot_to_record(external))
        self.assertEqual(external, rebuilt)

        with self.assertRaises(GameTreeSnapshotError) as caught:
            restore_game(rebuilt)

        self.assertEqual(GameTreeSnapshotCode.IDENTITY_MISMATCH, caught.exception.code)

    def test_canonical_snapshot_preserves_identity_source_index_and_warning_provenance(self) -> None:
        """Independent provenance warnings remain legal snapshot metadata."""

        game = parse_pgn_text(CANONICAL_NAG_PGN, strict=True)[0]
        game.source_index = 7
        game.warnings = ["source warning"]
        before = identity_for_game(game)

        snapshot = snapshot_game(game)
        rebuilt = snapshot_from_record(snapshot_to_record(snapshot))
        restored = restore_game(rebuilt)

        self.assertEqual(before, identity_for_game(restored))
        self.assertEqual(7, restored.source_index)
        self.assertEqual(["source warning"], restored.warnings)
        self.assertEqual("e4", restored.line.moves[0].san)
        self.assertEqual(["$5"], restored.line.moves[0].nags)


if __name__ == "__main__":
    unittest.main()

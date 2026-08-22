from __future__ import annotations

import unittest
from dataclasses import replace

from acs.game_identity import identity_for_game
from acs.gametree import parse_games
from acs.gametree_snapshot import (
    GAMETREE_SNAPSHOT_SCHEMA_VERSION,
    GameTreeSnapshotCode,
    GameTreeSnapshotError,
    MAX_SNAPSHOT_RECORD_BYTES,
    MAX_WARNING_CHARS,
    restore_game,
    snapshot_from_json,
    snapshot_from_record,
    snapshot_game,
    snapshot_to_json,
    snapshot_to_record,
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
        self.assertEqual(64, len(snapshot.pgn_digest))
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

    def test_tampered_pgn_fails_payload_digest_before_restore(self):
        snapshot = snapshot_game(self.game())
        with self.assertRaises(GameTreeSnapshotError) as caught:
            replace(snapshot, pgn_text=snapshot.pgn_text.replace("e4", "d4", 1))
        self.assertEqual(GameTreeSnapshotCode.PAYLOAD_MISMATCH, caught.exception.code)

    def test_move_number_tamper_is_detected_even_when_semantic_identity_would_match(self):
        snapshot = snapshot_game(self.game())
        self.assertIn("1. e4", snapshot.pgn_text)
        with self.assertRaises(GameTreeSnapshotError) as caught:
            replace(snapshot, pgn_text=snapshot.pgn_text.replace("1. e4", "1... e4", 1))
        self.assertEqual(GameTreeSnapshotCode.PAYLOAD_MISMATCH, caught.exception.code)

    def test_tampered_digest_fails_identity_check(self):
        snapshot = snapshot_game(self.game())
        tampered = replace(snapshot, tree_digest="0" * 64)
        with self.assertRaises(GameTreeSnapshotError) as caught:
            restore_game(tampered)
        self.assertEqual(GameTreeSnapshotCode.IDENTITY_MISMATCH, caught.exception.code)

    def test_multi_game_payload_with_matching_old_digest_is_rejected_immediately(self):
        snapshot = snapshot_game(self.game())
        with self.assertRaises(GameTreeSnapshotError) as caught:
            replace(snapshot, pgn_text=snapshot.pgn_text + "\n" + snapshot.pgn_text)
        self.assertEqual(GameTreeSnapshotCode.PAYLOAD_MISMATCH, caught.exception.code)

    def test_schema_and_scalar_boundaries_reject_bool_and_coercion(self):
        snapshot = snapshot_game(self.game())
        cases = (
            {"schema_version": True},
            {"schema_version": 2},
            {"source_index": True},
            {"source_index": "7"},
            {"warnings": ["not a tuple"]},
            {"tree_digest": snapshot.tree_digest.upper()},
            {"pgn_digest": snapshot.pgn_digest.upper()},
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

    def test_record_exchange_round_trip_preserves_exact_snapshot(self):
        snapshot = snapshot_game(self.game())
        record = snapshot_to_record(snapshot)
        rebuilt = snapshot_from_record(record)
        self.assertEqual(snapshot, rebuilt)
        self.assertEqual(snapshot.pgn_text, snapshot_to_record(rebuilt)["pgn_text"])
        self.assertIsInstance(record["warnings"], list)

    def test_record_exchange_detaches_mutable_warning_container(self):
        snapshot = snapshot_game(self.game())
        record = snapshot_to_record(snapshot)
        record["warnings"].append("caller mutation")
        self.assertEqual(("source warning",), snapshot.warnings)
        rebuilt_record = snapshot_to_record(snapshot)
        self.assertEqual(["source warning"], rebuilt_record["warnings"])

    def test_record_rejects_missing_and_unknown_fields_without_mutating_input(self):
        canonical = snapshot_to_record(snapshot_game(self.game()))
        for mutation in ("missing", "unknown"):
            with self.subTest(mutation=mutation):
                record = dict(canonical)
                record["warnings"] = list(canonical["warnings"])
                if mutation == "missing":
                    del record["record_digest"]
                else:
                    record["future_field"] = "silent migration forbidden"
                before = repr(record)
                with self.assertRaises(GameTreeSnapshotError) as caught:
                    snapshot_from_record(record)
                self.assertEqual(GameTreeSnapshotCode.INVALID_SNAPSHOT, caught.exception.code)
                self.assertEqual(before, repr(record))

    def test_record_rejects_noncanonical_container_and_scalar_shapes(self):
        canonical = snapshot_to_record(snapshot_game(self.game()))
        cases = (
            [],
            tuple(canonical.items()),
            {**canonical, "schema_version": True},
            {**canonical, "source_index": "7"},
            {**canonical, "warnings": tuple(canonical["warnings"])},
            {**canonical, "warnings": [1]},
        )
        for record in cases:
            with self.subTest(record_type=type(record).__name__):
                with self.assertRaises(GameTreeSnapshotError):
                    snapshot_from_record(record)

    def test_record_rejects_unsupported_version_and_payload_tamper(self):
        canonical = snapshot_to_record(snapshot_game(self.game()))
        with self.assertRaises(GameTreeSnapshotError) as caught:
            snapshot_from_record({**canonical, "schema_version": 2})
        self.assertEqual(GameTreeSnapshotCode.UNSUPPORTED_VERSION, caught.exception.code)

        tampered = dict(canonical)
        tampered["pgn_text"] = tampered["pgn_text"].replace("e4", "d4", 1)
        with self.assertRaises(GameTreeSnapshotError) as caught:
            snapshot_from_record(tampered)
        self.assertEqual(GameTreeSnapshotCode.PAYLOAD_MISMATCH, caught.exception.code)

    def test_record_import_is_detached_from_later_warning_mutation(self):
        record = snapshot_to_record(snapshot_game(self.game()))
        rebuilt = snapshot_from_record(record)
        record["warnings"].append("later")
        self.assertEqual(("source warning",), rebuilt.warnings)
        self.assertEqual(["source warning"], restore_game(rebuilt).warnings)

    def test_record_export_rejects_invalid_snapshot_type(self):
        with self.assertRaises(TypeError):
            snapshot_to_record({})

    def test_json_exchange_is_deterministic_and_round_trips_exactly(self):
        snapshot = snapshot_game(self.game())
        text_a = snapshot_to_json(snapshot)
        text_b = snapshot_to_json(snapshot)
        self.assertEqual(text_a, text_b)
        self.assertEqual(snapshot, snapshot_from_json(text_a))
        self.assertLess(len(text_a.encode("utf-8")), MAX_SNAPSHOT_RECORD_BYTES)
        self.assertTrue(text_a.startswith('{"pgn_digest":'))

    def test_json_rejects_duplicate_fields_instead_of_last_value_wins(self):
        canonical = snapshot_to_json(snapshot_game(self.game()))
        duplicate = canonical[:-1] + ',"source_index":999}'
        with self.assertRaises(GameTreeSnapshotError) as caught:
            snapshot_from_json(duplicate)
        self.assertEqual(GameTreeSnapshotCode.INVALID_SNAPSHOT, caught.exception.code)

    def test_json_rejects_nonfinite_constants_and_non_object_roots(self):
        canonical = snapshot_to_json(snapshot_game(self.game()))
        nonfinite = canonical.replace('"source_index":7', '"source_index":NaN')
        with self.assertRaises(GameTreeSnapshotError) as caught:
            snapshot_from_json(nonfinite)
        self.assertEqual(GameTreeSnapshotCode.INVALID_SNAPSHOT, caught.exception.code)

        for root in ('[]', '"text"', '7', 'null'):
            with self.subTest(root=root):
                with self.assertRaises(GameTreeSnapshotError):
                    snapshot_from_json(root)

    def test_json_rejects_malformed_empty_nontext_and_oversized_payloads(self):
        cases = ("", "{", b"{}")
        for value in cases:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(GameTreeSnapshotError):
                    snapshot_from_json(value)

        oversized = " " * (MAX_SNAPSHOT_RECORD_BYTES + 1)
        with self.assertRaises(GameTreeSnapshotError) as caught:
            snapshot_from_json(oversized)
        self.assertEqual(GameTreeSnapshotCode.RESOURCE_LIMIT, caught.exception.code)

    def test_json_unknown_field_and_tampered_payload_fail_closed(self):
        canonical = snapshot_to_json(snapshot_game(self.game()))
        unknown = canonical[:-1] + ',"future_field":1}'
        with self.assertRaises(GameTreeSnapshotError) as caught:
            snapshot_from_json(unknown)
        self.assertEqual(GameTreeSnapshotCode.INVALID_SNAPSHOT, caught.exception.code)

        tampered = canonical.replace("1. e4", "1. d4", 1)
        with self.assertRaises(GameTreeSnapshotError) as caught:
            snapshot_from_json(tampered)
        self.assertEqual(GameTreeSnapshotCode.PAYLOAD_MISMATCH, caught.exception.code)


if __name__ == "__main__":
    unittest.main()

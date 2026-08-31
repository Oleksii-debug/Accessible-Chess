from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.game_identity import identity_for_game
from acs.gametree import parse_games, serialize_game
from acs.gametree_navigation import (
    GameTreeCursor,
    VariationStep,
    current_move,
    resolve_line,
)
from acs.gametree_snapshot import (
    GAMETREE_SNAPSHOT_SCHEMA_VERSION,
    GameTreeSnapshot,
    snapshot_to_record,
)
from acs.gametree_resume import (
    GAMETREE_RESUME_SCHEMA_VERSION,
    GameTreeResumeCode,
    GameTreeResumeError,
    GameTreeResumeStore,
    resume_record_from_json,
)
from acs.pgn_roundtrip import parse_pgn_text


RESUME_PGN = '''[Event "D06 durable resume"]
[SetUp "1"]
[FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 {root e4} e5 $1
(1... c5!? {Sicilian} 2. Nf3 (2... d6?! {nested}) 2... Nc6)
(1... e6 {French} 2. d4 d5)
2. Nf3 {main knight} Nc6 *
'''

NONCANONICAL_PGN = '''[Event "raw attached nag"]
[Result "*"]

1. e4?! *
'''


class D06GameTreeSnapshotResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        game = parse_pgn_text(RESUME_PGN, strict=True)[0]
        game.source_index = 17
        game.warnings = ["recovery provenance"]
        self.game = game
        self.cursor = GameTreeCursor((VariationStep(1, 0),), 1)

    @staticmethod
    def _canonical_payload_bytes(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def _payload_digest(cls, record: dict[str, object]) -> str:
        payload = {key: value for key, value in record.items() if key != "payload_digest"}
        return hashlib.sha256(cls._canonical_payload_bytes(payload)).hexdigest()

    @classmethod
    def _write_valid_envelope(cls, path: Path, record: dict[str, object]) -> None:
        record["payload_digest"] = cls._payload_digest(record)
        path.write_bytes(cls._canonical_payload_bytes(record) + b"\n")

    @staticmethod
    def _assert_no_transaction_debris(folder: str, name: str) -> None:
        root = Path(folder)
        assert list(root.glob(name + ".*.tmp")) == []
        assert list(root.glob(name + ".cas-*.bak")) == []

    def test_restart_roundtrip_preserves_identity_cursor_current_node_and_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resume.json"
            first_process = GameTreeResumeStore(path)
            saved = first_process.save(self.game, self.cursor)

            # A new store instance models application restart. Durable state
            # must resolve through the canonical GameTree, not object identity.
            reopened = GameTreeResumeStore(path).load()

            self.assertEqual(reopened.generation, 1)
            self.assertEqual(reopened.token, saved.token)
            self.assertEqual(reopened.cursor, self.cursor)
            self.assertEqual(identity_for_game(reopened.game), identity_for_game(self.game))
            self.assertEqual(reopened.game.source_index, 17)
            self.assertEqual(reopened.game.warnings, ["recovery provenance"])
            self.assertEqual(reopened.game.tags["SetUp"], "1")
            self.assertEqual(reopened.game.tags["FEN"], self.game.tags["FEN"])

            node = current_move(reopened.game, reopened.cursor)
            self.assertIsNotNone(node)
            self.assertEqual(node.san, "Nf3")

            side = resolve_line(reopened.game, (VariationStep(1, 0),))
            self.assertEqual(side.moves[0].san, "c5")
            self.assertEqual(side.moves[0].nags, ["!?"])
            self.assertEqual(side.moves[0].comments_after[0].text, "Sicilian")
            nested = resolve_line(
                reopened.game,
                (VariationStep(1, 0), VariationStep(1, 0)),
            )
            self.assertEqual(nested.moves[0].san, "d6")
            self.assertEqual(nested.moves[0].nags, ["?!"])
            self.assertEqual(nested.moves[0].comments_after[0].text, "nested")

            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], GAMETREE_RESUME_SCHEMA_VERSION)
            self.assertEqual(
                raw["snapshot"]["schema_version"],
                GAMETREE_SNAPSHOT_SCHEMA_VERSION,
            )
            self._assert_no_transaction_debris(folder, path.name)

    def test_resume_save_rejects_noncanonical_structural_gametree(self):
        raw = parse_games(NONCANONICAL_PGN)[0]
        before = deepcopy(raw)
        with tempfile.TemporaryDirectory() as folder:
            store = GameTreeResumeStore(Path(folder) / "resume.json")
            with self.assertRaises(GameTreeResumeError) as caught:
                store.save(raw, GameTreeCursor())
            self.assertEqual(caught.exception.code, GameTreeResumeCode.SNAPSHOT_REJECTED)
            self.assertEqual(raw, before)

    def test_external_noncanonical_snapshot_is_never_exposed_even_with_valid_envelope_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resume.json"
            GameTreeResumeStore(path).save(self.game, self.cursor)
            envelope = json.loads(path.read_text(encoding="utf-8"))

            raw = parse_games(NONCANONICAL_PGN)[0]
            raw_identity = identity_for_game(raw)
            raw_text = serialize_game(raw)
            external_snapshot = GameTreeSnapshot(
                schema_version=GAMETREE_SNAPSHOT_SCHEMA_VERSION,
                pgn_text=raw_text,
                pgn_digest=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                tree_digest=raw_identity.tree_digest,
                record_digest=raw_identity.record_digest,
                source_index=3,
                warnings=("external warning",),
            )
            envelope["snapshot"] = snapshot_to_record(external_snapshot)
            envelope["cursor"] = {"line_path": [], "next_move_index": 0}
            self._write_valid_envelope(path, envelope)

            with self.assertRaises(GameTreeResumeError) as caught:
                GameTreeResumeStore(path).load()
            self.assertEqual(caught.exception.code, GameTreeResumeCode.SNAPSHOT_REJECTED)

    def test_corrupt_future_and_digest_mismatched_envelopes_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resume.json"
            store = GameTreeResumeStore(path)
            store.save(self.game, self.cursor)
            original = path.read_bytes()

            path.write_bytes(b'{"schema_version":1')
            with self.assertRaises(GameTreeResumeError) as caught:
                store.load()
            self.assertEqual(caught.exception.code, GameTreeResumeCode.INVALID_RESUME)

            path.write_bytes(original)
            future = json.loads(original)
            future["schema_version"] = GAMETREE_RESUME_SCHEMA_VERSION + 1
            self._write_valid_envelope(path, future)
            with self.assertRaises(GameTreeResumeError) as caught:
                store.load()
            self.assertEqual(caught.exception.code, GameTreeResumeCode.UNSUPPORTED_VERSION)

            path.write_bytes(original)
            tampered = json.loads(original)
            tampered["cursor"]["next_move_index"] = 2
            path.write_bytes(self._canonical_payload_bytes(tampered) + b"\n")
            with self.assertRaises(GameTreeResumeError) as caught:
                store.load()
            self.assertEqual(caught.exception.code, GameTreeResumeCode.PAYLOAD_MISMATCH)

            with self.assertRaises(GameTreeResumeError) as caught:
                resume_record_from_json(
                    '{"schema_version":1,"schema_version":1}'
                )
            self.assertEqual(caught.exception.code, GameTreeResumeCode.INVALID_RESUME)

    def test_nested_snapshot_digest_and_invalid_cursor_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resume.json"
            store = GameTreeResumeStore(path)
            store.save(self.game, self.cursor)
            original = path.read_bytes()

            bad_snapshot = json.loads(original)
            bad_snapshot["snapshot"]["pgn_text"] += " "
            self._write_valid_envelope(path, bad_snapshot)
            with self.assertRaises(GameTreeResumeError) as caught:
                store.load()
            self.assertEqual(caught.exception.code, GameTreeResumeCode.SNAPSHOT_REJECTED)

            path.write_bytes(original)
            bad_cursor = json.loads(original)
            bad_cursor["cursor"]["next_move_index"] = 999
            self._write_valid_envelope(path, bad_cursor)
            with self.assertRaises(GameTreeResumeError) as caught:
                store.load()
            self.assertEqual(caught.exception.code, GameTreeResumeCode.CURSOR_REJECTED)

    def test_stale_snapshot_expectation_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resume.json"
            store = GameTreeResumeStore(path)
            saved = store.save(self.game, self.cursor)
            before = path.read_bytes()

            with self.assertRaises(GameTreeResumeError) as caught:
                store.load(expected_tree_digest="0" * 64)
            self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_SNAPSHOT)
            self.assertEqual(path.read_bytes(), before)

            accepted = store.load(
                expected_tree_digest=identity_for_game(self.game).tree_digest
            )
            self.assertEqual(accepted.token, saved.token)

    def test_stale_writer_cannot_overwrite_newer_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resume.json"
            first = GameTreeResumeStore(path)
            stale = GameTreeResumeStore(path)
            state_a = first.save(self.game, self.cursor)
            stale_view = stale.load()
            self.assertEqual(stale_view.token, state_a.token)

            cursor_b = GameTreeCursor((), 2)
            state_b = first.save(
                self.game,
                cursor_b,
                expected_token=state_a.token,
            )
            self.assertEqual(state_b.generation, 2)

            with self.assertRaises(GameTreeResumeError) as caught:
                stale.save(
                    self.game,
                    GameTreeCursor((), 3),
                    expected_token=stale_view.token,
                )
            self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)

            authoritative = GameTreeResumeStore(path).load()
            self.assertEqual(authoritative.token, state_b.token)
            self.assertEqual(authoritative.cursor, cursor_b)
            self.assertEqual(authoritative.generation, 2)
            self._assert_no_transaction_debris(folder, path.name)

    def test_existing_resume_requires_explicit_cas_token(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resume.json"
            store = GameTreeResumeStore(path)
            state = store.save(self.game, self.cursor)
            before = path.read_bytes()

            with self.assertRaises(GameTreeResumeError) as caught:
                GameTreeResumeStore(path).save(self.game, GameTreeCursor((), 1))
            self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(GameTreeResumeStore(path).load().token, state.token)

    def test_publication_failure_keeps_previous_authoritative_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resume.json"
            store = GameTreeResumeStore(path)
            state_a = store.save(self.game, self.cursor)
            before = path.read_bytes()

            with mock.patch(
                "acs.gametree_resume.os.replace",
                side_effect=OSError("simulated publication crash"),
            ):
                with self.assertRaises(GameTreeResumeError) as caught:
                    store.save(
                        self.game,
                        GameTreeCursor((), 2),
                        expected_token=state_a.token,
                    )
            self.assertEqual(caught.exception.code, GameTreeResumeCode.IO_FAILURE)
            self.assertEqual(path.read_bytes(), before)

            reopened = GameTreeResumeStore(path).load()
            self.assertEqual(reopened.token, state_a.token)
            self.assertEqual(reopened.cursor, self.cursor)
            self.assertEqual(reopened.generation, 1)
            self._assert_no_transaction_debris(folder, path.name)


if __name__ == "__main__":
    unittest.main()

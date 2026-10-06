from __future__ import annotations

import ast
from pathlib import Path
import unittest

from acs.structured_broadcast import (
    BroadcastApplyKind,
    BroadcastConnectionState,
    BroadcastContractError,
    BroadcastErrorCode,
    BroadcastReconnectPolicy,
    CanonicalBroadcastGame,
    LICHESS_BROADCAST_MEDIA_TYPE,
    LICHESS_BROADCAST_REQUIRED_SCOPE,
    LichessBroadcastRound,
    MAX_BROADCAST_CHECKPOINT_BYTES,
    MAX_BROADCAST_IDENTIFIER_CHARS,
    MAX_BROADCAST_PGN_BYTES,
    StructuredBroadcastEnvelope,
    StructuredBroadcastSession,
)


class Canonical:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def ingest_broadcast_pgn(self, **kwargs):
        self.calls.append(kwargs)
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def game(game_id="g1", chess_ref="tree:g1:n4", revision="r4"):
    return CanonicalBroadcastGame(game_id, chess_ref, revision)


def envelope(sequence=1, observed=1000, pgn='[Event "Live"]\n\n1. e4 *', source="broadcast:Ab12Cd34"):
    return StructuredBroadcastEnvelope(
        provider="lichess", round_id="Ab12Cd34", source_id=source,
        sequence=sequence, observed_at_ms=observed, pgn_text=pgn,
    )


class StructuredBroadcastTests(unittest.TestCase):
    def session(self):
        return StructuredBroadcastSession(
            provider="lichess", round_id="Ab12Cd34", source_id="broadcast:Ab12Cd34"
        )

    def test_lichess_documented_request_contract_and_passive_inputs(self):
        request = LichessBroadcastRound("Ab12Cd34")
        self.assertEqual(request.required_oauth_scopes, (LICHESS_BROADCAST_REQUIRED_SCOPE,))
        self.assertEqual(request.expected_media_type, LICHESS_BROADCAST_MEDIA_TYPE)
        self.assertEqual(
            request.stream_url(),
            "https://lichess.org/api/stream/broadcast/round/Ab12Cd34.pgn?clocks=true&comments=true",
        )
        self.assertNotIn("token", request.stream_url().lower())
        class ActiveText(str):
            pass
        for value in ("short", "123456789", "1234-678", "абвгдеёж", ActiveText("Ab12Cd34")):
            with self.subTest(value=value), self.assertRaises(BroadcastContractError):
                LichessBroadcastRound(value)
        with self.assertRaises(BroadcastContractError):
            LichessBroadcastRound("Ab12Cd34", include_clocks=1)

    def test_reconnect_policy_is_bounded_and_respects_retry_after(self):
        policy = BroadcastReconnectPolicy(base_delay_ms=1000, max_delay_ms=8000)
        self.assertEqual([policy.delay_ms(i) for i in range(6)], [1000, 2000, 4000, 8000, 8000, 8000])
        self.assertEqual(policy.delay_ms(1, retry_after_ms=7000), 7000)
        self.assertEqual(policy.delay_ms(1, retry_after_ms=99_000), 8000)
        for bad in (True, -1):
            with self.subTest(bad=bad), self.assertRaises(BroadcastContractError):
                policy.delay_ms(bad)

    def test_envelope_preserves_unicode_and_bounds_passive_bytes(self):
        pgn = '[Event "Київ"]\n\n1. e4 {коментар} e5 *'
        item = envelope(pgn=pgn)
        self.assertEqual(item.pgn_text, pgn)
        self.assertEqual(len(item.payload_sha256), 64)
        with self.assertRaises(BroadcastContractError) as ctx:
            envelope(pgn="ж" * ((MAX_BROADCAST_PGN_BYTES // 2) + 1))
        self.assertEqual(ctx.exception.code, BroadcastErrorCode.PAYLOAD_TOO_LARGE)
        for bad in ("ok\x00bad", "bad\ud800"):
            with self.assertRaises(BroadcastContractError):
                envelope(pgn=bad)
        for sequence, observed in ((True, 1), (-1, 1), (1, True), (1, -1)):
            with self.assertRaises(BroadcastContractError):
                envelope(sequence=sequence, observed=observed)

    def test_pgn_is_opaque_and_replay_is_idempotent(self):
        session = self.session()
        pgn = '[Event "Київ"]\n\n1. e4 {коментар} e5 *'
        canonical = Canonical((game(),))
        first = session.apply(envelope(pgn=pgn), canonical)
        second = session.apply(envelope(observed=2000, pgn=pgn), canonical)
        self.assertEqual(first.kind, BroadcastApplyKind.APPLIED)
        self.assertEqual(second.kind, BroadcastApplyKind.NO_CHANGE)
        self.assertEqual(canonical.calls[0]["pgn_text"], pgn)
        self.assertEqual(len(canonical.calls), 1)
        self.assertEqual(session.last_observed_at_ms, 2000)

    def test_revision_sequence_time_and_source_conflicts_fail_before_mutation(self):
        session = self.session()
        canonical = Canonical((game(),))
        session.apply(envelope(sequence=3, observed=3000), canonical)
        cases = (
            (envelope(sequence=2, observed=4000), BroadcastErrorCode.OUT_OF_ORDER),
            (envelope(sequence=3, observed=3000, pgn='[Event "Other"]\n\n1. d4 *'), BroadcastErrorCode.REVISION_CONFLICT),
            (envelope(sequence=4, observed=2999), BroadcastErrorCode.OUT_OF_ORDER),
            (envelope(sequence=4, observed=4000, source="broadcast:other"), BroadcastErrorCode.SOURCE_MISMATCH),
        )
        for item, code in cases:
            with self.subTest(code=code), self.assertRaises(BroadcastContractError) as ctx:
                session.apply(item, canonical)
            self.assertEqual(ctx.exception.code, code)
        self.assertEqual(len(canonical.calls), 1)

    def test_canonical_failures_and_invalid_results_do_not_advance(self):
        responses = (
            RuntimeError("private parser detail"),
            (),
            [game()],
            (game(), game(chess_ref="tree:other", revision="r9")),
        )
        expected = (
            BroadcastErrorCode.CANONICAL_REJECTED,
            BroadcastErrorCode.INVALID_CANONICAL_RESULT,
            BroadcastErrorCode.INVALID_CANONICAL_RESULT,
            BroadcastErrorCode.DUPLICATE_GAME,
        )
        for value, code in zip(responses, expected):
            session = self.session()
            with self.subTest(code=code), self.assertRaises(BroadcastContractError) as ctx:
                session.apply(envelope(), Canonical(value))
            self.assertEqual(ctx.exception.code, code)
            self.assertIsNone(session.last_sequence)
            self.assertEqual(session.games, ())
            self.assertEqual(session.connection_state, BroadcastConnectionState.DISCONNECTED)

    def test_game_updates_merge_and_unchanged_revision_is_not_reannounced(self):
        session = self.session()
        canonical = Canonical(
            (game("g1", "tree:g1:n1", "r1"), game("g2", "tree:g2:n2", "r2")),
            (game("g1", "tree:g1:n3", "r3"),),
            (game("g1", "tree:g1:n3", "r3"),),
        )
        first = session.apply(envelope(sequence=1), canonical)
        second = session.apply(envelope(sequence=2, observed=1100, pgn='[Event "update"]\n\n1. e4 e5 *'), canonical)
        third = session.apply(envelope(sequence=3, observed=1200, pgn='[Event "same canonical"]\n\n1. e4 e5 *'), canonical)
        self.assertEqual(first.changed_game_ids, ("g1", "g2"))
        self.assertEqual(second.changed_game_ids, ("g1",))
        self.assertEqual(third.changed_game_ids, ())
        self.assertEqual([item.provider_game_id for item in session.games], ["g1", "g2"])

    def test_checkpoint_restores_replay_and_monotonic_guards_disconnected(self):
        session = self.session()
        original = envelope(sequence=7, observed=7000)
        session.apply(original, Canonical((game("g1", "tree:n7", "r7"),)))
        checkpoint = session.to_checkpoint_json()
        restored = StructuredBroadcastSession.from_checkpoint_json(checkpoint)

        self.assertEqual(restored.games, session.games)
        self.assertEqual(restored.last_sequence, 7)
        self.assertEqual(restored.last_observed_at_ms, 7000)
        self.assertEqual(restored.connection_state, BroadcastConnectionState.DISCONNECTED)
        self.assertEqual(checkpoint, restored.to_checkpoint_json())

        replay_canonical = Canonical((game("unused"),))
        replay = restored.apply(
            envelope(sequence=7, observed=7100),
            replay_canonical,
        )
        self.assertEqual(replay.kind, BroadcastApplyKind.NO_CHANGE)
        self.assertEqual(replay_canonical.calls, [])
        self.assertEqual(restored.connection_state, BroadcastConnectionState.CONNECTED)

        restarted = StructuredBroadcastSession.from_checkpoint_json(checkpoint)
        with self.assertRaises(BroadcastContractError) as conflict:
            restarted.apply(
                envelope(
                    sequence=7,
                    observed=7200,
                    pgn='[Event "Changed"]\\n\\n1. d4 *',
                ),
                Canonical((game(),)),
            )
        self.assertEqual(conflict.exception.code, BroadcastErrorCode.REVISION_CONFLICT)
        with self.assertRaises(BroadcastContractError) as backward:
            restarted.apply(envelope(sequence=6, observed=7300), Canonical((game(),)))
        self.assertEqual(backward.exception.code, BroadcastErrorCode.OUT_OF_ORDER)

    def test_empty_checkpoint_is_valid_but_applied_state_must_be_consistent(self):
        empty = self.session()
        restored = StructuredBroadcastSession.from_checkpoint_json(empty.to_checkpoint_json())
        self.assertEqual(restored.games, ())
        self.assertIsNone(restored.last_sequence)
        self.assertEqual(restored.connection_state, BroadcastConnectionState.DISCONNECTED)

        import json
        document = json.loads(empty.to_checkpoint_json())
        document["payload"]["games"] = [
            {
                "provider_game_id": "g1",
                "chess_ref": "tree:g1",
                "canonical_revision": "r1",
            }
        ]
        document["payload_sha256"] = StructuredBroadcastSession._checkpoint_payload_digest(
            document["payload"]
        )
        with self.assertRaises(BroadcastContractError) as inconsistent:
            StructuredBroadcastSession.from_checkpoint_json(
                json.dumps(document, sort_keys=True, separators=(",", ":"))
            )
        self.assertEqual(inconsistent.exception.code, BroadcastErrorCode.INVALID_CHECKPOINT)

    def test_checkpoint_rejects_corruption_duplicates_unknown_fields_and_oversize(self):
        import json
        session = self.session()
        session.apply(envelope(), Canonical((game(),)))
        document = json.loads(session.to_checkpoint_json())

        corrupt = dict(document)
        corrupt["payload_sha256"] = "0" * 64
        with self.assertRaises(BroadcastContractError) as digest:
            StructuredBroadcastSession.from_checkpoint_json(json.dumps(corrupt))
        self.assertEqual(digest.exception.code, BroadcastErrorCode.INVALID_CHECKPOINT)

        duplicate_key = '{"schema":1,"schema":1,"payload":{},"payload_sha256":"' + ("0" * 64) + '"}'
        with self.assertRaises(BroadcastContractError) as duplicate:
            StructuredBroadcastSession.from_checkpoint_json(duplicate_key)
        self.assertEqual(duplicate.exception.code, BroadcastErrorCode.INVALID_CHECKPOINT)

        unknown = dict(document)
        unknown["extra"] = True
        with self.assertRaises(BroadcastContractError) as extra:
            StructuredBroadcastSession.from_checkpoint_json(json.dumps(unknown))
        self.assertEqual(extra.exception.code, BroadcastErrorCode.INVALID_CHECKPOINT)

        with self.assertRaises(BroadcastContractError) as oversized:
            StructuredBroadcastSession.from_checkpoint_json(
                "x" * (MAX_BROADCAST_CHECKPOINT_BYTES + 1)
            )
        self.assertEqual(oversized.exception.code, BroadcastErrorCode.INVALID_CHECKPOINT)

        no_games = json.loads(session.to_checkpoint_json())
        no_games["payload"]["games"] = []
        no_games["payload_sha256"] = StructuredBroadcastSession._checkpoint_payload_digest(
            no_games["payload"]
        )
        with self.assertRaises(BroadcastContractError) as empty_applied:
            StructuredBroadcastSession.from_checkpoint_json(json.dumps(no_games))
        self.assertEqual(
            empty_applied.exception.code,
            BroadcastErrorCode.INVALID_CHECKPOINT,
        )

    def test_broadcast_identifiers_are_bounded_before_checkpointing(self):
        with self.assertRaises(BroadcastContractError) as game_id:
            CanonicalBroadcastGame(
                "g" * (MAX_BROADCAST_IDENTIFIER_CHARS + 1),
                "tree:g1",
                "r1",
            )
        self.assertEqual(game_id.exception.code, BroadcastErrorCode.INVALID_TEXT)
        with self.assertRaises(BroadcastContractError) as source_id:
            StructuredBroadcastSession(
                provider="lichess",
                round_id="Ab12Cd34",
                source_id="s" * (MAX_BROADCAST_IDENTIFIER_CHARS + 1),
            )
        self.assertEqual(source_id.exception.code, BroadcastErrorCode.INVALID_TEXT)

    def test_verified_game_projects_to_confirmed_media_core_link_only(self):
        session = self.session()
        session.apply(envelope(), Canonical((game(),)))
        link = session.media_link_for_game("g1", timestamp_ms=4321)
        self.assertTrue(link.confirmed)
        self.assertEqual((link.source_id, link.chess_ref, link.timestamp_ms), ("broadcast:Ab12Cd34", "tree:g1:n4", 4321))
        self.assertEqual(link.confidence, 1.0)
        self.assertIn("structured:lichess:Ab12Cd34:g1:r4", link.evidence)
        with self.assertRaises(BroadcastContractError) as ctx:
            session.media_link_for_game("missing", timestamp_ms=0)
        self.assertEqual(ctx.exception.code, BroadcastErrorCode.GAME_NOT_FOUND)

    def test_stale_disconnect_and_clock_rollback_are_explicit(self):
        session = self.session()
        session.apply(envelope(observed=1000), Canonical((game(),)))
        self.assertEqual(session.refresh_staleness(31_001, stale_after_ms=30_000), BroadcastConnectionState.STALE)
        self.assertEqual(session.refresh_staleness(31_000, stale_after_ms=30_000), BroadcastConnectionState.CONNECTED)
        with self.assertRaises(BroadcastContractError) as ctx:
            session.refresh_staleness(999)
        self.assertEqual(ctx.exception.code, BroadcastErrorCode.OUT_OF_ORDER)
        self.assertEqual(session.mark_disconnected(), BroadcastConnectionState.DISCONNECTED)
        self.assertEqual(session.refresh_staleness(99_000), BroadcastConnectionState.DISCONNECTED)

    def test_module_has_no_chess_parser_or_network_authority(self):
        path = Path(__file__).resolve().parents[1] / "acs" / "structured_broadcast.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = ("gametree", "pgn_roundtrip", "python_chess", "chess.", "urllib", "requests", "httpx", "aiohttp", "socket")
        for module in imported:
            self.assertFalse(any(fragment in module for fragment in forbidden), module)


if __name__ == "__main__":
    unittest.main()

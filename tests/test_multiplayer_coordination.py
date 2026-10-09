from __future__ import annotations

import json
import unittest

from acs.clock_service import ClockSnapshot, ClockState, TimeControl
from acs.game_lifecycle import EndReason, GameOutcome, GameStatus, LifecycleSnapshot
from acs.multiplayer_coordination import (
    ChallengeIntent,
    ChallengeIntentKind,
    ChallengeSnapshot,
    ChallengeSnapshotTracker,
    ChallengeState,
    GameIntent,
    GameIntentKind,
    MultiplayerContractError,
    MultiplayerGameSnapshot,
    MultiplayerSnapshotTracker,
    PresenceState,
    validate_challenge_intent,
    validate_game_intent,
)


CONTROL = TimeControl(300_000, 2_000)
ACTIVE = LifecycleSnapshot(GameStatus.ACTIVE, None, None, None)


def game_snapshot(
    *,
    sequence: int = 1,
    side_to_move: str = "w",
    lifecycle: LifecycleSnapshot = ACTIVE,
    clock: ClockSnapshot | None = None,
    position_revision: str = "pos-1",
    white_presence: PresenceState = PresenceState.CONNECTED,
    black_presence: PresenceState = PresenceState.CONNECTED,
    rematch_of: str | None = None,
    rematch_requested_by: str | None = None,
) -> MultiplayerGameSnapshot:
    if clock is None:
        if lifecycle.status is GameStatus.ACTIVE:
            clock = ClockSnapshot(
                300_000,
                300_000,
                side_to_move,
                ClockState.RUNNING,
            )
        else:
            clock = ClockSnapshot(250_000, 280_000, None, ClockState.STOPPED)
    return MultiplayerGameSnapshot(
        game_id="game-1",
        sequence=sequence,
        white_player_id="alice",
        black_player_id="bob",
        time_control=CONTROL,
        position_revision=position_revision,
        side_to_move=side_to_move,
        clock=clock,
        lifecycle=lifecycle,
        white_presence=white_presence,
        black_presence=black_presence,
        rematch_of=rematch_of,
        rematch_requested_by=rematch_requested_by,
    )


class ChallengeContractTests(unittest.TestCase):
    def test_challenge_intents_enforce_actor_and_revision_without_local_server_state(self) -> None:
        snapshot = ChallengeSnapshot(
            challenge_id="challenge-1",
            challenger_id="alice",
            opponent_id="bob",
            time_control=CONTROL,
        )
        accept = ChallengeIntent(
            "challenge-1",
            "bob",
            0,
            ChallengeIntentKind.ACCEPT,
        )
        validate_challenge_intent(snapshot, accept)
        self.assertEqual(
            accept.intent_id,
            ChallengeIntent("challenge-1", "bob", 0, "accept").intent_id,
        )

        with self.assertRaisesRegex(MultiplayerContractError, "challenged opponent"):
            validate_challenge_intent(
                snapshot,
                ChallengeIntent("challenge-1", "alice", 0, "accept"),
            )
        with self.assertRaisesRegex(MultiplayerContractError, "challenger may cancel"):
            validate_challenge_intent(
                snapshot,
                ChallengeIntent("challenge-1", "bob", 0, "cancel"),
            )
        with self.assertRaisesRegex(MultiplayerContractError, "stale"):
            validate_challenge_intent(
                snapshot,
                ChallengeIntent("challenge-1", "bob", 1, "decline"),
            )

    def test_challenge_intent_round_trip_is_content_bound(self) -> None:
        intent = ChallengeIntent("challenge-1", "bob", 4, "accept")
        self.assertEqual(ChallengeIntent.from_record(intent.to_record()), intent)
        tampered = intent.to_record()
        tampered["expected_revision"] = 5
        with self.assertRaisesRegex(MultiplayerContractError, "intent id does not match"):
            ChallengeIntent.from_record(tampered)

    def test_challenge_tracker_accepts_one_server_terminal_transition_and_is_idempotent(self) -> None:
        pending = ChallengeSnapshot("challenge-1", "alice", "bob", CONTROL)
        tracker = ChallengeSnapshotTracker(pending)
        accepted = ChallengeSnapshot(
            "challenge-1",
            "alice",
            "bob",
            CONTROL,
            revision=1,
            state=ChallengeState.ACCEPTED,
        )
        self.assertTrue(tracker.apply(accepted))
        self.assertFalse(tracker.apply(accepted))
        with self.assertRaisesRegex(MultiplayerContractError, "terminal"):
            tracker.apply(
                ChallengeSnapshot(
                    "challenge-1",
                    "alice",
                    "bob",
                    CONTROL,
                    revision=2,
                    state=ChallengeState.DECLINED,
                )
            )

    def test_challenge_tracker_rejects_stale_conflicting_and_identity_mutation(self) -> None:
        pending = ChallengeSnapshot(
            "challenge-1",
            "alice",
            "bob",
            CONTROL,
            revision=2,
        )
        tracker = ChallengeSnapshotTracker(pending)
        with self.assertRaisesRegex(MultiplayerContractError, "stale"):
            tracker.apply(
                ChallengeSnapshot(
                    "challenge-1",
                    "alice",
                    "bob",
                    CONTROL,
                    revision=1,
                )
            )
        with self.assertRaisesRegex(MultiplayerContractError, "conflicting"):
            tracker.apply(
                ChallengeSnapshot(
                    "challenge-1",
                    "alice",
                    "bob",
                    CONTROL,
                    revision=2,
                    state=ChallengeState.CANCELLED,
                )
            )
        with self.assertRaisesRegex(MultiplayerContractError, "identity changed"):
            tracker.apply(
                ChallengeSnapshot(
                    "challenge-1",
                    "alice",
                    "carol",
                    CONTROL,
                    revision=3,
                    state=ChallengeState.DECLINED,
                )
            )


class MultiplayerGameContractTests(unittest.TestCase):
    def test_snapshot_reuses_canonical_clock_and_lifecycle_and_keeps_position_opaque(self) -> None:
        snapshot = game_snapshot()
        self.assertIsInstance(snapshot.clock, ClockSnapshot)
        self.assertIsInstance(snapshot.lifecycle, LifecycleSnapshot)
        self.assertEqual(snapshot.position_revision, "pos-1")
        self.assertEqual(snapshot.side_for("alice"), "w")
        self.assertEqual(snapshot.side_for("bob"), "b")
        with self.assertRaises(MultiplayerContractError):
            snapshot.side_for("spectator")

    def test_active_timed_snapshot_requires_clock_to_match_side_to_move(self) -> None:
        with self.assertRaisesRegex(MultiplayerContractError, "active clock must match"):
            game_snapshot(
                side_to_move="w",
                clock=ClockSnapshot(
                    300_000,
                    300_000,
                    "b",
                    ClockState.RUNNING,
                ),
            )
        with self.assertRaisesRegex(MultiplayerContractError, "requires active clock"):
            game_snapshot(
                clock=ClockSnapshot(
                    300_000,
                    300_000,
                    None,
                    ClockState.STOPPED,
                ),
            )

    def test_finished_snapshot_cannot_resume_and_timeout_flag_is_allowed_only_after_finish(self) -> None:
        outcome = GameOutcome("0-1", EndReason.TIMEOUT, "b")
        finished = LifecycleSnapshot(GameStatus.FINISHED, outcome, None, None)
        flagged = ClockSnapshot(0, 280_000, None, ClockState.FLAGGED, "w")
        snapshot = game_snapshot(lifecycle=finished, clock=flagged)
        self.assertEqual(snapshot.lifecycle.outcome, outcome)
        with self.assertRaisesRegex(
            MultiplayerContractError,
            "active timed multiplayer game",
        ):
            game_snapshot(clock=flagged)

    def test_untimed_game_reuses_canonical_zero_clock(self) -> None:
        snapshot = MultiplayerGameSnapshot(
            game_id="game-u",
            sequence=0,
            white_player_id="alice",
            black_player_id="bob",
            time_control=TimeControl(0, 0),
            position_revision="initial",
            side_to_move="w",
            clock=ClockSnapshot(0, 0, None, ClockState.STOPPED),
            lifecycle=ACTIVE,
        )
        self.assertTrue(snapshot.time_control.untimed)
        with self.assertRaisesRegex(MultiplayerContractError, "stopped zero"):
            MultiplayerGameSnapshot(
                game_id="game-u",
                sequence=0,
                white_player_id="alice",
                black_player_id="bob",
                time_control=TimeControl(0, 0),
                position_revision="initial",
                side_to_move="w",
                clock=ClockSnapshot(1, 0, None, ClockState.STOPPED),
                lifecycle=ACTIVE,
            )

    def test_game_intent_is_content_bound_and_move_legality_is_not_duplicated(self) -> None:
        snapshot = game_snapshot()
        move = GameIntent(
            "game-1",
            "alice",
            1,
            GameIntentKind.MOVE,
            move_text="opaque-move",
        )
        validate_game_intent(snapshot, move)
        same = GameIntent(
            "game-1",
            "alice",
            1,
            "move",
            move_text="opaque-move",
        )
        self.assertEqual(move.intent_id, same.intent_id)
        self.assertEqual(move.move_text, "opaque-move")
        with self.assertRaisesRegex(MultiplayerContractError, "side to move"):
            validate_game_intent(
                snapshot,
                GameIntent(
                    "game-1",
                    "bob",
                    1,
                    "move",
                    move_text="opaque-move",
                ),
            )
        with self.assertRaisesRegex(MultiplayerContractError, "stale"):
            validate_game_intent(
                snapshot,
                GameIntent(
                    "game-1",
                    "alice",
                    0,
                    "move",
                    move_text="opaque-move",
                ),
            )

    def test_game_intent_round_trip_rejects_tamper_and_control_characters(self) -> None:
        intent = GameIntent("game-1", "alice", 1, "move", move_text="e2e4")
        self.assertEqual(GameIntent.from_record(intent.to_record()), intent)
        tampered = intent.to_record()
        tampered["move_text"] = "e2e3"
        with self.assertRaisesRegex(MultiplayerContractError, "intent id does not match"):
            GameIntent.from_record(tampered)
        with self.assertRaisesRegex(MultiplayerContractError, "control characters"):
            GameIntent("game-1", "alice", 1, "move", move_text="e2\x00e4")

    def test_draw_intents_delegate_state_to_canonical_lifecycle_snapshot(self) -> None:
        offered = LifecycleSnapshot(GameStatus.ACTIVE, None, "w", None)
        snapshot = game_snapshot(lifecycle=offered)
        validate_game_intent(
            snapshot,
            GameIntent("game-1", "bob", 1, "accept_draw"),
        )
        validate_game_intent(
            snapshot,
            GameIntent("game-1", "bob", 1, "decline_draw"),
        )
        with self.assertRaisesRegex(MultiplayerContractError, "own draw offer"):
            validate_game_intent(
                snapshot,
                GameIntent("game-1", "alice", 1, "accept_draw"),
            )
        with self.assertRaisesRegex(MultiplayerContractError, "already pending"):
            validate_game_intent(
                snapshot,
                GameIntent("game-1", "bob", 1, "offer_draw"),
            )

    def test_resign_and_rematch_intents_have_server_authoritative_handshake(self) -> None:
        snapshot = game_snapshot()
        validate_game_intent(snapshot, GameIntent("game-1", "alice", 1, "resign"))
        with self.assertRaisesRegex(MultiplayerContractError, "finished game"):
            validate_game_intent(snapshot, GameIntent("game-1", "alice", 1, "request_rematch"))

        finished = game_snapshot(
            lifecycle=LifecycleSnapshot(
                GameStatus.FINISHED,
                GameOutcome("0-1", EndReason.RESIGNATION, "b"),
                None,
                None,
            )
        )
        validate_game_intent(
            finished,
            GameIntent("game-1", "alice", 1, "request_rematch"),
        )
        with self.assertRaisesRegex(MultiplayerContractError, "no pending rematch"):
            validate_game_intent(
                finished,
                GameIntent("game-1", "bob", 1, "accept_rematch"),
            )

        pending = game_snapshot(
            lifecycle=finished.lifecycle,
            rematch_requested_by="alice",
        )
        validate_game_intent(
            pending,
            GameIntent("game-1", "bob", 1, "accept_rematch"),
        )
        with self.assertRaisesRegex(MultiplayerContractError, "own rematch"):
            validate_game_intent(
                pending,
                GameIntent("game-1", "alice", 1, "accept_rematch"),
            )
        with self.assertRaisesRegex(MultiplayerContractError, "already pending"):
            validate_game_intent(
                pending,
                GameIntent("game-1", "bob", 1, "request_rematch"),
            )
        with self.assertRaisesRegex(MultiplayerContractError, "active game"):
            validate_game_intent(
                finished,
                GameIntent("game-1", "alice", 1, "resign"),
            )

        with self.assertRaisesRegex(MultiplayerContractError, "active game cannot carry"):
            game_snapshot(rematch_requested_by="alice")

    def test_reconnect_intent_is_bounded_and_carries_only_sequence_checkpoint(self) -> None:
        snapshot = game_snapshot(
            white_presence=PresenceState.RECONNECTING,
        )
        reconnect = GameIntent(
            "game-1",
            "alice",
            1,
            "reconnect",
            resume_from_sequence=0,
        )
        validate_game_intent(snapshot, reconnect)
        self.assertEqual(reconnect.resume_from_sequence, 0)
        with self.assertRaisesRegex(MultiplayerContractError, "cannot exceed"):
            GameIntent(
                "game-1",
                "alice",
                1,
                "reconnect",
                resume_from_sequence=2,
            )

    def test_snapshot_tracker_accepts_monotonic_server_snapshots_and_reconnect_jump(self) -> None:
        first = game_snapshot(sequence=3, position_revision="pos-3")
        tracker = MultiplayerSnapshotTracker(first)
        self.assertFalse(tracker.apply(first))
        after_reconnect = game_snapshot(
            sequence=9,
            side_to_move="b",
            position_revision="pos-9",
            clock=ClockSnapshot(
                290_000,
                280_000,
                "b",
                ClockState.RUNNING,
            ),
        )
        self.assertTrue(tracker.apply(after_reconnect))
        self.assertEqual(tracker.snapshot, after_reconnect)

    def test_snapshot_tracker_rejects_stale_conflict_identity_change_and_finished_revival(self) -> None:
        current = game_snapshot(sequence=5, position_revision="pos-5")
        tracker = MultiplayerSnapshotTracker(current)
        with self.assertRaisesRegex(MultiplayerContractError, "stale"):
            tracker.apply(
                game_snapshot(
                    sequence=4,
                    position_revision="pos-4",
                )
            )
        with self.assertRaisesRegex(MultiplayerContractError, "conflicting"):
            tracker.apply(
                game_snapshot(
                    sequence=5,
                    position_revision="different",
                )
            )
        mutated = MultiplayerGameSnapshot(
            game_id="game-1",
            sequence=6,
            white_player_id="alice",
            black_player_id="carol",
            time_control=CONTROL,
            position_revision="pos-6",
            side_to_move="w",
            clock=ClockSnapshot(
                300_000,
                300_000,
                "w",
                ClockState.RUNNING,
            ),
            lifecycle=ACTIVE,
        )
        with self.assertRaisesRegex(MultiplayerContractError, "identity changed"):
            tracker.apply(mutated)

        finished = game_snapshot(
            sequence=8,
            lifecycle=LifecycleSnapshot(
                GameStatus.FINISHED,
                GameOutcome("1-0", EndReason.RESIGNATION, "w"),
                None,
                None,
            ),
        )
        terminal = MultiplayerSnapshotTracker(finished)
        with self.assertRaisesRegex(MultiplayerContractError, "cannot return"):
            terminal.apply(game_snapshot(sequence=9))

    def test_recovery_json_is_deterministic_tamper_evident_and_duplicate_key_safe(self) -> None:
        tracker = MultiplayerSnapshotTracker(game_snapshot())
        encoded = tracker.to_json()
        self.assertEqual(encoded, tracker.to_json())
        restored = MultiplayerSnapshotTracker.from_json(encoded)
        self.assertEqual(restored.snapshot, tracker.snapshot)

        record = json.loads(encoded)
        record["snapshot"]["position_revision"] = "tampered"
        with self.assertRaisesRegex(MultiplayerContractError, "digest mismatch"):
            MultiplayerSnapshotTracker.from_record(record)
        with self.assertRaisesRegex(MultiplayerContractError, "duplicate JSON key"):
            MultiplayerSnapshotTracker.from_json('{"version":1,"version":1}')
        with self.assertRaisesRegex(MultiplayerContractError, "non-finite"):
            MultiplayerSnapshotTracker.from_json('{"x":NaN}')

    def test_wire_round_trip_rejects_unknown_fields_and_unbounded_identifiers(self) -> None:
        snapshot = game_snapshot()
        record = snapshot.to_record()
        restored = MultiplayerGameSnapshot.from_record(record)
        self.assertEqual(restored, snapshot)
        record["extra"] = True
        with self.assertRaisesRegex(MultiplayerContractError, "schema mismatch"):
            MultiplayerGameSnapshot.from_record(record)
        with self.assertRaisesRegex(MultiplayerContractError, "opaque identifier"):
            game_snapshot().__class__(
                game_id="../game",
                sequence=1,
                white_player_id="alice",
                black_player_id="bob",
                time_control=CONTROL,
                position_revision="pos-1",
                side_to_move="w",
                clock=ClockSnapshot(
                    300_000,
                    300_000,
                    "w",
                    ClockState.RUNNING,
                ),
                lifecycle=ACTIVE,
            )
        with self.assertRaisesRegex(MultiplayerContractError, "opaque identifier"):
            ChallengeSnapshot(
                challenge_id=123,  # type: ignore[arg-type]
                challenger_id="alice",
                opponent_id="bob",
                time_control=CONTROL,
            )


if __name__ == "__main__":
    unittest.main()

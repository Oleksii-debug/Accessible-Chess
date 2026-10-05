from __future__ import annotations

import ast
from pathlib import Path
import unittest

from acs.structured_broadcast import (
    BroadcastApplyKind,
    BroadcastApplyResult,
    BroadcastConnectionState,
    BroadcastContractError,
    BroadcastErrorCode,
    BroadcastReconnectPolicy,
    CanonicalBroadcastGame,
    LichessBroadcastRound,
)
from acs.structured_broadcast_live import (
    AccessibleLiveEvent,
    LichessStructuredBroadcastProvider,
    LiveBroadcastError,
    LiveEventKind,
    LivePositionHistory,
    LiveSelectionState,
    MAX_LIVE_POSITION_HISTORY,
    MediaClockOffset,
    StructuredBroadcastProvider,
    connection_event,
    navigation_event,
    position_event,
    resolve_game_selection,
    selection_event,
)


def game(game_id="g1", ref="tree:g1:n1", revision="r1"):
    return CanonicalBroadcastGame(game_id, ref, revision)


def result(sequence, observed, *games):
    return BroadcastApplyResult(
        kind=BroadcastApplyKind.APPLIED,
        sequence=sequence,
        observed_at_ms=observed,
        payload_sha256="0" * 64,
        changed_game_ids=tuple(item.provider_game_id for item in games),
        games=tuple(games),
    )


class StructuredBroadcastLiveTests(unittest.TestCase):
    def test_lichess_provider_implements_transport_seam_without_token(self):
        provider = LichessStructuredBroadcastProvider(
            LichessBroadcastRound("Ab12Cd34"),
            BroadcastReconnectPolicy(base_delay_ms=1000, max_delay_ms=8000),
        )
        self.assertIsInstance(provider, StructuredBroadcastProvider)
        request = provider.stream_request()
        self.assertEqual(request.provider, "lichess")
        self.assertEqual(request.oauth_scopes, ("study:read",))
        self.assertEqual(request.expected_media_type, "application/x-chess-pgn")
        self.assertNotIn("token", request.url.lower())
        self.assertEqual(provider.reconnect_delay_ms(2), 4000)
        self.assertEqual(provider.reconnect_delay_ms(1, retry_after_ms=7000), 7000)

    def test_game_selection_never_guesses_when_multiple_games_exist(self):
        games = (game("g2"), game("g1"))
        ambiguous = resolve_game_selection(games)
        self.assertEqual(ambiguous.state, LiveSelectionState.AMBIGUOUS)
        self.assertIsNone(ambiguous.selected_game_id)
        self.assertEqual(ambiguous.available_game_ids, ("g1", "g2"))
        chosen = resolve_game_selection(games, "g2")
        self.assertEqual(chosen.state, LiveSelectionState.SELECTED)
        self.assertEqual(chosen.selected_game_id, "g2")
        with self.assertRaises(BroadcastContractError) as missing:
            resolve_game_selection(games, "missing")
        self.assertEqual(missing.exception.code, BroadcastErrorCode.GAME_NOT_FOUND)
        with self.assertRaises(BroadcastContractError) as duplicate:
            resolve_game_selection((game("g1"), game("g1")))
        self.assertEqual(duplicate.exception.code, BroadcastErrorCode.DUPLICATE_GAME)
        self.assertEqual(resolve_game_selection(()).state, LiveSelectionState.NONE)
        self.assertEqual(resolve_game_selection((game(),)).selected_game_id, "g1")

    def test_media_clock_offset_is_signed_bounded_and_invertible(self):
        offset = MediaClockOffset(5000)
        self.assertEqual(offset.media_time_ms(10_000), 15_000)
        self.assertEqual(offset.structured_time_ms(15_000), 10_000)
        negative = MediaClockOffset(-3000)
        self.assertEqual(negative.media_time_ms(10_000), 7000)
        with self.assertRaises(LiveBroadcastError):
            MediaClockOffset(24 * 60 * 60 * 1000 + 1)
        with self.assertRaises(LiveBroadcastError):
            MediaClockOffset(True)
        with self.assertRaises(LiveBroadcastError):
            offset.structured_time_ms(1000)

    def test_history_tracks_canonical_revisions_and_preserves_browse_cursor(self):
        history = LivePositionHistory("g1")
        self.assertTrue(history.record(result(1, 1000, game("g1", "tree:n1", "r1"))))
        self.assertTrue(history.record(result(2, 1100, game("g1", "tree:n2", "r2"))))
        self.assertFalse(history.record(result(3, 1200, game("g1", "tree:n2", "r2"))))
        self.assertEqual(history.current.canonical_revision, "r2")
        self.assertTrue(history.follow_live)
        self.assertEqual(history.previous().canonical_revision, "r1")
        self.assertFalse(history.follow_live)
        self.assertTrue(history.record(result(4, 1300, game("g1", "tree:n3", "r3"))))
        self.assertEqual(history.current.canonical_revision, "r1")
        self.assertEqual(history.next().canonical_revision, "r2")
        self.assertFalse(history.follow_live)
        self.assertEqual(history.next().canonical_revision, "r3")
        self.assertTrue(history.follow_live)

    def test_no_change_result_advances_sequence_and_time_watermarks(self):
        history = LivePositionHistory("g1")
        self.assertTrue(history.record(result(1, 1000, game("g1", "tree:n1", "r1"))))
        self.assertFalse(history.record(result(2, 1100, game("g1", "tree:n1", "r1"))))

        with self.assertRaises(BroadcastContractError) as same_sequence:
            history.record(result(2, 1200, game("g1", "tree:n2", "r2")))
        self.assertEqual(same_sequence.exception.code, BroadcastErrorCode.REVISION_CONFLICT)

        with self.assertRaises(BroadcastContractError) as backward_sequence:
            history.record(result(1, 1300, game("g1", "tree:n1", "r1")))
        self.assertEqual(backward_sequence.exception.code, BroadcastErrorCode.OUT_OF_ORDER)

        with self.assertRaises(BroadcastContractError) as backward_time:
            history.record(result(3, 1099, game("g1", "tree:n2", "r2")))
        self.assertEqual(backward_time.exception.code, BroadcastErrorCode.OUT_OF_ORDER)

    def test_history_rejects_out_of_order_or_conflicting_canonical_results(self):
        history = LivePositionHistory("g1")
        history.record(result(2, 2000, game("g1", "tree:n2", "r2")))
        with self.assertRaises(BroadcastContractError) as backward:
            history.record(result(1, 3000, game("g1", "tree:n1", "r1")))
        self.assertEqual(backward.exception.code, BroadcastErrorCode.OUT_OF_ORDER)
        with self.assertRaises(BroadcastContractError) as same_sequence:
            history.record(result(2, 2100, game("g1", "tree:n3", "r3")))
        self.assertEqual(same_sequence.exception.code, BroadcastErrorCode.REVISION_CONFLICT)
        with self.assertRaises(BroadcastContractError) as conflicting_ref:
            history.record(result(3, 2200, game("g1", "tree:other", "r2")))
        self.assertEqual(conflicting_ref.exception.code, BroadcastErrorCode.REVISION_CONFLICT)

    def test_history_is_bounded_and_marks_truncation(self):
        history = LivePositionHistory("g1")
        for index in range(MAX_LIVE_POSITION_HISTORY + 2):
            history.record(result(index, index, game("g1", f"tree:n{index}", f"r{index}")))
        self.assertEqual(len(history.items), MAX_LIVE_POSITION_HISTORY)
        self.assertTrue(history.history_truncated)
        self.assertEqual(history.current.canonical_revision, f"r{MAX_LIVE_POSITION_HISTORY + 1}")

    def test_truncation_preserves_browsed_oldest_revision_and_discloses_it(self):
        history = LivePositionHistory("g1")
        for index in range(MAX_LIVE_POSITION_HISTORY):
            self.assertTrue(
                history.record(
                    result(
                        index,
                        index,
                        game("g1", f"tree:n{index}", f"r{index}"),
                    )
                )
            )

        for _ in range(MAX_LIVE_POSITION_HISTORY - 1):
            history.previous()
        pinned = history.current
        self.assertIsNotNone(pinned)
        self.assertFalse(history.follow_live)

        self.assertTrue(
            history.record(
                result(
                    MAX_LIVE_POSITION_HISTORY,
                    MAX_LIVE_POSITION_HISTORY,
                    game(
                        "g1",
                        f"tree:n{MAX_LIVE_POSITION_HISTORY}",
                        f"r{MAX_LIVE_POSITION_HISTORY}",
                    ),
                )
            )
        )
        self.assertEqual(len(history.items), MAX_LIVE_POSITION_HISTORY)
        self.assertTrue(history.history_truncated)
        self.assertEqual(history.current, pinned)
        self.assertEqual(history.items[0], pinned)
        self.assertFalse(history.follow_live)

        event = navigation_event(history)
        self.assertEqual(event.visible_text, event.announcement_text)
        self.assertIn("truncated", event.visible_text.lower())

    def test_navigation_edges_fail_closed(self):
        history = LivePositionHistory("g1")
        with self.assertRaises(LiveBroadcastError):
            history.previous()
        history.record(result(1, 1000, game()))
        with self.assertRaises(LiveBroadcastError):
            history.previous()
        with self.assertRaises(LiveBroadcastError):
            history.next()
        self.assertEqual(history.jump_to_live().canonical_revision, "r1")

    def test_status_events_are_visible_copyable_and_announcement_equivalent(self):
        connected = connection_event(BroadcastConnectionState.CONNECTED)
        stale = connection_event(BroadcastConnectionState.STALE)
        ambiguous = selection_event(resolve_game_selection((game("g1"), game("g2"))))
        self.assertEqual(connected.visible_text, connected.announcement_text)
        self.assertIn("connected", connected.visible_text.lower())
        self.assertIn("stale", stale.visible_text.lower())
        self.assertEqual(ambiguous.visible_text, ambiguous.announcement_text)
        self.assertIn("Select a game", ambiguous.visible_text)
        with self.assertRaises(ValueError):
            AccessibleLiveEvent(LiveEventKind.CONNECTION, "Visible", "Different")

    def test_position_and_navigation_events_do_not_expose_opaque_revision(self):
        history = LivePositionHistory("g1")
        history.record(result(1, 1000, game("g1", "tree:opaque", "secret-revision-digest")))
        event = position_event(history.current)
        nav = navigation_event(history)
        self.assertEqual(event.visible_text, event.announcement_text)
        self.assertNotIn("secret-revision-digest", event.visible_text)
        self.assertEqual(nav.visible_text, nav.announcement_text)
        self.assertIn("Following live", nav.visible_text)

    def test_live_orchestration_has_no_pgn_parser_rules_or_network_io(self):
        path = Path(__file__).resolve().parents[1] / "acs" / "structured_broadcast_live.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = ("pgn_roundtrip", "gametree", "board_service", "notation", "requests", "urllib", "httpx", "aiohttp", "socket")
        for module in imported:
            self.assertFalse(any(fragment in module for fragment in forbidden), module)


if __name__ == "__main__":
    unittest.main()

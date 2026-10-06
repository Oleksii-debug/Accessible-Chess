from __future__ import annotations

import ast
from pathlib import Path
import unittest

from acs.structured_broadcast import StructuredBroadcastEnvelope, StructuredBroadcastSession
from acs.structured_broadcast_application import (
    BroadcastApplicationError,
    BroadcastApplicationErrorCode,
    LichessCanonicalBroadcastAdapter,
    MAX_CANONICAL_BROADCAST_POSITIONS,
)


ROUND = "Mj1X8U9H"
SOURCE = "broadcast:Mj1X8U9H"


def pgn(
    game_id: str = "1jbwRQGy",
    moves: str = "1. e4 e5 *",
    *,
    comment: str = "",
    site_id: str | None = None,
    round_id: str = ROUND,
    variant: str = "Standard",
) -> str:
    site_game = site_id if site_id is not None else game_id
    move_text = moves if not comment else moves.replace("e4", f"e4 {{{comment}}}", 1)
    return (
        '[Event "Knight Invitational"]\n'
        f'[Site "https://lichess.org/broadcast/knight-invitational-2/final-round-2/{round_id}/{site_game}"]\n'
        '[Date "2026.09.19"]\n'
        '[White "Player 1"]\n'
        '[Black "Player 2"]\n'
        '[Result "*"]\n'
        f'[Variant "{variant}"]\n'
        '[BroadcastName "Knight Invitational 2"]\n'
        f'[BroadcastURL "https://lichess.org/broadcast/knight-invitational-2/final-round-2/{round_id}"]\n'
        f'[GameURL "https://lichess.org/broadcast/knight-invitational-2/final-round-2/{round_id}/{game_id}"]\n\n'
        f"{move_text}\n"
    )


class StructuredBroadcastApplicationTests(unittest.TestCase):
    def adapter(self) -> LichessCanonicalBroadcastAdapter:
        return LichessCanonicalBroadcastAdapter()

    def ingest(self, adapter: LichessCanonicalBroadcastAdapter, text: str):
        return adapter.ingest_broadcast_pgn(
            provider="lichess",
            round_id=ROUND,
            source_id=SOURCE,
            pgn_text=text,
        )

    def test_official_lichess_multi_game_shape_uses_canonical_game_urls(self):
        adapter = self.adapter()
        text = pgn("1jbwRQGy", "1. e4 e5 *") + "\n" + pgn(
            "wWWXZ4ZM", "1. d4 d5 *"
        )
        games = self.ingest(adapter, text)

        self.assertEqual(
            tuple(game.provider_game_id for game in games),
            ("1jbwRQGy", "wWWXZ4ZM"),
        )
        self.assertTrue(all(game.chess_ref.startswith("ac-live-v1:") for game in games))
        self.assertTrue(
            all(game.canonical_revision.startswith("position-v1:") for game in games)
        )
        first = adapter.resolve_chess_ref(games[0].chess_ref)
        self.assertEqual(first.chess_ref, games[0].chess_ref)
        self.assertEqual(first.canonical_revision, games[0].canonical_revision)
        self.assertEqual(len(first.final_fen.split()), 6)

    def test_structured_session_accepts_real_adapter_without_media_parsing_chess(self):
        adapter = self.adapter()
        session = StructuredBroadcastSession(
            provider="lichess", round_id=ROUND, source_id=SOURCE
        )
        result = session.apply(
            StructuredBroadcastEnvelope(
                provider="lichess",
                round_id=ROUND,
                source_id=SOURCE,
                sequence=1,
                observed_at_ms=1000,
                pgn_text=pgn(),
            ),
            adapter,
        )
        self.assertEqual(result.changed_game_ids, ("1jbwRQGy",))
        link = session.media_link_for_game("1jbwRQGy", timestamp_ms=1500)
        resolved = adapter.resolve_chess_ref(link.chess_ref)
        self.assertEqual(resolved.chess_ref, link.chess_ref)

    def test_comment_and_clock_metadata_do_not_fabricate_a_new_position(self):
        adapter = self.adapter()
        first = self.ingest(adapter, pgn(comment="[%clk 1:01:27]"))[0]
        second = self.ingest(
            adapter,
            pgn(comment="[%clk 1:00:59] changed commentary"),
        )[0]
        self.assertEqual(first.canonical_revision, second.canonical_revision)
        self.assertEqual(first.chess_ref, second.chess_ref)

    def test_canonical_move_change_advances_position_revision_and_reference(self):
        adapter = self.adapter()
        first = self.ingest(adapter, pgn(moves="1. e4 e5 *"))[0]
        second = self.ingest(adapter, pgn(moves="1. e4 e5 2. Nf3 *"))[0]
        self.assertNotEqual(first.canonical_revision, second.canonical_revision)
        self.assertNotEqual(first.chess_ref, second.chess_ref)
        self.assertNotEqual(
            adapter.resolve_chess_ref(first.chess_ref).final_fen,
            adapter.resolve_chess_ref(second.chess_ref).final_fen,
        )

    def test_strict_pgn_and_canonical_legality_fail_closed(self):
        adapter = self.adapter()
        malformed = pgn(moves="1. e4 e5")
        with self.assertRaises(BroadcastApplicationError) as strict:
            self.ingest(adapter, malformed)
        self.assertEqual(
            strict.exception.code,
            BroadcastApplicationErrorCode.CANONICAL_PGN_REJECTED,
        )

        with self.assertRaises(BroadcastApplicationError) as illegal:
            self.ingest(adapter, pgn(moves="1. e5 *"))
        self.assertEqual(illegal.exception.code, BroadcastApplicationErrorCode.ILLEGAL_GAME)

        with self.assertRaises(BroadcastApplicationError) as variant:
            self.ingest(adapter, pgn(variant="Chess960"))
        self.assertEqual(variant.exception.code, BroadcastApplicationErrorCode.ILLEGAL_GAME)

    def test_provider_identity_is_round_bound_and_conflicts_fail_closed(self):
        adapter = self.adapter()
        with self.assertRaises(BroadcastApplicationError) as wrong_round:
            self.ingest(adapter, pgn(round_id="Ab12Cd34"))
        self.assertEqual(
            wrong_round.exception.code,
            BroadcastApplicationErrorCode.INVALID_PROVIDER_GAME_ID,
        )

        with self.assertRaises(BroadcastApplicationError) as conflict:
            self.ingest(adapter, pgn(site_id="wWWXZ4ZM"))
        self.assertEqual(
            conflict.exception.code,
            BroadcastApplicationErrorCode.INVALID_PROVIDER_GAME_ID,
        )

        with self.assertRaises(BroadcastApplicationError) as provider:
            adapter.ingest_broadcast_pgn(
                provider="other",
                round_id=ROUND,
                source_id=SOURCE,
                pgn_text=pgn(),
            )
        self.assertEqual(
            provider.exception.code,
            BroadcastApplicationErrorCode.UNSUPPORTED_PROVIDER,
        )

    def test_multi_game_ingest_is_atomic_before_application_publication(self):
        adapter = self.adapter()
        good = pgn("1jbwRQGy")
        bad = pgn("wWWXZ4ZM", moves="1. e5 *")
        with self.assertRaises(BroadcastApplicationError):
            self.ingest(adapter, good + "\n" + bad)
        with self.assertRaises(BroadcastApplicationError) as missing:
            adapter.current_game("1jbwRQGy")
        self.assertEqual(
            missing.exception.code,
            BroadcastApplicationErrorCode.UNKNOWN_PROVIDER_GAME,
        )

    def test_position_reference_cache_is_bounded_and_evicts_oldest(self):
        adapter = LichessCanonicalBroadcastAdapter(position_cache_limit=2)
        first = self.ingest(adapter, pgn(moves="1. e4 *"))[0]
        second = self.ingest(adapter, pgn(moves="1. e4 e5 *"))[0]
        third = self.ingest(adapter, pgn(moves="1. e4 e5 2. Nf3 *"))[0]

        self.assertEqual(adapter.resolve_chess_ref(second.chess_ref).chess_ref, second.chess_ref)
        self.assertEqual(adapter.resolve_chess_ref(third.chess_ref).chess_ref, third.chess_ref)
        with self.assertRaises(BroadcastApplicationError) as evicted:
            adapter.resolve_chess_ref(first.chess_ref)
        self.assertEqual(
            evicted.exception.code,
            BroadcastApplicationErrorCode.UNKNOWN_CHESS_REF,
        )
        for invalid in (0, MAX_CANONICAL_BROADCAST_POSITIONS + 1, True):
            with self.subTest(invalid=invalid), self.assertRaises(BroadcastApplicationError):
                LichessCanonicalBroadcastAdapter(position_cache_limit=invalid)

    def test_current_game_is_detached_from_application_owned_snapshot(self):
        adapter = self.adapter()
        self.ingest(adapter, pgn())
        detached = adapter.current_game("1jbwRQGy")
        detached.tags["White"] = "Mutated"
        self.assertEqual(adapter.current_game("1jbwRQGy").tags["White"], "Player 1")

    def test_adapter_uses_existing_canonical_services_not_direct_chess_rules_or_network(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "acs"
            / "structured_broadcast_application.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = (
            "chesscore",
            "requests",
            "httpx",
            "aiohttp",
            "socket",
            "urllib.request",
        )
        for module in imported:
            self.assertFalse(any(fragment in module for fragment in forbidden), module)


if __name__ == "__main__":
    unittest.main()

"""Section 50 isolated offline cross-product seam: media -> canonical board -> cloud model.

All HTTP is mocked; this is NOT a real video or authenticated provider PASS.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from acs.chesscore import Board
from acs.media_application import MediaApplicationCode, MediaApplicationError, MediaApplicationService
from acs.media_core import (
    MediaSource, MediaSourceKind, MediaPositionTimeline, MediaChessLink,
    MediaChessSession, MediaCursor, MediaLinkStatus,
    serialize_media_state, deserialize_media_state,
)
from acs.agent_cloud_provider import CloudChatProvider
from acs.agent_model_gateway import ModelGateway
from acs.agent_model_contracts import (
    ModelMessage, ModelRequest, PrivacyClass, ProviderKind,
)

try:
    import httpx
except ImportError:
    httpx = None


def media_fixture(confirmed=True):
    original = MediaSource("video:authored-test", "Chess video fixture",
                           MediaSourceKind.LOCAL_FILE, 20_000)
    timeline = MediaPositionTimeline(
        original.source_id,
        (MediaChessLink(original.source_id, 2000, "gametree:after-e4-e5",
                        status=(MediaLinkStatus.CONFIRMED if confirmed else MediaLinkStatus.CANDIDATE),
                        confidence=1.0 if confirmed else 0.70,
                        evidence="test-only structured reference"),)
    )
    session = MediaChessSession(MediaCursor(original.source_id, 0), "gametree:initial")
    return original, timeline, session


@unittest.skipIf(httpx is None, "optional httpx not installed")
class OfflineMediaAgentBoundary(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cloud = patch.dict(os.environ, {"MISTRAL_API_KEY": "fixture-only-value"})
        self.cloud.start()
        self.addCleanup(self.cloud.stop)

    async def test_media_provider_response_cannot_advance_canonical_board(self):
        board = Board()
        initial = board.fen()
        expected = Board()
        expected.push_text("e4")
        expected.push_text("e5")
        legal_after = expected.fen()
        refs = {"gametree:initial": initial, "gametree:after-e4-e5": legal_after}
        def restore(ref):
            board.set_fen(refs[ref])
        source, timeline, session = media_fixture()
        app = MediaApplicationService(
            source=source, timeline=timeline, session=session,
            restore_chess_ref=restore,
        )
        calls = []
        def handler(req):
            calls.append(req.url.path)
            return httpx.Response(200, json={
                "model": "fixture-model",
                "choices": [{"message": {"role": "assistant",
                                         "content": "Invented move: Qh9"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            })
        adapter = CloudChatProvider(
            provider_id="mistral", default_model="fixture-model",
            allow_live_requests=True,
            client_factory=lambda **kw: httpx.AsyncClient(
                transport=httpx.MockTransport(handler), **kw),
        )
        gateway = ModelGateway()
        gateway.register(adapter)
        response = await gateway.complete(ModelRequest(
            request_id="media-agent-offline", provider_id="mistral",
            provider_kind=ProviderKind.CLOUD, privacy=PrivacyClass.PUBLIC,
            model="fixture-model", timeout_seconds=3,
            messages=(ModelMessage("user", "What move follows 1. e4 e5?"),),
        ))
        self.assertIn("Qh9", response.text)
        self.assertEqual(board.fen(), initial, "untrusted model must not change board")
        snapshot = app.seek_media(2500)
        self.assertEqual(snapshot.synchronized_chess_ref, "gametree:after-e4-e5")
        self.assertEqual(board.fen(), initial, "media seek alone must not change board")
        app.restore_media_position()
        self.assertEqual(board.fen(), legal_after,
                         "only explicit canonical application restore updates board")
        self.assertEqual(calls, ["/v1/chat/completions"])

        preserved = serialize_media_state(source, timeline, app.session)
        source2, timeline2, session2 = deserialize_media_state(preserved)
        app2 = MediaApplicationService(
            source=source2, timeline=timeline2, session=session2,
            restore_chess_ref=restore,
        )
        self.assertEqual(app2.snapshot().synchronized_chess_ref,
                         "gametree:after-e4-e5")
        self.assertTrue(app2.snapshot().can_restore)
        self.assertEqual(app2.session.chess_ref, "gametree:after-e4-e5")

    async def test_ambiguous_candidate_does_not_publish_chess_state(self):
        board = Board()
        initial = board.fen()
        source, timeline, session = media_fixture(confirmed=False)
        attempts = []
        app = MediaApplicationService(
            source=source, timeline=timeline, session=session,
            restore_chess_ref=lambda ref: attempts.append(ref),
        )
        app.seek_media(2500)
        with self.assertRaises(MediaApplicationError) as captured:
            app.restore_media_position()
        self.assertEqual(captured.exception.code,
                         MediaApplicationCode.NO_CONFIRMED_POSITION)
        self.assertEqual(board.fen(), initial)
        self.assertFalse(attempts)
        self.assertEqual(app.session.chess_ref, "gametree:initial")


if __name__ == "__main__":
    unittest.main()

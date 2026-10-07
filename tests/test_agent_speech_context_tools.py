from __future__ import annotations

import asyncio
import unittest

from acs.agent_speech_context_tools import AgentSpeechContextTools
from acs.agent_tools import ToolCall, ToolExecutor
from acs.media_foundation import TranscriptSegment
from acs.media_subtitles import SubtitleContext


class AgentSpeechContextToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.allowed = True
        context = SubtitleContext(
            source_id="media-1",
            source_revision="rev-1",
            source_sha256="0" * 64,
            language="uk",
            segments=(
                TranscriptSegment(
                    segment_id="s1",
                    start_ms=1000,
                    end_ms=3000,
                    text="Кінь переходить на f3.",
                ),
            ),
        )
        self.executor = ToolExecutor()
        AgentSpeechContextTools(
            context,
            current_media=lambda: ("media-1", "rev-1", 2000),
            context_allowed=lambda: self.allowed,
        ).register(self.executor)

    def execute(self, arguments=None):
        return asyncio.run(
            self.executor.execute(
                ToolCall(
                    call_id="speech",
                    tool_id="speech_context.around_current_time",
                    arguments=arguments or {},
                )
            )
        )

    def test_registered_context_is_bounded_read_only_evidence(self):
        result = self.execute({"before_ms": 1500, "after_ms": 1500})
        self.assertTrue(result.ok)
        self.assertEqual(result.output["sourceId"], "media-1")
        self.assertEqual(result.output["sourceRevision"], "rev-1")
        self.assertEqual(result.output["language"], "uk")
        self.assertEqual(result.output["segments"][0]["text"], "Кінь переходить на f3.")
        self.assertFalse(result.output["chessAuthority"])

    def test_live_permission_revocation_fails_closed(self):
        self.allowed = False
        result = self.execute()
        self.assertFalse(result.ok)

    def test_unknown_argument_fails_closed(self):
        result = self.execute({"source_id": "other"})
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()

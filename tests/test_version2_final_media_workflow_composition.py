from __future__ import annotations

import unittest

from acs import version2_final_release as release
from acs import version2_release_ui
from acs.media_application import MediaApplicationService
from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaSource,
    MediaSourceKind,
)
from acs.media_user_workflow import (
    MediaUserWorkflowContext,
    MediaUserWorkflowService,
)


class _Api:
    def __init__(self, language: str = "en") -> None:
        self.lang = language
        self.invocations = 0

    def _invoke_ui(self, callback):
        self.invocations += 1
        return callback()


def _workflow(restored: list[str]) -> tuple[MediaUserWorkflowService, MediaApplicationService]:
    source_id = "youtube:dQw4w9WgXcQ"
    source = MediaSource(
        source_id=source_id,
        title="Section 20 YouTube fixture",
        kind=MediaSourceKind.PROVIDER,
        duration_ms=60_000,
    )
    timeline = MediaPositionTimeline(
        source_id,
        (
            MediaChessLink(
                source_id,
                20_000,
                "opaque:canonical-media-position",
                status=MediaLinkStatus.CONFIRMED,
                confidence=1.0,
            ),
        ),
    )
    application = MediaApplicationService(
        source=source,
        timeline=timeline,
        session=MediaChessSession(
            MediaCursor(source_id, 20_500),
            "opaque:analysis-position",
        ),
        restore_chess_ref=lambda value: restored.append(value),
    )
    workflow = MediaUserWorkflowService(
        open_pasted_source=lambda _source: MediaUserWorkflowContext(
            application=application,
            provider_kind="youtube",
        ),
        language="en",
    )
    return workflow, application


class Version2FinalMediaWorkflowCompositionTests(unittest.TestCase):
    def test_final_release_exposes_open_sync_and_restore_without_browser_chess_refs(self) -> None:
        restored: list[str] = []
        workflow, application = _workflow(restored)
        api = _Api()
        release._bind_api_media_workflow(api, workflow)

        opened = api.media_workflow_open_pasted(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        self.assertEqual("youtube", opened["providerKind"])
        self.assertNotIn("opaque:", repr(opened))

        synchronized = api.media_workflow_sync_playback(
            "youtube:dQw4w9WgXcQ",
            20_500,
            60_000,
            "paused",
        )
        self.assertEqual("confirmed", synchronized["player"]["qualification"])
        self.assertTrue(synchronized["player"]["restoreEnabled"])
        self.assertNotIn("opaque:", repr(synchronized))

        application.select_analysis_chess_ref("opaque:explored-variation")
        restored_state = api.media_workflow_command("restore", None)
        self.assertEqual(["opaque:canonical-media-position"], restored)
        self.assertNotIn("opaque:", repr(restored_state))
        self.assertIn("Restored", restored_state["player"]["announcement"])
        self.assertEqual(3, api.invocations)

    def test_unbound_workflow_fails_closed_with_accessible_player_state(self) -> None:
        api = _Api("uk")
        release._bind_api_media_workflow(api, None)

        state = api.media_workflow_snapshot()

        self.assertFalse(state["ok"])
        self.assertIsNone(state["providerKind"])
        self.assertFalse(state["player"]["restoreEnabled"])
        self.assertFalse(state["player"]["seekEnabled"])
        self.assertIn("недоступ", state["player"]["announcement"].lower())

    def test_media_workflow_resources_are_ordered_after_product_root_and_before_fallback(self) -> None:
        labels = [label for label, _source in release._final_product_resource_sources()]

        player = labels.index("Recorded Media accessible player")
        youtube = labels.index("YouTube IFrame playback adapter")
        product = labels.index("V2 final-product bootstrap")
        workflow = labels.index("V2 Media user workflow bootstrap")
        fallback = labels.index("V2 Media Restore Position bootstrap")
        p0 = labels.index("P0 event-aware accessibility runtime")

        self.assertLess(player, product)
        self.assertLess(youtube, product)
        self.assertLess(product, workflow)
        self.assertLess(workflow, fallback)
        self.assertLess(fallback, p0)

    def test_workflow_api_class_bindings_are_scoped_to_final_product_lifetime(self) -> None:
        api_type = version2_release_ui.Version2ReleaseAccessibleChessAPI
        names = tuple(release._WORKFLOW_API_METHODS)
        before = {
            name: (
                name in api_type.__dict__,
                api_type.__dict__.get(name),
            )
            for name in names
        }

        with release._final_product_bindings():
            for name, method in release._WORKFLOW_API_METHODS.items():
                self.assertIs(api_type.__dict__[name], method)

        for name in names:
            existed, value = before[name]
            self.assertEqual(name in api_type.__dict__, existed)
            self.assertIs(api_type.__dict__.get(name), value)

    def test_workflow_composition_rejects_duck_typed_parallel_authority(self) -> None:
        api = _Api()
        with self.assertRaisesRegex(TypeError, "MediaUserWorkflowService"):
            release._bind_api_media_workflow(api, object())
        with self.assertRaisesRegex(TypeError, "MediaUserWorkflowService"):
            release.create_version2_release_application(
                media_user_workflow_service=object(),
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from acs import version2_final_release as release
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


class _Api:
    def __init__(self, language: str = "en") -> None:
        self.lang = language
        self.invocations = 0

    def _invoke_ui(self, callback):
        self.invocations += 1
        return callback()


def _service(restored: list[str]) -> MediaApplicationService:
    source = MediaSource(
        source_id="product-media",
        title="Product Media",
        kind=MediaSourceKind.LOCAL_FILE,
        duration_ms=60_000,
    )
    timeline = MediaPositionTimeline(
        "product-media",
        (
            MediaChessLink(
                "product-media",
                20_000,
                "opaque:canonical-position",
                status=MediaLinkStatus.CONFIRMED,
                confidence=1.0,
                evidence="trusted product fixture",
            ),
        ),
    )
    session = MediaChessSession(
        MediaCursor("product-media", 20_500),
        "opaque:analysis-only",
    )
    return MediaApplicationService(
        source=source,
        timeline=timeline,
        session=session,
        restore_chess_ref=lambda value: restored.append(value),
    )


class Version2FinalMediaRestoreCompositionTests(unittest.TestCase):
    def test_unbound_product_surface_is_truthful_disabled_and_copyable(self) -> None:
        api = _Api()
        release._bind_api_media(api, None)

        state = api.media_restore_snapshot()

        self.assertFalse(state["ok"])
        self.assertFalse(state["restoreEnabled"])
        self.assertEqual("unavailable", state["qualification"])
        self.assertEqual("media-sync-status", state["focusTarget"])
        self.assertIn("unavailable", state["statusText"].lower())
        self.assertEqual(1, api.invocations)

        restored = api.media_restore_position()
        self.assertFalse(restored["ok"])
        self.assertEqual(restored["statusText"], restored["announcement"])
        self.assertEqual(2, api.invocations)

    def test_bound_product_surface_delegates_only_to_canonical_media_service(self) -> None:
        restored_refs: list[str] = []
        api = _Api()
        service = _service(restored_refs)
        release._bind_api_media(api, service)

        snapshot = api.media_restore_snapshot()
        self.assertTrue(snapshot["ok"])
        self.assertTrue(snapshot["restoreEnabled"])
        self.assertEqual("confirmed", snapshot["qualification"])
        self.assertNotIn("opaque:canonical-position", repr(snapshot))
        self.assertNotIn("opaque:analysis-only", repr(snapshot))

        result = api.media_restore_position()
        self.assertTrue(result["ok"])
        self.assertEqual(["opaque:canonical-position"], restored_refs)
        self.assertIn("Restored the chess position", result["announcement"])
        self.assertNotIn("opaque:canonical-position", repr(result))
        self.assertNotIn("opaque:analysis-only", repr(result))
        self.assertEqual(2, api.invocations)

    def test_media_projection_follows_current_product_language_without_new_authority(self) -> None:
        api = _Api("en")
        release._bind_api_media(api, _service([]))
        self.assertEqual("Restore Media Position", api.media_restore_snapshot()["restoreLabel"])

        api.lang = "uk"
        state = api.media_restore_snapshot()
        self.assertEqual("Відновити позицію медіа", state["restoreLabel"])
        self.assertIn("Позицію шахів підтверджено", state["statusText"])

    def test_final_product_resources_load_media_renderer_before_product_bootstrap(self) -> None:
        labels = [label for label, _source in release._final_product_resource_sources()]

        renderer = labels.index("Media accessible Restore Position surface")
        product = labels.index("V2 final-product bootstrap")
        media = labels.index("V2 Media Restore Position bootstrap")
        p0 = labels.index("P0 event-aware accessibility runtime")
        self.assertLess(renderer, product)
        self.assertLess(product, media)
        self.assertLess(media, p0)

    def test_media_service_composition_rejects_parallel_or_duck_typed_authority(self) -> None:
        api = _Api()
        with self.assertRaisesRegex(TypeError, "MediaApplicationService"):
            release._bind_api_media(api, object())
        with self.assertRaisesRegex(TypeError, "MediaApplicationService"):
            release.create_version2_release_application(
                media_application_service=object(),
            )


if __name__ == "__main__":
    unittest.main()

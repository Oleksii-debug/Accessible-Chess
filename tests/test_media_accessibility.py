from __future__ import annotations

import inspect
import unittest

from acs.media_accessibility import MediaAccessibilityBridge, MediaAccessibilityError
from acs.media_application import MediaApplicationService
from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaReconciliationState,
    MediaTimelineBarrier,
    MediaSource,
    MediaSourceKind,
)


def _source() -> MediaSource:
    return MediaSource(
        source_id="fixture-media",
        title="Accessible presentation fixture",
        kind=MediaSourceKind.LOCAL_FILE,
        duration_ms=7_200_000,
    )


def _link(
    timestamp_ms: int,
    chess_ref: str,
    *,
    confirmed: bool = True,
) -> MediaChessLink:
    return MediaChessLink(
        "fixture-media",
        timestamp_ms,
        chess_ref,
        status=(MediaLinkStatus.CONFIRMED if confirmed else MediaLinkStatus.CANDIDATE),
        confidence=1.0 if confirmed else 0.7,
        evidence="presentation fixture",
    )


def _service(
    links: tuple[MediaChessLink, ...],
    *,
    position_ms: int = 20_500,
    chess_ref: str | None = "tree:analysis-private",
    restore=None,
) -> MediaApplicationService:
    if restore is None:
        restore = lambda _value: None
    return MediaApplicationService(
        source=_source(),
        timeline=MediaPositionTimeline("fixture-media", links),
        session=MediaChessSession(
            MediaCursor("fixture-media", position_ms),
            chess_ref,
        ),
        restore_chess_ref=restore,
    )


class MediaAccessibilityBridgeTests(unittest.TestCase):
    def test_confirmed_snapshot_is_copyable_and_hides_opaque_chess_refs(self) -> None:
        bridge = MediaAccessibilityBridge(
            _service((_link(20_000, "opaque:canonical-secret"),))
        )

        state = bridge.snapshot()

        self.assertTrue(state["ok"])
        self.assertEqual(state["qualification"], "confirmed")
        self.assertTrue(state["restoreEnabled"])
        self.assertEqual(state["restoreLabel"], "Restore Media Position")
        self.assertEqual(state["focusTarget"], "media-restore-position")
        self.assertEqual(state["positionText"], "00:20.500")
        self.assertIn("confirmed chess position", state["statusText"].lower())
        rendered = repr(state)
        self.assertNotIn("opaque:canonical-secret", rendered)
        self.assertNotIn("tree:analysis-private", rendered)
        for forbidden in ("sourceId", "chessRef", "analysisChessRef", "synchronizedChessRef"):
            self.assertNotIn(forbidden, state)


    def test_resync_required_is_visible_copyable_localized_and_restore_disabled(self) -> None:
        timeline = MediaPositionTimeline(
            "fixture-media",
            (_link(10_000, "tree:old"),),
            barriers=(
                MediaTimelineBarrier(
                    source_id="fixture-media",
                    timestamp_ms=20_000,
                    state=MediaReconciliationState.RESYNC_REQUIRED,
                    reason="provider jumped to an unrelated position",
                ),
            ),
        )
        service = MediaApplicationService(
            source=_source(),
            timeline=timeline,
            session=MediaChessSession(
                MediaCursor("fixture-media", 20_500),
                "tree:analysis-private",
            ),
            restore_chess_ref=lambda _value: self.fail(
                "resync-required state must not invoke restore authority"
            ),
        )
        bridge = MediaAccessibilityBridge(service)

        state = bridge.snapshot()
        self.assertEqual(state["qualification"], "resync_required")
        self.assertFalse(state["restoreEnabled"])
        self.assertEqual(state["focusTarget"], "media-sync-status")
        self.assertIn("synchronization", state["statusText"].lower())

        failed = bridge.restore_position()
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["qualification"], "resync_required")
        self.assertIn("must be rebuilt", failed["announcement"].lower())
        self.assertIn("nothing was restored", failed["announcement"].lower())
        self.assertNotIn("tree:old", repr(failed))
        self.assertNotIn("tree:analysis-private", repr(failed))

        uk = bridge.set_language("uk")
        self.assertEqual(uk["qualification"], "resync_required")
        self.assertIn("Синхронізацію медіа", uk["statusText"])
        uk_failed = bridge.restore_position()
        self.assertIn("потрібно відновити", uk_failed["announcement"])
        self.assertIn("Нічого не відновлено", uk_failed["announcement"])

    def test_candidate_state_disables_restore_and_exposes_plain_status(self) -> None:
        bridge = MediaAccessibilityBridge(
            _service((_link(20_000, "tree:candidate", confirmed=False),))
        )

        state = bridge.snapshot()

        self.assertTrue(state["ok"])
        self.assertEqual(state["qualification"], "candidate")
        self.assertFalse(state["restoreEnabled"])
        self.assertEqual(state["focusTarget"], "media-sync-status")
        self.assertIn("unconfirmed", state["statusText"].lower())
        self.assertNotIn("tree:candidate", repr(state))

    def test_ambiguous_restore_fails_closed_without_invoking_chess_authority(self) -> None:
        restored: list[str] = []
        bridge = MediaAccessibilityBridge(
            _service(
                (_link(20_000, "tree:a"), _link(20_000, "tree:b")),
                restore=lambda value: restored.append(value),
            )
        )

        state = bridge.restore_position()

        self.assertFalse(state["ok"])
        self.assertFalse(state["restoreEnabled"])
        self.assertEqual(state["qualification"], "ambiguous")
        self.assertEqual(restored, [])
        self.assertIn("ambiguous", state["announcement"].lower())
        self.assertNotIn("tree:a", repr(state))
        self.assertNotIn("tree:b", repr(state))

    def test_no_confirmed_position_maps_to_bounded_accessible_error(self) -> None:
        bridge = MediaAccessibilityBridge(_service(()))

        state = bridge.restore_position()

        self.assertFalse(state["ok"])
        self.assertEqual(state["qualification"], "unlinked")
        self.assertFalse(state["restoreEnabled"])
        self.assertIn("no confirmed position", state["announcement"].lower())
        self.assertIn("nothing was restored", state["announcement"].lower())
        self.assertNotIn("MediaApplicationError", state["announcement"])

    def test_restore_callback_failure_never_claims_unknown_effect_rolled_back(self) -> None:
        def reject(_value: str) -> None:
            raise RuntimeError(r"private C:\Users\Oleksii\secret\media.db")

        service = _service((_link(20_000, "tree:restore"),), restore=reject)
        bridge = MediaAccessibilityBridge(service)

        state = bridge.restore_position()

        self.assertFalse(state["ok"])
        self.assertTrue(state["restoreEnabled"])
        self.assertEqual(service.revision, 0)
        self.assertEqual(service.session.chess_ref, "tree:analysis-private")
        self.assertIn("result could not be confirmed", state["announcement"].lower())
        self.assertIn("check the current chess board", state["announcement"].lower())
        self.assertNotIn("nothing was changed", state["announcement"].lower())
        self.assertNotIn("Oleksii", repr(state))
        self.assertNotIn("media.db", repr(state))
        self.assertNotIn("RuntimeError", repr(state))
        self.assertNotIn("tree:restore", repr(state))

    def test_successful_restore_returns_updated_revision_and_accessible_announcement(self) -> None:
        restored: list[str] = []
        service = _service(
            (_link(20_000, "tree:restore"),),
            restore=lambda value: restored.append(value),
        )
        bridge = MediaAccessibilityBridge(service)

        state = bridge.restore_position()

        self.assertTrue(state["ok"])
        self.assertEqual(restored, ["tree:restore"])
        self.assertEqual(service.revision, 1)
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["focusTarget"], "media-restore-position")
        self.assertIn("Restored the chess position", state["announcement"])
        self.assertNotIn("tree:restore", repr(state))

    def test_ukrainian_projection_localizes_status_control_and_announcement(self) -> None:
        bridge = MediaAccessibilityBridge(
            _service((_link(3_661_007, "tree:restore"),), position_ms=3_661_007),
            language="uk",
        )

        state = bridge.snapshot()
        restored = bridge.restore_position()

        self.assertEqual(state["positionText"], "1:01:01.007")
        self.assertEqual(state["restoreLabel"], "Відновити позицію медіа")
        self.assertIn("Позицію шахів підтверджено", state["statusText"])
        self.assertIn("Відновлено шахову позицію", restored["announcement"])

    def test_ukrainian_indeterminate_restore_result_is_explicit(self) -> None:
        def reject_after_unknown_effect(_value: str) -> None:
            raise RuntimeError("unknown external outcome")

        bridge = MediaAccessibilityBridge(
            _service((_link(20_000, "tree:restore"),), restore=reject_after_unknown_effect),
            language="uk",
        )

        state = bridge.restore_position()

        self.assertFalse(state["ok"])
        self.assertIn("Не вдалося підтвердити результат", state["announcement"])
        self.assertIn("Перевірте поточну шахову дошку", state["announcement"])
        self.assertNotIn("Нічого не змінено", state["announcement"])

    def test_language_change_rerenders_without_media_mutation(self) -> None:
        service = _service((_link(20_000, "tree:restore"),))
        bridge = MediaAccessibilityBridge(service)

        state = bridge.set_language("uk")

        self.assertEqual(bridge.language, "uk")
        self.assertEqual(service.revision, 0)
        self.assertEqual(state["revision"], 0)
        self.assertIn("Відновити", state["restoreLabel"])

    def test_invalid_language_fails_before_media_access(self) -> None:
        with self.assertRaises(MediaAccessibilityError):
            MediaAccessibilityBridge(
                _service((_link(20_000, "tree:restore"),)),
                language="de",
            )

    def test_presentation_module_contains_no_chess_or_format_authority(self) -> None:
        import acs.media_accessibility as module

        text = inspect.getsource(module)
        for forbidden in (
            "chesscore",
            "gametree",
            "parse_move",
            "set_fen",
            "pgn_",
            "Board(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()

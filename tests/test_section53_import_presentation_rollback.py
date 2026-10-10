from __future__ import annotations

import unittest

from acs.library_webview_projection import (
    LibraryImportPhase,
    LibraryImportWebViewProjection,
)


class Section53ImportPresentationRollbackTests(unittest.TestCase):
    def make_projection(self) -> LibraryImportWebViewProjection:
        return LibraryImportWebViewProjection(lambda *_: None)

    def test_failed_batch_restores_exact_initial_presentation(self) -> None:
        projection = self.make_projection()
        original = projection.snapshot()
        checkpoint = projection._capture_presentation_state()
        projection.prepare()
        projection.source_reading(12, 120, 1)
        projection.book_source_report("html", 3)
        projection.fail(RuntimeError("internal failure"))
        projection._restore_presentation_state(checkpoint)
        self.assertEqual(projection.phase, LibraryImportPhase.IDLE)
        self.assertEqual(projection.snapshot(), original)
        # The next independent attempt must be allowed after rollback.
        self.assertEqual(projection.prepare().kind, "render-import")

    def test_running_source_report_survives_failed_terminal_render(self) -> None:
        projection = self.make_projection()
        projection.prepare()
        projection.source_reading(10, 20, 0)
        projection.book_source_report("epub", 2)
        expected = projection.snapshot()
        checkpoint = projection._capture_presentation_state()
        projection.empty(warning_count=1)
        projection._restore_presentation_state(checkpoint)
        self.assertEqual(projection.phase, LibraryImportPhase.RUNNING)
        self.assertEqual(projection.snapshot(), expected)
        projection.empty(warning_count=1)
        self.assertIn("EPUB", projection.snapshot()["progress_label"])

    def test_malformed_checkpoint_rejected_without_state_mutation(self) -> None:
        projection = self.make_projection()
        original = projection.snapshot()
        with self.assertRaises(TypeError):
            projection._restore_presentation_state(("invalid",))
        self.assertEqual(projection.snapshot(), original)


if __name__ == "__main__":
    unittest.main()

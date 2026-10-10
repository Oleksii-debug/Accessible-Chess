from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.bookdocument import BookDocument, Heading, Paragraph
from acs.bookreader import BookReader
from acs.book_webview_projection import BookWebViewProjection
from acs.full_product_presenters import BookReaderPresenter, TrainingPresenter
from acs.full_product_ui_shell import UILanguage
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_webview_projection import TrainingWebViewProjection


FEN = "8/8/8/8/8/8/4P3/4K2k w - - 0 1"


class MutatingBookPresenter(BookReaderPresenter):
    def __init__(self, reader):
        super().__init__(reader, language=UILanguage.EN)
        self.current_calls = 0
        self.live_index_after_capture = None

    def current(self):
        self.current_calls += 1
        captured = super().current()
        if self.current_calls == 1:
            self._reader.next_block()
            self.live_index_after_capture = self._reader.index
        return captured


class MutatingTrainingPresenter(TrainingPresenter):
    def __init__(self, session):
        super().__init__(session, language=UILanguage.EN)
        self.view_calls = 0
        self.live_step_after_capture = None

    def view(self):
        self.view_calls += 1
        captured = super().view()
        if self.view_calls == 1:
            self.session.submit("e4")
            self.live_step_after_capture = self.session.step_index
        return captured


class BooksTrainingAtomicityTests(unittest.TestCase):
    def test_book_passive_snapshot_uses_exactly_one_immutable_block_view(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Heading(text="First", level=1), Paragraph(text="Second")],
        )
        presenter = BookReaderPresenter(BookReader(document), language=UILanguage.EN)
        projection = BookWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            language=UILanguage.EN,
        )
        original_current = presenter.current
        current_calls = 0
        live_index_after_capture = None

        def capture_then_advance():
            nonlocal current_calls, live_index_after_capture
            current_calls += 1
            captured = original_current()
            if current_calls == 1:
                presenter._reader.next_block()
                live_index_after_capture = presenter._reader.index
            return captured

        with patch.object(presenter, "current", side_effect=capture_then_advance):
            snapshot = projection.snapshot()
        self.assertEqual(1, current_calls)
        self.assertEqual(0, snapshot["block"]["index"])
        self.assertEqual("First", snapshot["block"]["text"])
        self.assertEqual(1, live_index_after_capture)

    def test_training_passive_snapshot_uses_exactly_one_immutable_training_view(self) -> None:
        definition = ExerciseDefinition(
            exercise_id="ex",
            start_fen=FEN,
            steps=(ExerciseStep(frozenset({"e4"})), ExerciseStep(frozenset({"Kh2"}))),
            title="Exercise",
        )
        presenter = TrainingPresenter(ExerciseSession(definition), language=UILanguage.EN)
        projection = TrainingWebViewProjection(presenter, language=UILanguage.EN)
        original_view = presenter.view
        view_calls = 0
        live_step_after_capture = None

        def capture_then_advance():
            nonlocal view_calls, live_step_after_capture
            view_calls += 1
            captured = original_view()
            if view_calls == 1:
                presenter.session.submit("e4")
                live_step_after_capture = presenter.session.step_index
            return captured

        with patch.object(presenter, "view", side_effect=capture_then_advance):
            snapshot = projection.snapshot()
        self.assertEqual(1, view_calls)
        self.assertEqual(1, snapshot["progress"]["step"])
        self.assertEqual(0, snapshot["progress"]["attempts"])
        self.assertEqual(1, live_step_after_capture)
        self.assertEqual(1, presenter.session.attempts)


    def test_noncanonical_book_presenter_is_rejected_before_override_hooks(self) -> None:
        document = BookDocument(title="Book", blocks=[Heading(text="First", level=1)])
        with self.assertRaisesRegex(TypeError, "presenter must be BookReaderPresenter"):
            BookWebViewProjection(
                MutatingBookPresenter(BookReader(document)),
                lambda _action, _payload: None,
                language=UILanguage.EN,
            )

    def test_noncanonical_training_presenter_is_rejected_before_override_hooks(self) -> None:
        definition = ExerciseDefinition(
            exercise_id="ex-reject", start_fen=FEN,
            steps=(ExerciseStep(frozenset({"e4"})),), title="Exercise",
        )
        with self.assertRaisesRegex(TypeError, "presenter must be TrainingPresenter"):
            TrainingWebViewProjection(
                MutatingTrainingPresenter(ExerciseSession(definition)),
                language=UILanguage.EN,
            )

if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Heading, Paragraph
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_progress_store import TrainingProgressStore
from acs.version2_application import Version2Application
from acs.version2_release_app import _version2_user_data_layout


class PortableLocalAppDataPersistenceBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.launcher_source = (
            cls.root / "packaging" / "portable_launcher.c"
        ).read_text(encoding="utf-8")
        cls.portable_package_source = (
            cls.root / "acs" / "version2_portable_package.py"
        ).read_text(encoding="utf-8")
        cls.release_app_source = (
            cls.root / "acs" / "version2_release_app.py"
        ).read_text(encoding="utf-8")
        cls.application_source = (
            cls.root / "acs" / "version2_application.py"
        ).read_text(encoding="utf-8")

    @staticmethod
    def _book() -> BookDocument:
        return BookDocument(
            "Portable persistence",
            blocks=[
                Heading(text="Chapter", level=1, block_id="chapter"),
                Paragraph(text="Resume here", block_id="resume"),
            ],
        )

    @staticmethod
    def _training() -> ExerciseDefinition:
        return ExerciseDefinition(
            "portable-localappdata-training",
            Board.START,
            (ExerciseStep(frozenset({"e4"}), hint="Play e4"),),
        )

    def test_launcher_manifest_and_production_root_form_one_exact_contract(self) -> None:
        self.assertIn(
            'ac_path_join(g_data, AC_PATH_CAP, g_root, L"data")',
            self.launcher_source,
        )
        self.assertIn(
            'SetEnvironmentVariableW(L"LOCALAPPDATA", g_data)',
            self.launcher_source,
        )
        self.assertIn(
            '"package_local_appdata": "data/AccessibleChess"',
            self.portable_package_source,
        )
        self.assertIn(
            'progress_store=BookProgressStore(layout.root / "book-progress.json")',
            self.release_app_source,
        )
        self.assertIn(
            'self.training_progress_root = progress_store.path.parent / "training-progress"',
            self.application_source,
        )

        with tempfile.TemporaryDirectory() as temp:
            package_root = Path(temp) / "AccessibleChess"
            redirected_local_appdata = package_root / "data"
            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(redirected_local_appdata)},
                clear=False,
            ):
                layout = _version2_user_data_layout()

            expected = redirected_local_appdata / "AccessibleChess"
            self.assertEqual(expected, layout.root)
            self.assertEqual(expected / "settings.json", layout.settings_path)
            self.assertEqual(expected / "library.acsdb", layout.library_path)
            self.assertEqual(
                expected / "book-progress.json",
                BookProgressStore(expected / "book-progress.json").path,
            )

    def test_runtime_application_derives_training_root_from_book_progress_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package_root = Path(temp) / "AccessibleChess"
            redirected_local_appdata = package_root / "data"
            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(redirected_local_appdata)},
                clear=False,
            ):
                layout = _version2_user_data_layout()

            layout.root.mkdir(parents=True, exist_ok=True)
            database = AcsDatabase(layout.library_path)
            try:
                progress_store = BookProgressStore(layout.root / "book-progress.json")
                application = Version2Application(
                    database,
                    progress_store=progress_store,
                    engine_assistance=object(),
                    board_dispatch=lambda _event: None,
                )

                self.assertIs(progress_store, application.progress_store)
                self.assertEqual(layout.root, application.progress_store.path.parent)
                self.assertEqual(
                    layout.root / "training-progress",
                    application.training_progress_root,
                )
                self.assertEqual(
                    package_root.resolve(),
                    application.training_progress_root.resolve().parents[2],
                )
            finally:
                database.close()

    def test_book_progress_reopens_inside_redirected_package_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package_root = Path(temp) / "AccessibleChess"
            redirected_local_appdata = package_root / "data"
            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(redirected_local_appdata)},
                clear=False,
            ):
                layout = _version2_user_data_layout()

            path = layout.root / "book-progress.json"
            reader = BookReader(self._book())
            reader.go_to(1)
            reader.save_return_point("portable-return")
            BookProgressStore(path).save("portable:book", reader)

            reopened = BookProgressStore(path).restore("portable:book", self._book())
            self.assertEqual("resume", reopened.location().block_id)
            self.assertEqual("resume", reopened.restore_return_point("portable-return").block_id)
            self.assertTrue(path.is_file())
            self.assertEqual(
                package_root.resolve(),
                path.resolve().parents[2],
            )

    def test_training_progress_reopens_inside_same_redirected_package_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package_root = Path(temp) / "AccessibleChess"
            redirected_local_appdata = package_root / "data"
            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(redirected_local_appdata)},
                clear=False,
            ):
                layout = _version2_user_data_layout()

            path = layout.root / "training-progress" / "portable-localappdata.json"
            definition = self._training()
            session = ExerciseSession(definition)
            rejected = session.submit("zz")
            self.assertFalse(rejected.accepted)
            self.assertEqual(1, rejected.attempts)
            self.assertEqual(1, rejected.mistakes)

            revision = TrainingProgressStore(path).save(
                session,
                expected_revision=None,
            )
            loaded = TrainingProgressStore(path).load(definition)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(revision, loaded.revision)
            self.assertEqual(1, loaded.session.attempts)
            self.assertEqual(1, loaded.session.mistakes)
            self.assertEqual(0, loaded.session.step_index)
            self.assertTrue(path.is_file())
            self.assertEqual(
                package_root.resolve(),
                path.resolve().parents[3],
            )


if __name__ == "__main__":
    unittest.main()

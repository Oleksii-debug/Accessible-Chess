from __future__ import annotations

import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.full_product_actions import FullProductActionRouter, build_full_product_action_registry
from acs.full_product_ui_shell import AccessibleShellState
from acs.gametree import serialize_game
from acs.keybindings import BindingContext
from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import parse_pgn_text
from acs.pgn_service import PgnConcurrentWriteError, open_pgn, save_pgn_atomic
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2WindowsFileActionDelegate,
)


_SAMPLE = """[Event "Київ ♞"]
[Site "Uzhhorod"]
[Date "2026.08.31"]
[Round "1"]
[White "Олексій"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0
"""


class _SaveDialogs:
    def __init__(self, destination: Path) -> None:
        self.destination = destination
        self.suggestions = []

    def open_pgn(self):
        return None

    def save_pgn_as(self, suggested_filename: str):
        self.suggestions.append(suggested_filename)
        return self.destination

    def select_library_import(self):
        return None


class V2PgnSaveExportCompletionTests(unittest.TestCase):
    def _game(self):
        games = parse_pgn_text(_SAMPLE, strict=True)
        self.assertEqual(len(games), 1)
        return games[0]

    def test_save_and_save_as_are_registered_with_standard_keyboard_paths(self) -> None:
        registry = build_full_product_action_registry()
        self.assertEqual(registry.definition("pgn.save").title, "Save PGN")
        self.assertEqual(registry.definition("pgn.save_as").title, "Save PGN As")
        self.assertEqual(
            registry.resolve_binding(BindingContext.DOCUMENT, "Ctrl+S").action_id,
            "pgn.save",
        )
        self.assertEqual(
            registry.resolve_binding(BindingContext.DOCUMENT, "Ctrl+Shift+S").action_id,
            "pgn.save_as",
        )

        calls = []
        router = FullProductActionRouter(
            AccessibleShellState(initial_route="pgn"),
            lambda action_id, payload: calls.append((action_id, payload)) or "ok",
            registry=registry,
        )
        self.assertEqual(router.dispatch("pgn.save").value, "ok")
        self.assertEqual(router.dispatch("pgn.save_as").value, "ok")
        self.assertEqual(calls, [("pgn.save", {}), ("pgn.save_as", {})])

    def test_canonical_router_reaches_existing_trusted_host_save_and_save_as_ports(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "збереження ♞.pgn"
            session = PgnDocumentSession.from_text(_SAMPLE)
            dialogs = _SaveDialogs(destination)
            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=dialogs,
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: (_ for _ in ()).throw(
                    AssertionError(f"unexpected delegated action: {action_id}")
                ),
                current_focus_provider=lambda: "pgn-tree-current",
            )
            router = FullProductActionRouter(
                AccessibleShellState(initial_route="pgn"),
                delegate,
                registry=build_full_product_action_registry(),
            )

            save_as = router.dispatch("pgn.save_as").value
            self.assertEqual(save_as.kind, FileWorkflowEventKind.PGN_SAVED_AS)
            self.assertEqual(save_as.focus_target, "pgn-tree-current")
            self.assertEqual(dialogs.suggestions, ["game.pgn"])
            self.assertEqual(open_pgn(destination).games, session.workspace.games())

            session.edit_tag("Event", "Updated Ω")
            save = router.dispatch("pgn.save").value
            self.assertEqual(save.kind, FileWorkflowEventKind.PGN_SAVED)
            self.assertEqual(save.focus_target, "pgn-tree-current")
            reopened = PgnDocumentSession.open(destination)
            self.assertEqual(reopened.workspace.current_game().tags["Event"], "Updated Ω")
            self.assertEqual(dialogs.suggestions, ["game.pgn"])
            self.assertEqual(events, [save_as, save])

    def test_disk_full_during_fsync_preserves_existing_destination_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            destination = directory / "existing.pgn"
            original = b"existing destination\n"
            destination.write_bytes(original)

            with patch(
                "acs.pgn_service.os.fsync",
                side_effect=OSError(errno.ENOSPC, "No space left on device"),
            ):
                with self.assertRaises(OSError):
                    save_pgn_atomic(destination, (self._game(),), overwrite=True)

            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(list(directory.glob(destination.name + ".*.tmp")), [])

    def test_permission_failure_during_replace_preserves_destination_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            destination = directory / "existing.pgn"
            original = b"existing destination\n"
            destination.write_bytes(original)

            with patch(
                "acs.pgn_service.os.replace",
                side_effect=PermissionError(errno.EACCES, "permission denied"),
            ):
                with self.assertRaises(PermissionError):
                    save_pgn_atomic(destination, (self._game(),), overwrite=True)

            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(list(directory.glob(destination.name + ".*.tmp")), [])

    def test_stale_open_fingerprint_never_overwrites_external_modification(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            source = Path(raw_dir) / "source.pgn"
            save_pgn_atomic(source, (self._game(),))
            session = PgnDocumentSession.open(source)
            external = b'[Event "External"]\n[Result "*"]\n\n*\n'
            source.write_bytes(external)

            with self.assertRaises(PgnConcurrentWriteError):
                session.save()

            self.assertEqual(source.read_bytes(), external)

    def test_unicode_filename_and_content_are_deterministic_utf8_and_reopen_equal(self) -> None:
        game = self._game()
        expected = (serialize_game(game).rstrip() + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "партія ♞ Олексій.pgn"
            save_pgn_atomic(destination, (game,))
            self.assertEqual(destination.read_bytes(), expected)
            self.assertNotIn(b"\r\n", destination.read_bytes())
            reopened = open_pgn(destination)
            self.assertEqual(reopened.games, (game,))

    def test_very_large_multigame_export_is_streamed_without_collection_materialization(self) -> None:
        game = self._game()
        block = serialize_game(game).rstrip().encode("utf-8")
        count = 20_000

        def games():
            for _ in range(count):
                yield game

        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "large-export.pgn"
            result = save_pgn_atomic(destination, games())
            expected_size = count * len(block) + (count - 1) * 2 + 1
            self.assertEqual(result.size, expected_size)
            self.assertEqual(destination.stat().st_size, expected_size)
            with destination.open("rb") as handle:
                self.assertEqual(handle.read(len(block)), block)
                handle.seek(-1, 2)
                self.assertEqual(handle.read(), b"\n")


if __name__ == "__main__":
    unittest.main()

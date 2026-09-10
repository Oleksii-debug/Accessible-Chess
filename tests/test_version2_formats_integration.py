from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.cbv_extractor import (
    CbvExtractCode,
    CbvExtractError,
    ExternalCbvExtractorConfig,
)
from acs.chessbase_decoder import (
    ChessBaseDecodeCode,
    ChessBaseDecodeError,
    ExternalChessBaseDecoderConfig,
)
from acs.chessbase_library_import import (
    ChessBaseLibraryImportService,
    ChessBaseLibraryImportStatus,
)
from acs.game_identity import same_game_tree
from acs.gametree import parse_games
from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportService,
)
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService


BACKEND_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _move(frm: int, to: int, *, comments=None) -> dict[str, object]:
    return {
        "kind": "move",
        "from": frm,
        "to": to,
        "promote": 7,
        "comments": [] if comments is None else comments,
    }


def _game(index: int, moves: list[dict[str, object]], **values) -> dict[str, object]:
    record: dict[str, object] = {
        "index": index,
        "status": "decoded",
        "start_fen": START_FEN,
        "result": 1,
        "white_first": "Олексій",
        "white_last": "Білий",
        "black_first": "Анна",
        "black_last": "Чорна",
        "event": "Київ ChessBase",
        "site": "Kyiv UKR",
        "year": 2026,
        "month": 8,
        "day": 27,
        "white_elo": 2100,
        "black_elo": 2050,
        "eco": 1,
        "round": 1,
        "subround": 0,
        "tags": [{"name": "Source", "value": "Version 2 integration"}],
        "moves": moves,
    }
    record.update(values)
    return record


def _payload(games: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "protocol": "accessible-chess-libcbh-v1",
            "backend": "libcbh",
            "backend_commit": BACKEND_COMMIT,
            "games": games,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class Version2FormatsIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private_root = self.root / "Users" / "private-account" / "databases"
        self.private_root.mkdir(parents=True)
        self.source = self.private_root / "Tournament.cbh"
        self.source.write_bytes(b"CBH header fixture")
        (self.private_root / "Tournament.cbg").write_bytes(b"CBH game fixture")
        (self.private_root / "Tournament.cba").write_bytes(b"CBH annotation fixture")
        self.backend = self.root / "libcbh-json-bridge"
        self.backend.write_bytes(b"external backend placeholder")
        self.cbv_source = self.private_root / "Archived Tournament.cbv"
        self.cbv_source.write_bytes(b"immutable CBV archive fixture")
        self.cbv_backend = self.root / "uncbv"
        self.cbv_backend.write_bytes(b"external CBV extractor placeholder")
        self.database = AcsDatabase(self.root / "version2.acsdb")
        self.addCleanup(self.database.close)
        self.service = ChessBaseLibraryImportService(
            self.database,
            ExternalChessBaseDecoderConfig(
                self.backend,
                expected_backend_commit=BACKEND_COMMIT,
                timeout_seconds=3,
            ),
            ExternalCbvExtractorConfig(
                self.cbv_backend,
                expected_backend_sha256=sha256(
                    self.cbv_backend.read_bytes()
                ).hexdigest(),
                timeout_seconds=3,
            ),
        )

    @staticmethod
    def _rich_payload() -> bytes:
        rich_moves = [
            _move(12, 28, comments=[{"kind": "text_after", "lang": 0, "text": "Main plan"}]),
            {"kind": "push"},
            _move(52, 36),
            _move(6, 21),
            {"kind": "pop"},
            {"kind": "push"},
            _move(50, 34),
            {"kind": "pop"},
            _move(50, 42),
            {"kind": "pop"},
        ]
        return _payload(
            [
                _game(0, rich_moves),
                {"index": 1, "status": "skipped", "error_code": 17},
                _game(
                    2,
                    [_move(11, 27), _move(51, 35)],
                    result=3,
                    white_first="Ірина",
                    white_last="Біла",
                    event="Львів ChessBase",
                ),
            ]
        )

    def _database_counts(self) -> tuple[int, int, int]:
        return tuple(
            int(self.database.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("import_attempts", "sources", "games")
        )

    def _assert_zero_publication(self) -> None:
        self.assertEqual(self._database_counts(), (0, 0, 0))

    def _assert_safe_error(self, error: BaseException, code: object) -> None:
        self.assertEqual(getattr(error, "code", None), code)
        public = str(error)
        self.assertNotIn(str(self.private_root), public)
        self.assertNotIn("private-account", public)
        self.assertNotIn("Traceback", public)
        self.assertNotIn("secret-stderr", public)

    def _import_payload(self, data: bytes, **kwargs):
        with mock.patch("acs.chessbase_decoder._run_backend", return_value=data):
            return self.service.import_database(self.source, **kwargs)

    def test_real_semantic_pipeline_decode_library_search_export_reopen(self) -> None:
        progress: list[tuple[int, int]] = []
        with mock.patch(
            "acs.chessbase_decoder._run_backend",
            return_value=self._rich_payload(),
        ):
            report = self.service.import_database(
                self.source,
                progress_callback=lambda item: progress.append(
                    (item.processed_games, item.total_games)
                ),
            )

        self.assertEqual(
            report.status,
            ChessBaseLibraryImportStatus.IMPORTED_WITH_WARNINGS,
        )
        self.assertEqual(report.source_name, "Tournament.cbh")
        self.assertEqual(report.decoded_game_count, 2)
        self.assertEqual(report.imported_game_count, 2)
        self.assertEqual(report.warning_count, 1)
        self.assertEqual(report.library_result.warning_count, 1)
        self.assertEqual(progress, [(0, 2), (1, 2), (2, 2)])
        self.assertNotIn(str(self.private_root), repr(report))
        self.assertNotIn("private-account", repr(report))

        attempt = self.database.get_import_attempt(report.library_result.attempt_id)
        self.assertEqual(attempt["status"], "warning")
        self.assertEqual(attempt["warning_count"], 1)
        source_row = self.database.get_source(report.library_result.source_id)
        self.assertEqual(source_row["source_name"], "Tournament.cbh")
        self.assertEqual(source_row["source_format"], "cbh")
        self.assertEqual(source_row["sha256"], report.source_sha256)

        page = GameSearchService(self.database).search(
            GameSearchQuery(player="олексій", event="київ", source_name="tournament")
        )
        self.assertEqual(len(page.items), 1)
        stored = self.database.get_game(page.items[0].game_id)
        canonical = parse_games(stored["pgn_text"])[0]
        self.assertEqual(canonical.line.moves[0].comments_after[0].text, "Main plan")
        self.assertEqual(
            [line.moves[0].san for line in canonical.line.moves[1].variations],
            ["c5", "c6"],
        )

        destination = self.root / "exported-from-cbh.pgn"
        save_pgn_atomic(destination, (canonical,))
        reopened = open_pgn(destination).games[0]
        self.assertTrue(same_game_tree(canonical, reopened))

    def test_decoder_failure_and_postdecode_cancel_publish_nothing(self) -> None:
        illegal = _payload([_game(0, [_move(12, 44)])])
        with mock.patch("acs.chessbase_decoder._run_backend", return_value=illegal):
            with self.assertRaises(ChessBaseDecodeError):
                self.service.import_database(self.source)

        checks = iter((False, True))
        with mock.patch(
            "acs.chessbase_decoder._run_backend",
            return_value=self._rich_payload(),
        ):
            with self.assertRaises(LibraryImportCancelledError):
                self.service.import_database(
                    self.source,
                    cancel_check=lambda: next(checks),
                )

        for table in ("import_attempts", "sources", "games"):
            count = self.database.conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            self.assertEqual(count, 0, table)

    def test_cbv_archive_extracts_then_uses_same_canonical_library_pipeline(self) -> None:
        def uncbv_runner(_executable, arguments, _config, *, cwd, monitor_directory=None):
            if arguments[0] == "list":
                return b"Archived Tournament.cbh\nArchived Tournament.cbg\n"
            destination = Path(cwd)
            self.assertEqual(Path(monitor_directory), destination)
            (destination / "Archived Tournament.cbh").write_bytes(b"CBH header")
            (destination / "Archived Tournament.cbg").write_bytes(b"CBH games")
            return b""

        with (
            mock.patch("acs.cbv_extractor._run_uncbv", side_effect=uncbv_runner),
            mock.patch(
                "acs.chessbase_decoder._run_backend",
                return_value=self._rich_payload(),
            ),
        ):
            report = self.service.import_database(self.cbv_source)

        self.assertEqual(report.status, ChessBaseLibraryImportStatus.IMPORTED_WITH_WARNINGS)
        self.assertEqual(report.source_name, "Archived Tournament.cbv")
        self.assertEqual(report.source_format, "cbv")
        self.assertEqual(report.archive_backend_name, "uncbv")
        self.assertEqual(
            report.archive_backend_sha256,
            sha256(self.cbv_backend.read_bytes()).hexdigest(),
        )
        self.assertEqual(report.imported_game_count, 2)
        source = self.database.get_source(report.library_result.source_id)
        self.assertEqual(source["source_format"], "cbv")
        self.assertEqual(source["source_name"], "Archived Tournament.cbv")
        self.assertEqual(source["sha256"], sha256(self.cbv_source.read_bytes()).hexdigest())
        self.assertNotIn("private-account", repr(report))

    def test_source_warning_validation_is_fail_closed_before_attempt(self) -> None:
        game = parse_games('[Event "Safe"]\n[Result "*"]\n\n1. e4 *\n')[0]
        importer = LibraryImportService(self.database)
        for invalid in (-1, True, "1"):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    importer.import_games(
                        (game,),
                        source_name="safe.pgn",
                        source_format="pgn",
                        source_sha256="0" * 64,
                        source_warning_count=invalid,
                    )
        self.assertEqual(
            self.database.conn.execute(
                "SELECT COUNT(*) FROM import_attempts"
            ).fetchone()[0],
            0,
        )

    def test_d17_truncated_primary_backend_rejection_is_atomic_and_retryable(self) -> None:
        self.source.write_bytes(b"CBH\x00truncated")
        truncated = self.source.read_bytes()
        failure = ChessBaseDecodeError(
            "ChessBase decoder backend failed",
            code=ChessBaseDecodeCode.BACKEND_FAILED,
        )
        with mock.patch("acs.chessbase_decoder._run_backend", side_effect=failure):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service.import_database(self.source)
        self._assert_safe_error(caught.exception, ChessBaseDecodeCode.BACKEND_FAILED)
        self.assertEqual(self.source.read_bytes(), truncated)
        self._assert_zero_publication()

        self.source.write_bytes(b"corrected test-owned primary")
        report = self._import_payload(_payload([_game(0, [_move(12, 28)])]))
        self.assertEqual(report.imported_game_count, 1)
        self.assertEqual(self._database_counts(), (1, 1, 1))

    def test_d17_postvalidation_companion_delete_or_change_never_reaches_acsdb(self) -> None:
        companion = self.private_root / "Tournament.cbg"
        original = companion.read_bytes()
        primary = self.source.read_bytes()

        for scenario in ("delete", "change"):
            with self.subTest(scenario=scenario):
                polls = 0

                def mutate_after_decode() -> bool:
                    nonlocal polls
                    polls += 1
                    if polls == 2:
                        if scenario == "delete":
                            companion.unlink()
                        else:
                            companion.write_bytes(b"post-validation mutation")
                    return False

                with mock.patch(
                    "acs.chessbase_decoder._run_backend",
                    return_value=_payload([_game(0, [_move(12, 28)])]),
                ):
                    with self.assertRaises(ChessBaseDecodeError) as caught:
                        self.service.import_database(
                            self.source,
                            cancel_check=mutate_after_decode,
                        )
                self._assert_safe_error(caught.exception, ChessBaseDecodeCode.SOURCE_CHANGED)
                self.assertEqual(self.source.read_bytes(), primary)
                self._assert_zero_publication()
                companion.write_bytes(original)

        report = self._import_payload(_payload([_game(0, [_move(12, 28)])]))
        self.assertEqual(report.imported_game_count, 1)
        self.assertEqual(self._database_counts(), (1, 1, 1))

    def test_d17_impossible_output_variation_move_and_metadata_fail_before_acsdb(self) -> None:
        primary = self.source.read_bytes()
        cases = (
            (
                "protocol",
                _payload([_game(0, [_move(12, 28)])]).replace(
                    b"accessible-chess-libcbh-v1",
                    b"impossible-protocol-v0001",
                ),
                ChessBaseDecodeCode.PROTOCOL_ERROR,
            ),
            (
                "variation",
                _payload([_game(0, [{"kind": "pop"}])]),
                ChessBaseDecodeCode.INVALID_VARIATION,
            ),
            (
                "move",
                _payload([_game(0, [_move(12, 44)])]),
                ChessBaseDecodeCode.INVALID_MOVE,
            ),
            (
                "metadata",
                _payload([_game(0, [_move(12, 28)], year="2026")]),
                ChessBaseDecodeCode.PROTOCOL_ERROR,
            ),
        )
        for label, data, code in cases:
            with self.subTest(label=label):
                with self.assertRaises(ChessBaseDecodeError) as caught:
                    self._import_payload(data)
                self._assert_safe_error(caught.exception, code)
                self.assertEqual(self.source.read_bytes(), primary)
                self._assert_zero_publication()

    def test_d17_excessive_decoder_output_is_bounded_before_acsdb(self) -> None:
        primary = self.source.read_bytes()
        data = _payload([
            _game(0, [_move(12, 28)]),
            _game(1, [_move(11, 27)]),
        ])
        with mock.patch("acs.chessbase_decoder.MAX_DECODED_GAMES", 1):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self._import_payload(data)
        self._assert_safe_error(caught.exception, ChessBaseDecodeCode.RESOURCE_LIMIT)
        self.assertEqual(self.source.read_bytes(), primary)
        self._assert_zero_publication()

    def test_d17_backend_timeout_and_crash_are_stable_atomic_failures(self) -> None:
        primary = self.source.read_bytes()
        for code in (ChessBaseDecodeCode.BACKEND_TIMEOUT, ChessBaseDecodeCode.BACKEND_FAILED):
            with self.subTest(code=code.value):
                failure = ChessBaseDecodeError(
                    "ChessBase decoder backend unavailable",
                    code=code,
                )
                with mock.patch("acs.chessbase_decoder._run_backend", side_effect=failure):
                    with self.assertRaises(ChessBaseDecodeError) as caught:
                        self.service.import_database(self.source)
                self._assert_safe_error(caught.exception, code)
                self.assertEqual(self.source.read_bytes(), primary)
                self._assert_zero_publication()

    def test_d17_corrupt_cbv_archive_is_atomic_cleanup_safe_and_retryable(self) -> None:
        archive = self.cbv_source.read_bytes()
        with mock.patch("acs.cbv_extractor._run_uncbv", return_value=b"../escape.cbh\n"):
            with self.assertRaises(CbvExtractError) as caught:
                self.service.import_database(self.cbv_source)
        self._assert_safe_error(caught.exception, CbvExtractCode.INVALID_ENTRY)
        self.assertEqual(self.cbv_source.read_bytes(), archive)
        self._assert_zero_publication()

        temp_dirs: list[Path] = []

        def uncbv_runner(_executable, arguments, _config, *, cwd, monitor_directory=None):
            destination = Path(cwd)
            if not temp_dirs:
                temp_dirs.append(destination)
            if arguments[0] == "list":
                return b"Corrected.cbh\nCorrected.cbg\n"
            self.assertEqual(Path(monitor_directory), destination)
            (destination / "Corrected.cbh").write_bytes(b"corrected primary")
            (destination / "Corrected.cbg").write_bytes(b"corrected companion")
            return b""

        with (
            mock.patch("acs.cbv_extractor._run_uncbv", side_effect=uncbv_runner),
            mock.patch(
                "acs.chessbase_decoder._run_backend",
                return_value=_payload([_game(0, [_move(12, 28)])]),
            ),
        ):
            report = self.service.import_database(self.cbv_source)
        self.assertEqual(report.imported_game_count, 1)
        self.assertEqual(self._database_counts(), (1, 1, 1))
        self.assertTrue(temp_dirs)
        self.assertFalse(temp_dirs[0].exists())
        self.assertEqual(self.cbv_source.read_bytes(), archive)

    def test_d17_cbv_temp_workspace_is_removed_on_decoder_failure(self) -> None:
        archive = self.cbv_source.read_bytes()
        temp_dirs: list[Path] = []

        def uncbv_runner(_executable, arguments, _config, *, cwd, monitor_directory=None):
            destination = Path(cwd)
            if not temp_dirs:
                temp_dirs.append(destination)
            if arguments[0] == "list":
                return b"Broken.cbh\nBroken.cbg\n"
            self.assertEqual(Path(monitor_directory), destination)
            (destination / "Broken.cbh").write_bytes(b"broken primary")
            (destination / "Broken.cbg").write_bytes(b"broken companion")
            return b""

        failure = ChessBaseDecodeError(
            "ChessBase decoder backend failed",
            code=ChessBaseDecodeCode.BACKEND_FAILED,
        )
        with (
            mock.patch("acs.cbv_extractor._run_uncbv", side_effect=uncbv_runner),
            mock.patch("acs.chessbase_decoder._run_backend", side_effect=failure),
        ):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service.import_database(self.cbv_source)
        self._assert_safe_error(caught.exception, ChessBaseDecodeCode.BACKEND_FAILED)
        self._assert_zero_publication()
        self.assertTrue(temp_dirs)
        self.assertFalse(temp_dirs[0].exists())
        self.assertEqual(self.cbv_source.read_bytes(), archive)


if __name__ == "__main__":
    unittest.main()

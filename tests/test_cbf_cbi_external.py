from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.cbf_cbi_external import (
    CbfCbiExternalCode,
    CbfCbiExternalError,
    CbfCbiLibraryImportService,
    CbfCbiLibraryImportStatus,
    CbfCbiReadResult,
    ExternalCbfCbiReaderConfig,
    SCIDB_COMMIT,
    SCID_COMMIT,
    read_cbf_cbi_external,
)
from acs.chessbase_integrity import capture_integrity_snapshot
from acs.gametree import parse_games
from acs.library_import_service import LibraryImportCancelledError


_PGN = b'''[Event "CBF qualification"]
[Site "Test"]
[Date "2026.08.31"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 {main comment} e5 (1... c5 {variation comment}) 2. Nf3 Nc6 3. Bb5 a6 1-0
'''


def _write(path: Path, payload: bytes) -> str:
    path.write_bytes(payload)
    return sha256(payload).hexdigest()


class CbfCbiExternalReaderTests(unittest.TestCase):
    def _source_family(self, root: Path) -> tuple[Path, Path]:
        cbf = root / "sample.cbf"
        cbi = root / "sample.cbi"
        cbf.write_bytes(b"real-format-placeholder-for-boundary-tests")
        cbi.write_bytes(b"paired-index-placeholder-for-boundary-tests")
        return cbf, cbi

    def _config(self, root: Path) -> ExternalCbfCbiReaderConfig:
        cbh2si4 = root / "cbh2si4.bin"
        scidpgn = root / "scidpgn.bin"
        cbh_hash = _write(cbh2si4, b"pinned-cbh2si4-test-double")
        pgn_hash = _write(scidpgn, b"pinned-scidpgn-test-double")
        return ExternalCbfCbiReaderConfig(
            cbh2si4_executable=cbh2si4,
            cbh2si4_sha256=cbh_hash,
            scidpgn_executable=scidpgn,
            scidpgn_sha256=pgn_hash,
            timeout_seconds=5,
            max_stdout_bytes=1024 * 1024,
            max_stderr_bytes=1024 * 1024,
            max_private_si4_bytes=1024 * 1024,
            max_games=10,
        )

    def test_source_and_exporter_commits_are_exactly_pinned(self) -> None:
        self.assertEqual(SCIDB_COMMIT, "7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415")
        self.assertEqual(SCID_COMMIT, "5837653efa3975c64cff232006d9f981b36ac56b")

    def test_hash_pins_are_mandatory_and_exact(self) -> None:
        with self.assertRaises(ValueError):
            ExternalCbfCbiReaderConfig(
                cbh2si4_executable=Path("cbh2si4"),
                cbh2si4_sha256="not-a-digest",
                scidpgn_executable=Path("scidpgn"),
                scidpgn_sha256="0" * 64,
            )

    def test_missing_cbi_fails_before_backend_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cbf = root / "sample.cbf"
            cbf.write_bytes(b"cbf")
            config = self._config(root)
            with patch("acs.cbf_cbi_external._run_process") as runner:
                with self.assertRaises(CbfCbiExternalError) as caught:
                    read_cbf_cbi_external(cbf, config)
            self.assertEqual(caught.exception.code, CbfCbiExternalCode.UNSUPPORTED_SOURCE)
            runner.assert_not_called()

    def test_bounded_chain_uses_private_si4_then_canonical_pgn_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cbf, _ = self._source_family(root)
            config = self._config(root)
            calls: list[list[str]] = []

            def fake_run(argv: list[str], **kwargs) -> bytes:
                calls.append(list(argv))
                if len(calls) == 1:
                    destination = Path(argv[-1])
                    destination.write_bytes(b"index")
                    destination.with_suffix(".sg4").write_bytes(b"games")
                    destination.with_suffix(".sn4").write_bytes(b"names")
                    return b"1 game(s) written.\n"
                return _PGN

            with patch("acs.cbf_cbi_external._run_process", side_effect=fake_run):
                decoded = read_cbf_cbi_external(cbf, config)

            self.assertEqual(decoded.total_games, 1)
            self.assertTrue(decoded.canonical_roundtrip_verified)
            self.assertEqual(decoded.cbh2si4_sha256, config.cbh2si4_sha256)
            self.assertEqual(decoded.scidpgn_sha256, config.scidpgn_sha256)
            self.assertEqual(len(decoded.source.files), 2)
            self.assertEqual(calls[0][1:3], ["--all-tags", "--unusual-tags"])
            self.assertTrue(calls[0][-2].lower().endswith("sample.cbf"))
            self.assertTrue(calls[0][-1].lower().endswith("decoded.si4"))
            self.assertTrue(calls[1][-1].lower().endswith("decoded.si4"))

    def test_unexpected_private_output_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cbf, _ = self._source_family(root)
            config = self._config(root)

            def fake_run(argv: list[str], **kwargs) -> bytes:
                destination = Path(argv[-1])
                destination.write_bytes(b"index")
                destination.with_suffix(".sg4").write_bytes(b"games")
                destination.with_suffix(".sn4").write_bytes(b"names")
                (destination.parent / "unexpected.txt").write_text("unexpected", encoding="utf-8")
                return b"ok"

            with patch("acs.cbf_cbi_external._run_process", side_effect=fake_run):
                with self.assertRaises(CbfCbiExternalError) as caught:
                    read_cbf_cbi_external(cbf, config)
            self.assertEqual(caught.exception.code, CbfCbiExternalCode.TEMP_OUTPUT_INVALID)

    def test_source_mutation_discards_decoded_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cbf, cbi = self._source_family(root)
            config = self._config(root)
            calls = 0

            def fake_run(argv: list[str], **kwargs) -> bytes:
                nonlocal calls
                calls += 1
                if calls == 1:
                    destination = Path(argv[-1])
                    destination.write_bytes(b"index")
                    destination.with_suffix(".sg4").write_bytes(b"games")
                    destination.with_suffix(".sn4").write_bytes(b"names")
                    return b"ok"
                cbi.write_bytes(b"mutated after decode")
                return _PGN

            with patch("acs.cbf_cbi_external._run_process", side_effect=fake_run):
                with self.assertRaises(CbfCbiExternalError) as caught:
                    read_cbf_cbi_external(cbf, config)
            self.assertEqual(caught.exception.code, CbfCbiExternalCode.SOURCE_CHANGED)

    def test_invalid_external_pgn_fails_before_library_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cbf, _ = self._source_family(root)
            config = self._config(root)
            calls = 0

            def fake_run(argv: list[str], **kwargs) -> bytes:
                nonlocal calls
                calls += 1
                if calls == 1:
                    destination = Path(argv[-1])
                    destination.write_bytes(b"index")
                    destination.with_suffix(".sg4").write_bytes(b"games")
                    destination.with_suffix(".sn4").write_bytes(b"names")
                    return b"ok"
                return b"\xff\xfe"

            with patch("acs.cbf_cbi_external._run_process", side_effect=fake_run):
                with self.assertRaises(CbfCbiExternalError) as caught:
                    read_cbf_cbi_external(cbf, config)
            self.assertEqual(caught.exception.code, CbfCbiExternalCode.PGN_INVALID)

    def test_library_seam_publishes_canonical_games_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cbf, _ = self._source_family(root)
            config = self._config(root)
            snapshot = capture_integrity_snapshot(cbf)
            games = tuple(parse_games(_PGN.decode("utf-8")))
            decoded = CbfCbiReadResult(
                source=snapshot,
                source_family_sha256="1" * 64,
                cbh2si4_sha256=config.cbh2si4_sha256,
                scidpgn_sha256=config.scidpgn_sha256,
                games=games,
                canonical_roundtrip_verified=True,
            )
            with AcsDatabase() as database:
                service = CbfCbiLibraryImportService(database, config)
                with patch("acs.cbf_cbi_external.read_cbf_cbi_external", return_value=decoded):
                    report = service.import_database(cbf)
                self.assertEqual(report.status, CbfCbiLibraryImportStatus.IMPORTED)
                self.assertEqual(report.decoded_game_count, 1)
                self.assertEqual(report.imported_game_count, 1)
                self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)

    def test_library_cancellation_after_decode_publishes_no_games(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cbf, _ = self._source_family(root)
            config = self._config(root)
            snapshot = capture_integrity_snapshot(cbf)
            games = tuple(parse_games(_PGN.decode("utf-8")))
            decoded = CbfCbiReadResult(
                source=snapshot,
                source_family_sha256="2" * 64,
                cbh2si4_sha256=config.cbh2si4_sha256,
                scidpgn_sha256=config.scidpgn_sha256,
                games=games,
                canonical_roundtrip_verified=True,
            )
            polls = 0

            def cancel() -> bool:
                nonlocal polls
                polls += 1
                return polls >= 2

            with AcsDatabase() as database:
                service = CbfCbiLibraryImportService(database, config)
                with patch("acs.cbf_cbi_external.read_cbf_cbi_external", return_value=decoded):
                    with self.assertRaises(LibraryImportCancelledError):
                        service.import_database(cbf, cancel_check=cancel)
                self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.chessbase_decoder import ExternalChessBaseDecoderConfig, decode_chessbase_external
from acs.chessbase_metadata import (
    ChessBaseMetadataStatus,
    PINNED_LIBCBH_COMMIT,
    chessbase_metadata_capabilities,
    chessbase_metadata_unavailable_fields,
    scid_eco_main_to_pgn,
)


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _move(frm: int, to: int) -> dict[str, object]:
    return {"kind": "move", "from": frm, "to": to, "promote": 7, "comments": []}


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "index": 0,
        "status": "decoded",
        "start_fen": START_FEN,
        "result": 1,
        "white_first": "Ірина",
        "white_last": "Коваль",
        "black_first": "José",
        "black_last": "Niño",
        "event": "Český šach",
        "site": "Košice",
        "year": 2026,
        "month": 8,
        "day": 31,
        "white_elo": 2412,
        "black_elo": 2333,
        "eco": 132,
        "round": 4,
        "subround": 2,
        "tags": [
            {"name": "ECO", "value": "A01"},
            {"name": "SourceTitle", "value": "München Ω source"},
        ],
        "moves": [_move(12, 28), _move(52, 36)],
    }
    record.update(overrides)
    return record


def _payload(record: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "protocol": "accessible-chess-libcbh-v1",
            "backend": "libcbh",
            "backend_commit": PINNED_LIBCBH_COMMIT,
            "games": [record],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class ChessBaseMetadataContractTests(unittest.TestCase):
    def test_scid_main_eco_mapping_is_exact_and_bounded(self) -> None:
        self.assertIsNone(scid_eco_main_to_pgn(0))
        self.assertEqual(scid_eco_main_to_pgn(1), "A00")
        self.assertEqual(scid_eco_main_to_pgn(132), "A01")
        self.assertEqual(scid_eco_main_to_pgn(12970), "A99")
        self.assertEqual(scid_eco_main_to_pgn(13101), "B00")
        self.assertEqual(scid_eco_main_to_pgn(65370), "E99")
        self.assertIsNone(scid_eco_main_to_pgn(2))
        self.assertIsNone(scid_eco_main_to_pgn(65371))
        self.assertIsNone(scid_eco_main_to_pgn(65535))
        with self.assertRaises(TypeError):
            scid_eco_main_to_pgn(True)  # type: ignore[arg-type]

    def test_capability_accounting_does_not_invent_titles_or_opening(self) -> None:
        capabilities = {item.field: item for item in chessbase_metadata_capabilities()}
        for field in ("White", "Black", "Event", "Site", "Date", "Round", "Result", "WhiteElo", "BlackElo", "ECO"):
            self.assertEqual(capabilities[field].status, ChessBaseMetadataStatus.MAPPED)
        for field in ("SourceDatabase", "SourceIndex", "SourceSHA256"):
            self.assertEqual(capabilities[field].status, ChessBaseMetadataStatus.PROVENANCE)
        self.assertEqual(capabilities["BackendTags"].status, ChessBaseMetadataStatus.PASSTHROUGH)
        self.assertEqual(capabilities["BackendTextEncoding"].status, ChessBaseMetadataStatus.PASSTHROUGH)
        self.assertEqual(
            chessbase_metadata_unavailable_fields(),
            ("Opening", "WhiteTitle", "BlackTitle"),
        )

    def test_decoder_preserves_canonical_metadata_unicode_ratings_and_eco(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Метадані.cbh"
            source.write_bytes(b"fixture")
            (root / "Метадані.cbg").write_bytes(b"moves")
            backend = root / "libcbh-json-bridge"
            backend.write_bytes(b"backend")
            config = ExternalChessBaseDecoderConfig(
                backend,
                expected_backend_commit=PINNED_LIBCBH_COMMIT,
                timeout_seconds=3,
            )
            with mock.patch("acs.chessbase_decoder._run_backend", return_value=_payload(_record())):
                game = decode_chessbase_external(source, config).games[0]

        self.assertEqual(game.tags["White"], "Ірина Коваль")
        self.assertEqual(game.tags["Black"], "José Niño")
        self.assertEqual(game.tags["Event"], "Český šach")
        self.assertEqual(game.tags["Site"], "Košice")
        self.assertEqual(game.tags["Date"], "2026.08.31")
        self.assertEqual(game.tags["Round"], "4.2")
        self.assertEqual(game.tags["Result"], "1-0")
        self.assertEqual(game.tags["WhiteElo"], "2412")
        self.assertEqual(game.tags["BlackElo"], "2333")
        self.assertEqual(game.tags["ECO"], "A01")
        self.assertEqual(game.tags["CBH_ECO"], "132")
        self.assertEqual(game.tags["SourceTitle"], "München Ω source")

    def test_missing_optional_metadata_stays_unknown_instead_of_fabricated(self) -> None:
        record = _record(
            white_first="",
            white_last="",
            black_first="",
            black_last="",
            event="",
            site="",
            year=0,
            month=0,
            day=0,
            white_elo=0,
            black_elo=0,
            eco=0,
            round=0,
            subround=0,
            tags=[],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "missing.cbh"
            source.write_bytes(b"fixture")
            (root / "missing.cbg").write_bytes(b"moves")
            backend = root / "bridge"
            backend.write_bytes(b"backend")
            config = ExternalChessBaseDecoderConfig(
                backend,
                expected_backend_commit=PINNED_LIBCBH_COMMIT,
                timeout_seconds=3,
            )
            with mock.patch("acs.chessbase_decoder._run_backend", return_value=_payload(record)):
                game = decode_chessbase_external(source, config).games[0]

        self.assertEqual(game.tags["White"], "?")
        self.assertEqual(game.tags["Black"], "?")
        self.assertEqual(game.tags["Event"], "?")
        self.assertEqual(game.tags["Site"], "?")
        self.assertEqual(game.tags["Date"], "????.??.??")
        self.assertEqual(game.tags["Round"], "?")
        self.assertNotIn("WhiteElo", game.tags)
        self.assertNotIn("BlackElo", game.tags)
        self.assertNotIn("ECO", game.tags)
        self.assertNotIn("Opening", game.tags)
        self.assertNotIn("WhiteTitle", game.tags)
        self.assertNotIn("BlackTitle", game.tags)


if __name__ == "__main__":
    unittest.main()

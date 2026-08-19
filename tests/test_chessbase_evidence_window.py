from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.chessbase_evidence_window import (
    MAX_CLASSIC_EVIDENCE_WINDOW_RECORDS,
    ChessBaseEvidenceBlockedError,
    ChessBaseEvidenceWindowError,
    read_classic_chessbase_evidence_window,
)
from acs.chessbase_integrity import (
    ChessBaseSourceChangedError,
    verify_integrity_snapshot,
)


def _cbg_game(payload: bytes, *, unsupported: bool = False) -> bytes:
    raw_header = 4 + len(payload)
    if unsupported:
        raw_header |= 0x80000000
    return raw_header.to_bytes(4, "big") + payload


def _cbh_record(
    *,
    game_offset: int,
    flags: int = 0x01,
    white: int = 0,
    black: int = 1,
    tournament: int = 0,
) -> bytes:
    raw = bytearray(46)
    raw[0] = flags
    raw[1:5] = game_offset.to_bytes(4, "big")
    raw[9:12] = white.to_bytes(3, "big")
    raw[12:15] = black.to_bytes(3, "big")
    raw[15:18] = tournament.to_bytes(3, "big")
    return bytes(raw)


def _cbh_file(records: list[bytes]) -> bytes:
    return bytes(46) + b"".join(records)


def _cbp_file() -> bytes:
    data = bytearray(28 + 2 * 67)
    data[0x18] = 0
    for player_no, (last, first) in enumerate(
        (("Carlsen", "Magnus"), ("Anand", "Viswanathan"))
    ):
        base = 28 + player_no * 67
        data[base + 9:base + 9 + len(last)] = last.encode("utf-8")
        data[base + 39:base + 39 + len(first)] = first.encode("utf-8")
    return bytes(data)


def _cbt_file() -> bytes:
    data = bytearray(28 + 99)
    data[0x18] = 0
    data[37:55] = b"World Championship"
    data[77:82] = b"Sochi"
    return bytes(data)


def _write_family(
    root: Path,
    *,
    records: list[bytes],
    cbg_bytes: bytes,
    include_optional: bool = True,
) -> dict[str, Path]:
    paths = {
        "cbh": root / "sample.cbh",
        "cbg": root / "sample.CBG",
        "cbp": root / "sample.cbp",
        "cbt": root / "sample.CbT",
        "cba": root / "sample.cba",
    }
    paths["cbh"].write_bytes(_cbh_file(records))
    paths["cbg"].write_bytes(cbg_bytes)
    paths["cbp"].write_bytes(_cbp_file())
    paths["cbt"].write_bytes(_cbt_file())
    if include_optional:
        paths["cba"].write_bytes(b"optional-annotation-evidence")
    return paths


class ClassicChessBaseEvidenceWindowTests(unittest.TestCase):
    def _standard_family(self, root: Path) -> tuple[dict[str, Path], bytes, bytes]:
        first = _cbg_game(b"one")
        second = _cbg_game(b"two")
        paths = _write_family(
            root,
            records=[
                _cbh_record(game_offset=0),
                _cbh_record(game_offset=len(first)),
            ],
            cbg_bytes=first + second,
        )
        return paths, first, second

    def test_happy_path_is_integrity_verified_partial_evidence_not_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, _, _ = self._standard_family(Path(tmp))
            before = {
                key: path.read_bytes()
                for key, path in paths.items()
                if path.exists()
            }

            window = read_classic_chessbase_evidence_window(
                paths["cbh"],
                start_record_index=1,
                max_records=2,
            )

            self.assertEqual(window.returned_count, 2)
            self.assertEqual(window.projection.complete_count, 2)
            self.assertEqual(window.capability_status, "PARTIAL")
            self.assertTrue(window.source_read_only)
            self.assertTrue(window.integrity_verified)
            self.assertFalse(window.decoder_available)
            self.assertFalse(window.safe_to_import)
            self.assertEqual(
                window.projection.items[0].payload.link.payload.payload_bytes,
                b"one",
            )
            self.assertEqual(
                window.projection.items[1].metadata.metadata.black.pgn_name,
                "Anand, Viswanathan",
            )
            self.assertEqual(
                [item.extension for item in window.source_snapshot.files],
                [".cbh", ".cbg", ".cba", ".cbp", ".cbt"],
            )
            self.assertEqual(
                {
                    key: path.read_bytes()
                    for key, path in paths.items()
                    if path.exists()
                },
                before,
            )

    def test_requested_record_window_does_not_project_other_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, _, _ = self._standard_family(Path(tmp))

            window = read_classic_chessbase_evidence_window(
                paths["cbh"],
                start_record_index=2,
                max_records=1,
            )

        self.assertEqual(window.returned_count, 1)
        self.assertEqual(window.projection.items[0].record_index, 2)
        self.assertEqual(
            window.projection.items[0].payload.link.payload.payload_bytes,
            b"two",
        )

    def test_payload_and_metadata_failures_remain_independent_per_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = _cbg_game(b"valid-payload")
            second = _cbg_game(b"unsupported", unsupported=True)
            paths = _write_family(
                root,
                records=[
                    _cbh_record(game_offset=0, white=99),
                    _cbh_record(game_offset=len(first)),
                ],
                cbg_bytes=first + second,
            )

            window = read_classic_chessbase_evidence_window(
                paths["cbh"],
                start_record_index=1,
                max_records=2,
            )

        first_item, second_item = window.projection.items
        self.assertEqual([first_item.status, second_item.status], ["partial", "partial"])
        self.assertEqual(first_item.payload.status, "linked")
        self.assertEqual(first_item.metadata.error_type, "CbpDecodeError")
        self.assertEqual(second_item.payload.error_type, "CbgDecodeError")
        self.assertEqual(second_item.metadata.status, "projected")

    def test_payload_limit_is_an_explicit_record_failure_not_a_decode_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, _, _ = self._standard_family(Path(tmp))

            window = read_classic_chessbase_evidence_window(
                paths["cbh"],
                start_record_index=1,
                max_records=1,
                max_payload_bytes=2,
            )

        item = window.projection.items[0]
        self.assertEqual(item.status, "partial")
        self.assertEqual(item.payload.status, "failed")
        self.assertIn("exceeds configured bound", item.payload.reason)
        self.assertEqual(item.metadata.status, "projected")

    def test_missing_required_components_is_blocked_with_exact_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cbh = root / "incomplete.cbh"
            cbh.write_bytes(_cbh_file([]))
            (root / "incomplete.cbg").write_bytes(b"")

            with self.assertRaisesRegex(
                ChessBaseEvidenceBlockedError,
                r"\.cbp, \.cbt",
            ):
                read_classic_chessbase_evidence_window(
                    cbh,
                    start_record_index=1,
                    max_records=0,
                )

        self.assertEqual(ChessBaseEvidenceBlockedError.status, "BLOCKED")

    def test_non_cbh_primary_is_blocked_before_any_decode_attempt(self):
        with self.assertRaisesRegex(
            ChessBaseEvidenceBlockedError,
            "primary .cbh source",
        ):
            read_classic_chessbase_evidence_window(
                "archive.cbv",
                start_record_index=1,
                max_records=1,
            )

    def test_window_and_payload_bounds_require_exact_integers(self):
        for value in (0, True, 1.5):
            with self.subTest(field="start_record_index", value=value):
                with self.assertRaises(ChessBaseEvidenceWindowError):
                    read_classic_chessbase_evidence_window(
                        "missing.cbh",
                        start_record_index=value,
                        max_records=1,
                    )
        for value in (-1, True, 1.5, MAX_CLASSIC_EVIDENCE_WINDOW_RECORDS + 1):
            with self.subTest(field="max_records", value=value):
                with self.assertRaises(ChessBaseEvidenceWindowError):
                    read_classic_chessbase_evidence_window(
                        "missing.cbh",
                        start_record_index=1,
                        max_records=value,
                    )
        for value in (-1, True, 1.5):
            with self.subTest(field="max_payload_bytes", value=value):
                with self.assertRaises(ChessBaseEvidenceWindowError):
                    read_classic_chessbase_evidence_window(
                        "missing.cbh",
                        start_record_index=1,
                        max_records=1,
                        max_payload_bytes=value,
                    )

    def test_zero_record_window_still_verifies_the_complete_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, _, _ = self._standard_family(Path(tmp))

            window = read_classic_chessbase_evidence_window(
                paths["cbh"],
                start_record_index=99,
                max_records=0,
            )

        self.assertEqual(window.returned_count, 0)
        self.assertEqual(window.projection.items, ())
        self.assertTrue(window.integrity_verified)

    def test_post_read_family_change_discards_the_evidence_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, _, _ = self._standard_family(Path(tmp))

            def mutate_then_verify(snapshot):
                paths["cba"].write_bytes(b"changed-after-bounded-reads")
                return verify_integrity_snapshot(snapshot)

            with mock.patch(
                "acs.chessbase_evidence_window.verify_integrity_snapshot",
                side_effect=mutate_then_verify,
            ):
                with self.assertRaises(ChessBaseSourceChangedError):
                    read_classic_chessbase_evidence_window(
                        paths["cbh"],
                        start_record_index=1,
                        max_records=1,
                    )


if __name__ == "__main__":
    unittest.main()

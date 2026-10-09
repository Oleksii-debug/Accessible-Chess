from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.section37_closure_gate import (
    CATALOG,
    REGISTRY,
    Section37ClosureError,
    build_report,
    load_json,
    safe_single_member_zip,
    validate_registry,
    verified_snapshot,
)


class Section37TerminalClosureTests(unittest.TestCase):
    def test_exact_repository_corpus_passes_terminal_gate(self) -> None:
        report = build_report()
        self.assertEqual(report["status"], "DONE_TERMINAL")
        self.assertEqual(set(report["subsections"].values()), {"PASS"})
        self.assertGreaterEqual(report["registry"]["canonical_entries"], 24)
        self.assertGreaterEqual(report["registry"]["supplemental_sources"], 69)
        self.assertGreaterEqual(report["registry"]["qualified_local_sources"], 14)
        self.assertEqual(report["semantic_readback"]["opening_tsv_rows"], 3865)
        self.assertEqual(report["semantic_readback"]["stockfish_pgn_games"], 12092)
        self.assertEqual(report["semantic_readback"]["epd_fen_rows"], 1596)
        self.assertEqual(
            report["external_literature_readback"],
            {
                "pinned_raw_originals": 3,
                "semantic_restart_pass": 2,
                "documented_unsupported_encoding": 1,
            },
        )
        self.assertEqual(report["real_chessbase_readback"]["cbv_decoded_games"], 113)
        self.assertEqual(
            report["documented_unavailable_not_blocking"],
            ["CBF+CBI", "2CBH", "CBONE"],
        )

    def test_registry_mutations_fail_closed(self) -> None:
        registry = load_json(REGISTRY)
        catalog = load_json(CATALOG)
        bad_cases = []
        duplicate = json.loads(json.dumps(registry))
        duplicate["entries"].append(duplicate["entries"][0])
        bad_cases.append(duplicate)
        rights = json.loads(json.dumps(registry))
        rights["entries"][0].pop("rights")
        bad_cases.append(rights)
        false_done = json.loads(json.dumps(registry))
        false_done["closure"]["documented_unavailable_not_blocking"] = []
        bad_cases.append(false_done)
        reopened = json.loads(json.dumps(registry))
        reopened["closure"]["partial"] = ["37.4"]
        bad_cases.append(reopened)
        for candidate in bad_cases:
            with self.subTest(candidate=candidate["closure"]):
                with self.assertRaises(Section37ClosureError):
                    validate_registry(candidate, catalog)

        from tools.section37_closure_gate import _external_book_qualification

        bad_catalog = json.loads(json.dumps(catalog))
        for source in bad_catalog["sources"]:
            if source["id"] == "gutenberg_blue_book_chess_staunton":
                source["upstream_commit"] = "0" * 40
        with self.assertRaises(Section37ClosureError):
            _external_book_qualification(
                bad_catalog,
                load_json(
                    REGISTRY.parent
                    / "SECTION37_GITENBERG_ORIGINAL_TEXT_SHA256_READBACK_20261009.json"
                ),
            )

    def test_checksum_tamper_and_indirect_file_are_rejected(self) -> None:
        original = b"pinned original source bytes"
        with tempfile.TemporaryDirectory(prefix="section37-negative-") as temporary:
            root = Path(temporary)
            source = root / "source.bin"
            source.write_bytes(original)
            digest = hashlib.sha256(original).hexdigest()
            self.assertEqual(
                verified_snapshot(source, digest=digest, max_bytes=1024), original
            )
            source.write_bytes(original + b"tampered")
            with self.assertRaises(Section37ClosureError):
                verified_snapshot(source, digest=digest, max_bytes=1024)
            source.write_bytes(original)
            indirect = root / "indirect.bin"
            try:
                indirect.symlink_to(source)
            except (NotImplementedError, OSError):
                return
            with self.assertRaises(Section37ClosureError):
                verified_snapshot(indirect, digest=digest, max_bytes=1024)

    @staticmethod
    def _zip(files: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in files.items():
                archive.writestr(name, payload)
        return buffer.getvalue()

    def test_zip_traversal_multiple_members_bomb_and_corruption_are_rejected(self) -> None:
        name, payload = safe_single_member_zip(
            self._zip({"safe.pgn": b"1. e4 e5 *\n"}), expected_member="safe.pgn"
        )
        self.assertEqual((name, payload), ("safe.pgn", b"1. e4 e5 *\n"))
        invalid = (
            self._zip({"../escape.pgn": b"bad"}),
            self._zip({"one.pgn": b"1", "two.pgn": b"2"}),
            self._zip({"large.pgn": b"x" * 4097}),
            b"PK\x03\x04damaged",
        )
        for index, archive in enumerate(invalid):
            with self.subTest(index=index):
                with self.assertRaises(Section37ClosureError):
                    safe_single_member_zip(archive, max_unpacked_bytes=4096)

    def test_duplicate_json_keys_and_nonfinite_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="section37-json-") as temporary:
            path = Path(temporary) / "bad.json"
            for raw in (b'{"section":37,"section":38}', b'{"value":NaN}'):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    with self.assertRaises(Section37ClosureError):
                        load_json(path)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from copy import deepcopy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from acs.lawful_corpus_registry import (
    LawfulCorpusError, _NoRedirect, acquire_cc0_source, load_catalog,
    verified_local_source, qualify_offline_collection,
)
from urllib.request import Request


class Response(io.BytesIO):
    def __init__(self, content: bytes, url: str):
        super().__init__(content)
        self.url = url

    def geturl(self) -> str:
        return self.url


class RevisedCorpusContractTests(unittest.TestCase):
    def test_catalog_is_size_bounded_before_parsing(self):
        # The size guard must bound the read call, not just check its result.
        source_bytes = (Path(__file__).resolve().parents[1] /
                        "docs/corpus/revised_sections37_40_sources.json").read_bytes()
        class GuardedInput(io.BytesIO):
            def read(self, size=-1):
                if size != 256 * 1024 + 1:
                    raise AssertionError("unbounded catalog read")
                return super().read(size)

        with patch.object(Path, "open", return_value=GuardedInput(source_bytes)):
            self.assertGreater(len(load_catalog(Path("virtual-catalog.json"))), 0)
        with tempfile.TemporaryDirectory() as tmp:
            too_large = Path(tmp) / "oversized.json"
            too_large.write_bytes(b" " * (256 * 1024 + 1))
            with self.assertRaisesRegex(LawfulCorpusError, "exceeds maximum"):
                load_catalog(too_large)

    def test_source_growth_stops_hashing_at_byte_budget(self):
        payload = b"origin"
        record = self._record(payload)
        record["max_bytes"] = len(payload) + 4
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "growing.pgn.zst"
            path.write_bytes(payload)

            class GrowingStream:
                def __init__(self, stream):
                    self.stream = stream
                    self.reads = 0

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return self.stream.__exit__(*args)

                def fileno(self):
                    return self.stream.fileno()

                def read(self, size):
                    self.reads += 1
                    if self.reads == 1:
                        with open(path, "ab") as writer:
                            writer.write(b"x" * 8192)
                    return self.stream.read(size)

            stream = GrowingStream(path.open("rb"))
            with patch.object(Path, "open", return_value=stream):
                with self.assertRaisesRegex(LawfulCorpusError, "grew beyond"):
                    verified_local_source(path, record)
            self.assertEqual(stream.reads, 1)

    def test_actual_catalog_truth_and_unsupported_families(self):
        records = {entry["id"]: entry for entry in load_catalog()}
        self.assertIn("lichess_standard_rated_2013_01", records)
        lichess = records["lichess_standard_rated_2013_01"]
        self.assertEqual(lichess["sha256"], "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635")
        self.assertEqual(lichess["license"], "CC0")
        self.assertIn("NOT_DOWNLOADED", lichess["acquisition"])
        self.assertIsNone(records["capablanca_chess_fundamentals_txt"]["sha256"])
        cbh = records["chessbase_family_complete_real_samples"]
        self.assertEqual(cbh["acquisition"], "BLOCKED_NO_LAWFUL_COMPLETE_SAMPLE")
        self.assertEqual(cbh["redistribution"], "NOT_CLEARED")
        for identifier in (
            "lichess_standard_rated_2013_02",
            "lichess_standard_rated_2013_03",
        ):
            with self.subTest(source=identifier):
                candidate = records[identifier]
                self.assertEqual(candidate["license"], "CC0")
                self.assertEqual(candidate["acquisition"], "DISCOVERED_NOT_HASH_VERIFIED")
                self.assertIsNone(candidate["sha256"])
        for identifier in (
            "gutenberg_chess_strategy_lasker",
            "gutenberg_blue_book_chess_staunton",
            "gutenberg_chess_and_checkers_lasker",
            "gutenberg_szachy_warcaby_polish",
        ):
            with self.subTest(source=identifier):
                candidate = records[identifier]
                self.assertEqual(candidate["acquisition"], "SOURCE_PAGE_ONLY")
                self.assertEqual(candidate["redistribution"], "NOT_CLEARED")
                self.assertIsNone(candidate["sha256"])

    def _record(self, payload: bytes) -> dict:
        return {
            "id": "licensed_small_fixture", "license": "CC0",
            "redistribution": "permitted", "format": "pgn.zst",
            "acquisition": "PINNED_NOT_DOWNLOADED_IN_THIS_PASS",
            "download_url": "https://database.lichess.org/standard/test.pgn.zst",
            "sha256": hashlib.sha256(payload).hexdigest(), "max_bytes": 4096,
        }

    def test_verified_payload_publishes_once_no_overwrite(self):
        data = b"real-transport-fixture-not-represented-as-real-chess-games"
        record = self._record(data)
        hits = []
        def opener(request, timeout):
            hits.append(request.full_url)
            return Response(data, request.full_url)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = acquire_cc0_source(record, root, opener=opener)
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(verified_local_source(target, record), record["sha256"])
            self.assertEqual(acquire_cc0_source(record, root, opener=lambda *_a, **_kw: self.fail("unexpected network")), target)
        self.assertEqual(hits, [record["download_url"]])

    def test_unpinned_or_unlicensed_material_never_opens_network(self):
        base = self._record(b"sample")
        for bad in (
            {"license": "UNKNOWN"},
            {"redistribution": "NOT_CLEARED"},
            {"sha256": None},
            {"acquisition": "DISCOVERED_NOT_HASH_VERIFIED"},
            {"download_url": "http://database.lichess.org/a"},
            {"download_url": "https://example.com/a"},
            {"download_url": "https://database.lichess.org/a?token=secret"},
            {"id": "../escape"},
        ):
            with self.subTest(bad=bad):
                record = {**base, **bad}
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(LawfulCorpusError):
                        acquire_cc0_source(record, Path(tmp), opener=lambda *_a, **_kw: self.fail("network should not be called"))

    def test_redirect_overlong_and_digest_mismatch_never_publish(self):
        data = b"payload-with-changed-sha"
        record = self._record(data)
        variants = (
            (b"untrusted", record["download_url"]),
            (data * 600, record["download_url"]),
            (data, "https://example.com/malicious"),
        )
        for content, final_url in variants:
            with self.subTest(size=len(content), final_url=final_url):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with self.assertRaises(LawfulCorpusError):
                        acquire_cc0_source(
                            record, root,
                            opener=lambda *_a, **_kw: Response(content, final_url),
                        )
                    self.assertEqual(list(root.iterdir()), [])

    def test_offline_test_and_public_release_split_never_leaks_unqualified_material(self):
        payload = b"CC0 fixture bytes"
        accepted = self._record(payload)
        book = {**accepted, "id": "unverified_book", "license": "UNKNOWN", "redistribution": "NOT_CLEARED"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for mode in ("TEST_BUILD", "PUBLIC_RELEASE"):
                self.assertEqual(qualify_offline_collection((accepted, book), root, distribution=mode), ())
            target = root / (accepted["id"] + ".pgn.zst")
            target.write_bytes(payload)
            for mode in ("TEST_BUILD", "PUBLIC_RELEASE"):
                result = qualify_offline_collection((accepted, book), root, distribution=mode)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["source_id"], accepted["id"])
                self.assertEqual(result[0]["semantic_state"], "VERIFIED_BYTES_NOT_IMPORTED")
            target.write_bytes(b"tampered")
            with self.assertRaises(LawfulCorpusError):
                qualify_offline_collection((accepted, book), root, distribution="PUBLIC_RELEASE")
            with self.assertRaises(LawfulCorpusError):
                qualify_offline_collection((accepted, book), root, distribution="production")

    def test_private_file_symlink_and_checksum_mutation_fail_closed(self):
        record = self._record(b"correct")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data.pgn.zst"
            path.write_bytes(b"correct")
            self.assertEqual(verified_local_source(path, record), record["sha256"])
            path.write_bytes(b"changed")
            with self.assertRaises(LawfulCorpusError):
                verified_local_source(path, record)
            path.unlink()
            target = root / "target"
            target.write_bytes(b"correct")
            try:
                path.symlink_to(target)
            except (OSError, NotImplementedError):
                return
            with self.assertRaises(LawfulCorpusError):
                verified_local_source(path, record)

    def test_default_transport_disables_redirects_before_second_request(self):
        data = b"approved-source-bytes"
        record = self._record(data)
        with tempfile.TemporaryDirectory() as tmp:
            fake_opener = Mock()
            fake_opener.open.return_value = Response(data, record["download_url"])
            with patch("acs.lawful_corpus_registry.build_opener", return_value=fake_opener) as factory:
                source = acquire_cc0_source(record, Path(tmp))
            self.assertEqual(source.read_bytes(), data)
            self.assertEqual(factory.call_count, 1)
            self.assertIsInstance(factory.call_args.args[0], _NoRedirect)
            fake_opener.open.assert_called_once()
            self.assertIsNone(_NoRedirect().redirect_request(
                Request(record["download_url"]), None, 302, "Redirect", {},
                "https://example.com/disallowed.pgn.zst",
            ))

    def test_malformed_url_ports_and_brackets_fail_as_corpus_errors(self):
        base = self._record(b"safe")
        for url in (
            "https://database.lichess.org:wrong/standard/data.pgn.zst",
            "https://[malformed/standard/data.pgn.zst",
            "https://database.lichess.org:444/standard/data.pgn.zst",
        ):
            with self.subTest(url=url):
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(LawfulCorpusError):
                        acquire_cc0_source(
                            {**base, "download_url": url}, Path(tmp),
                            opener=lambda *_a, **_kw: self.fail("must not use network"),
                        )


if __name__ == "__main__":
    unittest.main()

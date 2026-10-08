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
    iter_bounded_corpus_lines,
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

    def test_catalog_schema_version_rejects_bool_and_float_forgery(self):
        # JSON true == 1 and 1.0 == 1 under Python equality; neither is
        # an actual integer schema revision. Reject before trusting records.
        canonical = (Path(__file__).resolve().parents[1] /
                     "docs/corpus/revised_sections37_40_sources.json").read_bytes()
        marker = b'"schema_version": 1'
        self.assertIn(marker, canonical)
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "forged-schema.json"
            for forged in (b"true", b"1.0", b'"1"', b"false", b"null"):
                with self.subTest(schema=forged):
                    catalog.write_bytes(
                        canonical.replace(marker, b'"schema_version": ' + forged, 1)
                    )
                    with self.assertRaisesRegex(LawfulCorpusError, "schema invalid"):
                        load_catalog(catalog)

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
        # Official checksums: database.lichess.org/standard/sha256sums.txt.
        # This proves catalog pinning, NOT a download or semantic import.
        for identifier, digest in (
            ("lichess_standard_rated_2013_02", "c136acdf343293c45252906fee91e3b561fb26a936979f52dbe04bb649a2fd86"),
            ("lichess_standard_rated_2013_03", "89da64fc3c1fe3bfd571d7f626232189f3259aa728b46ea81e5cb8f3fdb34b9e"),
        ):
            with self.subTest(source=identifier):
                candidate = records[identifier]
                self.assertEqual(candidate["license"], "CC0")
                self.assertEqual(candidate["redistribution"], "permitted")
                self.assertEqual(candidate["acquisition"], "PINNED_NOT_DOWNLOADED_IN_THIS_PASS")
                self.assertEqual(candidate["sha256"], digest)
        for identifier in (
            "gutenberg_chess_strategy_lasker",
            "gutenberg_chess_and_checkers_lasker",
            "gutenberg_szachy_warcaby_polish",
        ):
            with self.subTest(source=identifier):
                candidate = records[identifier]
                self.assertEqual(candidate["acquisition"], "SOURCE_PAGE_ONLY")
                self.assertEqual(candidate["redistribution"], "NOT_CLEARED")
                self.assertIsNone(candidate["sha256"])
        # Official 2013-04 and 2013-08 pinned source listing; catalog only.
        for source_id, digest, expected_bytes in (
            ("lichess_standard_rated_2013_04", "11c795d3c81c49fa97cd958b0984c044410c78ad90f454ed08abb57ab7d00d52", 23299559),
            ("lichess_standard_rated_2013_08", "6202408d1c1cf11b1a9043b84c6bd2c03a01cb31597863857c26ee6ff82eea1b", 47706246),
        ):
            with self.subTest(source=source_id):
                record = records[source_id]
                self.assertEqual(record["sha256"], digest)
                self.assertEqual(record["indexed_bytes"], expected_bytes)
                self.assertGreaterEqual(record["max_bytes"], expected_bytes)
                self.assertEqual(record["license"], "CC0")
                self.assertEqual(record["redistribution"], "permitted")
                self.assertEqual(record["acquisition"], "PINNED_NOT_DOWNLOADED_IN_THIS_PASS")
        # The official 2013-04 and 2013-08 pinned source listing does not prove download.
        # Ebook #15201 explicitly says 'Copyrighted' on Project Gutenberg.
        polish = records["gutenberg_szachy_warcaby_polish"]
        self.assertTrue(polish["license"].startswith("COPYRIGHTED"))
        self.assertEqual(polish["redistribution"], "NOT_CLEARED")

    def test_extreme_lichess_fixture_requires_pinned_cc0_license_for_inventory(self):
        from acs.lawful_corpus_registry import inventory_vendored_corpus

        records = {record["id"]: record for record in load_catalog()}
        source = records["lichess_cc0_extreme_4_original_derived_puzzles"]
        self.assertEqual(source["license"], "CC0-1.0")
        self.assertEqual(source["license_source"], "tests/real_corpus/lichess_openings_COPYING.txt")
        self.assertEqual(
            source["license_sha256"],
            "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499",
        )
        root = Path(__file__).resolve().parents[1]
        actual = inventory_vendored_corpus((source,), root, distribution="TEST_BUILD")
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]["sha256"], source["sha256"])
        # Wrong attestation must never turn unverified bytes into an inventory PASS.
        tampered = {**source, "license_sha256": "0" * 64}
        with self.assertRaisesRegex(LawfulCorpusError, "mismatch"):
            inventory_vendored_corpus((tampered,), root, distribution="TEST_BUILD")
        uncleared = {**source, "redistribution": "NOT_CLEARED"}
        self.assertEqual(
            inventory_vendored_corpus((uncleared,), root, distribution="TEST_BUILD"),
            (),
        )

    def test_catalog_only_official_positions_and_broadcasts_never_auto_download(self):
        records = {entry["id"]: entry for entry in load_catalog()}
        candidates = (
            ("lichess_official_puzzles_fen_csv", "csv.zst (FEN/UCI puzzles)", "CC0"),
            ("lichess_official_broadcast_pgn", "pgn.zst (annotated broadcasts)", "CC BY-SA 4.0"),
        )
        for identifier, expected_format, license_marker in candidates:
            with self.subTest(source=identifier):
                entry = records[identifier]
                self.assertEqual(entry["format"], expected_format)
                self.assertIn(license_marker, entry["license"])
                self.assertEqual(entry["source_page"], "https://database.lichess.org/")
                self.assertIsNone(entry["sha256"])
                self.assertIsNone(entry["download_url"])
                self.assertEqual(entry["max_bytes"], 0)
                self.assertEqual(entry["acquisition"], "SOURCE_PAGE_ONLY")
                self.assertEqual(entry["redistribution"], "NOT_CLEARED")
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(LawfulCorpusError):
                        acquire_cc0_source(
                            entry, Path(tmp),
                            opener=lambda *_args, **_kwargs: self.fail(
                                "discovered source must never use network implicitly"
                            ),
                        )

    def test_official_cbv_free_sample_is_discovery_only_and_never_auto_fetched(self):
        records = {entry["id"]: entry for entry in load_catalog()}
        cbv = records["chessbase_official_free_rossolimo_cbv_sample"]
        self.assertEqual(cbv["format"], "cbv")
        self.assertEqual(cbv["acquisition"], "DISCOVERED_NOT_HASH_VERIFIED")
        self.assertEqual(cbv["redistribution"], "NOT_CLEARED")
        self.assertIsNone(cbv["sha256"])
        self.assertEqual(cbv["max_bytes"], 0)
        self.assertEqual(
            cbv["source_page"],
            "https://shop.chessbase.com/en/products/chessbase_17_starter_package",
        )
        self.assertEqual(
            cbv["download_url"],
            "https://de.chessbase.com/Portals/3/files/2013/CBM155Leseprobe/B30SicilianRossolimo155.cbv",
        )
        with tempfile.TemporaryDirectory() as tmp:
            network = Mock(side_effect=AssertionError("CBV discovery must never fetch"))
            with self.assertRaises(LawfulCorpusError):
                acquire_cc0_source(cbv, Path(tmp), opener=network)
            network.assert_not_called()
            # A forged caller-side CC0 label also cannot repurpose the pinned
            # PGN transfer capability into a ChessBase-origin downloader.
            spoof = {**self._record(b"dummy"), "download_url": cbv["download_url"]}
            with self.assertRaisesRegex(LawfulCorpusError, "host not authorized"):
                acquire_cc0_source(spoof, Path(tmp), opener=network)
            network.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_genuine_upstream_cc0_source_bytes_license_and_tamper_refusal(self):
        from acs.lawful_corpus_registry import _https_url
        records = {record["id"]: record for record in load_catalog()}
        original = records["lichess_openings_original_eco_a_tsv"]
        root = Path(__file__).resolve().parents[1]
        source = root / original["local_source"]
        license_file = root / original["license_source"]

        self.assertEqual(original["upstream_git_blob"], "561099854a15dfb523759aa87993a1fe480a6abc")
        self.assertEqual(original["indexed_bytes"], 67257)
        self.assertEqual(original["acquisition"], "VENDORED_SOURCE_VERIFIED")
        self.assertEqual(original["sha256"], "3282e4c9155289a29224f9a85fba0decb46efa35c2fa5e39662d2ac48fb0f793")
        self.assertEqual(original["license_sha256"], "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499")
        self.assertEqual(source.stat().st_size, original["indexed_bytes"])
        self.assertEqual(verified_local_source(source, original), original["sha256"])
        self.assertEqual(hashlib.sha256(license_file.read_bytes()).hexdigest(), original["license_sha256"])
        self.assertIn(b"CC0 1.0 Universal", license_file.read_bytes())
        self.assertEqual(_https_url(original["source_page"], source_page=True), original["source_page"])
        with self.assertRaises(LawfulCorpusError):
            _https_url(original["source_page"])

        # These 823 genuine rows are upstream opening-line facts, NOT
        # full PGN games; never pass them off as native multi-game imports.
        rows = source.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 824)
        self.assertEqual(rows[0], "eco\tname\tpgn")
        for row in rows[1:]:
            eco, name, sequence = row.split("\t")
            self.assertTrue(eco.startswith("A") and len(eco) == 3)
            self.assertTrue(name and sequence)
        with tempfile.TemporaryDirectory() as tmp:
            tampered = Path(tmp) / "tampered.tsv"
            damaged = bytearray(source.read_bytes())
            damaged[0] ^= 1
            tampered.write_bytes(damaged)
            with self.assertRaises(LawfulCorpusError):
                verified_local_source(tampered, original)
            with self.assertRaises(LawfulCorpusError):
                acquire_cc0_source(
                    original, Path(tmp),
                    opener=lambda *_args, **_kwargs: self.fail(
                        "vendored source is not authorized for implicit network"
                    ),
                )

    def test_decoded_pgn_framer_uses_bounded_lines_and_total_budget(self):
        # Deliberately exercise transport resource checks without inventing
        # syntactically valid Product PGN or mocking real source qualification.
        payload = '[Event "One"]\n1. e4 e5 1-0\n'
        self.assertEqual(
            "".join(iter_bounded_corpus_lines(
                io.StringIO(payload), max_line_chars=64,
                max_decoded_chars=len(payload),
            )),
            payload,
        )
        # An unterminated final line exactly on the bound is allowed.
        self.assertEqual(
            list(iter_bounded_corpus_lines(
                io.StringIO("x" * 16), max_line_chars=16,
                max_decoded_chars=16,
            )),
            ["x" * 16],
        )
        for payload, line_budget, total_budget in (
            ("x" * 129 + "\n", 128, 4096),
            ("x" * 17, 16, 4096),
            ("ok\n" * 12, 16, 32),
        ):
            with self.subTest(length=len(payload), line_budget=line_budget):
                with self.assertRaisesRegex(LawfulCorpusError, "resource limit"):
                    list(iter_bounded_corpus_lines(
                        io.StringIO(payload),
                        max_line_chars=line_budget,
                        max_decoded_chars=total_budget,
                    ))

    def test_decoded_pgn_framer_rejects_invalid_limits(self):
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit):
                with self.assertRaises(LawfulCorpusError):
                    list(iter_bounded_corpus_lines(
                        io.StringIO("[Event \"A\"]\n"),
                        max_line_chars=limit,
                    ))

    def test_direct_corpus_callers_cannot_disable_source_size_bounds(self):
        # The catalog is validated, but the transport also accepts record
        # dictionaries directly. Reject missing/non-integer/oversized budgets
        # BEFORE any network access or source-byte consumption.
        content = b"bounded-licensed-source"
        authorized = self._record(content)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "input.pgn.zst"
            existing.write_bytes(content)
            self.assertEqual(verified_local_source(existing, authorized), authorized["sha256"])
            for bad_limit in (
                None, True, False, 0, -1, 1.5, float("inf"),
                "4096", 128 * 1024 * 1024 + 1,
            ):
                with self.subTest(budget=repr(bad_limit)):
                    tampered = {**authorized, "max_bytes": bad_limit}
                    with self.assertRaisesRegex(LawfulCorpusError, "byte limit"):
                        verified_local_source(existing, tampered)
                    with self.assertRaisesRegex(LawfulCorpusError, "byte limit"):
                        acquire_cc0_source(
                            tampered, root,
                            opener=lambda *_a, **_kw: self.fail(
                                "invalid byte limit must never contact network"
                            ),
                        )
            absent = {k: v for k, v in authorized.items() if k != "max_bytes"}
            with self.assertRaisesRegex(LawfulCorpusError, "byte limit"):
                acquire_cc0_source(
                    absent, root,
                    opener=lambda *_a, **_kw: self.fail("missing limit contacted network"),
                )
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["input.pgn.zst"])

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


    def test_real_lichess_eco_b_source_provenance_and_opening_readback(self):
        """Genuine upstream CC0 B-family chess data, not invented full games."""
        import csv

        from acs.pgn_roundtrip import parse_pgn_text

        root = Path(__file__).resolve().parents[1]
        catalog = {item["id"]: item for item in load_catalog()}
        record = catalog["lichess_openings_original_eco_b_tsv"]
        source = root / record["local_source"]
        license_file = root / record["license_source"]
        original = source.read_bytes()
        self.assertEqual(record["acquisition"], "VENDORED_SOURCE_VERIFIED")
        self.assertEqual(record["license"], "CC0")
        self.assertEqual(record["redistribution"], "permitted")
        self.assertEqual(len(original), 78124)
        self.assertEqual(record["indexed_bytes"], len(original))
        self.assertEqual(
            verified_local_source(source, record),
            "1d5ed134ebbd87915ead5683416e37583bb3e5ae3582b4d8cb5cb4aa7ef4f623",
        )
        header = f"blob {len(original)}\0".encode("ascii")
        self.assertEqual(
            hashlib.sha1(header + original).hexdigest(),
            "41c3727d28fc0b5915f30f3b634c07bd296f4bdb",
        )
        self.assertEqual(
            hashlib.sha256(license_file.read_bytes()).hexdigest(),
            record["license_sha256"],
        )
        rows = list(csv.DictReader(
            io.StringIO(original.decode("utf-8-sig")), delimiter="\t"
        ))
        self.assertEqual(len(rows), 781)
        self.assertEqual(tuple(rows[0]), ("eco", "name", "pgn"))
        for row in rows[:12]:
            with self.subTest(name=row["name"]):
                self.assertTrue(row["eco"].startswith("B"))
                self.assertTrue(row["pgn"].startswith("1. "))
                parsed = parse_pgn_text(
                    '[Event "Official Lichess ECO B opening"]\n[Result "*"]\n\n'
                    + row["pgn"] + " *\n", strict=False,
                )
                self.assertEqual(len(parsed), 1)
        with tempfile.TemporaryDirectory() as temp:
            tampered = Path(temp) / "tampered.tsv"
            damaged = bytearray(original)
            damaged[-1] ^= 1
            tampered.write_bytes(damaged)
            with self.assertRaises(LawfulCorpusError):
                verified_local_source(tampered, record)
            with self.assertRaises(LawfulCorpusError):
                acquire_cc0_source(
                    record, Path(temp),
                    opener=lambda *_args, **_kw: self.fail(
                        "vendored TSV must not trigger implicit network calls"
                    ),
                )

    def test_real_lichess_eco_a_openings_match_upstream_and_canonical_pgn(self):
        """Read actual vendored CC0 openings, not a generated format fixture.

        This qualifies one limited read-side source slice. An ECO opening line
        is not a complete historical game or proof of full Section-37 closure.
        """
        import csv

        from acs.pgn_roundtrip import parse_pgn_text

        record = {
            item["id"]: item for item in load_catalog()
        }["lichess_openings_original_eco_a_tsv"]
        self.assertEqual(record["license"], "CC0")
        self.assertEqual(record["acquisition"], "VENDORED_SOURCE_VERIFIED")
        original = (
            Path(__file__).resolve().parents[1]
            / "tests/real_corpus/lichess_openings_a.tsv"
        ).read_bytes()
        # Git's object hash binds the actual test source to the upstream
        # Lichess revision, rather than to a worker-authored imitation.
        git_header = f"blob {len(original)}\0".encode("ascii")
        self.assertEqual(
            hashlib.sha1(git_header + original).hexdigest(),
            record["upstream_git_blob"],
        )
        rows = list(csv.DictReader(
            io.StringIO(original.decode("utf-8-sig")), delimiter="\t"
        ))
        self.assertGreaterEqual(len(rows), 12)
        self.assertEqual(tuple(rows[0]), ("eco", "name", "pgn"))
        for row in rows[:12]:
            with self.subTest(opening=row["name"]):
                self.assertTrue(row["eco"].startswith("A"))
                self.assertTrue(row["name"])
                self.assertTrue(row["pgn"].startswith("1. "))
                pgn = (
                    '[Event "Lichess ECO A opening"]\n'
                    '[Result "*"]\n\n'
                    + row["pgn"] + ' *\n'
                )
                self.assertEqual(len(parse_pgn_text(pgn, strict=False)), 1)
        # Byte modification must invalidate provenance independently of PGN.
        corrupted = bytearray(original)
        corrupted[-1] ^= 1
        self.assertNotEqual(
            hashlib.sha1(git_header + corrupted).hexdigest(),
            record["upstream_git_blob"],
        )



    def test_real_lichess_eco_c_d_e_upstream_sources_and_canonical_readback(self):
        """Official CC0 source bytes, never synthetic completed games or ChessBase."""
        import csv

        from acs.pgn_roundtrip import parse_pgn_text

        records = {item["id"]: item for item in load_catalog()}
        root = Path(__file__).resolve().parents[1]
        for family, expected_rows, expected_size, expected_digest, expected_blob in (
            ("c", 1250, 132304, "45e843c7b7e79a0d04d5bda879c9bd23f5a10974488bd8615e4f4c5d0749986f", "4b3d9c90c67864db6eb728d82b225b44d91fccbd"),
            ("d", 644, 73318, "1cf4057a8aece94f27bb3f278ad410ee2844831a642364eeceaafa091dbcceda", "a829bac9d2f288b033d605e842f3b802379e3455"),
            ("e", 367, 44061, "48c6f6645b031a5937c8386839debab0e2e48837251687ba1afb6369677f8546", "93a82e1f505e06256530736b45460738bd50e897"),
        ):
            with self.subTest(eco=family):
                record = records["lichess_openings_original_eco_" + family + "_tsv"]
                path = root / record["local_source"]
                raw = path.read_bytes()
                self.assertEqual(len(raw), expected_size)
                self.assertEqual(record["indexed_bytes"], expected_size)
                self.assertEqual(record["max_bytes"], expected_size)
                self.assertEqual(record["license"], "CC0")
                self.assertEqual(record["redistribution"], "permitted")
                self.assertEqual(record["acquisition"], "VENDORED_SOURCE_VERIFIED")
                self.assertEqual(record["upstream_git_blob"], expected_blob)
                self.assertEqual(verified_local_source(path, record), expected_digest)
                self.assertEqual(
                    hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest(),
                    expected_blob,
                )
                license_file = root / record["license_source"]
                self.assertEqual(
                    hashlib.sha256(license_file.read_bytes()).hexdigest(),
                    record["license_sha256"],
                )
                rows = list(csv.DictReader(
                    io.StringIO(raw.decode("utf-8-sig")), delimiter="\t"
                ))
                self.assertEqual(len(rows), expected_rows)
                self.assertEqual(tuple(rows[0]), ("eco", "name", "pgn"))
                for row in rows:
                    self.assertTrue(row["eco"].startswith(family.upper()))
                    self.assertTrue(row["name"])
                    self.assertTrue(row["pgn"].startswith("1. "))
                for row in rows[:8]:
                    self.assertEqual(len(parse_pgn_text(
                        '[Event "Official Lichess opening"]\n[Result "*"]\n\n'
                        + row["pgn"] + " *\n", strict=False,
                    )), 1)
                with tempfile.TemporaryDirectory() as tmp:
                    corrupted = Path(tmp) / "corrupted.tsv"
                    damaged = bytearray(raw)
                    damaged[-1] ^= 1
                    corrupted.write_bytes(damaged)
                    with self.assertRaises(LawfulCorpusError):
                        verified_local_source(corrupted, record)
                    with self.assertRaises(LawfulCorpusError):
                        acquire_cc0_source(
                            record, Path(tmp),
                            opener=lambda *_a, **_kw: self.fail(
                                "vendored TSV cannot trigger implicit network"
                            ),
                        )


    def test_official_stockfish_original_zip_bytes_provenance_and_bounded_read(self):
        """Real upstream CC0 archive bytes, not a claim of full format roundtrip."""
        import zipfile
        from acs.lawful_corpus_registry import read_verified_zip_member
        from acs.position_editor import PositionState

        records = {entry["id"]: entry for entry in load_catalog()}
        root = Path(__file__).resolve().parents[1]
        sources = (
            ("stockfish_startpos_epd_zip", "epd.zip", 216, "1cab3bc1cfbfe2291591d454004269b3bcda5ab3", "startpos.epd"),
            ("stockfish_frc_openings_epd_zip", "epd.zip", 6426, "05710b911d050ba511c382f735034ae90ba35151", "FRC_openings.epd"),
            ("stockfish_4mvs_90_99_epd_zip", "epd.zip", 7399, "4ef91a4563e3bb310026f04b731a9ea517117d58", "4mvs_+90_+99.epd"),
            ("stockfish_2moves_v2_pgn_zip", "pgn.zip", 57325, "ba7bb324fa5763d961bb50d7a28d03c9462a5e51", "2moves_v2.pgn"),
        )
        for identifier, fmt, size, upstream_blob, member in sources:
            with self.subTest(source=identifier):
                record = records[identifier]
                archive_path = root / record["local_source"]
                license_file = root / record["license_source"]
                self.assertEqual(record["format"], fmt)
                self.assertEqual(record["indexed_bytes"], size)
                self.assertEqual(record["upstream_git_blob"], upstream_blob)
                self.assertEqual(record["upstream_commit"], "65815ccdbc7727cd4f6aee252ba8f67fb740e92f")
                self.assertEqual(record["acquisition"], "VENDORED_SOURCE_VERIFIED")
                self.assertEqual(record["max_bytes"], size)
                self.assertIsNone(record["download_url"])
                self.assertEqual(archive_path.stat().st_size, size)
                self.assertEqual(verified_local_source(archive_path, record), record["sha256"])
                self.assertEqual(hashlib.sha256(license_file.read_bytes()).hexdigest(), record["license_sha256"])
                self.assertIn(b"CC0 1.0 Universal", license_file.read_bytes())
                content = read_verified_zip_member(
                    archive_path, record, expected_member=member,
                    max_unpacked_bytes=record["max_unpacked_bytes"],
                )
                self.assertTrue(content.strip())
                # The upstream ZIP is a single genuine data member; no path extraction.
                with zipfile.ZipFile(archive_path) as zf:
                    self.assertEqual(zf.namelist(), [member])
                    self.assertIsNone(zf.testzip())
                if identifier == "stockfish_startpos_epd_zip":
                    first = content.decode("utf-8").strip().splitlines()[0]
                    position = PositionState.from_fen(first)
                    self.assertEqual(position.to_fen(), first)
                with tempfile.TemporaryDirectory() as tmp:
                    tampered = Path(tmp) / "tampered.zip"
                    raw = bytearray(archive_path.read_bytes())
                    raw[0] ^= 1
                    tampered.write_bytes(raw)
                    with self.assertRaises(LawfulCorpusError):
                        read_verified_zip_member(tampered, record, expected_member=member)
                    with self.assertRaises(LawfulCorpusError):
                        acquire_cc0_source(
                            record, Path(tmp),
                            opener=lambda *_a, **_kw: self.fail("vendored archive must never contact network"),
                        )

    def test_verified_zip_reader_rejects_traversal_extra_files_and_bombs(self):
        import zipfile
        from acs.lawful_corpus_registry import read_verified_zip_member
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "malicious.zip"
            for names, payload, max_unpacked in (
                (("../escape.epd",), b"safe", 1024),
                (("safe.epd", "other.epd"), b"safe", 1024),
                (("safe.epd",), b"x" * 4096, 1024),
            ):
                with self.subTest(names=names):
                    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        for name in names:
                            zf.writestr(name, payload)
                    raw = archive_path.read_bytes()
                    record = {
                        **self._record(raw),
                        "max_bytes": max(len(raw), 1),
                    }
                    with self.assertRaises(LawfulCorpusError):
                        read_verified_zip_member(
                            archive_path, record, expected_member="safe.epd",
                            max_unpacked_bytes=max_unpacked,
                        )
            with self.assertRaisesRegex(LawfulCorpusError, "ZIP member name"):
                read_verified_zip_member(archive_path, record, expected_member="../unsafe")
            with self.assertRaisesRegex(LawfulCorpusError, "ZIP expansion budget"):
                read_verified_zip_member(archive_path, record, expected_member="safe.epd", max_unpacked_bytes=True)


    def test_verified_zip_snapshot_refuses_valid_archive_swapped_after_hash_check(self):
        """A source swap between pathname hash verification and ZIP parsing is denied."""
        import zipfile
        from acs.lawful_corpus_registry import read_verified_zip_member

        def archive(payload):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as writer:
                writer.writestr("sample.epd", payload)
            return output.getvalue()

        original = archive(b"verified-source")
        replacement = archive(b"altered!-source")
        self.assertEqual(len(original), len(replacement))
        self.assertNotEqual(hashlib.sha256(original).digest(), hashlib.sha256(replacement).digest())
        record = self._record(original)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.zip"
            path.write_bytes(original)

            def replace_after_verification(source_path, source_record):
                verified = verified_local_source(source_path, source_record)
                source_path.write_bytes(replacement)
                return verified

            with patch(
                "acs.lawful_corpus_registry.verified_local_source",
                side_effect=replace_after_verification,
            ):
                with self.assertRaisesRegex(
                    LawfulCorpusError, "ZIP source changed after verification"
                ):
                    read_verified_zip_member(
                        path, record, expected_member="sample.epd",
                        max_unpacked_bytes=1024,
                    )
            # A bad attempted read must not poison the original authorized bytes.
            path.write_bytes(original)
            self.assertEqual(
                read_verified_zip_member(
                    path, record, expected_member="sample.epd",
                    max_unpacked_bytes=1024,
                ),
                b"verified-source",
            )


if __name__ == "__main__":
    unittest.main()

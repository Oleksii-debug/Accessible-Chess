"""Original Northwest Chess CBV + PGN pairing: fail closed until fetched bytes.

No synthetic sample may be published as authenticated historical origin.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.lawful_corpus_registry import LawfulCorpusError
from tools import section38_39_nwc_genuine_cbv_pgn as nw


class NorthwestChessSourceOnlyTests(unittest.TestCase):
    def test_source_urls_are_from_same_first_party_publisher(self):
        self.assertEqual(nw._qualified_url(nw.PGN_URL), nw.PGN_URL)
        self.assertEqual(nw._qualified_url(nw.CBV_URL), nw.CBV_URL)
        self.assertIn("2013-01", nw.CBV_URL)
        self.assertTrue(nw.PGN_URL.endswith("Games.pgn"))
        self.assertTrue(nw.CBV_URL.endswith("Games.cbv"))
        self.assertTrue(nw.PUBLISHER.startswith("https://www.nwchess.com/"))
        for url in (
            "http://www.nwchess.com/articles/games/published/sample.cbv",
            "https://evil.invalid/articles/games/published/sample.cbv",
            "https://www.nwchess.com.evil.invalid/articles/games/published/a.pgn",
            "https://www.nwchess.com@evil.invalid/articles/games/published/a.pgn",
            "https://www.nwchess.com:8443/articles/games/published/sample.cbv",
            "https://www.nwchess.com/articles/games/published/a.cbv?secret=123",
            "https://www.nwchess.com/articles/games/published/../hidden.cbv",
            "https://www.nwchess.com/articles/games/published/test.cbv#frag",
            "https://www.nwchess.com/articles/games/published/%2e%2e/private.cbv",
            "https://www.nwchess.com/articles/games/published/%252e%252e/private.cbv",
            "https://www.nwchess.com/articles/games/published/%25252e%25252e/private.cbv",
            "https://www.nwchess.com/articles/games/published/evil%2f..%2fprivate.pgn",
            "https://www.nwchess.com/articles/games/published/a%5cb.pgn",
            "https://www.nwchess.com/articles/games/published/secret%3Ftoken.cbv",
            "https://www.nwchess.com/articles/games/published/secret%00zero.cbv",
            "https://www.nwchess.com/articles/games/published/readme.txt",
            "",
        ):
            with self.subTest(url=url):
                with self.assertRaises(LawfulCorpusError):
                    nw._qualified_url(url)
        with self.assertRaises((LawfulCorpusError, TypeError)):
            nw._qualified_url(None)

    def test_new_original_cbv_and_pgn_are_registered_only_as_source_pages(self):
        from acs.lawful_corpus_registry import load_catalog
        catalogue = {r["id"]: r for r in load_catalog()}
        expected = (
            ("northwest_chess_2013_01_annotated_cbv_original_external", nw.CBV_URL, "cbv"),
            ("northwest_chess_2013_01_annotated_pgn_independent_oracle_external", nw.PGN_URL, "pgn"),
        )
        for ident, uri, extension in expected:
            with self.subTest(source=ident):
                item = catalogue[ident]
                self.assertEqual(item["source_page"], nw.PUBLISHER)
                self.assertEqual(item["download_url"], uri)
                self.assertEqual(item["format"], extension)
                self.assertEqual(item["acquisition"], "SOURCE_PAGE_ONLY")
                self.assertIsNone(item["sha256"])
                self.assertEqual(item["redistribution"], "NOT_CLEARED")
                self.assertEqual(item["public_release"], "EXCLUDED")
        nzcf = catalogue["nzcf_peter_stuart_historical_full_cbv_pgn_bibliography"]
        self.assertEqual(nzcf["acquisition"], "SOURCE_PAGE_ONLY")
        self.assertEqual(nzcf["redistribution"], "NOT_CLEARED")
        self.assertIsNone(nzcf["download_url"])
        self.assertIsNone(nzcf["sha256"])

    def test_source_registry_is_the_only_url_and_license_authority(self):
        cbv, pgn = nw._catalog_source_pair()
        self.assertEqual(cbv["id"], nw.CBV_SOURCE_ID)
        self.assertEqual(pgn["id"], nw.PGN_SOURCE_ID)
        self.assertEqual(cbv["download_url"], nw.CBV_URL)
        self.assertEqual(pgn["download_url"], nw.PGN_URL)
        good = nw.load_catalog()
        for mutated_field, value in (
            ("acquisition", "VENDORED_SOURCE_VERIFIED"),
            ("redistribution", "permitted"),
            ("public_release", "INCLUDED"),
            ("sha256", "0" * 64),
            ("download_url", "https://evil.invalid/not-original.cbv"),
            ("max_bytes", 0),
        ):
            with self.subTest(field=mutated_field):
                bogus = tuple(
                    {**record, mutated_field: value}
                    if record["id"] == nw.CBV_SOURCE_ID else record
                    for record in good
                )
                with patch.object(nw, "load_catalog", return_value=bogus):
                    with self.assertRaises(LawfulCorpusError):
                        nw._catalog_source_pair()

    def test_absent_external_mit_binary_refuses_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            no_file = Path(temp) / "not-cbvault.exe"
            with patch.object(nw, "_read_publisher_source") as getter:
                with self.assertRaises(LawfulCorpusError):
                    nw.qualify_original_publisher_pair(
                        binary=no_file,
                        expected_binary_sha256="0" * 64,
                    )
                getter.assert_not_called()
        for digest in ("", "a" * 32, "NOT-A-SHA", None):
            with self.subTest(digest=digest):
                with self.assertRaises(LawfulCorpusError):
                    nw.qualify_original_publisher_pair(
                        binary=Path("unavailable"),
                        expected_binary_sha256=digest,
                    )

    def test_partial_original_cbv_extraction_reports_only_bounded_counters(self):
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary, source, target = root / "cbvault", root / "real.cbv", root / "expanded"
            binary.write_bytes(b"stub")
            source.write_bytes(b"original archive")
            def partial(args, **kwargs):
                self.assertEqual(args[-3:], ["--threads", "1", "--json"])
                kwargs["stdout"].write(
                    b'{"written":2,"bytes":100,"skipped":["/secret/owner.cbh: invalid"]}\n'
                )
                kwargs["stdout"].flush()
                child = MagicMock()
                child.poll.return_value = 1
                child.returncode = 1
                return child

            with patch.object(nw.subprocess, "Popen", side_effect=partial):
                with self.assertRaisesRegex(
                    LawfulCorpusError,
                    r"refused real publisher original \(exit=1; written=2; skipped=1\)",
                ) as error:
                    nw._extract_with_mit(binary, source, target)
            self.assertNotIn("secret", str(error.exception))
            self.assertNotIn("owner.cbh", str(error.exception))

    def test_real_original_cbv_extraction_timeout_kills_child_and_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_binary = root / "stub-binary"
            fake_source = root / "original-source.cbv"
            fake_binary.write_bytes(b"read-only dummy")
            fake_source.write_bytes(b"read-only dummy")
            target = root / "output"
            with patch.object(nw.subprocess, "Popen") as constructor:
                child = constructor.return_value
                child.poll.return_value = None
                with patch("time.monotonic", side_effect=[0, 121]):
                    with self.assertRaisesRegex(LawfulCorpusError, "timed out"):
                        nw._extract_with_mit(fake_binary, fake_source, target)
                child.kill.assert_called_once()
                child.wait.assert_called_once()
                self.assertFalse(target.exists())

    def test_genuine_publisher_bytes_are_hash_recorded_but_blocked_on_unpack_error(self):
        genuine_pgn = b'[Event "Historical"]\n[Result "*"]\n\n1. e4 e5 *\n'
        genuine_cbv = b"publisher archive with original metadata"
        with (
            patch.object(nw, "_bounded_file_digest", return_value=("a" * 64, 100)),
            patch.object(nw, "_catalog_source_pair", return_value=(
                {"download_url": nw.CBV_URL},
                {"download_url": nw.PGN_URL},
            )),
            patch.object(nw, "_read_publisher_source", side_effect=[
                genuine_pgn, genuine_cbv,
            ]) as downloader,
            patch.object(nw, "_extract_with_mit",
                         side_effect=LawfulCorpusError("original unpacker refused")) as unpack,
        ):
            result = nw.qualify_original_publisher_pair(
                binary=Path("external-test-only-backend"),
                expected_binary_sha256="a" * 64,
            )
        self.assertEqual(downloader.call_count, 2)
        unpack.assert_called_once()
        self.assertEqual(result["qualification"], "BLOCKED")
        self.assertEqual(result["blocked_reason"], "MIT_EXTERNAL_CBV_UNPACK_FAILED_CLOSED")
        self.assertEqual(result["observed_source_pgn_sha256"], hashlib.sha256(genuine_pgn).hexdigest())
        self.assertEqual(result["observed_source_cbv_sha256"], hashlib.sha256(genuine_cbv).hexdigest())
        self.assertEqual(result["pgn_expected_games"], 1)
        self.assertIsNone(result["cbv_decoder_actual_games"])
        self.assertIsNone(result["actual_acsdb_imported_games"])
        self.assertFalse(result["full_semantic_game_tree_match"])
        self.assertFalse(result["acsdb_restart_full_semantic_match"])
        self.assertFalse(result["section38_terminal_done"])
        self.assertFalse(result["original_files_redistributed"])

    def test_original_pgn_and_original_cbv_are_distinct_source_bytes(self):
        # This is a negative *metadata* test, not a substitute for downloading
        # actual CBV and PGN or their independent oracle.
        self.assertNotEqual(nw.PGN_URL, nw.CBV_URL)
        self.assertEqual(
            nw.PGN_URL.removesuffix(".pgn"),
            nw.CBV_URL.removesuffix(".cbv"),
        )
        self.assertGreater(nw.MAX_SOURCE, 1024)
        self.assertGreater(nw.MAX_EXTRACTED_TOTAL, nw.MAX_SOURCE)
        self.assertLessEqual(nw.MAX_GAME_COUNT, 25_000)
        self.assertNotEqual(
            hashlib.sha256(b"synthetic").hexdigest(), "0" * 64
        )


if __name__ == "__main__":
    unittest.main()
